"""Signal detection and context orchestration for QaLens LLM queries.

Replaces the brittle ``_RISK_PHRASES`` set with a semantic signals approach:

1. *Normalise* — lowercase, collapse whitespace, strip punctuation variants.
2. *Detect signals* — map the normalised text to a :class:`QuerySignals`
   instance whose boolean flags identify which aspects the question covers.
3. *Orchestrate context* — :func:`gather_context_for_signals` calls the
   appropriate context builder(s) and prepends a ``[QUERY SIGNALS]`` header
   so the LLM knows exactly what data has been provided and what guardrails
   apply to its answer.

Usage::

    from qalens.llm.routing import detect_signals, gather_context_for_signals, normalize_query

    normalized = normalize_query(question)
    signals    = detect_signals(normalized)
    context, sources, mode = gather_context_for_signals(
        signals, question, project=project, db_path=db_path
    )
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# QueryIntent dataclass — LLM-parsed structured intent
# ---------------------------------------------------------------------------


@dataclass
class QueryIntent:
    """Structured intent extracted from a user question by the LLM.

    Produced by :func:`parse_query_intent`.  When the LLM is unavailable or
    the parse fails, a fallback populated from keyword matching is returned.
    """

    intents: list[str] = field(default_factory=list)
    """List of intent tags, e.g. ``["owner_lookup", "failure_summary"]``."""

    owner_name: str | None = None
    """Extracted person or team name for owner-related questions."""

    test_name: str | None = None
    """Extracted test name when question is about a specific test."""

    source: str = "keyword"
    """``"llm"`` when parsed by the LLM, ``"keyword"`` when from fallback."""

    @property
    def is_owner_query(self) -> bool:
        return "owner_lookup" in self.intents

    @property
    def is_risk_query(self) -> bool:
        return "risk_prediction" in self.intents

    @property
    def is_stability_query(self) -> bool:
        return "stability" in self.intents

    @property
    def is_duration_query(self) -> bool:
        return "duration" in self.intents


# ---------------------------------------------------------------------------
# Intent parsing — LLM-powered with keyword fallback
# ---------------------------------------------------------------------------

_INTENT_SYSTEM_PROMPT = """\
You are a query intent classifier for a test analytics system.
Given a user question about software tests, extract structured intent as JSON.

Return ONLY valid JSON with these fields (no markdown, no explanation):
{
  "intents": [<list of applicable tags from the allowed set>],
  "owner_name": <string or null>,
  "test_name": <string or null>
}

Allowed intent tags:
- "owner_lookup"      : question asks which tests belong to a person/team, or asks about a person's tests
- "risk_prediction"   : question asks about failure likelihood, risk scores, or which tests might fail
- "stability"         : question asks about flaky tests, flip rates, consistent failures
- "duration"          : question asks about slow tests, execution time, performance
- "failure_summary"   : question asks for a list or summary of failures
- "trend"             : question asks about improvement or decline over time
- "root_cause"        : question asks why a test fails or what caused a failure
- "history"           : question asks about past runs or historical patterns
- "comparison"        : question compares two things (runs, dates, owners, tests)
- "general"           : none of the above

Rules:
- owner_name: extract the full person or team name if mentioned (preserve original casing, e.g. "Fatima Al-Rashid")
- test_name: extract the test method name if mentioned (e.g. "testCreateOrder")
- Multiple intents are allowed; always include at least one
"""


def parse_query_intent(
    question: str,
    *,
    config: "LLMConfig | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> QueryIntent:
    """Parse the user *question* into a :class:`QueryIntent` using the LLM.

    Makes a short, cheap LLM call with a tight JSON-only prompt.  Falls back
    to keyword-based detection if the LLM is unreachable, returns malformed
    JSON, or if *config* is ``None``.

    Args:
        question: The raw user question.
        config:   LLM config to use.  When ``None``, loaded automatically via
                  :func:`~qalens.llm.config.load_config`.

    Returns:
        A :class:`QueryIntent` with ``source="llm"`` on success or
        ``source="keyword"`` on fallback.
    """
    intent = _parse_intent_llm(question, config=config)
    if intent is not None:
        return intent
    # Fallback: derive from keyword signals
    return _parse_intent_keywords(question)


def _parse_intent_llm(
    question: str,
    *,
    config: "LLMConfig | None" = None,  # type: ignore[name-defined]
) -> QueryIntent | None:
    """Run the LLM intent-parse call.  Returns ``None`` on any failure."""
    try:
        from qalens.llm.client import LLMClient, LLMError
        from qalens.llm.config import load_config

        cfg = config or load_config(None)
        client = LLMClient(cfg)
        raw = client.chat(question, system_prompt=_INTENT_SYSTEM_PROMPT)
        # Strip markdown code fences if the model returned them
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        data = json.loads(raw)
        return QueryIntent(
            intents=data.get("intents") or ["general"],
            owner_name=data.get("owner_name") or None,
            test_name=data.get("test_name") or None,
            source="llm",
        )
    except Exception:  # noqa: BLE001
        return None


def _parse_intent_keywords(question: str) -> QueryIntent:
    """Keyword-based intent fallback (no LLM call)."""
    norm = normalize_query(question)
    signals = detect_signals(norm)
    intents: list[str] = []
    if signals.asks_about_owner:
        intents.append("owner_lookup")
    if signals.needs_risk_context:
        intents.append("risk_prediction")
    if signals.asks_about_stability:
        intents.append("stability")
    if signals.asks_about_duration:
        intents.append("duration")
    if signals.asks_about_failures:
        intents.append("failure_summary")
    if signals.asks_about_trend:
        intents.append("trend")
    if signals.asks_about_root_cause:
        intents.append("root_cause")
    if signals.asks_about_history:
        intents.append("history")
    if signals.asks_about_comparison:
        intents.append("comparison")
    if not intents:
        intents.append("general")
    return QueryIntent(
        intents=intents,
        owner_name=_extract_owner_from_question(question),
        source="keyword",
    )


# ---------------------------------------------------------------------------
# QuerySignals dataclass
# ---------------------------------------------------------------------------


@dataclass
class QuerySignals:
    """Boolean flags describing which aspects a user question touches.

    Each flag is independent — multiple may be ``True`` for a single query
    (e.g. "which stable tests are slowing down over time" fires
    ``asks_about_stability``, ``asks_about_duration``, and
    ``asks_about_trend``).
    """

    asks_about_risk: bool = False
    """Failure prediction / next-run risk likelihood."""

    asks_about_duration: bool = False
    """Execution time / performance / slowing tests."""

    asks_about_stability: bool = False
    """Flaky, volatile, on-streak, or consistently passing tests."""

    asks_about_failures: bool = False
    """Currently broken or failing tests."""

    asks_about_history: bool = False
    """Historical run patterns over time."""

    asks_about_comparison: bool = False
    """A-vs-B, improved, degraded comparisons."""

    asks_about_suite: bool = False
    """Suite / module / package grouping questions."""

    asks_about_owner: bool = False
    """Owner / team / responsible-party questions."""

    asks_about_owner_aggregate: bool = False
    """Aggregate breakdown across all engineers (failure rate per engineer, etc.)."""

    asks_about_root_cause: bool = False
    """Why / cause / explain questions."""

    asks_about_trend: bool = False
    """Improving, declining, getting-worse trend questions."""

    # ------------------------------------------------------------------
    # Derived properties (not persisted as fields)
    # ------------------------------------------------------------------

    @property
    def needs_risk_context(self) -> bool:
        """``True`` when risk-page / predictor data is relevant to this query.

        Risk context contains all four risk tiers (CRITICAL → LOW), failure
        signals, duration-spike data for slowing tests, and volatility scores.
        It is the right context source for any question touching risk,
        duration, stability, or trend.
        """
        return (
            self.asks_about_risk
            or self.asks_about_duration
            or self.asks_about_stability
            or self.asks_about_trend
        )

    @property
    def any_signal(self) -> bool:
        """``True`` if at least one signal flag is set."""
        return (
            self.asks_about_risk
            or self.asks_about_duration
            or self.asks_about_stability
            or self.asks_about_failures
            or self.asks_about_history
            or self.asks_about_comparison
            or self.asks_about_suite
            or self.asks_about_owner
            or self.asks_about_root_cause
            or self.asks_about_trend
        )


# ---------------------------------------------------------------------------
# Signal keyword sets
# ---------------------------------------------------------------------------

_RISK_KEYWORDS: frozenset[str] = frozenset({
    "almost certain", "certain to fail", "likely to fail", "will fail",
    "going to fail", "fail next", "fail in the next", "next run",
    "at risk", "high risk", "risk score", "risk tier", "risk prediction",
    "predict", "prediction", "forecast",
    "which tests will", "which test will",
})

_DURATION_KEYWORDS: frozenset[str] = frozenset({
    "taking longer", "slower", "slowing", "duration spike", "getting slow",
    "execution time", "slow test", "slow down", "duration trend",
    "performance", "running slow", "takes too long",
    "duration", "running longer", "getting slower",
})

_STABILITY_KEYWORDS: frozenset[str] = frozenset({
    "stable", "flaky", "volatile", "consistent", "unstable", "intermittent",
    "on fail streak", "fail streak", "streak", "reliable", "reliability",
})

_FAILURE_KEYWORDS: frozenset[str] = frozenset({
    "failing", "broken", "error", "failed", "failure", "exception",
    "crash", "breaking", "broke",
})

_HISTORY_KEYWORDS: frozenset[str] = frozenset({
    "history", "over time", "historically", "last few runs",
    "previous runs", "past runs", "run history",
})

_COMPARISON_KEYWORDS: frozenset[str] = frozenset({
    "compare", "versus", " vs ", "worse than", "better than",
    "improved", "degraded", "changed",
})

_SUITE_KEYWORDS: frozenset[str] = frozenset({
    "suite", "module", "package", "folder",
})

_OWNER_KEYWORDS: frozenset[str] = frozenset({
    "owner", "owned by", "owned", "team", "responsible", "assigned",
    "who owns", "maintainer", "belonging to", "tests by", "tests for",
})

# Aggregate owner-analytics questions — no single owner name, asks for a
# breakdown or ranking across all engineers.
_OWNER_AGGREGATE_KEYWORDS: frozenset[str] = frozenset({
    "per engineer", "per owner", "per developer", "per person", "per team member",
    "each engineer", "each owner", "each developer",
    "failure rate per", "failure count per", "failures per",
    "most failures", "highest failure", "engineer with", "owner with",
    "who has the most", "who has more", "who owns the most",
    "most flaky", "flakiest engineer", "flakiest owner",
    "breakdown by engineer", "breakdown by owner", "breakdown by developer",
    "by engineer", "by owner", "by developer",
})

_ROOT_CAUSE_KEYWORDS: frozenset[str] = frozenset({
    "why", "what caused", "cause", "reason", "explain",
    "root cause", "investigation", "investigate",
})

_TREND_KEYWORDS: frozenset[str] = frozenset({
    "trend", "getting worse", "improving", "declining",
    "worsening", "deteriorating", "over time",
})


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize_query(text: str) -> str:
    """Return a canonical form of *text* suitable for keyword matching.

    Lowercases the input, strips apostrophe/backtick characters (so "it's"
    becomes "its"), and collapses internal whitespace to single spaces.

    Args:
        text: Raw user question.

    Returns:
        Normalised string (lowercased, whitespace-collapsed, no apostrophes).
    """
    lower = text.lower()
    no_apos = re.sub(r"['\u2018\u2019`]", "", lower)
    return re.sub(r"\s+", " ", no_apos).strip()


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------


def detect_signals(normalized: str) -> QuerySignals:
    """Map a normalised query string to a :class:`QuerySignals` instance.

    Each field is set to ``True`` when at least one keyword from the
    corresponding set appears as a substring in *normalized*.

    Args:
        normalized: Output of :func:`normalize_query`.

    Returns:
        A populated :class:`QuerySignals` instance.
    """

    def _hit(keywords: frozenset[str]) -> bool:
        return any(kw in normalized for kw in keywords)

    return QuerySignals(
        asks_about_risk=_hit(_RISK_KEYWORDS),
        asks_about_duration=_hit(_DURATION_KEYWORDS),
        asks_about_stability=_hit(_STABILITY_KEYWORDS),
        asks_about_failures=_hit(_FAILURE_KEYWORDS),
        asks_about_history=_hit(_HISTORY_KEYWORDS),
        asks_about_comparison=_hit(_COMPARISON_KEYWORDS),
        asks_about_suite=_hit(_SUITE_KEYWORDS),
        asks_about_owner=_hit(_OWNER_KEYWORDS),
        asks_about_owner_aggregate=_hit(_OWNER_AGGREGATE_KEYWORDS),
        asks_about_root_cause=_hit(_ROOT_CAUSE_KEYWORDS),
        asks_about_trend=_hit(_TREND_KEYWORDS),
    )


# ---------------------------------------------------------------------------
# Context orchestration
# ---------------------------------------------------------------------------


def gather_context_for_signals(
    signals: QuerySignals,
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
    intent: "QueryIntent | None" = None,
    answer_plan: "AnswerPlan | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> tuple[str, str, list[dict], str]:
    """Return ``(context, structured_facts, sources, mode)`` appropriate for *signals*.

    When *answer_plan* is supplied, intent-specific context builders are
    invoked first, each returning a 3-tuple of
    ``(context_text, structured_facts_text, sources)``:

    * ``RANKING_LIST``        → :func:`gather_ranking_context`  (metric-aware)
    * ``COMPARISON_CHANGE``   → :func:`gather_comparison_context`
    * ``RECOMMENDATION_ACTION`` → :func:`gather_recommendation_context`
    * ``SUMMARY_OVERVIEW``    → :func:`gather_summary_context`

    ``DIAGNOSTIC_ROOT_CAUSE`` and ``DRILL_DOWN_DETAIL`` fall through to the
    standard signal/risk routing so the LLM receives the most relevant
    evidence already filtered by the signals that were detected.

    When :attr:`QuerySignals.needs_risk_context` is ``True``, the function
    calls :func:`~qalens.llm.context.gather_risk_context` and prepends a
    ``[QUERY SIGNALS]`` block.

    When no signal routing applies, returns ``("", "", [], "")`` to signal
    that the caller should use its standard routing.

    Args:
        signals:     Detected :class:`QuerySignals` for the user's question.
        question:    The original (un-normalised) user question.
        project:     Optional project name filter.
        db_path:     Path to the QaLens SQLite database.
        intent:      Optional pre-parsed :class:`QueryIntent`.
        answer_plan: Optional :class:`~qalens.llm.answer_plan.AnswerPlan`.

    Returns:
        A 4-tuple of ``(context_text, structured_facts, sources, mode)`` or
        ``("", "", [], "")`` when no signal-based routing applies.
    """
    # ── Owner aggregate: failure rate / count across ALL engineers ───────────
    # Must come before single-owner check so "failure rate per engineer" doesn't
    # accidentally try to extract a single owner name from the question.
    if signals.asks_about_owner_aggregate:
        if signals.asks_about_stability:
            # "Who owns the most flaky tests?" — route to flaky-specific ranking.
            from qalens.llm.context import gather_flaky_owner_context

            context, sources = gather_flaky_owner_context(
                project=project, db_path=db_path
            )
        else:
            from qalens.llm.context import gather_owner_aggregate_context

            context, sources = gather_owner_aggregate_context(
                project=project, db_path=db_path
            )
        return context, "", sources, "project"

    # ── Owner query: always intercept first before answer-plan routing ───────
    # "Which tests owned by Fatima are failing?" classifies as SUMMARY_OVERVIEW
    # by the heuristic intent detector, so it would fall into the summary branch
    # and never reach the owner-context builder below. Checking owner first
    # ensures the DB-backed gather_owner_context is always used for owner queries.
    is_owner = (intent.is_owner_query if intent else signals.asks_about_owner)
    if is_owner:
        owner = (intent.owner_name if intent else None) or _extract_owner_from_question(question)
        if owner:
            from qalens.llm.context import gather_owner_context

            context, sources = gather_owner_context(
                owner, project=project, db_path=db_path
            )
            header = _build_signals_header(signals)
            full_context = header + "\n\n" + context if header else context
            return full_context, "", sources, "project"

    # ── Answer-plan routing (takes priority over remaining signal routing) ───
    if answer_plan is not None:
        from qalens.llm.answer_plan import AnswerIntent

        if answer_plan.intent == AnswerIntent.RANKING_LIST:
            ctx, facts, src = gather_ranking_context(
                project=project,
                db_path=db_path,
                metric=answer_plan.ranking_metric,
                top_n=answer_plan.max_results or 10,
            )
            answer_plan.scope = _scope_from_sources(src, label="RANKED TESTS")
            return ctx, facts, src, "project"

        if answer_plan.intent == AnswerIntent.NEW_REGRESSIONS:
            ctx, facts, src = gather_comparison_context(
                project=project,
                db_path=db_path,
                is_trend=False,  # NEW_REGRESSIONS is always non-trend
            )
            scope = _build_newly_failing_scope(project=project, db_path=db_path)
            answer_plan.scope = scope
            ctx = _inject_scope_context(ctx, scope)
            return ctx, facts, src, "project"

        if answer_plan.intent == AnswerIntent.COMPARISON_CHANGE:
            ctx, facts, src = gather_comparison_context(
                project=project,
                db_path=db_path,
                is_trend=getattr(answer_plan, "is_trend_question", False),
            )
            answer_plan.scope = _scope_from_sources(src, label="COMPARISON")
            return ctx, facts, src, "project"

        if answer_plan.intent == AnswerIntent.RECOMMENDATION_ACTION:
            _cap = answer_plan.max_results or 10
            ctx, facts, src = gather_recommendation_context(
                project=project,
                db_path=db_path,
                top_n_risk=_cap,
                top_n_flaky=min(5, _cap),
            )
            answer_plan.scope = _scope_from_sources(src, label="RECOMMENDATION TARGETS")
            return ctx, facts, src, "project"

        if answer_plan.intent == AnswerIntent.SUMMARY_OVERVIEW:
            ctx, facts, src = gather_summary_context(
                project=project, db_path=db_path
            )
            answer_plan.scope = _scope_from_sources(src, label="SUMMARY")
            return ctx, facts, src, "project"

        if answer_plan.intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE:
            # Flakiness-history follow-up ("Were any of these tests flaky before
            # this regression?") needs BOTH:
            #   1. A compact scope listing the newly-failing test names only.
            #      Using a compact list (not the full formatted comparison breakdown)
            #      prevents the LLM from re-outputting group blocks and error messages.
            #   2. Ranking/stability context — supplies flip_score for each test
            #      so the LLM can classify each one into a flakiness tier.
            from qalens.llm.answer_plan import _is_flakiness_history_query, _is_flakiness_ranking_query  # type: ignore[attr-defined]

            if _is_flakiness_history_query(question) or _is_flakiness_ranking_query(question):
                # Call gather_comparison_context solely for its source cards (UI chips).
                # We deliberately discard cmp_ctx AND cmp_facts (the full formatted
                # breakdown contains error messages / root-cause groups that leak
                # into the flakiness answer).
                _cmp_ctx, _cmp_facts, cmp_src = gather_comparison_context(
                    project=project,
                    db_path=db_path,
                    is_trend=False,
                )
                cmp_scope = _build_newly_failing_scope(project=project, db_path=db_path)
                prebuilt_answer = _build_recent_flip_context(
                    project=project, db_path=db_path, window=5
                )
                merged_ctx = _inject_scope_context(
                    "=== PRE-BUILT ANSWER (output this verbatim) ===\n" + prebuilt_answer,
                    cmp_scope,
                )
                # Minimal structured facts — no error messages, no root-cause groups
                scope_facts = (
                    "The '=== PRE-BUILT ANSWER ===' section above contains the complete, "
                    "ready-to-output answer. Copy it verbatim as your response."
                )
                # Deduplicate sources — comparison sources take priority
                seen = {s.get("label") for s in cmp_src}
                merged_src = list(cmp_src)
                return merged_ctx, scope_facts, merged_src, "project"

    # ── Specific-run query: "Run No 18", "run #18", "run 18" ─────────────
    run_number = _extract_run_number_from_question(question)
    if run_number is not None:
        ctx, facts, src = gather_specific_run_context(
            run_number=run_number,
            project=project,
            db_path=db_path,
        )
        if ctx:  # run was found
            return ctx, facts, src, "project"

    if not signals.needs_risk_context:
        return "", "", [], ""

    from qalens.llm.context import gather_risk_context

    context, sources = gather_risk_context(project=project, db_path=db_path)
    header = _build_signals_header(signals)
    full_context = header + "\n\n" + context if header else context
    return full_context, "", sources, "project"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scope_from_sources(
    sources: list[dict],
    *,
    label: str = "",
) -> "AnswerScope":
    """Build an :class:`AnswerScope` from source cards.

    Extracts test names and run labels from the source-card list and wraps
    them in a lightweight scope object.  Used by
    :func:`gather_context_for_signals` to attach scope to the answer plan
    for intent paths that don't have a dedicated scope builder.
    """
    from qalens.llm.answer_types import AnswerScope

    tests = [
        (s.get("label") or "").strip()
        for s in sources
        if s.get("type") == "test" and (s.get("label") or "").strip()
    ]
    runs = [
        (s.get("label") or "").strip()
        for s in sources
        if s.get("type") == "run" and (s.get("label") or "").strip()
    ]
    return AnswerScope(
        tests=tests,
        runs=runs,
        total=len(tests),
        label=label,
    )


def _inject_scope_context(context: str, scope: "AnswerScope") -> str:
    """Prepend an :class:`AnswerScope` block to *context* when scope is non-empty.

    This is the single helper that guarantees consistent scope injection
    across all answer paths.  If *scope* has no tests, returns *context*
    unchanged so callers don't need to check emptiness.
    """
    if not scope.tests:
        return context
    return scope.format_block() + "\n\n" + context


def _build_newly_failing_scope(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
) -> "AnswerScope":
    """Return an :class:`AnswerScope` for newly failing tests.

    Used instead of the full :func:`gather_comparison_context` output so the LLM
    receives only the scope boundary (which tests to analyse) without the full
    formatted breakdown of groups, error messages, or recovered/consistently-failing
    sections that can cause it to reproduce the entire regression table.

    Args:
        project:  Optional project name filter.
        db_path:  Path to the QaLens SQLite database.

    Returns:
        An :class:`AnswerScope` with the newly failing test names.
    """
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection
    from qalens.llm.answer_plan import AnswerScope

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        runs = repo.list_runs(project=project, limit=2)
        if len(runs) < 2:
            return AnswerScope(label="NEWLY FAILING TESTS")
        newer_tests = repo.get_test_cases_for_run(runs[0].run_id)
        older_tests = repo.get_test_cases_for_run(runs[1].run_id)
    finally:
        conn.close()

    def _failed(status: str) -> bool:
        return status in ("failed", "broken")

    newer_map = {tc.name: tc for tc in newer_tests}
    older_map = {tc.name: tc for tc in older_tests}

    newly_failing = sorted(
        name
        for name, tc in newer_map.items()
        if _failed(tc.status) and not _failed((older_map[name].status if name in older_map else "passed"))
    )

    run_labels = [f"Run #{r.run_id}" for r in runs[:2]]

    return AnswerScope(
        tests=newly_failing,
        runs=run_labels,
        total=len(newly_failing),
        label="NEWLY FAILING TESTS",
    )


def _build_recent_flip_context(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    window: int = 5,
) -> str:
    """Return a **pre-formatted answer block** for the flakiness-history question.

    The block is ready to be copied verbatim by the LLM.  It contains:

    * A bold verdict line (Yes/No/Mixed).
    * A **Recently flaky** bullet list with flakiness scores, flip counts,
      and per-run status symbols (✅/❌).
    * A **Stable in the recent window** bullet list for tests with zero flips.
    * A **Why they were marked flaky** explanation footer.

    All arithmetic (flip counts, flaky-vs-stable classification) is done here
    so the LLM never has to re-count or re-classify.

    Internally constructs a :class:`StructuredPayload` and calls
    ``format_block()`` for consistent formatting.

    Args:
        project: Optional project name filter.
        db_path: Path to the QaLens SQLite database.
        window:  Rolling window size (default: 5 most recent runs).

    Returns:
        The fully formatted answer block, or a sentinel string when there is
        no scope data.
    """
    payload = _build_flakiness_binary_payload(
        project=project, db_path=db_path, window=window,
    )
    if payload is None:
        return "(no newly failing tests — window data not applicable)"
    return payload.format_block()


def _build_flakiness_binary_payload(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    window: int = 5,
) -> "StructuredPayload | None":
    """Build a :class:`StructuredPayload` for the flakiness-binary answer.

    Returns ``None`` when there are not enough runs or no newly failing tests.
    """
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection
    from qalens.analyzers.flaky import FlakyScorer
    from qalens.llm.answer_plan import PayloadSection, StructuredPayload

    def _failed(status: str) -> bool:
        return status in ("failed", "broken")

    # ── Identify newly failing tests (display_name, canonical_name) ──────────
    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        runs = repo.list_runs(project=project, limit=2)
        if len(runs) < 2:
            return None
        newer_tests = repo.get_test_cases_for_run(runs[0].run_id)
        older_tests = repo.get_test_cases_for_run(runs[1].run_id)
    finally:
        conn.close()

    newer_map = {tc.name: tc for tc in newer_tests}
    older_map = {tc.name: tc for tc in older_tests}

    newly_failing = sorted(
        (tc.name, tc.canonical_name)
        for name, tc in newer_map.items()
        if _failed(tc.status)
        and not _failed((older_map[name].status if name in older_map else "passed"))
    )

    if not newly_failing:
        return None

    total = len(newly_failing)

    # ── Fetch full history and compute flips in the rolling window ────────────
    conn2 = get_connection(db_path)
    try:
        scorer = FlakyScorer(conn2)
        flaky_items: list[str] = []
        stable_items: list[str] = []
        flaky_count = 0

        def _is_passing(s: str) -> bool:
            return s == "passed"

        for display_name, canonical_name in newly_failing:
            result = scorer.score(canonical_name, project=project, limit=30)
            recent = result.history[-window:] if result and result.history else []
            # Count flips using the same 3-state logic as _compute_flip_score:
            # only pass→fail and fail→pass count; skipped/unknown are ignored.
            flips = sum(
                1
                for i in range(1, len(recent))
                if (_is_passing(recent[i - 1]) and _failed(recent[i]))
                or (_failed(recent[i - 1]) and _is_passing(recent[i]))
            )
            flaky_pct = round(result.flip_score * 100) if result else 0
            # Use 3-state symbols: ✅ pass, ❌ fail/broken, ⏭ skipped/other
            symbols = " ".join(
                "\u274c" if _failed(s)
                else "\u2705" if _is_passing(s)
                else "\u23ed"
                for s in recent
            )
            actual_window = len(recent)
            if flips > 0:
                flaky_count += 1
                time_word = "time" if flips == 1 else "times"
                flaky_items.append(
                    f"- {display_name} \u2014 **{flaky_pct}%** flaky \u00b7 "
                    f"flipped {flips} {time_word} "
                    f"in the last {actual_window} runs ({symbols})"
                )
            else:
                stable_items.append(
                    f"- {display_name} \u2014 **{flaky_pct}%** flaky \u00b7 "
                    f"no flips in the last {actual_window} runs ({symbols})"
                )
    finally:
        conn2.close()

    # ── Verdict ───────────────────────────────────────────────────────────────
    if flaky_count == total:
        verdict = (
            f"**Yes \u2014 all {total} newly failing tests showed prior flakiness "
            f"in the recent pre-regression window.**"
        )
    elif flaky_count == 0:
        verdict = (
            f"**No \u2014 none of the {total} newly failing tests showed "
            f"flakiness before this regression.**"
        )
    else:
        verdict = (
            f"**Yes \u2014 {flaky_count} of the {total} newly failing tests "
            f"showed prior flakiness in the recent pre-regression window.**"
        )

    # ── Assemble payload ─────────────────────────────────────────────────────
    sections = [
        PayloadSection(
            heading="Recently flaky",
            items=flaky_items,
            empty=not flaky_items,
            format_hint="Bullet list with flakiness % and run symbols.",
        ),
        PayloadSection(
            heading="Stable in the recent window",
            items=stable_items,
            empty=not stable_items,
            format_hint="Bullet list with flakiness % and run symbols.",
        ),
        PayloadSection(
            heading="Why they were marked flaky",
            items=[
                "QaLens treats a test as flaky here based on recent pass\u2194fail "
                "switching before the regression, not total lifetime failures."
            ],
        ),
    ]

    return StructuredPayload(sections=sections, verdict=verdict)


def _build_regression_diff_payload(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
) -> "StructuredPayload | None":
    """Build a :class:`StructuredPayload` for the regression-diff answer.

    Categorises tests into Newly Failing, Recovered, Consistently Failing,
    and Consistently Passing sections with backend-computed counts.

    Returns ``None`` when there are fewer than 2 runs to compare.
    """
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection
    from qalens.llm.answer_plan import PayloadSection, StructuredPayload

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        runs = repo.list_runs(project=project, limit=2)
        if len(runs) < 2:
            return None
        newer_tests = repo.get_test_cases_for_run(runs[0].run_id)
        older_tests = repo.get_test_cases_for_run(runs[1].run_id)
    finally:
        conn.close()

    def _failed(status: str) -> bool:
        return status in ("failed", "broken")

    newer_map = {tc.name: tc for tc in newer_tests}
    older_map = {tc.name: tc for tc in older_tests}
    all_names = sorted(set(newer_map) | set(older_map))

    newly_failing: list[str] = []
    recovered: list[str] = []
    consistently_failing: list[str] = []
    consistently_passing: list[str] = []

    for name in all_names:
        newer_tc = newer_map.get(name)
        older_tc = older_map.get(name)
        newer_failed = _failed(newer_tc.status) if newer_tc else False
        older_failed = _failed(older_tc.status) if older_tc else False

        if newer_failed and not older_failed:
            newly_failing.append(name)
        elif not newer_failed and older_failed:
            recovered.append(name)
        elif newer_failed and older_failed:
            consistently_failing.append(name)
        else:
            consistently_passing.append(name)

    newer_run, older_run = runs[0], runs[1]
    newer_label = (
        f"Run #{newer_run.run_sequence}" if newer_run.run_sequence
        else newer_run.run_id
    )
    older_label = (
        f"Run #{older_run.run_sequence}" if older_run.run_sequence
        else older_run.run_id
    )

    verdict = (
        f"**Comparing {older_label} \u2192 {newer_label}: "
        f"+{len(newly_failing)} newly failing, "
        f"-{len(recovered)} recovered**"
    )

    nf_items = [f"- \u2717 {n}" for n in newly_failing]
    rec_items = [f"- \u2713 {n}" for n in recovered]
    cf_items = [f"- \u2717 {n}" for n in consistently_failing]

    sections = [
        PayloadSection(
            heading=f"Newly Failing ({len(newly_failing)})",
            items=nf_items,
            empty=not nf_items,
            format_hint="Group by root-cause from context; use \u274c per test, then 1-line error.",
        ),
        PayloadSection(
            heading=f"Recovered ({len(recovered)})",
            items=rec_items,
            empty=not rec_items,
            format_hint="Simple \u2713 list, no error details.",
        ),
        PayloadSection(
            heading=f"Consistently Failing ({len(consistently_failing)})",
            items=cf_items,
            empty=not cf_items,
        ),
        PayloadSection(
            heading=f"Consistently Passing ({len(consistently_passing)})",
            items=[f"{len(consistently_passing)} tests (not listed individually)"],
        ),
    ]

    return StructuredPayload(sections=sections, verdict=verdict)


def _extract_owner_from_question(question: str) -> str | None:
    """Extract a person or team name from an owner-related question.

    Recognises patterns like "tests owned by X", "assigned to X",
    "belonging to X", "tests by X", "maintained by X", etc.

    Args:
        question: The raw user question (not normalised, preserves case).

    Returns:
        The extracted name string, or ``None`` if no pattern matched.
    """
    import re as _re

    _OWNER_PATTERNS = [
        r"owned\s+by\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"assigned\s+to\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"belonging\s+to\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"tests\s+(?:for|by)\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"maintained\s+by\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"written\s+by\s+([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
        r"(?:^|[\s])owner\s+(?:is\s+)?([A-Za-z][A-Za-z0-9\s\-\.]+?)(?:\?|$|[,.])",
    ]
    for pat in _OWNER_PATTERNS:
        m = _re.search(pat, question, _re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _build_signals_header(signals: QuerySignals) -> str:
    """Build a ``[QUERY SIGNALS]`` preamble block for the context string.

    The block lists every active signal as a bullet point and appends a
    concise guardrail note reminding the model not to fabricate data for
    signals whose evidence is absent from the context.

    Args:
        signals: The detected signals.

    Returns:
        A multi-line string starting with ``[QUERY SIGNALS]``, or an empty
        string if no signals are active.
    """
    active: list[str] = []
    if signals.asks_about_risk:
        active.append("Risk prediction (next-run failure likelihood)")
    if signals.asks_about_duration:
        active.append("Duration / performance (execution time trends)")
    if signals.asks_about_stability:
        active.append("Stability (flaky / volatile / streak patterns)")
    if signals.asks_about_failures:
        active.append("Current failures (broken / failing tests)")
    if signals.asks_about_trend:
        active.append("Trend (improving / declining over time)")
    if signals.asks_about_history:
        active.append("History (run-level patterns)")
    if signals.asks_about_comparison:
        active.append("Comparison (A vs B / improved / degraded)")
    if signals.asks_about_root_cause:
        active.append("Root-cause analysis (why / explain / cause)")
    if signals.asks_about_suite:
        active.append("Suite / module grouping")
    if signals.asks_about_owner:
        active.append("Owner / team attribution")

    if not active:
        return ""

    lines = ["[QUERY SIGNALS]"]
    for item in active:
        lines.append(f"  - {item}")
    lines.append(
        "\nNote to model: Answer only from the evidence blocks that follow. "
        "Do not infer execution-time or duration trends from pass/fail data alone — "
        "only describe duration growth when duration_spike values are explicitly "
        "present in the data. "
        "If a requested signal has no supporting data in the context, say so explicitly "
        "rather than guessing."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ranking context builder (RANKING_LIST answer intent)
# ---------------------------------------------------------------------------


def gather_ranking_context(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    top_n: int = 20,
    min_runs: int = 2,
    metric: "RankingMetric | None" = None,
) -> tuple[str, str, list[dict]]:
    """Build a focused ranking context for "which tests are most X" queries.

    The sort column is determined by *metric* (defaults to FLAKINESS when
    ``None``).  Pre-computes the ranked list in backend code and returns it
    both as a ready-to-display ``structured_facts`` string (injected into
    ``[STRUCTURED FACTS]``) and as a fuller ``context_text`` block.  The LLM
    only narrates the pre-computed order — it does not re-infer rankings.

    Args:
        project:  Optional project name filter.
        db_path:  Path to the QaLens SQLite database.
        top_n:    Maximum number of tests to include.
        min_runs: Minimum run appearances required for classification.
        metric:   Which :class:`~qalens.llm.answer_plan.RankingMetric` to sort by.
                  ``None`` defaults to FLAKINESS.

    Returns:
        A 3-tuple of ``(context_text, structured_facts_text, sources)``.
    """
    from qalens.analyzers.flaky import FlakyScorer
    from qalens.db.schema import get_connection
    from qalens.llm.answer_plan import RankingMetric

    _metric = metric or RankingMetric.FLAKINESS

    # ── For RISK metric use the predictor ──────────────────────────────────
    if _metric == RankingMetric.RISK:
        return _gather_risk_ranking_context(
            project=project, db_path=db_path, top_n=top_n, min_runs=min_runs
        )

    conn = get_connection(db_path)
    try:
        scorer = FlakyScorer(conn)
        all_results = scorer.get_all(project=project, min_runs=min_runs)

        if _metric == RankingMetric.DURATION:
            ranked = _rank_by_duration(
                all_results, conn=conn, project=project, top_n=top_n
            )
        elif _metric == RankingMetric.FAILURE_BURDEN:
            ranked = sorted(
                all_results,
                key=lambda r: (-r.fail_count, -r.run_count),
            )[:top_n]
        else:  # FLAKINESS (default)
            ranked = sorted(
                all_results,
                key=lambda r: (-r.flip_score, r.pass_rate),
            )[:top_n]
    finally:
        conn.close()

    proj_label = project or "(all projects)"

    # ── Metric-specific column headers ─────────────────────────────────────
    if _metric == RankingMetric.FAILURE_BURDEN:
        metric_label = "failure_count"
        metric_hdr = f"{'fail_count':>10}"
        def _metric_val(r: object) -> str:
            return f"{r.fail_count:>10}"  # type: ignore[attr-defined]
    else:  # FLAKINESS
        metric_label = "flip_score"
        metric_hdr = f"{'flip_score':>10}"
        def _metric_val(r: object) -> str:
            return f"{r.flip_score:>10.2f}"  # type: ignore[attr-defined]

    parts: list[str] = []
    sources: list[dict] = []

    parts.append(f"=== Test Ranking ({metric_label}): {proj_label} ===")
    parts.append(
        f"Top {len(ranked)} of {len(all_results)} tests "
        f"(min {min_runs} runs, ranked by {metric_label} descending)."
    )
    parts.append(
        f"Columns: rank, test name, {metric_label}, "
        "pass_rate, runs, classification"
    )
    parts.append("")
    parts.append(
        f"{'Rank':>4}  {'Test Name':<42}  {metric_hdr}  "
        f"{'pass_rate':>9}  {'runs':>4}  classification"
    )
    parts.append("-" * 92)

    facts_rows: list[str] = [
        f"Ranking metric: {metric_label}",
        f"{'Rank':>4}  {'Test Name':<42}  {metric_hdr}  "
        f"{'pass_rate':>9}  {'runs':>4}  classification",
        "-" * 92,
    ]

    for i, r in enumerate(ranked, 1):
        row = (
            f"{i:>4}  {r.display_name:<42}  "
            f"{_metric_val(r)}  "
            f"{r.pass_rate:>8.0%}  "
            f"{r.run_count:>4}  "
            f"{r.classification.label}"
        )
        parts.append(row)
        facts_rows.append(row)
        sources.append({
            "type": "test",
            "icon": "\U0001f4ca",
            "label": r.display_name,
            "meta": (
                f"{metric_label}={_metric_val(r).strip()} \u00b7 "
                f"pass_rate={r.pass_rate:.0%} \u00b7 "
                f"{r.run_count} runs \u00b7 "
                f"{r.classification.label}"
            ),
            "canonical_name": r.canonical_name,
        })

    if not ranked:
        no_data = "(No tests with sufficient run history found.)"
        parts.append(no_data)
        facts_rows.append(no_data)

    context_text = "\n".join(parts).strip()
    structured_facts = "\n".join(facts_rows)
    return context_text, structured_facts, sources


def _rank_by_duration(
    flaky_results: list,
    *,
    conn: "sqlite3.Connection",
    project: str | None,
    top_n: int,
) -> list:
    """Sort *flaky_results* by average duration_ms from the DB."""
    import sqlite3 as _sqlite3

    # Build a map canonical_name → avg duration from the raw test_cases table
    project_filter = "AND LOWER(r.project) = LOWER(?)" if project else ""
    params: list = [project] if project else []

    sql = f"""
        SELECT
            tc.name,
            AVG(tc.duration_ms) AS avg_ms
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        WHERE tc.duration_ms IS NOT NULL
        {project_filter}
        GROUP BY tc.name
    """
    cur = conn.execute(sql, params)
    duration_map: dict[str, float] = {
        row["name"]: row["avg_ms"] for row in cur.fetchall()
    }

    # Annotate flaky results with avg_duration, sort desc
    annotated = []
    for r in flaky_results:
        avg_ms = duration_map.get(r.display_name) or duration_map.get(r.canonical_name) or 0.0
        annotated.append((avg_ms, r))
    annotated.sort(key=lambda x: -x[0])

    # Attach avg_ms as attribute so the row formatter can access it
    result = []
    for avg_ms, r in annotated[:top_n]:
        # We cannot mutate dataclass instances directly; wrap in a simple object
        class _Annotated:
            pass
        obj = _Annotated()
        obj.__dict__.update(r.__dict__)
        obj.avg_duration_ms = avg_ms
        obj.flip_score = r.flip_score
        obj.pass_rate = r.pass_rate
        obj.fail_count = r.fail_count
        obj.run_count = r.run_count
        obj.display_name = r.display_name
        obj.canonical_name = r.canonical_name
        obj.classification = r.classification
        result.append(obj)
    return result


def _gather_risk_ranking_context(
    *,
    project: str | None,
    db_path: "str | Path | None",
    top_n: int,
    min_runs: int,
) -> tuple[str, str, list[dict]]:
    """Ranking context sorted by predicted failure risk (RiskPredictor)."""
    from qalens.analyzers.predictor import RiskPredictor, RiskTier
    from qalens.db.schema import get_connection

    def _load_ranked_predictions() -> tuple[list, int]:
        conn = get_connection(db_path)
        try:
            predictor = RiskPredictor(conn)
            predictions = predictor.predict_all(project=project, min_runs=min_runs)
        finally:
            conn.close()

        _TIER_ORDER = {
            RiskTier.CRITICAL: 0,
            RiskTier.HIGH: 1,
            RiskTier.MEDIUM: 2,
            RiskTier.LOW: 3,
        }
        ranked_predictions = sorted(
            predictions,
            key=lambda p: (_TIER_ORDER.get(p.tier, 9), -p.risk_pct),
        )[:top_n]
        return ranked_predictions, len(predictions)

    ranked, total_predictions = _load_ranked_predictions()

    proj_label = project or "(all projects)"
    parts: list[str] = []
    facts_rows: list[str] = []
    sources: list[dict] = []

    parts.append(f"=== Test Ranking (risk_tier): {proj_label} ===")
    parts.append(
        f"Top {len(ranked)} of {total_predictions} tests "
        f"(ranked by predicted failure risk: CRITICAL > HIGH > MEDIUM > LOW)."
    )
    hdr = f"{'Rank':>4}  {'Test Name':<42}  {'risk_pct':>9}  {'tier':<10}  {'pass_rate':>9}"
    sep = "-" * 84
    parts.append("")
    parts.append(hdr)
    parts.append(sep)

    facts_rows.extend(["Ranking metric: risk_tier (CRITICAL > HIGH > MEDIUM > LOW)", hdr, sep])

    for i, p in enumerate(ranked, 1):
        row = (
            f"{i:>4}  {p.display_name:<42}  "
            f"{p.risk_pct:>8}%  "
            f"{p.tier.value:<10}  "
            f"{p.pass_rate:>8.0%}"
        )
        parts.append(row)
        facts_rows.append(row)
        sources.append({
            "type": "test",
            "icon": "\U0001f6a8",
            "label": p.display_name,
            "meta": f"{p.tier.value} \u00b7 {p.risk_pct}% risk \u00b7 pass_rate={p.pass_rate:.0%}",
            "canonical_name": p.canonical_name,
        })

    if not ranked:
        no_data = "(No tests with sufficient run history found.)"
        parts.append(no_data)
        facts_rows.append(no_data)

    return "\n".join(parts).strip(), "\n".join(facts_rows), sources


def _risk_driver_summary(prediction: object) -> str:
    """Return a compact human-readable risk-driver summary for narration."""
    signal_labels = [
        (getattr(prediction.signals, "volatility", 0.0), "high volatility"),
        (getattr(prediction.signals, "failure_burden", 0.0), "elevated failure burden"),
        (getattr(prediction.signals, "recent_decline", 0.0), "recent decline"),
        (getattr(prediction.signals, "fail_streak", 0.0), "active fail streak"),
        (getattr(prediction.signals, "duration_spike", 0.0), "duration slowdown"),
    ]
    top_labels = [label for value, label in sorted(signal_labels, key=lambda item: item[0], reverse=True) if value >= 0.15][:2]
    if len(top_labels) >= 2:
        return f"{top_labels[0]} + {top_labels[1]}"
    if top_labels:
        return top_labels[0]
    return "mixed historical risk signals"


def gather_risk_ranking_fact_bundle(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    top_n: int = 20,
    min_runs: int = 2,
    scope_label: str = "Selected run window",
) -> dict[str, object]:
    """Return a compact fact bundle for risk-ranking narration."""
    from qalens.analyzers.predictor import RiskPredictor, RiskTier
    from qalens.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        predictor = RiskPredictor(conn)
        predictions = predictor.predict_all(project=project, min_runs=min_runs)
    finally:
        conn.close()

    _TIER_ORDER = {
        RiskTier.CRITICAL: 0,
        RiskTier.HIGH: 1,
        RiskTier.MEDIUM: 2,
        RiskTier.LOW: 3,
    }
    ranked = sorted(
        predictions,
        key=lambda p: (_TIER_ORDER.get(p.tier, 9), -p.risk_pct),
    )[:top_n]
    high_risk = sum(1 for prediction in ranked if prediction.tier in (RiskTier.CRITICAL, RiskTier.HIGH))
    medium_risk = sum(1 for prediction in ranked if prediction.tier == RiskTier.MEDIUM)
    low_risk = sum(1 for prediction in ranked if prediction.tier == RiskTier.LOW)

    return {
        "type": "risk_ranking",
        "scope_label": scope_label,
        "eligible_tests": len(predictions),
        "high_risk": high_risk,
        "medium_risk": medium_risk,
        "low_risk": low_risk,
        "top_tests": [
            {
                "rank": index,
                "name": prediction.display_name,
                "tier": prediction.tier.value,
                "risk_pct": prediction.risk_pct,
                "pass_rate": round(prediction.pass_rate, 4),
                "driver": _risk_driver_summary(prediction),
            }
            for index, prediction in enumerate(ranked[:5], 1)
        ],
    }


# ---------------------------------------------------------------------------
# Comparison context builder (COMPARISON_CHANGE answer intent)
# ---------------------------------------------------------------------------


def _group_tests_by_cause(
    names: list[str],
    test_map: dict,
) -> list[dict]:
    """Group a list of test names by their root-cause category.

    Returns a list of group dicts, largest group first:
        {"label": str, "error_type": str, "tests": [str], "sample_error": str}
    """
    from collections import defaultdict

    try:
        from qalens.analyzers.categorizer import FailureCategory, categorize_failure
    except Exception:  # noqa: BLE001
        return [{"label": "Unknown", "error_type": "", "tests": names, "sample_error": ""}]

    # Key = (short_error_type, category_value) for fine-grained grouping
    buckets: dict[tuple, list[str]] = defaultdict(list)
    sample_errors: dict[tuple, str] = {}

    for name in names:
        tc = test_map.get(name)
        if tc is None:
            key = ("", "unknown")
            buckets[key].append(name)
            continue

        short_type = (tc.error_type or "").split(".")[-1]
        try:
            cat = categorize_failure(error_type=tc.error_type, message=tc.message)
            cat_val = cat.value if cat.value != "unknown" else ""
        except Exception:  # noqa: BLE001
            cat_val = ""

        key = (short_type, cat_val)
        buckets[key].append(name)
        if key not in sample_errors:
            msg_line = (tc.message or "").split("\n")[0][:120]
            sample_errors[key] = (
                f"{short_type}: {msg_line}" if (short_type and msg_line)
                else short_type or msg_line or "Unknown error"
            )

    result = []
    for (short_type, cat_val), test_names in sorted(
        buckets.items(), key=lambda kv: -len(kv[1])
    ):
        label = cat_val.replace("_", " ").title() if cat_val else (short_type or "Unknown")
        result.append({
            "label": label,
            "error_type": short_type,
            "tests": test_names,
            "sample_error": sample_errors.get((short_type, cat_val), ""),
        })
    return result


def gather_comparison_context(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    n_runs: int = 2,
    is_trend: bool = False,
) -> tuple[str, str, list[dict]]:
    """Build a diff-view context for "compare the last N runs" queries.

    Fetches the *n_runs* most-recent runs and categorises each test into one
    of four change groups: Newly Failing, Recovered, Consistently Failing,
    Consistently Passing.

    When *is_trend* is ``True``, fetches 5 runs instead of 2 and prepends
    a ``[TREND ANALYSIS]`` block to the structured facts using pre-computed
    pass-rate trend direction and confidence from :mod:`qalens.llm.trend`.

    Args:
        project:   Optional project name filter.
        db_path:   Path to the QaLens SQLite database.
        n_runs:    Number of most-recent runs to compare (minimum 2).
        is_trend:  When True, use 5 runs and compute trend metrics.

    Returns:
        A 3-tuple of ``(context_text, structured_facts_text, sources)``.
    """
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    fetch_limit = max(n_runs, 5) if is_trend else n_runs
    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        runs = repo.list_runs(project=project, limit=fetch_limit)
        if len(runs) < 2:
            msg = (
                f"Not enough runs to compare "
                f"(found {len(runs)}, need at least 2)."
            )
            return msg, "", []
        newer_run = runs[0]
        older_run = runs[-1]
        newer_tests = repo.get_test_cases_for_run(newer_run.run_id)
        older_tests = repo.get_test_cases_for_run(older_run.run_id)
    finally:
        conn.close()

    def _failed(status: str) -> bool:
        return status in ("failed", "broken")

    newer_map = {tc.name: tc for tc in newer_tests}
    older_map = {tc.name: tc for tc in older_tests}
    all_names = sorted(set(newer_map) | set(older_map))

    newly_failing: list[str] = []
    recovered: list[str] = []
    consistently_failing: list[str] = []
    consistently_passing: list[str] = []

    for name in all_names:
        newer_tc = newer_map.get(name)
        older_tc = older_map.get(name)
        newer_failed = _failed(newer_tc.status) if newer_tc else False
        older_failed = _failed(older_tc.status) if older_tc else False

        if newer_failed and not older_failed:
            newly_failing.append(name)
        elif not newer_failed and older_failed:
            recovered.append(name)
        elif newer_failed and older_failed:
            consistently_failing.append(name)
        else:
            consistently_passing.append(name)

    newer_label = (
        f"Run #{newer_run.run_sequence}" if newer_run.run_sequence
        else newer_run.run_id
    )
    older_label = (
        f"Run #{older_run.run_sequence}" if older_run.run_sequence
        else older_run.run_id
    )

    # For trend queries we fetched multiple runs; card meta should reflect
    # the full range analysed, not just the two boundary runs.
    if is_trend:
        _card_comparison_meta = f"Runs {older_label}\u2013{newer_label}"
        _card_consistent_meta = f"Across {older_label}\u2013{newer_label}"
    else:
        _card_comparison_meta = f"{newer_label} vs {older_label}"
        _card_consistent_meta = f"Both {older_label} and {newer_label}"

    parts: list[str] = []
    sources: list[dict] = []

    proj_label = project or "(all projects)"
    parts.append(f"=== Run Comparison: {proj_label} ===")
    parts.append(f"Comparing {older_label} (older) \u2192 {newer_label} (newer)")
    parts.append(
        f"Net change: +{len(newly_failing)} newly failing, "
        f"-{len(recovered)} recovered"
    )
    parts.append("")

    if newly_failing:
        # Build root-cause groups first; if useful compression exists, use
        # ONLY the grouped view so the LLM doesn't reproduce a flat list too.
        groups = _group_tests_by_cause(newly_failing, newer_map)
        use_groups = len(groups) < len(newly_failing)

        if not use_groups:
            # No compression possible — fall back to individual flat list
            parts.append(f"--- Newly Failing ({len(newly_failing)}) ---")
            for name in newly_failing:
                tc = newer_map[name]
                msg_suffix = ""
                if tc.message:
                    msg_suffix = "  \u2192 " + tc.message.split("\n")[0][:100]
                parts.append(f"  \u2717 {name}{msg_suffix}")
            parts.append("")
        else:
            # Grouped view — emit ONLY this section (suppresses flat list to
            # prevent the LLM from reproducing both)
            parts.append(
                f"--- Newly Failing ({len(newly_failing)}) — grouped by root cause "
                f"[build your output from these groups, do NOT output a flat list] ---"
            )
            for g in groups:
                test_list = ", ".join(g["tests"])
                n = len(g["tests"])
                parts.append(
                    f"  GROUP-ERROR-TYPE: {g['label']}  |  COUNT: {n}  |  TESTS: {test_list}"
                )
                if g["sample_error"]:
                    parts.append(f"    GROUP-SAMPLE-ERROR: {g['sample_error']}")
            parts.append("")

        sources.append({
            "type": "run",
            "icon": "\U0001f4c9",
            "label": f"Newly Failing ({len(newly_failing)} tests)",
            "meta": _card_comparison_meta,
            "run_id": newer_run.run_id,
            "vs_run_id": older_run.run_id,
            "category": "newly_failing",
        })

    if recovered:
        parts.append(f"--- Recovered ({len(recovered)}) ---")
        for name in recovered:
            parts.append(f"  \u2713 {name}")
        parts.append("")
        sources.append({
            "type": "run",
            "icon": "\U0001f4c8",
            "label": f"Recovered ({len(recovered)} tests)",
            "meta": _card_comparison_meta,
            "run_id": newer_run.run_id,
            "vs_run_id": older_run.run_id,
            "category": "recovered",
        })

    if consistently_failing:
        parts.append(f"--- Consistently Failing ({len(consistently_failing)}) ---")
        for name in consistently_failing:
            parts.append(f"  \u2717 {name}")
        parts.append("")
        sources.append({
            "type": "run",
            "icon": "\u26a0\ufe0f",
            "label": f"Consistently Failing ({len(consistently_failing)} tests)",
            "meta": _card_consistent_meta,
            "run_id": newer_run.run_id,
            "vs_run_id": older_run.run_id,
            "category": "consistently_failing",
        })

    parts.append(
        f"Consistently Passing: {len(consistently_passing)} tests "
        f"(not listed individually)"
    )

    context_text = "\n".join(parts).strip()

    # Build a compact structured_facts block: summary counts for the LLM
    facts_lines = [
        f"Run comparison: {older_label} → {newer_label}",
        f"Newly Failing: {len(newly_failing)}",
        f"Recovered:     {len(recovered)}",
        f"Consistently Failing: {len(consistently_failing)}",
        f"Consistently Passing: {len(consistently_passing)}",
    ]
    if newly_failing:
        facts_lines.append("Newly failing tests: " + ", ".join(newly_failing[:10]))
    if recovered:
        facts_lines.append("Recovered tests: " + ", ".join(recovered[:10]))
    if consistently_failing:
        facts_lines.append("Consistently failing: " + ", ".join(consistently_failing[:10]))

    # Add pre-grouped newly-failing root-cause summary to facts
    if newly_failing:
        nf_groups = _group_tests_by_cause(newly_failing, newer_map)
        if nf_groups:
            facts_lines.append("")
            facts_lines.append("Newly failing — root-cause groups:")
            for g in nf_groups:
                facts_lines.append(
                    f"  GROUP-ERROR-TYPE: {g['label']}  |  COUNT: {len(g['tests'])}  |  TESTS: "
                    + ", ".join(g["tests"])
                )
                if g["sample_error"]:
                    facts_lines.append(f"    GROUP-SAMPLE-ERROR: {g['sample_error']}")

    structured_facts = "\n".join(facts_lines)

    # ── Trend analysis (injected when caller is a trend question) ──────────
    if is_trend:
        from qalens.llm.trend import RunRate, compute_trend, render_trend_facts

        # Build RunRate list: runs is newest-first, reverse to oldest-first
        trend_run_data: list[RunRate] = []
        for r in reversed(runs):
            total = r.total_tests or 0
            passed = r.passed_count or 0
            failed = r.failed_count or 0
            label = f"Run #{r.run_sequence}" if r.run_sequence else r.run_id[:8]
            trend_run_data.append(
                RunRate(
                    label=label,
                    pass_rate=passed / total if total else 0.0,
                    passed=passed,
                    failed=failed,
                    total=total,
                )
            )
        trend = compute_trend(trend_run_data)
        trend_block = render_trend_facts(
            trend,
            newly_failing=len(newly_failing),
            recovered=len(recovered),
            consistently_failing=len(consistently_failing),
        )
        structured_facts = trend_block + "\n\n" + structured_facts

    return context_text, structured_facts, sources

# ---------------------------------------------------------------------------
# Recommendation context builder (RECOMMENDATION_ACTION answer intent)
# ---------------------------------------------------------------------------


def gather_recommendation_context(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    top_n_risk: int = 10,
    top_n_flaky: int = 5,
    min_runs: int = 2,
) -> tuple[str, str, list[dict]]:
    """Focused context for "what should I fix / prioritize" queries.

    Returns a compact snapshot: top-N risk-tier tests + top-N flip_score
    tests.  Intentionally omits the full project dump so the LLM stays
    focused on actionable items.

    Args:
        project:      Optional project name filter.
        db_path:      Path to the QaLens SQLite database.
        top_n_risk:   Number of highest-risk tests to include.
        top_n_flaky:  Number of flakiest tests to include.
        min_runs:     Minimum run appearances for stability stats.

    Returns:
        A 3-tuple of ``(context_text, structured_facts_text, sources)``.
    """
    from qalens.analyzers.flaky import FlakyScorer
    from qalens.analyzers.predictor import RiskPredictor, RiskTier
    from qalens.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        predictor = RiskPredictor(conn)
        predictions = predictor.predict_all(project=project, min_runs=min_runs)
        scorer = FlakyScorer(conn)
        flaky_results = scorer.get_all(project=project, min_runs=min_runs)
    finally:
        conn.close()

    _TIER_ORDER = {
        RiskTier.CRITICAL: 0,
        RiskTier.HIGH: 1,
        RiskTier.MEDIUM: 2,
        RiskTier.LOW: 3,
    }
    top_risk = sorted(
        predictions, key=lambda p: (_TIER_ORDER.get(p.tier, 9), -p.risk_pct)
    )[:top_n_risk]
    top_flaky = sorted(
        flaky_results, key=lambda r: (-r.flip_score, r.pass_rate)
    )[:top_n_flaky]

    parts: list[str] = []
    facts_rows: list[str] = []
    sources: list[dict] = []

    proj_label = project or "(all projects)"
    parts.append(f"=== Recommendation Context: {proj_label} ===")

    parts.append(f"\n--- Top {len(top_risk)} High-Risk Tests (by predicted failure likelihood) ---")
    facts_rows.append(f"Top {len(top_risk)} by risk:")
    for i, p in enumerate(top_risk, 1):
        row = f"  {i}. {p.display_name} — {p.tier.value} ({p.risk_pct}% risk, pass_rate={p.pass_rate:.0%})"
        parts.append(row)
        facts_rows.append(row)
        sources.append({
            "type": "test",
            "icon": "\U0001f6a8",
            "label": p.display_name,
            "meta": f"{p.tier.value} \u00b7 {p.risk_pct}% risk",
            "canonical_name": p.canonical_name,
        })

    parts.append(f"\n--- Top {len(top_flaky)} Flakiest Tests (by flip_score) ---")
    facts_rows.append(f"\nTop {len(top_flaky)} by flakiness:")
    for i, r in enumerate(top_flaky, 1):
        row = f"  {i}. {r.display_name} — flip_score={r.flip_score:.2f}, pass_rate={r.pass_rate:.0%}"
        parts.append(row)
        facts_rows.append(row)
        if not any(s.get("canonical_name") == r.canonical_name for s in sources):
            sources.append({
                "type": "test",
                "icon": "\U0001f4ca",
                "label": r.display_name,
                "meta": f"flip_score={r.flip_score:.2f} \u00b7 pass_rate={r.pass_rate:.0%}",
                "canonical_name": r.canonical_name,
            })

    context_text = "\n".join(parts).strip()
    structured_facts = "\n".join(facts_rows)
    return context_text, structured_facts, sources


# ---------------------------------------------------------------------------
# Summary context builder (SUMMARY_OVERVIEW answer intent)
# ---------------------------------------------------------------------------


def gather_summary_context(
    *,
    project: str | None = None,
    db_path: "str | Path | None" = None,
    max_failures: int = 10,
    min_runs: int = 2,
) -> tuple[str, str, list[dict]]:
    """Focused context for high-level summary queries.

    Returns latest run stats + top failures + flaky test count.  Capped at
    *max_failures* entries to prevent over-broad context.

    Args:
        project:      Optional project name filter.
        db_path:      Path to the QaLens SQLite database.
        max_failures: Maximum number of failing tests to list.
        min_runs:     Minimum run appearances for stability stats.

    Returns:
        A 3-tuple of ``(context_text, structured_facts_text, sources)``.
    """
    from qalens.analyzers.flaky import FlakyClassification, FlakyScorer
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        runs = repo.list_runs(project=project, limit=5)
        if not runs:
            empty = "No run data available for this project."
            return empty, empty, []
        latest_run = runs[0]
        latest_tests = repo.get_test_cases_for_run(latest_run.run_id)
        prev_tests = repo.get_test_cases_for_run(runs[1].run_id) if len(runs) >= 2 else []
        scorer = FlakyScorer(conn)
        flaky_results = scorer.get_all(project=project, min_runs=min_runs)
    finally:
        conn.close()

    passed = sum(1 for tc in latest_tests if tc.status == "passed")
    failed = sum(1 for tc in latest_tests if tc.status in ("failed", "broken"))
    skipped = sum(1 for tc in latest_tests if tc.status == "skipped")
    total = len(latest_tests)
    pass_pct = (passed / total * 100) if total else 0

    flaky_count = sum(
        1 for r in flaky_results
        if r.classification in (FlakyClassification.FLAKY,)
    )
    broken_count = sum(
        1 for r in flaky_results
        if r.classification.label in ("CONSISTENTLY_FAILING",)
    )

    failing_tests = [tc for tc in latest_tests if tc.status in ("failed", "broken")]

    run_label = (
        f"Run #{latest_run.run_sequence}" if latest_run.run_sequence
        else latest_run.run_id
    )

    parts: list[str] = []
    facts_rows: list[str] = []
    sources: list[dict] = []

    proj_label = project or "(all projects)"
    parts.append(f"=== Project Summary: {proj_label} ===")
    summary_line = (
        f"Latest run ({run_label}): {total} tests — "
        f"{passed} passed ({pass_pct:.0f}%), {failed} failed, {skipped} skipped."
    )
    parts.append(summary_line)
    facts_rows.append(summary_line)

    trend_line = (
        f"Stability: {flaky_count} flaky test(s), "
        f"{broken_count} consistently failing test(s) across recent runs."
    )
    parts.append(trend_line)
    facts_rows.append(trend_line)

    sources.append({
        "type": "run",
        "icon": "\U0001f4cb",
        "label": run_label,
        "meta": f"{passed}/{total} passed \u00b7 {failed} failed",
        "run_id": latest_run.run_id,
    })

    if failing_tests:
        parts.append(f"\nTop failing tests in {run_label} (up to {max_failures}):")
        facts_rows.append(f"\nFailing tests ({min(len(failing_tests), max_failures)}):")
        for tc in failing_tests[:max_failures]:
            msg = ""
            if tc.message:
                msg = "  \u2192 " + tc.message.split("\n")[0][:80]
            row = f"  \u2717 {tc.name}{msg}"
            parts.append(row)
            facts_rows.append(row)

    # ── Delta: what changed between previous run and latest run ──────────────
    _FAILING = {"failed", "broken"}
    if prev_tests and latest_tests:
        prev_run = runs[1]
        prev_label = (
            f"Run #{prev_run.run_sequence}" if prev_run.run_sequence
            else prev_run.run_id[:8]
        )
        latest_by_c = {tc.canonical_name: tc for tc in latest_tests}
        prev_by_c = {tc.canonical_name: tc for tc in prev_tests}

        fixed = [
            tc for cname, tc in latest_by_c.items()
            if tc.status == "passed"
            and cname in prev_by_c
            and prev_by_c[cname].status in _FAILING
        ]
        new_fail = [
            tc for cname, tc in latest_by_c.items()
            if tc.status in _FAILING
            and cname in prev_by_c
            and prev_by_c[cname].status == "passed"
        ]

        delta_header = (
            f"\n--- Changes: {prev_label} \u2192 {run_label} "
            f"(FIXED={len(fixed)}  NEW FAILURES={len(new_fail)}) ---"
        )
        parts.append(delta_header)
        facts_rows.append(delta_header)

        if fixed:
            line = f"  Tests FIXED in {run_label} (were failing in {prev_label}):"
            parts.append(line); facts_rows.append(line)
            for tc in fixed:
                prev_tc = prev_by_c[tc.canonical_name]
                prev_err = (prev_tc.error_type or "").split(".")[-1] if prev_tc.error_type else ""
                row = f"    \u2713 {tc.name}" + (f"  [was: {prev_err}]" if prev_err else "")
                parts.append(row); facts_rows.append(row)
        else:
            line = f"  No tests were fixed in {run_label}."
            parts.append(line); facts_rows.append(line)

        if new_fail:
            line = f"  Tests NEWLY FAILING in {run_label} (were passing in {prev_label}):"
            parts.append(line); facts_rows.append(line)
            for tc in new_fail:
                err = (tc.error_type or "").split(".")[-1] if tc.error_type else ""
                row = f"    \u2717 {tc.name}" + (f"  [{err}]" if err else "")
                parts.append(row); facts_rows.append(row)
        else:
            line = f"  No new failures in {run_label}."
            parts.append(line); facts_rows.append(line)

    context_text = "\n".join(parts).strip()
    structured_facts = "\n".join(facts_rows)
    return context_text, structured_facts, sources


# ---------------------------------------------------------------------------
# Specific-run context
# ---------------------------------------------------------------------------


_RUN_NUMBER_RE = re.compile(
    r"\brun\s*(?:no\.?|number|#|num\.?)?\s*(\d{1,5})\b",
    re.IGNORECASE,
)


def _extract_run_number_from_question(question: str) -> int | None:
    """Return the run sequence number mentioned in *question*, or ``None``.

    Recognises patterns like:
    * "Run No 18" / "run no. 18"
    * "Run #18" / "run#18"
    * "run number 18"
    * "run 18"

    Args:
        question: The raw user question.

    Returns:
        Integer run sequence number, or ``None`` if no match.
    """
    m = _RUN_NUMBER_RE.search(question)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def gather_specific_run_context(
    *,
    run_number: int,
    project: str | None = None,
    db_path: "str | Path | None" = None,
) -> tuple[str, str, list[dict]]:
    """Build context for a question about a specific run by sequence number.

    Returns all test cases for the run, with failures listed first.

    Args:
        run_number: The ``run_sequence`` value (1-based integer shown to users).
        project:    Optional project name filter.
        db_path:    Path to the QaLens SQLite database.

    Returns:
        A 3-tuple of ``(context_text, structured_facts_text, sources)``.  When
        no run with that sequence exists returns ``("", "", [])``.
    """
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        run = repo.get_run_by_sequence(run_number, project=project)
        if run is None:
            return "", "", []
        test_cases = repo.get_test_cases_for_run(run.run_id)
    finally:
        conn.close()

    run_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id

    passed = [tc for tc in test_cases if tc.status == "passed"]
    failed = [tc for tc in test_cases if tc.status in ("failed", "broken")]
    skipped = [tc for tc in test_cases if tc.status == "skipped"]
    total = len(test_cases)
    pass_pct = (len(passed) / total * 100) if total else 0

    parts: list[str] = []
    facts: list[str] = []
    sources: list[dict] = []

    header = f"=== {run_label} \u2014 {run.project or 'unknown project'} ==="
    parts.append(header)
    stats_line = (
        f"Total: {total}  Passed: {len(passed)} ({pass_pct:.0f}%)  "
        f"Failed: {len(failed)}  Skipped: {len(skipped)}"
    )
    parts.append(stats_line)
    facts.append(stats_line)

    sources.append({
        "type": "run",
        "icon": "\U0001f4cb",
        "label": run_label,
        "meta": f"{len(passed)}/{total} passed \u00b7 {len(failed)} failed",
        "run_id": run.run_id,
    })

    if failed:
        parts.append(f"\nFailed tests ({len(failed)}):")
        facts.append(f"Failed tests ({len(failed)}):")
        for tc in failed:
            msg = ""
            if tc.message:
                first_line = tc.message.split("\n")[0][:120]
                msg = f"  \u2192 {first_line}"
            err = ""
            if tc.error_type:
                short = tc.error_type.split(".")[-1]
                err = f" [{short}]"
            row = f"  \u2717 {tc.name}{err}{msg}"
            parts.append(row)
            facts.append(row)
    else:
        no_fail = "No failed tests in this run."
        parts.append(no_fail)
        facts.append(no_fail)

    if passed:
        parts.append(f"\nPassed tests ({len(passed)}):")
        for tc in passed:
            parts.append(f"  \u2713 {tc.name}")

    if skipped:
        parts.append(f"\nSkipped tests ({len(skipped)}):")
        for tc in skipped:
            parts.append(f"  \u25cb {tc.name}")

    context_text = "\n".join(parts).strip()
    structured_facts = "\n".join(facts)
    return context_text, structured_facts, sources
