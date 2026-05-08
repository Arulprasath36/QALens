"""Deterministic follow-up question generator for QARA chat.

Follow-ups are driven by the current **answer scope** and **answer type**,
not by source cards.  This ensures every suggested question references only
entities present in the answer the user just received.

Architecture::

    AnswerPlan  (answer_type + scope + payload)
         │
         ▼
    _GENERATORS_BY_TYPE[answer_type](scope, payload)
         │
         ▼
    _validate_grounding(candidates, scope, sources)
         │
         ▼
    up to 3 grounded follow-up questions

Sources are *optional supporting metadata*.  They provide entity names only
when the answer scope is empty and must never override scope entities.

Public API
----------
``generate_follow_ups(answer_plan_or_intent, sources, *, question) -> list[str]``
"""

from __future__ import annotations

from typing import Any

from qara.llm.answer_types import AnswerIntent, AnswerScope, AnswerType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FALLBACK: list[str] = [
    "Which test suite is most affected?",
    "Has this pattern appeared in previous runs?",
    "What should I investigate first?",
]

_SAFE_GENERIC: list[str] = [
    "Which of these tests should we investigate first?",
    "Show more detail for these failures",
    "Which of these failures is most likely environmental?",
]


def _label(s: dict[str, Any]) -> str:
    return (s.get("label") or "").strip()


def _test_names_from_sources(sources: list[dict[str, Any]]) -> list[str]:
    """Extract distinct test display-names from source cards (fallback only)."""
    seen: set[str] = set()
    names: list[str] = []
    for s in sources:
        if s.get("type") == "test":
            n = _label(s)
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def _run_labels_from_sources(sources: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    labels: list[str] = []
    for s in sources:
        if s.get("type") == "run":
            lbl = _label(s)
            if lbl and lbl not in seen:
                seen.add(lbl)
                labels.append(lbl)
    return labels


def _effective_scope(
    plan: "AnswerPlan",  # type: ignore[name-defined]
    sources: list[dict[str, Any]],
) -> AnswerScope:
    """Return the best available scope: plan.scope > source-derived > empty.

    When ``plan.scope`` is already populated (e.g. from routing.py), use it
    directly.  Otherwise build a lightweight scope from *sources* so that
    generators still have test/run names to work with, then attach it back
    to *plan* for downstream validation.
    """
    if plan.scope and plan.scope.tests:
        return plan.scope

    # Derive a fallback scope from source cards.
    tests = _test_names_from_sources(sources)
    runs = _run_labels_from_sources(sources)
    if tests or runs:
        scope = AnswerScope(
            tests=tests,
            runs=runs,
            total=len(tests),
            label="SOURCE-DERIVED",
        )
        plan.scope = scope
        return scope

    return AnswerScope()


# ---------------------------------------------------------------------------
# Entity grounding validation
# ---------------------------------------------------------------------------


def _validate_grounding(
    candidates: list[str],
    scope: AnswerScope,
    sources: list[dict[str, Any]],
) -> list[str]:
    """Reject follow-up candidates that reference out-of-scope entities.

    If a candidate mentions a *specific* test/run name extracted from
    *sources* that is NOT present in *scope*, the candidate is dropped.
    Generic phrases (e.g. "these tests") are always safe.

    Returns the validated subset, preserving original order.
    """
    if not scope.tests:
        return candidates  # No scope boundary — allow everything.

    scope_tests = set(scope.tests)
    scope_runs = set(scope.runs) if scope.runs else set()

    # Collect source-card entity names that are NOT in the current scope.
    out_of_scope: set[str] = set()
    for s in sources:
        name = _label(s)
        if not name:
            continue
        if s.get("type") == "test" and name not in scope_tests:
            out_of_scope.add(name)
        elif s.get("type") == "run" and name not in scope_runs:
            # Only reject specific run labels, not summary cards like
            # "Newly Failing (3 tests)".
            if "(" not in name:
                out_of_scope.add(name)

    if not out_of_scope:
        return candidates  # All source entities are in scope — no risk.

    validated: list[str] = []
    for c in candidates:
        if any(name in c for name in out_of_scope):
            continue
        validated.append(c)
    return validated


# ---------------------------------------------------------------------------
# Payload introspection helpers
# ---------------------------------------------------------------------------


def _payload_verdict_polarity(payload: Any) -> str | None:
    """Classify a StructuredPayload's verdict as ``"all"``, ``"some"``, ``"none"``, or *None*.

    Used by generators to branch follow-up suggestions based on the backend
    verdict (e.g. flakiness-binary: all-flaky vs none-flaky).
    """
    if payload is None or not getattr(payload, "verdict", None):
        return None
    v = payload.verdict.lower()
    if v.startswith("**no"):
        return "none"
    if "all" in v and "yes" in v:
        return "all"
    if "yes" in v:
        return "some"
    return None


def _payload_section_count(payload: Any, prefix: str) -> int | None:
    """Return the item count of the first payload section whose heading starts with *prefix*.

    Returns *None* when the payload is absent or no matching section exists.
    """
    if payload is None:
        return None
    for sec in getattr(payload, "sections", []):
        if sec.heading.startswith(prefix) and not sec.empty:
            return len(sec.items)
    return None


# ---------------------------------------------------------------------------
# Per-answer-type generators
#
# Each generator receives (scope, payload) and returns up to 4 candidates
# (the extra allows _validate_grounding to drop one and still return 3).
# ---------------------------------------------------------------------------


def _followups_regression_diff(scope: AnswerScope, payload: Any) -> list[str]:
    tests = scope.tests
    recovered = _payload_section_count(payload, "Recovered")
    out: list[str] = []
    if tests:
        out.append(f"Why did {tests[0]} start failing?")
    if len(tests) >= 2:
        out.append(f"Are {tests[0]} and {tests[1]} failing for the same reason?")
    if recovered:
        out.append("Are any of the recovered tests at risk of failing again?")
    out.append("Were any of these tests flaky before this regression?")
    out.append("Which of these newly failing tests should I investigate first?")
    return out[:4]


def _followups_flakiness_binary(scope: AnswerScope, payload: Any) -> list[str]:
    """Follow-ups after a binary flakiness verdict (Yes/No + tiers).

    When the backend payload is available, the verdict polarity drives
    which follow-ups are most relevant.
    """
    polarity = _payload_verdict_polarity(payload)
    if polarity == "none":
        return [
            "What are the likely root causes for these stable tests suddenly failing?",
            "Are there any newly failing tests that were completely stable before?",
            "What should I prioritise investigating given these are genuine regressions?",
        ]
    if polarity == "all":
        return [
            "Which of the newly failing tests have the worst pre-existing flakiness?",
            "Should I quarantine the flaky tests and focus on real regressions?",
            "What should I prioritise investigating given this flakiness pattern?",
        ]
    # "some" or unknown — mixed/fallback
    return [
        "Which of the newly failing tests have the worst pre-existing flakiness?",
        "Are there any newly failing tests that were completely stable before?",
        "What should I prioritise investigating given this flakiness pattern?",
    ]


def _followups_flakiness_ranking(scope: AnswerScope, payload: Any) -> list[str]:
    """Follow-ups after a flakiness-ranking answer."""
    return [
        "Which newly failing tests are the most reliable regression signals?",
        "Why are the newly failing tests with no prior flakiness failing now?",
        "Should I quarantine the highly flaky tests and focus on the stable ones?",
    ]


def _followups_risk_ranking(scope: AnswerScope, payload: Any) -> list[str]:
    tests = scope.tests
    out: list[str] = []
    if tests:
        out.append(f"What is causing {tests[0]} to be high risk?")
    if len(tests) >= 2:
        out.append(f"Show the failure history for {tests[1]}")
    out.append("Which high-risk tests belong to the same module?")
    out.append("Which of these high-risk tests should we fix first?")
    return out[:4]


def _followups_trend(scope: AnswerScope, payload: Any) -> list[str]:
    runs = scope.runs
    out: list[str] = []
    if runs:
        out.append(f"What changed between {runs[0]} and the previous run?")
    out.append("Which failure group is driving the pass-rate drop?")
    out.append("Are there any tests that recovered recently?")
    out.append("Which tests are contributing most to the declining trend?")
    return out[:4]


def _followups_root_cause(scope: AnswerScope, payload: Any) -> list[str]:
    tests = scope.tests
    out: list[str] = []
    if tests:
        out.append(f"Has {tests[0]} been fixed in any recent run?")
    out.append("Are other tests failing for the same root cause?")
    if len(tests) >= 2:
        out.append(f"Show the full error for {tests[1]}")
    else:
        out.append("What should I fix first to have the most impact?")
    return out[:4]


def _followups_detail(scope: AnswerScope, payload: Any) -> list[str]:
    tests = scope.tests
    runs = scope.runs
    out: list[str] = []
    if tests:
        out.append(f"What is the failure history of {tests[0]}?")
    if runs:
        out.append(f"Show all failures in {runs[0]}")
    out.append("Has this test ever passed consistently?")
    out.append("Show more detail for these failures")
    return out[:4]


def _followups_recommendation(scope: AnswerScope, payload: Any) -> list[str]:
    tests = scope.tests
    out: list[str] = []
    if tests:
        out.append(f"How do I fix {tests[0]}?")
    out.append("Which failures would have the highest impact if resolved?")
    out.append("Are there quick wins — tests that just need a retry policy?")
    return out[:4]


def _followups_summary(scope: AnswerScope, payload: Any) -> list[str]:
    runs = scope.runs
    nf_count = _payload_section_count(payload, "Newly Failing")
    out: list[str] = []
    if runs:
        out.append(f"What failed most in {runs[0]}?")
    if nf_count:
        out.append(f"Why did these {nf_count} tests start failing?")
    else:
        out.append("Which tests are at highest risk of failing next run?")
    out.append("Show me what's been consistently failing across runs")
    return out[:4]


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

_GENERATORS_BY_TYPE: dict[AnswerType, Any] = {
    AnswerType.REGRESSION_DIFF:     _followups_regression_diff,
    AnswerType.FLAKINESS_BINARY:    _followups_flakiness_binary,
    AnswerType.FLAKINESS_RANKING:   _followups_flakiness_ranking,
    AnswerType.RISK_RANKING:        _followups_risk_ranking,
    AnswerType.TREND:               _followups_trend,
    AnswerType.ROOT_CAUSE:          _followups_root_cause,
    AnswerType.DETAIL:              _followups_detail,
    AnswerType.RECOMMENDATION:      _followups_recommendation,
    AnswerType.SUMMARY:             _followups_summary,
}

# Legacy intent → type mapping for backward-compatible calls that pass
# AnswerIntent instead of AnswerPlan.
_INTENT_TO_TYPE: dict[AnswerIntent, AnswerType] = {
    AnswerIntent.NEW_REGRESSIONS:        AnswerType.REGRESSION_DIFF,
    AnswerIntent.RANKING_LIST:           AnswerType.RISK_RANKING,
    AnswerIntent.DIAGNOSTIC_ROOT_CAUSE:  AnswerType.ROOT_CAUSE,
    AnswerIntent.COMPARISON_CHANGE:      AnswerType.REGRESSION_DIFF,
    AnswerIntent.DRILL_DOWN_DETAIL:      AnswerType.DETAIL,
    AnswerIntent.RECOMMENDATION_ACTION:  AnswerType.RECOMMENDATION,
    AnswerIntent.SUMMARY_OVERVIEW:       AnswerType.SUMMARY,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_follow_ups(
    answer_plan_or_intent: "AnswerPlan | AnswerIntent",  # type: ignore[name-defined]
    sources: list[dict[str, Any]] | None = None,
    *,
    question: str = "",
) -> list[str]:
    """Return up to 3 answer-scope-driven follow-up question strings.

    Parameters
    ----------
    answer_plan_or_intent:
        An :class:`~qara.llm.answer_plan.AnswerPlan` (preferred) or a bare
        :class:`~qara.llm.answer_types.AnswerIntent` (backward-compatible).
        When an ``AnswerPlan`` is supplied, its ``answer_type``, ``scope``,
        and ``payload`` drive follow-up generation.
    sources:
        Optional source-card list.  Used as a fallback to derive scope when
        ``plan.scope`` is not populated, and for entity-grounding validation.
    question:
        The original user question (optional).  Used only for legacy
        backward-compatible sub-intent detection when a bare
        ``AnswerIntent`` is passed.

    Returns
    -------
    list[str]
        Between 1 and 3 non-empty, entity-grounded question strings.
    """
    from qara.llm.answer_plan import AnswerPlan

    sources = sources or []

    # ── Backward compatibility: wrap bare AnswerIntent ──────────────────
    if isinstance(answer_plan_or_intent, AnswerIntent):
        intent = answer_plan_or_intent
        # Sub-intent detection for legacy callers
        answer_type = _resolve_legacy_type(intent, question)
        plan = AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            include_root_cause=False,
            include_recommendations=False,
        )
    else:
        plan = answer_plan_or_intent

    # ── Build effective scope ───────────────────────────────────────────
    scope = _effective_scope(plan, sources)

    # ── Dispatch by AnswerType ──────────────────────────────────────────
    generator = _GENERATORS_BY_TYPE.get(plan.answer_type)
    if generator is None:
        return _FALLBACK[:3]

    candidates = generator(scope, plan.payload)
    candidates = [q for q in candidates if q.strip()]

    # ── Entity grounding validation ─────────────────────────────────────
    validated = _validate_grounding(candidates, scope, sources)

    if validated:
        return validated[:3]

    # Too many candidates failed validation — return safe generics.
    return _SAFE_GENERIC[:3]


def _resolve_legacy_type(intent: AnswerIntent, question: str) -> AnswerType:
    """Map a bare AnswerIntent + question to the correct AnswerType.

    Handles flakiness sub-intent detection that was previously done inline.
    """
    if intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE and question:
        from qara.llm.intent_detection import (
            _is_flakiness_history_query,
            _is_flakiness_ranking_query,
        )
        if _is_flakiness_ranking_query(question):
            return AnswerType.FLAKINESS_RANKING
        if _is_flakiness_history_query(question):
            return AnswerType.FLAKINESS_BINARY

    return _INTENT_TO_TYPE.get(intent, AnswerType.SUMMARY)
