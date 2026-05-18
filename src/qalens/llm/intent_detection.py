"""Heuristic intent and answer-type detection for QA Lens LLM queries.

Contains keyword cue sets and detection functions extracted from
``answer_plan.py``.  These are pure functions with no side effects — they
classify a user question string into :class:`AnswerIntent` /
:class:`AnswerType` / :class:`RankingMetric` values.

Public API:

* :func:`detect_answer_intent` — question → AnswerIntent
* :func:`detect_answer_type` — (intent, question) → AnswerType
* :func:`detect_ranking_metric` — question → RankingMetric
* :func:`detect_secondary_intent` — (question, primary) → AnswerIntent | None

Internal helpers (prefixed with ``_``) are importable for testing but are
not considered stable API.
"""

from __future__ import annotations

import re

from qalens.llm.answer_types import AnswerIntent, AnswerType, RankingMetric

# Detects a single ordinal run reference such as "Run 25", "run #18", "run no. 7".
# Used to distinguish single-run lookup questions from cross-run comparisons.
_SPECIFIC_RUN_NUMBER_RE = re.compile(
    r"\brun\s*(?:no\.?|number|#|num\.?)?\s*\d{1,5}\b",
    re.IGNORECASE,
)

# Detects explicit time-window phrases that scope the question to a specific period.
# When present the question has an explicit scope and default-scope rules do not apply.
_EXPLICIT_WINDOW_RE = re.compile(
    r"\blast\s+\d+\s+runs?\b"          # "last 5 runs", "last 10 run"
    r"|\blast\s+(?:week|month|sprint|day|days|weeks|months)\b"  # "last week"
    r"|\bthis\s+(?:week|month|sprint)\b"  # "this sprint"
    r"|\bsince\s+\w"                   # "since Monday", "since v2.0"
    r"|\bfrom\s+\w+\s+to\b",           # "from Jan to Feb"
    re.IGNORECASE,
)

# Detects threshold/filter queries such as "pass rate below 60%".
# Two sub-patterns must both match: a metric term AND a comparison operator.
_THRESHOLD_METRIC_RE = re.compile(
    r"\bpass\s+rate\b|\bfailure\s+rate\b|\bfail\s+rate\b"
    r"|\bpass\s*%\b|\bfailure\s+frequency\b|\bfail\s+count\b",
    re.IGNORECASE,
)
# Each alternative requires a digit to follow the operator so "over time",
# "above average" etc. do not produce false positives.
_THRESHOLD_OPERATOR_RE = re.compile(
    r"\bbelow\s+\d|\babove\s+\d|\bunder\s+\d|\bover\s+\d"
    r"|\bmore\s+than\s+\d|\bless\s+than\s+\d|\bgreater\s+than\s+\d"
    r"|\bat\s+least\s+\d|\bat\s+most\s+\d"
    r"|\b[<>]=?\s*\d",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Scope detection helpers
# ---------------------------------------------------------------------------


def has_explicit_scope(question: str) -> bool:
    """Return ``True`` when the question explicitly limits its own scope.

    A question has an explicit scope when it references a specific run number
    (e.g. "Run 25"), an explicit time window (e.g. "last 5 runs", "last week"),
    or a date range.  Questions without an explicit scope receive a default
    scope of the last 10 runs so the LLM can disclose the assumed data window.

    Examples that return ``True``::

        "Show failed tests in Run 18"
        "Compare last 5 runs"
        "What broke this sprint?"

    Examples that return ``False`` (default scope applies)::

        "Which test has the highest failure frequency?"
        "Find tests failing with StaleElementReferenceException"
        "Show tests with pass rate below 60%"
    """
    if _SPECIFIC_RUN_NUMBER_RE.search(question):
        return True
    if _EXPLICIT_WINDOW_RE.search(question):
        return True
    return False


def _is_threshold_filter_query(question: str) -> bool:
    """Return ``True`` when the question filters tests by a metric threshold.

    Threshold queries name a metric (pass rate, failure rate) AND a comparison
    operator (below, above, less than, greater than, at most, etc.).  They are
    ranking/filter queries rather than run-vs-run comparisons, so they should
    route to :attr:`AnswerIntent.RANKING_LIST` even when "pass rate" appears
    (which would otherwise trigger :attr:`AnswerIntent.COMPARISON_CHANGE`).

    Examples that return ``True``::

        "Show tests with pass rate below 60%"
        "Find tests with failure rate above 40%"
        "Which tests have pass rate less than 50%?"
        "List tests with pass rate at most 30%"
    """
    norm = question.lower().strip()
    return bool(
        _THRESHOLD_METRIC_RE.search(norm) and _THRESHOLD_OPERATOR_RE.search(norm)
    )


# ---------------------------------------------------------------------------
# Keyword cue sets for heuristic detection
# ---------------------------------------------------------------------------

# NOTE: Time-window phrases ("last 5 runs", "last 10 runs") were removed
# from _RANKING_CUES because they trigger false positives on questions like
# "How has pass rate changed in the last 5 runs?" (TREND, not RANKING).
# Time-window context only contributes to ranking when paired with true
# ranking language (most/top/worst/highest/rank/flakiest/riskiest).

_RANKING_CUES: frozenset[str] = frozenset({
    "most flaky", "most unstable", "most volatile", "flakiest",
    "top ", "worst", "best", "highest", "lowest", "most failing",
    "most broken", "riskiest", "most at risk", "rank", "ranked",
    "list the", "which are the most", "which tests have the most",
    "most failures", "fail the most", "most often",
    "fewest passes",
    # Risk-prediction phrases
    "likely to fail", "most likely to fail", "most likely",
    "about to fail", "predicted to fail", "fail next",
    "at risk of failing", "expected to fail",
})

_DIAGNOSTIC_CUES: frozenset[str] = frozenset({
    "why ", "why does", "why did", "why is", "why has",
    "what caused", "cause of", "cause for", "reason", "explain",
    "root cause", "investigate", "investigation",
    "what's wrong", "whats wrong", "what is wrong", "what went wrong",
    "diagnose",
    "how to fix", "how do i fix", "how can i fix", "how should i fix",
    "help me fix", "troubleshoot",
})

# ---------------------------------------------------------------------------
# NEW_REGRESSIONS canonical cue set
# "tests that failed in this run but were passing in the previous run"
# ---------------------------------------------------------------------------

_NEW_REGRESSIONS_CUES: frozenset[str] = frozenset({
    # Core new-failure phrasing
    "new failure", "new failures", "newly failing", "newly broken",
    "new regression", "new regressions",
    # First-time failure phrasing
    "first-time failure", "first time failure", "first-time failing",
    "failed for the first time", "failing for the first time",
    # "Was passing before" phrasing (multi-word — unambiguous)
    "passing in the previous", "passing before", "were passing before",
    "previously passing", "passed in the previous", "passed before",
    "passing last run", "passed last run",
    # Explicit regression / delta phrasing
    "regressions introduced", "introduced in the latest", "introduced in the most recent",
    "delta between",
})


def _is_new_regressions_query(question: str) -> bool:
    """Return True when the question is specifically about newly-failing tests.

    Uses a two-signal semantic check: the question must express both
    *failure in the current run* and *passing in a previous run*.  Broad
    time-reference words ("previous", "last run") are intentionally excluded
    from the *was-passing* signal to avoid false positives from general
    historical queries like "What failed in the previous run?"

    Examples that return True::

        "What tests failed now but were passing before?"
        "Which tests broke since the last run?"
        "Tests that passed last time but now fail"
    """
    norm = question.lower().strip()

    # Signal A: reference to current/latest failure
    _fail_now = (
        "fail" in norm or "broke" in norm or "broken" in norm
        or "regression" in norm
    )
    # Signal B: explicit statement that the test *was* passing before.
    # Uses past-tense / explicit passing verbs only — not broad time references.
    _was_passing = (
        "passing" in norm or "passed" in norm
        or "was passing" in norm or "were passing" in norm
        or "used to pass" in norm or "used to work" in norm
    )
    # Exclude pure trend questions
    _trend_phrases = (
        "over time", "trend", "trending", "improving", "declining",
        "worsening", "pass rate", "failure rate", "progression",
    )
    _is_trend = any(p in norm for p in _trend_phrases)

    # Exclude root-cause questions (they ask WHY not WHICH)
    _is_diagnostic = any(c in norm for c in ("why ", "why does", "why did", "why is",
                                              "root cause", "what caused", "explain"))

    return _fail_now and _was_passing and not _is_trend and not _is_diagnostic


_COMPARISON_CUES: frozenset[str] = frozenset({
    "compare", "comparison", "versus", " vs ", "vs.",
    "last two runs", "last 2 runs",
    "between runs", "what changed", "how has", "how have",
    "has changed", "difference", "diff", "changed between",
    "degraded", "improved",
    # Fixed / recovered tests
    "got fixed", "were fixed", "fixed in", "got resolved",
    "newly fixed", "recovered", "recover", "no longer failing",
    # General regression — kept here for broad comparison questions
    "regressed", "regression",
    # Broad previous-run / build references (non-specific to passing state)
    "previous execution", "previous build",
    # Trend / time-series phrases
    "over time", "over the last", "over recent", "across runs",
    "trend", "trending", "improving", "declining", "worsening",
    "getting better", "getting worse", "pass rate", "pass %",
    "failure rate", "week over week", "run over run",
    "progression", "trajectory", "historically",
})

_DRILLDOWN_CUES: frozenset[str] = frozenset({
    "specific", "exact", "run id", "which run", "in run",
    "timeline", "full history", "history of",
    "show me the details", "details on", "details for",
    "trace", "stack trace for",
    # Suite / project / membership lookups
    "which suite", "what suite", "which test suite", "what test suite",
    "which project", "what project", "belong to", "belongs to",
    "part of", "which collection", "which module",
    # Temporal / first-occurrence lookups (specific — avoid broad "first time" false positives)
    "when did", "when was", "when were", "first appear", "first appeared",
    "first seen", "first occurred", "first introduced", "introduced in",
    "first reported", "first failure",
    # Historical recurrence lookups (multi-word — plural form avoids 'previous run' false positive)
    "in previous runs", "in past runs", "in earlier runs",
    "happened before", "occurred before", "seen before",
    "failed before", "recurring failure", "is this recurring",
    "have we seen", "before too", "before as well",
})

_RECOMMENDATION_CUES: frozenset[str] = frozenset({
    "what should", "should i ", "what do i", "what would you",
    "recommend", "recommendation", "next step", "next steps",
    "prioritize", "prioritise", "fix first", "quarantine",
    "focus on", "what to do", "action plan",
    "investigate first",
})

_SUMMARY_CUES: frozenset[str] = frozenset({
    "summarize", "summarise", "summary", "overview",
    "recap", "what happened", "health", "status",
    "give me an overview", "how are we doing",
    "what is the state", "whats the state",
    "what is going on", "high level",
})

# ---------------------------------------------------------------------------
# Ranking-metric keyword cues (used to resolve the metric inside RANKING_LIST)
# ---------------------------------------------------------------------------

_DURATION_RANKING_CUES: frozenset[str] = frozenset({
    "slowest", "slow", "duration", "execution time", "taking longest",
    "running longest", "performance", "time", "longest", "takes too long",
})

_RISK_RANKING_CUES: frozenset[str] = frozenset({
    "most at risk", "highest risk", "riskiest", "risk tier", "risk score",
    "likely to fail", "will fail", "about to fail", "predicted",
    "fail next", "at risk",
})

_FAILURE_BURDEN_CUES: frozenset[str] = frozenset({
    "most failures", "most failed", "failure count", "fail the most",
    "failed the most", "highest failure", "most often", "most broken",
})

# FLAKINESS is the default — no dedicated cue set needed.

# Plural/list-oriented words that signal the user wants a ranked enumeration,
# not a single-test diagnosis.  Used by _is_ranking_first_mixed_query() to
# distinguish "Why are the most flaky tests failing?" (list) from
# "Why is testCheckout flaky?" (single-test diagnosis).
_LIST_ORIENTATION_CUES: frozenset[str] = frozenset({
    "tests", "test cases", "test suites", "modules", "suites",
    "which tests", "which test cases", "which modules",
    "most flaky tests", "flakiest tests", "most unstable tests",
    "top failing tests", "worst tests", "riskiest tests",
    "most at risk tests", "most failing tests",
})


# ---------------------------------------------------------------------------
# Heuristic detection helpers
# ---------------------------------------------------------------------------


def _is_flakiness_history_query(question: str) -> bool:
    """Return True when the question asks whether regressing tests had *prior* flakiness.

    Examples::

        "Were any of these tests flaky before this regression?"
        "Were these tests flaky prior to this failure?"
        "Did any of the failing tests have a flaky history?"
        "Had these tests been flaky in previous runs?"
        "Were any failing tests already unstable before they regressed?"
        "Which of the newly failing tests have the worst pre-existing flakiness?"

    These are diagnostic questions, not run-vs-run comparison questions, so
    they must be intercepted before ``"regression"`` in *_COMPARISON_CUES*
    pulls them into COMPARISON_CHANGE.
    """
    norm = question.lower().strip()

    # Signal A: flakiness / instability vocabulary
    _flaky = (
        "flaky" in norm
        or "flakiness" in norm
        or "unstable" in norm
        or "intermittent" in norm
        or "instability" in norm
        or "flake" in norm
    )

    # Signal B: historical / prior framing (not a ranking question).
    _prior = (
        "before" in norm
        or "prior" in norm
        or "previously" in norm
        or "already" in norm
        or "had been" in norm
        or "have been" in norm
        or "in previous" in norm
        or "in past" in norm
        or "in earlier" in norm
        or "history" in norm
        or "historically" in norm
        or "pre-existing" in norm
        or "pre existing" in norm
    )

    # Exclude ranking questions — these route to _is_flakiness_ranking_query instead.
    _is_ranking = any(cue in norm for cue in (
        "most flaky", "flakiest", "most unstable", "most volatile",
        "rank", "top ", "worst", "highest", "strongest",
    ))

    # Exclude negated prior-flakiness questions
    _is_negated_prior = (
        "no prior flakiness" in norm
        or "no prior instability" in norm
        or "no flakiness history" in norm
        or "no flaky history" in norm
        or "without prior flakiness" in norm
        or "not flaky before" in norm
        or ("no prior" in norm and _flaky)
        or ("without prior" in norm and _flaky)
    )

    return _flaky and _prior and not _is_ranking and not _is_negated_prior


def _is_flakiness_ranking_query(question: str) -> bool:
    """Return True when the question asks for a *ranked list* of newly failing tests by prior flakiness.

    Distinct from :func:`_is_flakiness_history_query` which handles the
    binary/categorisation case ("Were any flaky before?").  This function
    fires on superlative/ranking phrasings::

        "Which of the newly failing tests have the worst pre-existing flakiness?"
        "Which of these were already the flakiest?"
        "Rank the newly failing tests by prior flakiness"
        "Which had the highest pre-existing flakiness?"
        "Which newly failing tests had the most prior instability?"
    """
    norm = question.lower().strip()

    # Signal A: flakiness / instability vocabulary
    _flaky = (
        "flaky" in norm
        or "flakiness" in norm
        or "flakiest" in norm
        or "unstable" in norm
        or "intermittent" in norm
        or "instability" in norm
    )

    # Signal B: ranking / superlative framing specific to flakiness
    _ranking = (
        "worst" in norm
        or "most flaky" in norm
        or "flakiest" in norm
        or "most unstable" in norm
        or "most volatile" in norm
        or "rank" in norm
        or "ranked" in norm
        or "highest" in norm
        or "strongest" in norm
    )

    # Signal C: prior / historical framing (distinguishes from project-wide ranking)
    _prior = (
        "pre-existing" in norm
        or "pre existing" in norm
        or "prior" in norm
        or "before" in norm
        or "already" in norm
        or "history" in norm
        or "historically" in norm
        or "previously" in norm
    )

    return _flaky and _ranking and _prior


def _is_historical_recurrence_query(question: str) -> bool:
    """Return True when the question asks whether a failure has recurred in past runs.

    These are lookup questions ("Has this happened before?"), not comparison
    queries ("Compare run A with run B").  They should route to
    DRILL_DOWN_DETAIL so the LLM delivers a compact factual answer instead of
    a full run-vs-run comparison panel.
    """
    norm = question.lower().strip()

    _recurrence = (
        "happened before" in norm
        or "happened in previous" in norm
        or "happened in past" in norm
        or "happened in earlier" in norm
        or "occurred before" in norm
        or "seen before" in norm
        or "seen in previous" in norm
        or "seen in past" in norm
        or "appeared before" in norm
        or "in previous runs" in norm
        or "in past runs" in norm
        or "in earlier runs" in norm
        or "before too" in norm
        or "before as well" in norm
        or "recurring" in norm
        or "is this a recur" in norm
        or "have we seen" in norm
        or "have they seen" in norm
        or "failed before" in norm
        or "failed in past" in norm
        or "failed in previous runs" in norm
    )

    _is_comparison = (
        "compare" in norm or "comparison" in norm
        or " vs " in norm or "versus" in norm
        or "what changed" in norm or "difference" in norm
    )

    return _recurrence and not _is_comparison


def _is_single_test_fix_query(question: str) -> bool:
    """Return True when the question asks whether a *specific* test has been fixed.

    Distinguishes "Has testFoo been fixed?" (specific-test lookup → DRILL_DOWN_DETAIL)
    from "Which tests got fixed?" (list comparison → COMPARISON_CHANGE).

    Examples that return True::

        "Has testAddItemToCart() been fixed in any recent run?"
        "Has this issue been fixed?"
        "Has the login test been fixed yet?"
    """
    norm = question.lower().strip()
    return "been fixed" in norm and norm.startswith("has ")


def _is_ranking_first_mixed_query(question: str) -> bool:
    """Return ``True`` when the question is list-oriented despite containing 'why'.

    Detects questions like "Why are the most flaky tests failing?" where the
    user wants a *ranked list* with explanations, not a single-test diagnosis.
    Requires all three signals:
    * A ranking cue
    * A diagnostic cue
    * A list-orientation cue
    """
    norm = question.lower().strip()
    has_ranking = any(cue in norm for cue in _RANKING_CUES)
    has_diagnostic = any(cue in norm for cue in _DIAGNOSTIC_CUES)
    has_list_orientation = any(cue in norm for cue in _LIST_ORIENTATION_CUES)
    return has_ranking and has_diagnostic and has_list_orientation


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_answer_intent(question: str) -> AnswerIntent:
    """Heuristically classify *question* into one of seven :class:`AnswerIntent` values.

    Uses substring matching on lowercased input.  Priority order encodes
    specificity — diagnostic beats summary, ranking beats general failure lists,
    new-regressions beats general comparison.

    Returns:
        The most specific matching :class:`AnswerIntent`, defaulting to
        :attr:`AnswerIntent.SUMMARY_OVERVIEW` when nothing matches.
    """
    norm = question.lower().strip()

    def _hit(cues: frozenset[str]) -> bool:
        return any(cue in norm for cue in cues)

    # Pre-pass 1: ranking-first mixed queries override the standard priority chain.
    if _is_ranking_first_mixed_query(question):
        return AnswerIntent.RANKING_LIST

    # Pre-pass 1b: flakiness ranking follow-ups
    if _is_flakiness_ranking_query(question):
        return AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    # Pre-pass 1c: binary flakiness-history follow-ups
    if _is_flakiness_history_query(question):
        return AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    # Guard: if the question names exactly one run by ordinal (e.g. "Run 25"),
    # it is a single-run lookup regardless of other signals — even when it
    # contains " vs " (e.g. "passed vs failed count for Run 25") or when metric
    # words like "passed" / "failed" happen to match the new-regressions signals.
    # Two or more distinct run numbers → still a comparison (e.g. "Run 52 vs Run 53").
    _single_run = len(_SPECIFIC_RUN_NUMBER_RE.findall(question)) == 1

    # Priority: diagnostic > drilldown (recurrence) > new_regressions > comparison > drilldown > recommendation > ranking > summary
    if _hit(_DIAGNOSTIC_CUES):
        return AnswerIntent.DIAGNOSTIC_ROOT_CAUSE
    if _is_historical_recurrence_query(question):
        return AnswerIntent.DRILL_DOWN_DETAIL
    # Guard against trend questions so e.g. "delta between pass rates over time" → COMPARISON_CHANGE.
    _trend_guard = any(
        p in norm
        for p in ("over time", "trend", "trending", "improving", "declining",
                  "worsening", "pass rate", "failure rate", "progression")
    )
    if not _trend_guard and not _single_run and (
        _is_new_regressions_query(question) or _hit(_NEW_REGRESSIONS_CUES)
    ):
        return AnswerIntent.NEW_REGRESSIONS
    if _is_single_test_fix_query(question):
        return AnswerIntent.DRILL_DOWN_DETAIL
    # Guard: threshold filter queries ("pass rate below 60%", "failure rate above 40%")
    # are ranking/filter questions, not run-vs-run comparisons — even though they
    # contain "pass rate" which is in _COMPARISON_CUES.
    if _is_threshold_filter_query(question):
        return AnswerIntent.RANKING_LIST
    if _hit(_COMPARISON_CUES) and not _single_run:
        return AnswerIntent.COMPARISON_CHANGE
    if _hit(_DRILLDOWN_CUES) or _single_run:
        return AnswerIntent.DRILL_DOWN_DETAIL
    if _hit(_RECOMMENDATION_CUES):
        return AnswerIntent.RECOMMENDATION_ACTION
    if _hit(_RANKING_CUES):
        return AnswerIntent.RANKING_LIST
    if _hit(_SUMMARY_CUES):
        return AnswerIntent.SUMMARY_OVERVIEW

    return AnswerIntent.SUMMARY_OVERVIEW


# ---------------------------------------------------------------------------
# Answer-type detection
# ---------------------------------------------------------------------------


def detect_answer_type(intent: AnswerIntent, question: str = "") -> AnswerType:
    """Resolve the canonical output shape from intent + question.

    Deterministic — same (intent, question) always produces the same
    ``AnswerType``.
    """
    if intent == AnswerIntent.NEW_REGRESSIONS:
        return AnswerType.REGRESSION_DIFF

    if intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE:
        if _is_flakiness_ranking_query(question):
            return AnswerType.FLAKINESS_RANKING
        if _is_flakiness_history_query(question):
            return AnswerType.FLAKINESS_BINARY
        return AnswerType.ROOT_CAUSE

    if intent == AnswerIntent.RANKING_LIST:
        metric = detect_ranking_metric(question) if question else RankingMetric.FLAKINESS
        if metric == RankingMetric.RISK:
            return AnswerType.RISK_RANKING
        return AnswerType.FLAKINESS_RANKING

    if intent == AnswerIntent.COMPARISON_CHANGE:
        norm_q = question.lower().strip()
        _trend_phrases = (
            "over time", "trend", "trending", "improving", "declining",
            "worsening", "getting better", "getting worse", "pass rate",
            "pass %", "failure rate", "progression", "trajectory",
            "over the last", "over recent", "across runs", "run over run",
        )
        if any(p in norm_q for p in _trend_phrases):
            return AnswerType.TREND
        return AnswerType.REGRESSION_DIFF

    if intent == AnswerIntent.DRILL_DOWN_DETAIL:
        return AnswerType.DETAIL

    if intent == AnswerIntent.RECOMMENDATION_ACTION:
        return AnswerType.RECOMMENDATION

    # SUMMARY_OVERVIEW and anything else
    return AnswerType.SUMMARY


def detect_ranking_metric(question: str) -> RankingMetric:
    """Resolve which ranking metric the user intends for a RANKING_LIST query.

    Defaults to FLAKINESS when no specific metric keyword is present.
    """
    norm = question.lower().strip()

    def _hit(cues: frozenset[str]) -> bool:
        return any(cue in norm for cue in cues)

    if _hit(_DURATION_RANKING_CUES):
        return RankingMetric.DURATION
    if _hit(_RISK_RANKING_CUES):
        return RankingMetric.RISK
    if _hit(_FAILURE_BURDEN_CUES):
        return RankingMetric.FAILURE_BURDEN
    return RankingMetric.FLAKINESS


def detect_secondary_intent(
    question: str, primary: AnswerIntent
) -> AnswerIntent | None:
    """Detect an optional secondary intent that co-occurs with *primary*.

    Runs the same cue-matching as :func:`detect_answer_intent` but skips
    *primary* so mixed queries like "rank the flaky tests and explain why"
    return ``(RANKING_LIST, DIAGNOSTIC_ROOT_CAUSE)`` rather than collapsing
    to DIAGNOSTIC alone.
    """
    norm = question.lower().strip()

    def _hit(cues: frozenset[str]) -> bool:
        return any(cue in norm for cue in cues)

    candidates: list[tuple[AnswerIntent, frozenset[str]]] = [
        (AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _DIAGNOSTIC_CUES),
        (AnswerIntent.NEW_REGRESSIONS, _NEW_REGRESSIONS_CUES),
        (AnswerIntent.COMPARISON_CHANGE, _COMPARISON_CUES),
        (AnswerIntent.DRILL_DOWN_DETAIL, _DRILLDOWN_CUES),
        (AnswerIntent.RECOMMENDATION_ACTION, _RECOMMENDATION_CUES),
        (AnswerIntent.RANKING_LIST, _RANKING_CUES),
        (AnswerIntent.SUMMARY_OVERVIEW, _SUMMARY_CUES),
    ]
    for intent, cues in candidates:
        if intent == primary:
            continue
        if _hit(cues):
            return intent
    return None
