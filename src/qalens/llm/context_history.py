"""Conversation-history helpers for QALens LLM context building.

Extracted from :mod:`qalens.llm.context` for cohesion.
All public names are re-exported from :mod:`qalens.llm.context` for backward
compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches camelCase test names like testCreateOrder, testLoginFunctionality
_TEST_NAME_RE = re.compile(r'\btest[A-Z][A-Za-z0-9]+\b')

# Matches "last N runs", "past N runs", "previous N runs", "over N runs"
_TIME_WINDOW_RE = re.compile(
    r'\b(?:last|past|previous|over|in the last)\s+(\d+)\s+runs?\b',
    re.IGNORECASE,
)

# Matches run IDs (UUIDs) or "Run #N" references
_RUN_REF_RE = re.compile(
    r'\brun[- _]?#?(\d+)\b'
    r'|([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
    re.IGNORECASE,
)

# Patterns that indicate a numeric override in a follow-up question,
# e.g. "show just the top 3" → extract max_results=3
_MAX_RESULTS_OVERRIDE_RE = re.compile(
    r'\btop\s+(\d+)\b|\bjust\s+(\d+)\b|\bonly\s+(\d+)\b|\bfirst\s+(\d+)\b',
    re.IGNORECASE,
)

# Specific date pattern: "3/7/2026", "2026-03-07"
_DATE_PATTERN_RE = re.compile(
    r'\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Follow-up detection cue sets
# ---------------------------------------------------------------------------

# Phrases that explicitly refer back to entities or results from a prior turn.
# These signal "I am continuing the previous analysis" rather than starting fresh.
_FOLLOWUP_REFERENCE_CUES: frozenset[str] = frozenset({
    # Compound phrases with demonstrative pronouns
    "explain that", "explain those", "about that", "about those",
    "more on that", "more about that", "tell me more", "more detail",
    "why those", "why those ones", "for those",
    "those ones", "those tests", "those results", "those failures",
    "these ones", "these tests",
    # Relative references to a prior list
    "which ones", "which one", "which of",
    "the ones", "for the above",
    # Drill-down onto prior results
    "run ids", "run id", "which run ids", "which run id",
    "drill down", "drill into",
    "show me the details", "details for",
    # Generic continuation that requires prior context
    "what about",
    # Scope narrowers that explicitly reference prior results
    "just for those", "only for those", "also for",
})

# Phrases that indicate an explicit constraint override applied to a prior
# analytical frame — the user is narrowing or redirecting, not restarting.
_FOLLOWUP_OVERRIDE_CUES: frozenset[str] = frozenset({
    # Time-window override: "in the last 10 runs instead"
    "instead",
    # Scope refinement applied to prior result set
    "what about in", "what about the last",
    "only those", "only for",
    "but only", "just those",
})

# Temporal/date keywords that introduce a fresh time context, signalling a
# new question rather than a continuation of prior results.
_NEW_TOPIC_DATE_CUES: frozenset[str] = frozenset({
    "yesterday", "today", "last week", "this week",
    "this month", "last month", "this sprint", "last sprint",
    "this year", "last year",
})

# Phrases that clearly restart analysis from scratch — fresh comparisons,
# fresh summaries, or direct failure queries unrelated to prior ranking.
_NEW_TOPIC_FRESH_QUERY_CUES: frozenset[str] = frozenset({
    "what failed", "what broke", "whats failing", "what is failing",
    "summarize the latest", "summarise the latest",
    "the latest run",
    "compare the last", "compare run", "compare the two",
})


@dataclass
class ConversationContext:
    """Structured context extracted from prior conversation turns.

    Carries forward the entities and constraints that were discussed so
    follow-up questions can be resolved without repeating them.

    Attributes:
        prior_tests:       Test names mentioned in prior turns.
        prior_intent:      The dominant intent of the previous assistant turn
                           (e.g. ``"ranking_list"``), or ``None``.
        prior_entity:      A non-test entity (run ID, owner name, etc.)
                           mentioned in prior turns, or ``None``.
        prior_time_window: A time-window phrase such as ``"last 5 runs"``,
                           or ``None`` if none was mentioned.
    """

    prior_tests: list[str] = field(default_factory=list)
    prior_intent: str | None = None
    prior_entity: str | None = None
    prior_time_window: str | None = None


@dataclass
class ResolvedQueryContext:
    """Resolved plan details from the previous conversation turn.

    Passed into :func:`~qalens.llm.answer_plan.build_answer_plan` so follow-up
    questions inherit the intent, metric, and numeric cap from the prior turn
    without the user having to repeat them.

    Attributes:
        prior_intent:           Primary :class:`~qalens.llm.answer_plan.AnswerIntent` of the last turn.
        prior_secondary_intent: Secondary intent of the last turn, or ``None``.
        prior_ranking_metric:   Ranking metric used in the last turn, or ``None``.
        prior_max_results:      ``max_results`` cap from the last turn, or ``None``.
        prior_test_names:       Test names that were the subject of the last turn.
        prior_time_window:      Time-window phrase from the last turn, or ``None``.
    """

    prior_intent: "AnswerIntent | None" = None  # type: ignore[name-defined]  # noqa: F821
    prior_secondary_intent: "AnswerIntent | None" = None  # type: ignore[name-defined]  # noqa: F821
    prior_ranking_metric: "RankingMetric | None" = None  # type: ignore[name-defined]  # noqa: F821
    prior_max_results: int | None = None
    prior_test_names: list[str] = field(default_factory=list)
    prior_time_window: str | None = None


def extract_query_context_from_plan(
    plan: "AnswerPlan",  # type: ignore[name-defined]  # noqa: F821
    test_names: list[str] | None = None,
    time_window: str | None = None,
) -> ResolvedQueryContext:
    """Snapshot the key resolved fields of *plan* for follow-up inheritance.

    Call this after building an :class:`~qalens.llm.answer_plan.AnswerPlan` and
    store the result; on the next turn pass it to
    :func:`~qalens.llm.answer_plan.build_answer_plan` as ``prior_context`` so
    follow-up questions do not need to re-state the metric/intent.

    Args:
        plan:        The :class:`~qalens.llm.answer_plan.AnswerPlan` from this turn.
        test_names:  Test names that were discussed this turn (e.g. from
                     :func:`~qalens.llm.context.extract_test_from_history`).
        time_window: Time-window phrase extracted from the question.

    Returns:
        A :class:`ResolvedQueryContext` ready to pass to the next turn.
    """
    return ResolvedQueryContext(
        prior_intent=plan.intent,
        prior_secondary_intent=plan.secondary_intent,
        prior_ranking_metric=plan.ranking_metric,
        prior_max_results=plan.max_results,
        prior_test_names=list(test_names or []),
        prior_time_window=time_window,
    )


def has_followup_reference(question: str) -> bool:
    """Return ``True`` when *question* contains an explicit back-reference.

    Detected patterns include demonstrative-pronoun compounds ("explain that",
    "about those"), drill-down phrases ("run ids", "drill down"), and generic
    continuation starters ("what about", "the ones").

    Args:
        question: The raw user question.

    Returns:
        ``True`` when at least one back-reference phrase is matched.
    """
    norm = question.lower().strip()
    return any(cue in norm for cue in _FOLLOWUP_REFERENCE_CUES)


def has_followup_override(question: str) -> bool:
    """Return ``True`` when *question* contains an explicit constraint override.

    Covers:
    * Numeric cap overrides — "show just the top 3", "only 5" → checked via
      :func:`extract_max_results_override`.
    * Time-window overrides — "in the last 10 runs instead".
    * Scope narrowers — "only those", "only for".

    Args:
        question: The raw user question.

    Returns:
        ``True`` when an override phrase or numeric cap is detected.
    """
    if extract_max_results_override(question) is not None:
        return True
    norm = question.lower().strip()
    return any(cue in norm for cue in _FOLLOWUP_OVERRIDE_CUES)


def has_strong_new_topic_signal(
    question: str,
    prior: ResolvedQueryContext | None = None,
) -> bool:
    """Return ``True`` when *question* introduces a clearly fresh analytical topic.

    Checks for:

    * New explicit date/temporal reference (e.g. "yesterday", "last week",
      a specific date like ``3/7/2026``).
    * Fresh-query restart phrases ("compare the last …", "summarize the latest
      run", "what failed", "what broke").
    * A new camelCase test name (``testXxx`` pattern) that is not present in
      *prior*.prior_test_names — the user is targeting a specific new entity
      rather than continuing from the prior ranked list.

    Args:
        question: The raw user question.
        prior:    The :class:`ResolvedQueryContext` from the previous turn.

    Returns:
        ``True`` when the question is clearly a fresh query, not a continuation.
    """
    if prior is None:
        return False

    norm = question.lower().strip()

    # Explicit date/temporal restart
    if any(cue in norm for cue in _NEW_TOPIC_DATE_CUES):
        return True
    if _DATE_PATTERN_RE.search(norm):
        return True

    # Fresh-query phrases that restart analysis
    if any(cue in norm for cue in _NEW_TOPIC_FRESH_QUERY_CUES):
        return True

    # New camelCase test name not mentioned in prior history
    new_names = _TEST_NAME_RE.findall(question)
    if new_names:
        prior_names_lower = {n.lower() for n in (prior.prior_test_names or [])}
        if any(n.lower() not in prior_names_lower for n in new_names):
            return True

    return False


def is_followup_question(
    question: str,
    prior: ResolvedQueryContext | None,
) -> bool:
    """Return ``True`` when *question* is a follow-up to *prior* context.

    Uses an evidence-based approach rather than word-count heuristics:

    1. Always ``False`` when *prior* is ``None``.
    2. ``False`` when the question introduces a **strong new-topic signal**
       (see :func:`has_strong_new_topic_signal`).  New-topic signals override
       any apparent back-reference phrases.
    3. ``True`` when the question contains an **explicit back-reference**
       (see :func:`has_followup_reference`) *or* an **explicit override**
       (see :func:`has_followup_override`).
    4. ``False`` otherwise — a short question alone is not enough evidence.

    This prevents short but genuinely new questions (e.g. "What failed
    yesterday?") from accidentally inheriting the prior analytical frame.

    Follow-up patterns covered (non-exhaustive):
    * "Can you explain that more?" → back-reference → True
    * "Which run IDs?" → drill-down reference → True
    * "Show just the top 3" → numeric override → True
    * "What about in the last 10 runs instead?" → override → True
    * "Only for checkout tests" → scope narrower → True

    Non-follow-up patterns:
    * "What failed yesterday?" → date signal → False
    * "Summarize the latest run" → fresh-query signal → False
    * "Compare the last two runs" → fresh-query signal → False
    * "Why is testCheckout flaky?" → new entity (testCheckout) → False

    Args:
        question: The current raw user question.
        prior:    The :class:`ResolvedQueryContext` from the previous turn.

    Returns:
        ``True`` when the question should inherit the prior context.
    """
    if prior is None:
        return False

    # New-topic signals take priority — do not inherit even if reference phrases present
    if has_strong_new_topic_signal(question, prior):
        return False

    # Explicit back-reference or constraint override → follow-up
    if has_followup_reference(question) or has_followup_override(question):
        return True

    # No evidence of continuation → treat as a new query
    return False


def extract_max_results_override(question: str) -> int | None:
    """Extract an explicit numeric cap from a follow-up question.

    Recognises patterns like: "show just the top 3", "only 5 please",
    "first 10", "top 7 tests".

    Args:
        question: The raw user question.

    Returns:
        The parsed integer cap, or ``None`` if no pattern matched.
    """
    m = _MAX_RESULTS_OVERRIDE_RE.search(question)
    if m:
        # Return the first captured group that is not None
        for g in m.groups():
            if g is not None:
                return int(g)
    return None


def extract_conversation_context(history: list[dict]) -> ConversationContext:
    """Extract structured context from conversation *history*.

    Scans all turns (newest first for priority) and populates a
    :class:`ConversationContext` with:

    * **prior_tests** — all distinct camelCase test names already discussed.
    * **prior_time_window** — the last "last N runs" / "past N runs" phrase.
    * **prior_entity** — the last run-ID or "Run #N" reference found.
    * **prior_intent** — not currently extractable from plain text; left as
      ``None`` for future use (callers can set it explicitly if needed).

    Args:
        history: List of conversation turn dicts, each with ``"role"`` and
                 ``"content"`` keys.

    Returns:
        A populated :class:`ConversationContext`.
    """
    tests: list[str] = []
    time_window: str | None = None
    entity: str | None = None

    for msg in reversed(history or []):
        content = msg.get("content", "") or ""

        for m in _TEST_NAME_RE.finditer(content):
            name = m.group()
            if name not in tests:
                tests.append(name)

        if time_window is None:
            tw = _TIME_WINDOW_RE.search(content)
            if tw:
                time_window = tw.group(0)

        if entity is None:
            er = _RUN_REF_RE.search(content)
            if er:
                entity = er.group(0)

    return ConversationContext(
        prior_tests=tests,
        prior_time_window=time_window,
        prior_entity=entity,
    )


def extract_prior_context_from_history(
    history: list[dict],
) -> "ResolvedQueryContext | None":
    """Build a :class:`ResolvedQueryContext` from the last user turn in *history*.

    Re-runs intent detection on the previous user question so the plan for the
    current turn can inherit intent, metric, and max_results without the user
    having to repeat themselves.

    Returns ``None`` when *history* is empty or contains no user messages.

    Args:
        history: List of conversation turn dicts (``"role"`` + ``"content"``).

    Returns:
        A :class:`ResolvedQueryContext` or ``None``.
    """
    if not history:
        return None

    # Find the most recent user message (last element before the current turn)
    last_user_question: str | None = None
    for msg in reversed(history):
        if msg.get("role") == "user":
            last_user_question = msg.get("content", "").strip()
            break

    if not last_user_question:
        return None

    # Late import to avoid circular dependency: answer_plan → context_history
    from qalens.llm.answer_plan import build_answer_plan, detect_answer_intent

    prior_intent = detect_answer_intent(last_user_question)
    prior_plan = build_answer_plan(prior_intent, question=last_user_question)

    conv_ctx = extract_conversation_context(history)
    return ResolvedQueryContext(
        prior_intent=prior_plan.intent,
        prior_secondary_intent=prior_plan.secondary_intent,
        prior_ranking_metric=prior_plan.ranking_metric,
        prior_max_results=prior_plan.max_results,
        prior_test_names=conv_ctx.prior_tests,
        prior_time_window=conv_ctx.prior_time_window,
    )


def extract_test_from_history(history: list[dict]) -> str | None:
    """Return the most recently mentioned test name from conversation history.

    Scans assistant then user messages (newest first) for camelCase test
    names so that follow-up questions like "Which suite does this belong to?"
    can resolve "this" to the test discussed in the prior turn.

    .. note::
        For richer extraction use :func:`extract_conversation_context` which
        also resolves time windows and run-ID references.
    """
    ctx = extract_conversation_context(history)
    return ctx.prior_tests[0] if ctx.prior_tests else None
