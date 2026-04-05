"""LLM Ask route handler for the QARA FastAPI server.

Factory function :func:`make_llm_router` registers the ``/api/ask`` endpoint.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from qara.server.models import AskRequest, AskResponse


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (in-memory, no external dependency)
# ---------------------------------------------------------------------------

class _SlidingWindowLimiter:
    """Thread-safe per-key sliding-window rate limiter."""

    def __init__(self, max_calls: int, window_seconds: int) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._lock = threading.Lock()
        self._log: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        """Raise HTTP 429 if *key* has exceeded the allowed call rate."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            calls = self._log[key]
            # Drop timestamps outside the current window
            while calls and calls[0] < cutoff:
                calls.pop(0)
            if len(calls) >= self._max:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded: max {self._max} requests "
                        f"per {self._window}s. Please wait before retrying."
                    ),
                    headers={"Retry-After": str(self._window)},
                )
            calls.append(now)


# One limiter instance shared across all requests: 10 calls / 60 s per IP.
_ask_limiter = _SlidingWindowLimiter(max_calls=10, window_seconds=60)


def _ask_rate_limit(request: Request) -> None:
    """FastAPI dependency — enforces the /api/ask rate limit."""
    key = request.client.host if request.client else "unknown"
    _ask_limiter.check(key)


def make_llm_router(
    db_path: str | Path | None,
    cfg_path: str | Path | None,
) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with the LLM ask endpoint."""
    router = APIRouter()

    @router.post("/api/ask", tags=["llm"], response_model=AskResponse)
    async def ask(
        body: AskRequest,
        _rl: None = Depends(_ask_rate_limit),
    ) -> AskResponse:
        """Send a natural-language question to the configured LLM.

        Raises HTTP 503 if the LLM is unreachable, HTTP 400 if the question
        is empty.
        """
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="Question must not be empty.")

        from qara.llm.answer_plan import build_answer_plan, detect_answer_intent
        from qara.llm.client import LLMClient, LLMError
        from qara.llm.config import load_config
        from qara.llm.context import (
            extract_test_from_history,
            gather_date_context,
            gather_project_context,
            gather_test_context,
        )
        from qara.llm.context_history import extract_prior_context_from_history
        from qara.llm.prompts import build_prompt, build_system_prompt, infer_mode
        from qara.llm.routing import (
            detect_signals,
            gather_context_for_signals,
            normalize_query,
            parse_query_intent,
        )

        cfg = load_config(None if cfg_path is None else Path(cfg_path))
        mode = infer_mode(body.question)

        # Build prior context from conversation history so follow-up questions
        # can inherit intent, metric, and max_results from the previous turn.
        _prior_context = extract_prior_context_from_history(body.history or [])

        # Detect answer intent — drives prompt structure and context selection.
        _answer_intent = detect_answer_intent(body.question)
        _answer_plan = build_answer_plan(
            _answer_intent, question=body.question, prior_context=_prior_context
        )

        # Mine conversation history for a test name so follow-up questions like
        # "Which suite does this belong to?" resolve "this" to the right test.
        history_test = extract_test_from_history(body.history or [])

        # LLM-powered intent + entity extraction. Falls back to keyword matching
        # when the LLM is unavailable, so latency is only added when needed.
        _intent = parse_query_intent(body.question, config=cfg)

        # Semantic signal detection: replaces the old _RISK_PHRASES exact-match
        # check with a multi-signal approach that handles duration/stability/trend
        # questions in addition to pure risk/prediction queries.
        _signals = detect_signals(normalize_query(body.question))
        _routed_ctx, _routed_facts, _routed_src, _routed_mode = gather_context_for_signals(
            _signals,
            body.question,
            project=body.project,
            db_path=db_path,
            intent=_intent,
            answer_plan=_answer_plan,
        )
        _structured_facts: str | None = _routed_facts if _routed_facts else None

        if _routed_ctx:
            # Signals routing fired (risk / duration / stability / trend)
            context, sources, mode = _routed_ctx, _routed_src, _routed_mode
        elif mode == "project":
            # Try date-filtered context first; fall back to generic project context
            date_result = gather_date_context(
                body.question, project=body.project, db_path=db_path
            )
            if date_result is not None:
                context, sources = date_result
            else:
                context, sources = gather_project_context(project=body.project, db_path=db_path)
        else:
            # Try the literal question first
            context, sources = gather_test_context(
                body.question, project=body.project, db_path=db_path
            )
            # If nothing matched (fix: actual return string is "No test matching")
            if not context.strip() or "No test matching" in context:
                # Before falling back to project, try the test name from history
                if history_test:
                    context, sources = gather_test_context(
                        history_test, project=body.project, db_path=db_path
                    )
            # Still nothing — fall back to project context
            if not context.strip() or "No test matching" in context:
                mode = "project"
                date_result = gather_date_context(
                    body.question, project=body.project, db_path=db_path
                )
                if date_result is not None:
                    context, sources = date_result
                else:
                    context, sources = gather_project_context(project=body.project, db_path=db_path)
                    # Prune sources: when we fell back from a test question,
                    # the generic flaky/broken/group cards are not relevant.
                    # Keep only run card(s) to give the LLM run-level context.
                    if history_test or mode == "project":
                        sources = [s for s in sources if s.get("type") == "run"][:2]

        prompt = build_prompt(
            body.question,
            context,
            mode=mode,
            history=body.history or [],
            answer_plan=_answer_plan,
            structured_facts=_structured_facts,
        )
        try:
            answer = LLMClient(cfg).chat(
                prompt, system_prompt=build_system_prompt(_answer_plan)
            )
        except LLMError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return AskResponse(
            answer=answer,
            context_mode=mode,
            sources=sources,
            intent=_answer_intent.value,
            follow_ups=_generate_chips(_answer_plan, sources, question=body.question),
        )

    @router.get("/api/llm/info", tags=["llm"])
    async def llm_info() -> dict:
        """Return the active LLM provider and model name."""
        from qara.llm.config import load_config
        cfg = load_config(None if cfg_path is None else Path(cfg_path))
        return {"provider": cfg.provider, "model": cfg.model}

    return router


def _generate_chips(answer_plan, sources, *, question: str = ""):
    from qara.llm.followups import generate_follow_ups
    return generate_follow_ups(answer_plan, sources, question=question)
