"""Intent-driven answer planning for QARA LLM queries.

The :class:`AnswerPlan` drives *how* the LLM should structure its reply for a
given question type.  It is derived deterministically from heuristic keyword
rules — no extra LLM call is made.

Flow::

    question
      │
      ▼
    detect_answer_intent()  →  AnswerIntent
      │
      ▼
    build_answer_plan()     →  AnswerPlan
      │
      ▼
    build_prompt()          →  structured LLM prompt
    build_system_prompt()   →  intent-aware system prompt

Enums and data models live in :mod:`ari.llm.answer_types`.
Heuristic keyword cues and detection functions live in
:mod:`ari.llm.intent_detection`.  This module re-exports them for
backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Re-exports from answer_types (backward compat) ──────────────────────────
from qara.llm.answer_types import (  # noqa: F401
    AnswerIntent,
    AnswerScope,
    AnswerType,
    DefaultScopeInfo,
    PayloadSection,
    RankingMetric,
    StructuredPayload,
)

# ── Re-exports from intent_detection (backward compat) ──────────────────────
from qara.llm.intent_detection import (  # noqa: F401
    _is_flakiness_history_query,
    _is_flakiness_ranking_query,
    _is_ranking_first_mixed_query,
    detect_answer_intent,
    detect_answer_type,
    detect_ranking_metric,
    detect_secondary_intent,
    has_explicit_scope,
)


# ---------------------------------------------------------------------------
# AnswerPlan
# ---------------------------------------------------------------------------


@dataclass
class AnswerPlan:
    """Controls how the LLM answer should be structured for a given query.

    Consumed by :func:`~ari.llm.prompts.build_prompt` and
    :func:`~ari.llm.prompts.build_system_prompt` to inject structured
    per-intent guidance instead of using a generic freeform template.
    """

    intent: AnswerIntent
    answer_type: AnswerType
    include_root_cause: bool
    include_recommendations: bool
    secondary_intent: AnswerIntent | None = None
    ranking_metric: RankingMetric | None = None
    no_unsolicited_root_cause: bool = True
    no_unsolicited_recommendations: bool = True
    ranking_basis: str | None = None
    max_results: int | None = None
    needs_exact_records: bool = False
    confidence_style: str = "implicit"   # "explicit" | "implicit" | "none"
    answer_rules: list[str] = field(default_factory=list)
    is_trend_question: bool = False
    scope: AnswerScope | None = None
    payload: StructuredPayload | None = None
    default_scope: DefaultScopeInfo | None = None
    """Set when the question specified no run/time/dataset and defaults were applied."""


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------

# NOTE: Cue sets, detection helpers, and public detection functions
# (detect_answer_intent, detect_answer_type, detect_ranking_metric,
# detect_secondary_intent) now live in ari.llm.intent_detection and are
# re-exported above for backward compatibility.

_RANKING_CUES_REMOVED = True  # marker — see intent_detection.py


def build_answer_plan(
    intent: AnswerIntent,
    question: str = "",
    prior_context: "ResolvedQueryContext | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> AnswerPlan:
    """Return the canonical :class:`AnswerPlan` for a given *intent*.

    When *question* is provided, the ranking metric and secondary intent are
    resolved automatically from keyword cues so the context builder knows
    which DB column to sort by and the prompt can cover both intents.

    When *prior_context* is provided and the current question is a follow-up
    (short, no strong new intent signals), the plan inherits the prior
    intent, ranking metric, and ``max_results`` so the user does not need to
    repeat them.  An explicit numeric override in the question (e.g. "top 3")
    still takes effect regardless of *prior_context*.

    When the question contains no explicit scope (no run number, no time window),
    a :class:`DefaultScopeInfo` is attached to the plan so the prompt builder can
    inject scope-disclosure instructions and the LLM discloses what data it used.

    Args:
        intent:        The detected :class:`AnswerIntent`.
        question:      Original user question (optional).  Used to resolve
                       :class:`RankingMetric` and detect a secondary intent.
        prior_context: Resolved context from the previous conversation turn.
                       When provided and the question is a follow-up, fields
                       are inherited from this context.

    Returns:
        A fully populated :class:`AnswerPlan` ready for prompt construction.
    """
    plan = _resolve_answer_plan(intent, question=question, prior_context=prior_context)

    # Annotate with default scope when the question is underspecified.
    # COMPARISON_CHANGE and NEW_REGRESSIONS always operate on last-run-vs-previous-run
    # and have their own implicit scope — skip them to avoid conflicting messages.
    _scope_applicable = {
        AnswerIntent.RANKING_LIST,
        AnswerIntent.SUMMARY_OVERVIEW,
        AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
        AnswerIntent.RECOMMENDATION_ACTION,
        AnswerIntent.DRILL_DOWN_DETAIL,
    }
    if (
        question
        and plan.intent in _scope_applicable
        and not has_explicit_scope(question)
    ):
        plan.default_scope = DefaultScopeInfo()

    return plan


def _resolve_answer_plan(
    intent: AnswerIntent,
    question: str = "",
    prior_context: "ResolvedQueryContext | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> AnswerPlan:
    """Internal plan builder — handles follow-up inheritance and delegates to core."""
    from qara.llm.context_history import (
        ResolvedQueryContext,
        extract_max_results_override,
        is_followup_question,
    )

    # ── Follow-up inheritance ──────────────────────────────────────────────
    # When the current question is short and there is prior context, inherit
    # intent, metric, and max_results from the prior turn.
    # EXCEPTION: if the current question has strong DRILLDOWN signals (single-fact
    # lookup like run ID, suite name, date), always use DRILL_DOWN_DETAIL as
    # the primary so we don't repeat a full comparison/summary for a simple lookup.
    _drilldown_override = intent == AnswerIntent.DRILL_DOWN_DETAIL
    # Flakiness-history questions (e.g. "Were any of these tests flaky before this
    # regression?") contain "these tests" which fires has_followup_reference(), but they
    # carry a completely new analytical intent.  Treat them like drilldown — skip
    # follow-up inheritance so the detected DIAGNOSTIC_ROOT_CAUSE intent is preserved.
    _flakiness_history_override = _is_flakiness_history_query(question)
    _flakiness_ranking_override = _is_flakiness_ranking_query(question)
    _skip_inheritance = _drilldown_override or _flakiness_history_override or _flakiness_ranking_override
    if prior_context is not None and is_followup_question(question, prior_context) and not _skip_inheritance:
        effective_intent = prior_context.prior_intent or intent
        effective_metric = prior_context.prior_ranking_metric
        # An explicit "top N" / "only N" override always wins
        numeric_override = extract_max_results_override(question)
        effective_max = numeric_override or prior_context.prior_max_results
        # Rebuild with the inherited values — reuse the same plan logic below
        # by overriding intent/ranking_metric/max_results after construction.
        base_plan = _build_answer_plan_core(
            effective_intent, question=question, ranking_metric_override=effective_metric
        )
        if effective_max is not None:
            # Patch max_results and the corresponding answer rule
            new_rules = [
                r if not r.startswith("List at most") else
                f"List at most {effective_max} entries; state total eligible count after the list."
                for r in base_plan.answer_rules
            ]
            return AnswerPlan(
                intent=base_plan.intent,
                answer_type=base_plan.answer_type,
                secondary_intent=base_plan.secondary_intent,
                ranking_metric=base_plan.ranking_metric,
                include_root_cause=base_plan.include_root_cause,
                include_recommendations=base_plan.include_recommendations,
                no_unsolicited_root_cause=base_plan.no_unsolicited_root_cause,
                no_unsolicited_recommendations=base_plan.no_unsolicited_recommendations,
                ranking_basis=base_plan.ranking_basis,
                max_results=effective_max,
                needs_exact_records=base_plan.needs_exact_records,
                confidence_style=base_plan.confidence_style,
                answer_rules=new_rules,
            )
        return base_plan

    return _build_answer_plan_core(intent, question=question)


def _build_answer_plan_core(
    intent: AnswerIntent,
    question: str = "",
    ranking_metric_override: "RankingMetric | None" = None,
) -> AnswerPlan:
    """Internal plan builder — no follow-up resolution, called by :func:`build_answer_plan`."""
    # Resolve the canonical output shape first — this drives everything else
    answer_type = detect_answer_type(intent, question)

    secondary = detect_secondary_intent(question, primary=intent) if question else None
    # Ranking metric is only relevant for RANKING_LIST, but also useful when
    # the secondary intent is RANKING_LIST (e.g. root-cause + ranked list).
    ranking_metric: RankingMetric | None = None
    if intent == AnswerIntent.RANKING_LIST or secondary == AnswerIntent.RANKING_LIST:
        # Use the override (from follow-up inheritance) when provided; otherwise detect.
        ranking_metric = (
            ranking_metric_override
            if ranking_metric_override is not None
            else (detect_ranking_metric(question) if question else None)
        )

    if intent == AnswerIntent.RANKING_LIST:
        # Resolve human-readable basis from the metric enum
        _metric_labels: dict[RankingMetric, str] = {
            RankingMetric.FLAKINESS: "flip_score (pass↔fail transitions, higher = more unstable)",
            RankingMetric.RISK: (
                "QARA next-run risk score — combines volatility (flip_score), failure burden "
                "(fail count), recent decline (pass-rate trend), fail streak, and duration spike. "
                "Expressed as risk_tier: CRITICAL > HIGH > MEDIUM > LOW."
            ),
            RankingMetric.FAILURE_BURDEN: "failure_count (total failures across all runs)",
            RankingMetric.DURATION: "avg_duration (average execution time in seconds)",
        }
        metric = ranking_metric or RankingMetric.FLAKINESS
        basis = _metric_labels[metric]
        # Include diagnostic rules as appendix when secondary intent is diagnostic
        extra_rules: list[str] = []
        if secondary == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE:
            extra_rules = [
                "After the ranked list, add a brief 'Why these tests fail' section.",
                "For each top entry, cite the dominant error type from the context.",
                "Keep the diagnostic section to one paragraph — do not repeat the full list.",
            ]
        # RISK ranking gets a richer format: tier + pass rate per entry, plus explanation sections
        if metric == RankingMetric.RISK:
            list_format_rule = (
                "For each entry use the format: NUMBER. TEST_NAME — TIER risk · pass rate: PASS_RATE% "
                "(e.g. '1. testFoo() — HIGH risk · pass rate: 49%'). "
                "Use the risk_tier and pass_rate columns from the context table. "
                "NEVER output a bare percentage without a metric label."
            )
            risk_extra_rules = [
                "After the list, add a short 'How I ranked them' section: state that tests are "
                "ranked by QARA next-run risk score, which combines volatility, failure burden, "
                "recent decline, fail streak, and duration spike — NOT by pass rate.",
                "Then add a 'What the numbers mean' section with exactly these three bullets:\n"
                "- Risk tier = ARI's prediction of next-run failure likelihood (CRITICAL > HIGH > MEDIUM > LOW)\n"
                "- Pass rate = how often the test has passed historically\n"
                "- A test can rank high-risk even with a high pass rate if recent signals worsened sharply",
                "Then add a 'Why these rank highly' section with one evidence sentence per top 3–5 entry. "
                "Explicitly separate the QARA risk basis from the pass rate. "
                "Example: 'testFoo() ranks HIGH because its recent signals worsened sharply "
                "(fail streak + recent decline), even though its historical pass rate is 90%.'",
            ]
        else:
            list_format_rule = "Then present a simple numbered list — one test name per line, no metric columns."
            risk_extra_rules = []
        _max_results = 10
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,  # None when no question given; resolved metric for basis only
            include_root_cause=secondary == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            include_recommendations=secondary == AnswerIntent.RECOMMENDATION_ACTION,
            no_unsolicited_root_cause=secondary != AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            no_unsolicited_recommendations=secondary != AnswerIntent.RECOMMENDATION_ACTION,
            ranking_basis=basis,
            max_results=_max_results,
            needs_exact_records=False,
            confidence_style="none",
            answer_rules=[
                f"Ranking metric: {basis}.",
                "Begin with one natural-language summary sentence that directly answers the question "
                "(e.g. 'The tests most likely to fail next run are:').",
                list_format_rule,
                "DO NOT output a table. DO NOT use column headers such as 'Rank', 'flip_score', "
                "'pass_rate', 'runs', or 'classification'.",
                f"List at most {_max_results} entries; after the list add a single plain sentence with the total eligible count.",
                "You MUST NOT add a root-cause section unless this instruction set includes one.",
                "You MUST NOT add recommendations unless this instruction set includes one.",
            ] + risk_extra_rules + extra_rules,
        )

    if intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE:
        norm_q = question.lower().strip()

        # ── Sub-case A: flakiness RANKING follow-up ───────────────────────────
        # "Which of the newly failing tests have the worst pre-existing flakiness?"
        # → ranked numbered list by flip_score, NO tier grid.
        if _is_flakiness_ranking_query(question):
            return AnswerPlan(
                intent=intent,
            answer_type=answer_type,
                secondary_intent=secondary,
                ranking_metric=ranking_metric,
                include_root_cause=False,
                include_recommendations=False,
                no_unsolicited_root_cause=True,
                no_unsolicited_recommendations=True,
                ranking_basis=None,
                max_results=None,
                needs_exact_records=True,
                confidence_style="none",
                answer_rules=[
                    # ── Content guard ─────────────────────────────────────────────
                    "DO NOT reproduce any content from the run comparison context. "
                    "Your answer covers ONLY the pre-existing flakiness ranking of the newly failing tests.",
                    # ── Scope guard ───────────────────────────────────────────────
                    "⚠️ SCOPE: Use ONLY the tests listed in the "
                    "'=== SCOPE: NEWLY FAILING TESTS' block in the context. "
                    "Do NOT rank or mention recovered tests, consistently failing tests, "
                    "or tests not in that block. Do NOT draw test names from conversation history.",
                    # ── Line 1: heading ───────────────────────────────────────────
                    "Line 1 of your output must be exactly: "
                    "### 🔍 Worst Pre-Existing Flakiness Among Newly Failing Tests",
                    # ── Line 2: intro ─────────────────────────────────────────────
                    "Line 2 must be exactly: "
                    "'The newly failing tests ranked from worst to best pre-existing instability:'",
                    # ── Ranked list ───────────────────────────────────────────────
                    "From the '=== TEST FLAKINESS HISTORY' table in the context, find the "
                    "flakiness_% value for each test in the SCOPE block. "
                    "The flakiness_% column is already a whole-number percentage — e.g. 90 means 90%. "
                    "Rank the scope tests from HIGHEST flakiness_% to LOWEST. "
                    "Output a numbered list — one entry per line in exactly this format: "
                    "'1. testName() — X%' where X is the flakiness_% value from the table. "
                    "Example: '1. testDashboardLoadsInUnder3s() — 90%'. "
                    "Include ALL scope tests (even those not in the flakiness table — show them as 0%). "
                    "Do NOT skip any scope test. Do NOT show the raw decimal. "
                    "Do NOT use tier section labels (🔴/🟡/🔵). Do NOT use a table.",
                    # ── Closing ───────────────────────────────────────────────────
                    "After the last numbered entry, output a blank line, then '---', then:\n"
                    "  **What this means:** followed by ONE sentence interpreting the ranking "
                    "(e.g. which tests had the strongest pre-existing instability and may be "
                    "less reliable regression signals, vs. the stable tests that are stronger "
                    "indicators of a real code-level change).",
                    # ── Hard constraints ──────────────────────────────────────────
                    "DO NOT use 🔴/🟡/🔵 tier blocks — this is a ranking answer, not a categorisation answer.",
                    "DO NOT add a 'Debugging implication' section.",
                    "DO NOT add recommendations.",
                    "Keep total answer under 200 words.",
                ],
            )

        # ── Sub-case B: flakiness BINARY/CATEGORISATION follow-up ────────────
        # "Were any of these tests flaky before this regression?"
        # → yes/no verdict + tier buckets.
        if _is_flakiness_history_query(question):
            return AnswerPlan(
                intent=intent,
            answer_type=answer_type,
                secondary_intent=None,
                ranking_metric=ranking_metric,
                include_root_cause=False,
                include_recommendations=False,
                no_unsolicited_root_cause=True,
                no_unsolicited_recommendations=True,
                ranking_basis=None,
                max_results=None,
                needs_exact_records=True,
                confidence_style="explicit",
                answer_rules=[
                    # ── Verbatim copy rule ────────────────────────────────────────
                    "Your ENTIRE answer is the text inside the "
                    "'=== PRE-BUILT ANSWER (output this verbatim) ===' block from the context. "
                    "Copy it exactly — do not rephrase, reorder, add, or remove anything. "
                    "The verdict, bullet list, flip counts, status symbols, and explanation "
                    "are all pre-computed and correct.",
                    # ── Hard constraints ──────────────────────────────────────────
                    "DO NOT add any text before or after the pre-built answer.",
                    "DO NOT recalculate flip counts — the numbers are authoritative.",
                    "DO NOT add error messages, root-cause groups, or tier classifications.",
                    "DO NOT add recommendations or debugging implications.",
                    "DO NOT use tables.",
                ],
            )

        # If secondary is RANKING_LIST, prepend a short ranked list before diagnosis
        extra_rules_diag: list[str] = []
        if secondary == AnswerIntent.RANKING_LIST:
            extra_rules_diag = [
                "Before the diagnostic section, show a compact ranked list of the top 5 affected tests.",
            ]
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,
            include_root_cause=True,
            include_recommendations=True,
            no_unsolicited_root_cause=False,
            no_unsolicited_recommendations=False,
            ranking_basis=None,
            max_results=None,
            needs_exact_records=True,
            confidence_style="explicit",
            answer_rules=[
                "Open with a single direct sentence answering 'why'.",
                "Provide: Probable Root Cause · Evidence · Confidence level.",
                "Cite exact error type, message, and stack top when present in context.",
                "Limit recommendations to one concrete next step.",
                "Focus on the specific failing test(s) — do not enumerate all runs.",
            ] + extra_rules_diag,
        )

    if intent == AnswerIntent.NEW_REGRESSIONS:
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,
            include_root_cause=secondary == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            include_recommendations=False,
            no_unsolicited_root_cause=secondary != AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            no_unsolicited_recommendations=True,
            ranking_basis=None,
            max_results=None,
            needs_exact_records=True,
            confidence_style="implicit",
            is_trend_question=False,
            answer_rules=[
                *(
                    [
                        "The user asked a follow-up lookup question. Answer it in ONE sentence "
                        "at the very top, before any section headings. Then proceed below.",
                    ]
                    if secondary == AnswerIntent.DRILL_DOWN_DETAIL
                    else []
                ),
                "The user is asking specifically about NEW REGRESSIONS — tests that FAILED in "
                "the latest run but PASSED in the previous run. Focus exclusively on this set.",
                "Open with heading: '## 🚨 New Regressions — Run #X → Run #Y' (exact run labels from context).",
                "Immediately below, place a one-line stat strip: '+N newly failing · −M recovered'.",
                "Then output a blank line, then '---' on its own line.",
                "=== NEWLY FAILING SECTION ===",
                "Output '### 🔴 New Regressions (N)' (use real count).",
                "One brief sentence interpreting the overall pattern (e.g. 'These regressions indicate "
                "instability in the payment and authentication flows.').",
                "⚠️ CRITICAL — the context contains internal data tags. Your response MUST NOT output any line "
                "that starts with GROUP-ERROR-TYPE, GROUP-SAMPLE-ERROR, COUNT:, or TESTS:. "
                "Those are input labels only. If any such line appears in your answer it is WRONG.",
                "For each group in the context, produce this exact block:",
                "  Line 1: ---",
                "  Line 2: 🔴 Database Connection Issue (3 tests)",
                "  Line 3: ❌ testAddItemToCart()",
                "  Line 4: ❌ testCreateOrder()",
                "  Line 5: ❌ testValidUserLogin()",
                "  Line 6: Error:",
                "  Line 7: No connections available in pool (pool_size=10, active=10)",
                "Use 🔴 for N≥2 tests; use ⚠️ for N=1 test. Emoji is the FIRST character of heading line.",
                "Derive the human-readable title from the error type and sample error text. "
                "Examples: ConnectionPoolException → 'Database Connection Issue', "
                "AssertionError+HTTP 503 → 'Service Unavailable', "
                "TimeoutException → 'Performance / SLA Breach', "
                "JavaScriptException → 'Frontend JavaScript Error'.",
                "Each test on its own ❌ line — never concatenate tests on one line.",
                "DO NOT use bold markdown (`**`) anywhere in this answer. "
                "Group titles, test names, 'Error:' labels, and error messages must all be plain text.",
                "After the last group's error text, do NOT output a trailing '---' line. "
                "The Recovered section heading that follows provides sufficient visual separation.",
                "=== RECOVERED SECTION ===",
                "If M > 0: output '### ✅ Recovered (M)' (use real M count) on its own line.",
                "Then one '• testName()' bullet per test, each on its own line.",
                "Do NOT output a '---' line after the recovered bullets.",
                "OMIT the 'Consistently Failing' section — the user asked only about new regressions.",
                "DO NOT speculate on root cause beyond the context.",
                "DO NOT add recommendations.",
                "Keep total answer under 350 words.",
            ],
        )

    if intent == AnswerIntent.COMPARISON_CHANGE:
        norm_q = question.lower().strip()
        _trend_phrases = (
            "over time", "trend", "trending", "improving", "declining",
            "worsening", "getting better", "getting worse", "pass rate",
            "pass %", "failure rate", "progression", "trajectory",
            "over the last", "over recent", "across runs", "run over run",
        )
        is_trend_question = any(p in norm_q for p in _trend_phrases)

        _recovery_phrases = (
            "recovered", "which tests recovered", "tests that recovered",
            "fixed since", "passing again", "no longer failing",
            "back to passing", "started passing",
        )
        is_recovery_question = any(p in norm_q for p in _recovery_phrases)

        if is_recovery_question:
            return AnswerPlan(
                intent=intent,
            answer_type=answer_type,
                secondary_intent=secondary,
                ranking_metric=ranking_metric,
                include_root_cause=False,
                include_recommendations=False,
                no_unsolicited_root_cause=True,
                no_unsolicited_recommendations=True,
                ranking_basis=None,
                max_results=None,
                needs_exact_records=True,
                confidence_style="implicit",
                answer_rules=[
                    "Open with a heading: '## 📊 Comparing Run #X → Run #Y' (use exact run labels from context).",
                    "Immediately below the heading, place a one-line stat strip: '+N newly failing · −M recovered'.",
                    "Then output a blank line, then '---' on its own line.",
                    "=== RECOVERED SECTION (lead section — output this FIRST) ===",
                    "Output '### ✅ Recovered (M)' (use real M count) on its own line.",
                    "Then one sentence: 'These tests were failing in the previous run and are now passing.'",
                    "Then one '• testName()' bullet per recovered test, each on its own line.",
                    "Then output '---' on its own line after all bullets.",
                    "=== NEWLY FAILING SECTION (output second) ===",
                    "If N > 0: output '### 🚨 Newly Failing (N)' then list '❌ testName()' per test, each on its own line.",
                    "Then output '---'.",
                    "=== CONSISTENTLY FAILING SECTION (output last) ===",
                    "If K > 0: output '### ⚠️ Consistently Failing (K)' then list '❌ testName()' per test, each on its own line.",
                    "Do NOT place '---' after the Consistently Failing section.",
                    "Omit any section whose count is zero.",
                    "You MUST NOT speculate on root cause.",
                    "You MUST NOT add recommendations.",
                    "Keep total answer under 250 words.",
                ],
            )

        if is_trend_question:
            return AnswerPlan(
                intent=intent,
            answer_type=answer_type,
                secondary_intent=secondary,
                ranking_metric=ranking_metric,
                include_root_cause=False,
                include_recommendations=False,
                no_unsolicited_root_cause=True,
                no_unsolicited_recommendations=True,
                ranking_basis=None,
                max_results=None,
                needs_exact_records=True,
                confidence_style="explicit",
                is_trend_question=True,
                answer_rules=[
                    "Read the [TREND ANALYSIS] block in the [STRUCTURED FACTS] section.",
                    "If it says 'Not enough data', respond exactly: "
                    "'Not enough data to determine a trend.'",
                    "OTHERWISE follow this exact structure:",
                    "1. FIRST LINE: state the direction and confidence from [TREND ANALYSIS], e.g. "
                    "'The test pass rate is declining slightly (medium confidence).'",
                    "2. QUANTIFIED CHANGE: one sentence citing the exact change between the "
                    "most recent two runs, using real run labels and percentages from [TREND ANALYSIS].",
                    "3. RECENT TREND: introduce with 'Recent trend:' then list EVERY run from "
                    "the 'Per-run rates' table in [TREND ANALYSIS], newest first, one bullet each. "
                    "Show only the label and percentage, e.g.:",
                    "   Recent trend:",
                    "   • Run #53: 72%",
                    "   • Run #52: 80%",
                    "   • Run #51: 76%",
                    "   Include ALL runs listed — do not drop any.",
                    "4. SHORT INTERPRETATION: one sentence describing the trend severity, e.g. "
                    "'This indicates a mild downward trend in stability.'",
                    "5. OPTIONAL (only if supporting evidence exists in [TREND ANALYSIS]): "
                    "up to 3 bullets from the 'Supporting evidence' sub-section, introduced by "
                    "'This trend aligns with recent test changes:'",
                    "STRICT CONSTRAINTS:",
                    "  - Copy run labels and percentages EXACTLY from [TREND ANALYSIS]. Never invent values.",
                    "  - DO NOT add an Executive Summary section.",
                    "  - DO NOT add root-cause analysis.",
                    "  - DO NOT add recommendations.",
                    "  - DO NOT list individual test failures unless in the evidence bullets.",
                    "  - Keep the entire answer under 200 words.",
                ],
            )
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,
            include_root_cause=secondary == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            include_recommendations=secondary == AnswerIntent.RECOMMENDATION_ACTION,
            no_unsolicited_root_cause=secondary != AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            no_unsolicited_recommendations=secondary != AnswerIntent.RECOMMENDATION_ACTION,
            ranking_basis=None,
            max_results=None,
            needs_exact_records=True,
            confidence_style="implicit",
            answer_rules=[
                *([
                    "The user asked a follow-up lookup question. Answer it in ONE sentence "
                    "at the very top, before any section headings "
                    "(e.g. 'Run #53 had this issue.' or 'The run ID is #53.'). "
                    "Then proceed with the full comparison below.",
                ] if secondary == AnswerIntent.DRILL_DOWN_DETAIL else []),
                "Open with a heading: '## 📊 Comparing Run #X → Run #Y' (use exact run labels from context).",
                "Immediately below the heading, place a one-line stat strip: '+N newly failing · −M recovered'.",
                "Then output a blank line, then '---' on its own line.",
                "=== NEWLY FAILING SECTION ===",
                "Output '### 🚨 Newly Failing (N)'.",
                "Then write ONE brief sentence interpreting the overall pattern (e.g. 'This indicates a regression affecting database connectivity and service availability.').",
                "⚠️ CRITICAL — the context contains internal data tags. Your response MUST NOT output any line "
                "that starts with GROUP-ERROR-TYPE, GROUP-SAMPLE-ERROR, COUNT:, or TESTS:. "
                "Those are input labels only. If any such line appears in your answer it is WRONG.",
                "For each group in the context, produce this exact block:",
                "  Line 1: ---",
                "  Line 2: 🔴 Database Connection Issue (3 tests)",
                "  Line 3: ❌ testAddItemToCart()",
                "  Line 4: ❌ testCreateOrder()",
                "  Line 5: ❌ testValidUserLogin()",
                "  Line 6: Error:",
                "  Line 7: No connections available in pool (pool_size=10, active=10)",
                "Use 🔴 for N≥2 tests; use ⚠️ for N=1 test. Emoji is the FIRST character of heading line.",
                "Derive the human-readable title from the error type and sample error text. "
                "Examples: ConnectionPoolException → 'Database Connection Issue', "
                "AssertionError+HTTP 503 → 'Service Unavailable', "
                "TimeoutException → 'Performance / SLA Breach', "
                "JavaScriptException → 'Frontend JavaScript Error'.",
                "Each test on its own ❌ line — never concatenate tests on one line.",
                "After the last group's error line, output one final '---' on its own line.",
                "=== RECOVERED SECTION ===",
                "If M > 0: output '### ✅ Recovered (M)' (use real M count) on its own line.",
                "Then one '• testName()' bullet per test, each on its own line. No [was:] suffix.",
                "Then output '---' on its own line after all bullets.",
                "=== CONSISTENTLY FAILING SECTION ===",
                "If K > 0: output '### ⚠️ Consistently Failing (K)' (use real K count) on its own line.",
                "Then output 'These tests have failed across multiple runs:' on its own line.",
                "Then one '❌ testName()' per test, each on its own line.",
                "Do NOT place '---' after the Consistently Failing section.",
                "Omit any section whose count is zero.",
                "You MUST NOT speculate on root cause beyond the context.",
                "You MUST NOT add recommendations.",
                "Keep total answer under 380 words.",
            ],
        )

    if intent == AnswerIntent.DRILL_DOWN_DETAIL:
        norm_q = question.lower().strip()
        _is_recurrence_q = (
            "previous run" in norm_q
            or "previous runs" in norm_q
            or "past run" in norm_q
            or "happened before" in norm_q
            or "occurred before" in norm_q
            or "seen before" in norm_q
            or "failed before" in norm_q
            or "recurring" in norm_q
            or "have we seen" in norm_q
            or "before too" in norm_q
            or "before as well" in norm_q
        )
        # Detect "list failed/failing tests in/for Run N" pattern
        import re as _re
        _is_failed_list_q = bool(
            _re.search(
                r"(list|give|show|what|which).*?(failed|failing|fail).*?test",
                norm_q,
            )
            and _re.search(r"\brun\s*(?:no\.?|number|#|num\.?)?\s*\d+", norm_q)
        )
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,
            include_root_cause=False,
            include_recommendations=False,
            no_unsolicited_root_cause=True,
            no_unsolicited_recommendations=True,
            ranking_basis=None,
            max_results=None,
            needs_exact_records=True,
            confidence_style="none",
            answer_rules=[
                *(
                    [
                        # Recurrence follow-up: answer is in the comparison context already.
                        # Give a direct 2-3 sentence answer — do NOT re-render the panel.
                        "The user is asking whether these failures are recurring or new. "
                        "Answer in 2-3 sentences maximum following this pattern:",
                        "  1. State YES or NO: 'No — all 8 of these are NEW failures' / "
                        "'Yes — X of these have appeared in previous runs'.",
                        "  2. Cite evidence: look at the [Consistently Failing] count in context. "
                        "If it is 0, these are brand-new. If > 0, name those tests.",
                        "  3. Optional: one sentence naming the run(s) where consistent failures appeared.",
                        "DO NOT re-output the full comparison table or the list of newly-failing tests.",
                        "DO NOT use any section headings.",
                        "DO NOT use bullet lists.",
                    ]
                    if _is_recurrence_q
                    else [
                        # Failed-test list for a specific run
                        "## Direct answer",
                        "One sentence stating the run number and how many tests failed "
                        "(e.g. 'Run #18 had 8 failed test cases:').",
                        "Bullet list of all failed tests using this format per line:",
                        "  `<test name>` — <ExceptionType>",
                        "  - Wrap test names in backticks.",
                        "  - Use ‘—’ between test name and exception.",
                        "  - Keep exception names plain (no extra explanation).",
                        "  - If a test has no exception type, omit the exception part.",
                        "## Summary",
                        "  - Total failed: N",
                        "  - Most common exception (if one clearly dominates): ExceptionType (N tests)",
                        "  - If no failures: output exactly: "
                        "'No failed test cases were found in Run No: <run_number>.'",
                        "  - If the run is not in the context: output exactly: "
                        "'I could not find data for Run No: <run_number>.'",
                        "DO NOT include root-cause analysis unless explicitly requested.",
                        "DO NOT include recommendations unless explicitly requested.",
                        "DO NOT mention unavailable data if the data is present in the context.",
                    ]
                    if _is_failed_list_q
                    else [
                        "If the question asks for a single fact (a name, ID, date, or yes/no), "
                        "answer in ONE natural sentence only — do NOT output a summary, headings, or bullet lists. "
                        "Examples of correct single-fact answers:",
                        "  'This belongs to the ShopNow E-Commerce test suite.'",
                        "  'The run ID is #53.'",
                        "  'This test was added on 2026-01-15.'",
                        "For multi-record lookups (e.g. 'list all runs where X failed'), "
                        "deliver exact records as a compact list: run IDs, test names, dates, statuses.",
                    ]
                ),
                "Preserve original names and identifiers verbatim from the context.",
                "You MUST NOT add root-cause speculation.",
                "You MUST NOT add recommendations unless explicitly requested.",
                "You MUST NOT output a summary panel or section headings for a single-fact question.",
            ],
        )

    if intent == AnswerIntent.RECOMMENDATION_ACTION:
        return AnswerPlan(
            intent=intent,
            answer_type=answer_type,
            secondary_intent=secondary,
            ranking_metric=ranking_metric,
            include_root_cause=True,
            include_recommendations=True,
            no_unsolicited_root_cause=False,
            no_unsolicited_recommendations=False,
            ranking_basis=None,
            max_results=5,
            needs_exact_records=False,
            confidence_style="explicit",
            answer_rules=[
                "Lead with the single highest-priority action.",
                "Follow with 2–4 additional items ranked by urgency.",
                "For each item: action · why it matters · supporting evidence.",
                "State the signal that drives the priority (risk tier, flip score, streak).",
                "Ground every recommendation in the context data — no generic advice.",
            ],
        )

    # SUMMARY_OVERVIEW (default)
    return AnswerPlan(
        intent=AnswerIntent.SUMMARY_OVERVIEW,
        answer_type=answer_type,
        secondary_intent=secondary,
        ranking_metric=ranking_metric,
        include_root_cause=True,
        include_recommendations=True,
        no_unsolicited_root_cause=False,
        no_unsolicited_recommendations=False,
        ranking_basis=None,
        max_results=None,
        needs_exact_records=False,
        confidence_style="implicit",
        answer_rules=[
            "Open with a heading '## 📊 Run #N — <Project>' and a one-line stat strip: 'Passed: X · Failed: Y · Flaky: Z'.",
            "If a changes section is present in context (FIXED / NEW FAILURES), add ONE '### 🔄 Changes Since Last Run' heading (exactly once, not repeated) with bullet lists of fixed and newly-failing tests.",
            "Follow with '### ❗ Key Failures' listing the most significant failing tests.",
            "If flaky tests appear in context, add '### 🌀 Flaky Tests' with a brief list.",
            "Close with '### 👀 Watch List' — one actionable risk or focus area per bullet (omit if no risks).",
            "Keep length proportional to the complexity of the question; aim for under 300 words.",
        ],
    )
