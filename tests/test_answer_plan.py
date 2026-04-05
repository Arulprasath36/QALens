"""Tests for ari.llm.answer_plan, ari.llm.prompts (intent-aware), and
ari.llm.context_history (ConversationContext).

Coverage:
- detect_answer_intent: all 6 intents + priority ordering + default
- build_answer_plan: field assertions for all 6 intents
- build_prompt: structured vs legacy, section presence/absence
- build_system_prompt: base + per-intent addendum
- ConversationContext / extract_conversation_context
- extract_test_from_history backward-compat
"""
from __future__ import annotations

import pytest

from qara.llm.answer_plan import AnswerIntent, AnswerPlan, AnswerType, build_answer_plan, detect_answer_intent, detect_answer_type
from qara.llm.answer_plan import _is_flakiness_history_query, _is_flakiness_ranking_query  # noqa: E402
from qara.llm.prompts import build_prompt, build_system_prompt, infer_mode
from qara.llm.context_history import (
    ConversationContext,
    extract_conversation_context,
    extract_test_from_history,
)


# ===========================================================================
# detect_answer_intent — 6 intents
# ===========================================================================

RANKING_QUESTIONS = [
    "Which tests are the most flaky in the last 5 runs?",
    "What are the top 10 worst tests?",
    "List the most failing tests",
    "Which tests fail the most often?",
    "Rank every test by instability",
    "Give me the flakiest tests in the last 10 runs",
]

DIAGNOSTIC_QUESTIONS = [
    "Why did checkout fail in the latest run?",
    "Why does testCreateOrder keep failing?",
    "What caused the payment test to break?",
    "Explain why testLogin is broken",
    "Root cause of the NPE in testCheckout?",
    "What's wrong with testAddToCart?",
    "Diagnose the failure in the cart suite",
]

COMPARISON_QUESTIONS = [
    "Compare the last two runs",
    "What changed between run #50 and run #51?",
    "Compare run 49 vs run 50",
    "How has the test suite degraded?",
    "Show me the difference between the last 2 runs",
    "What tests have changed between runs?",
]

DRILLDOWN_QUESTIONS = [
    "Which specific run ID had this issue?",
    "Show me the exact run where testPayment failed",
    "What is the full history of testAddToCart?",
    "Show me the stack trace for this test",
    "Give me details for testLogin",
]

RECOMMENDATION_QUESTIONS = [
    "What do I fix first?",
    "Recommend the next steps for this failure",
    "What would you prioritize?",
    "Which tests should I quarantine?",
    "Give me an action plan",
    "What should I focus on?",
]

SUMMARY_QUESTIONS = [
    "Summarize the latest run.",
    "Give me an overview of the test health",
    "What is the status of the project?",
    "High level summary please",
    "Recap what happened this sprint",
    "How are we doing overall?",
]


@pytest.mark.parametrize("question", RANKING_QUESTIONS)
def test_detect_intent_ranking(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.RANKING_LIST


@pytest.mark.parametrize("question", DIAGNOSTIC_QUESTIONS)
def test_detect_intent_diagnostic(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE


@pytest.mark.parametrize("question", COMPARISON_QUESTIONS)
def test_detect_intent_comparison(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.COMPARISON_CHANGE


@pytest.mark.parametrize("question", DRILLDOWN_QUESTIONS)
def test_detect_intent_drilldown(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.DRILL_DOWN_DETAIL


@pytest.mark.parametrize("question", RECOMMENDATION_QUESTIONS)
def test_detect_intent_recommendation(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.RECOMMENDATION_ACTION


@pytest.mark.parametrize("question", SUMMARY_QUESTIONS)
def test_detect_intent_summary(question: str) -> None:
    assert detect_answer_intent(question) == AnswerIntent.SUMMARY_OVERVIEW


def test_detect_intent_default_for_generic_question() -> None:
    assert detect_answer_intent("What is happening?") == AnswerIntent.SUMMARY_OVERVIEW


def test_detect_intent_diagnostic_beats_ranking() -> None:
    # "Why are the most tests failing?" — diagnostic cue should win over ranking.
    q = "Why are the most tests failing?"
    assert detect_answer_intent(q) == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE


def test_detect_intent_comparison_beats_drilldown() -> None:
    # "Compare the exact last two runs" — comparison beats drilldown.
    q = "Compare the exact last two runs"
    assert detect_answer_intent(q) == AnswerIntent.COMPARISON_CHANGE


# ===========================================================================
# build_answer_plan — field contracts per intent
# ===========================================================================


def test_build_plan_ranking_list() -> None:
    plan = build_answer_plan(AnswerIntent.RANKING_LIST)
    assert plan.intent == AnswerIntent.RANKING_LIST
    assert plan.include_root_cause is False
    assert plan.include_recommendations is False
    assert plan.ranking_basis is not None
    assert plan.max_results is not None
    assert len(plan.answer_rules) > 0


def test_build_plan_diagnostic() -> None:
    plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
    assert plan.intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE
    assert plan.include_root_cause is True
    assert plan.needs_exact_records is True
    assert plan.confidence_style == "explicit"
    assert len(plan.answer_rules) > 0


def test_build_plan_comparison() -> None:
    plan = build_answer_plan(AnswerIntent.COMPARISON_CHANGE)
    assert plan.intent == AnswerIntent.COMPARISON_CHANGE
    assert plan.include_root_cause is False
    assert len(plan.answer_rules) > 0


def test_build_plan_drilldown() -> None:
    plan = build_answer_plan(AnswerIntent.DRILL_DOWN_DETAIL)
    assert plan.intent == AnswerIntent.DRILL_DOWN_DETAIL
    assert plan.needs_exact_records is True
    assert len(plan.answer_rules) > 0


def test_build_plan_recommendation() -> None:
    plan = build_answer_plan(AnswerIntent.RECOMMENDATION_ACTION)
    assert plan.intent == AnswerIntent.RECOMMENDATION_ACTION
    assert plan.include_recommendations is True
    assert len(plan.answer_rules) > 0


def test_build_plan_summary() -> None:
    plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW)
    assert plan.intent == AnswerIntent.SUMMARY_OVERVIEW
    assert len(plan.answer_rules) > 0


def test_build_plan_returns_answer_plan_instance() -> None:
    for intent in AnswerIntent:
        plan = build_answer_plan(intent)
        assert isinstance(plan, AnswerPlan)


# ===========================================================================
# build_prompt — structured sections present/absent
# ===========================================================================


def test_build_prompt_structured_sections_present() -> None:
    plan = build_answer_plan(AnswerIntent.RANKING_LIST)
    prompt = build_prompt(
        "Which tests are most flaky?", "context block", answer_plan=plan
    )
    assert "[QUESTION INTENT: RANKING LIST]" in prompt
    assert "[ANSWER RULES]" in prompt
    assert "[STRUCTURED FACTS]" in prompt
    assert "===== CONTEXT =====" in prompt
    assert "[QUESTION]" in prompt
    assert "context block" in prompt
    assert "Which tests are most flaky?" in prompt


def test_build_prompt_structured_contains_answer_rules_bullets() -> None:
    plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
    prompt = build_prompt("Why did it fail?", "ctx", answer_plan=plan)
    # Each answer rule must appear as a bullet
    for rule in plan.answer_rules:
        assert f"- {rule}" in prompt


def test_build_prompt_all_seven_intents_render() -> None:
    for intent in AnswerIntent:
        plan = build_answer_plan(intent)
        prompt = build_prompt("Some question", "some context", answer_plan=plan)
        assert "[QUESTION INTENT:" in prompt
        assert "===== CONTEXT =====" in prompt


def test_build_prompt_legacy_fallback_without_plan_test_mode() -> None:
    prompt = build_prompt("Why does testLogin fail?", "context block", mode="test")
    # Legacy template — no structured sections
    assert "[QUESTION INTENT" not in prompt
    assert "[ANSWER RULES]" not in prompt
    assert "context block" in prompt
    assert "Why does testLogin fail?" in prompt


def test_build_prompt_legacy_fallback_without_plan_project_mode() -> None:
    prompt = build_prompt("Summarize failures", "project ctx", mode="project")
    assert "[QUESTION INTENT" not in prompt
    assert "project ctx" in prompt


def test_build_prompt_history_block_included_in_structured() -> None:
    plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW)
    history = [
        {"role": "user", "content": "What failed?"},
        {"role": "assistant", "content": "testLogin failed."},
    ]
    prompt = build_prompt("Tell me more", "ctx", answer_plan=plan, history=history)
    assert "CONVERSATION SO FAR" in prompt
    assert "testLogin failed." in prompt


def test_build_prompt_history_block_included_in_legacy() -> None:
    history = [{"role": "user", "content": "Hello"}]
    prompt = build_prompt("Follow up?", "ctx", mode="project", history=history)
    assert "CONVERSATION SO FAR" in prompt


# ===========================================================================
# build_system_prompt
# ===========================================================================


def test_build_system_prompt_none_returns_base() -> None:
    system = build_system_prompt(None)
    assert "QARA" in system
    assert "test-analytics" in system


def test_build_system_prompt_with_plan_adds_addendum() -> None:
    plan = build_answer_plan(AnswerIntent.RANKING_LIST)
    system = build_system_prompt(plan)
    assert "RANKED LIST" in system


def test_build_system_prompt_diagnostic_addendum() -> None:
    plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
    system = build_system_prompt(plan)
    assert "DIAGNOSTIC" in system


def test_build_system_prompt_comparison_addendum() -> None:
    plan = build_answer_plan(AnswerIntent.COMPARISON_CHANGE)
    system = build_system_prompt(plan)
    assert "COMPARISON" in system


def test_build_system_prompt_all_intents_differ_from_base() -> None:
    base = build_system_prompt(None)
    for intent in AnswerIntent:
        plan = build_answer_plan(intent)
        system = build_system_prompt(plan)
        assert system != base or intent == AnswerIntent.SUMMARY_OVERVIEW


# ===========================================================================
# ConversationContext / extract_conversation_context
# ===========================================================================


def test_extract_conversation_context_finds_test_names() -> None:
    history = [
        {"role": "user", "content": "Why does testCreateOrder fail?"},
        {"role": "assistant", "content": "testCreateOrder is consistently broken."},
    ]
    ctx = extract_conversation_context(history)
    assert "testCreateOrder" in ctx.prior_tests


def test_extract_conversation_context_finds_time_window() -> None:
    history = [
        {"role": "user", "content": "Which tests failed in the last 5 runs?"},
    ]
    ctx = extract_conversation_context(history)
    assert ctx.prior_time_window is not None
    assert "5" in ctx.prior_time_window


def test_extract_conversation_context_finds_run_entity() -> None:
    history = [
        {"role": "user", "content": "Show me run #42"},
    ]
    ctx = extract_conversation_context(history)
    assert ctx.prior_entity is not None
    assert "42" in ctx.prior_entity


def test_extract_conversation_context_empty_history() -> None:
    ctx = extract_conversation_context([])
    assert ctx.prior_tests == []
    assert ctx.prior_time_window is None
    assert ctx.prior_entity is None
    assert ctx.prior_intent is None


def test_extract_conversation_context_multiple_tests() -> None:
    history = [
        {"role": "user", "content": "Compare testLogin and testCheckout"},
        {"role": "assistant", "content": "testLogin and testCheckout differ."},
    ]
    ctx = extract_conversation_context(history)
    assert "testLogin" in ctx.prior_tests
    assert "testCheckout" in ctx.prior_tests


def test_conversation_context_is_dataclass() -> None:
    ctx = ConversationContext()
    assert ctx.prior_tests == []
    assert ctx.prior_intent is None
    assert ctx.prior_entity is None
    assert ctx.prior_time_window is None


# ===========================================================================
# extract_test_from_history — backward compatibility
# ===========================================================================


def test_extract_test_from_history_backward_compat() -> None:
    history = [
        {"role": "user", "content": "Why does testFoo keep failing?"},
    ]
    assert extract_test_from_history(history) == "testFoo"


def test_extract_test_from_history_none_when_empty() -> None:
    assert extract_test_from_history([]) is None


def test_extract_test_from_history_none_when_no_test_names() -> None:
    history = [{"role": "user", "content": "What is the status?"}]
    assert extract_test_from_history(history) is None


# ===========================================================================
# Integration: detect_intent → build_plan → build_prompt pipeline
# ===========================================================================


def test_pipeline_ranking_question_no_root_cause_section() -> None:
    """'Which tests are the most flaky in the last 5 runs?' must NOT produce a
    root-cause section."""
    question = "Which tests are the most flaky in the last 5 runs?"
    plan = build_answer_plan(detect_answer_intent(question))
    prompt = build_prompt(question, "context", answer_plan=plan)
    # The intent label must be RANKING LIST, not diagnostic
    assert "RANKING LIST" in prompt
    # The plan should explicitly forbid root-cause content
    assert plan.include_root_cause is False


def test_pipeline_diagnostic_question_includes_confidence() -> None:
    """'Why did checkout fail in the latest run?' → plan should require
    explicit confidence level in answers."""
    question = "Why did checkout fail in the latest run?"
    plan = build_answer_plan(detect_answer_intent(question))
    assert plan.confidence_style == "explicit"


def test_pipeline_comparison_question_four_group_categories() -> None:
    """'Compare the last two runs.' → structured facts must reference all four
    change categories."""
    question = "Compare the last two runs."
    plan = build_answer_plan(detect_answer_intent(question))
    prompt = build_prompt(question, "ctx", answer_plan=plan)
    # Structured facts section should include category names
    assert "Newly Failing" in prompt
    assert "Recovered" in prompt
    assert "Consistently Failing" in prompt


def test_pipeline_drilldown_exact_records_required() -> None:
    """'Which specific run ID had this issue?' → plan must request exact records."""
    question = "Which specific run ID had this issue?"
    plan = build_answer_plan(detect_answer_intent(question))
    assert plan.needs_exact_records is True


# ===========================================================================
# RankingMetric detection — detect_ranking_metric
# ===========================================================================

from qara.llm.answer_plan import RankingMetric, detect_ranking_metric, detect_secondary_intent


class TestDetectRankingMetric:
    def test_default_is_flakiness(self) -> None:
        assert detect_ranking_metric("which tests are most flaky") == RankingMetric.FLAKINESS

    def test_duration_keywords(self) -> None:
        for q in [
            "which tests are the slowest",
            "show me tests with longest duration",
            "what tests are taking the most time",
            "worst execution time",
        ]:
            assert detect_ranking_metric(q) == RankingMetric.DURATION, q

    def test_risk_keywords(self) -> None:
        for q in [
            "which tests are most at risk",
            "riskiest tests",
            "which tests are likely to fail",
            "highest risk tests",
            "which tests are most likely to fail next run",
            "tests most likely to fail",
            "which tests are about to fail",
            "tests predicted to fail",
        ]:
            assert detect_ranking_metric(q) == RankingMetric.RISK, q

    def test_failure_burden_keywords(self) -> None:
        for q in [
            "which tests have the most failures",
            "tests with highest failure count",
            "tests that failed the most",
        ]:
            assert detect_ranking_metric(q) == RankingMetric.FAILURE_BURDEN, q

    def test_no_specific_cue_defaults_to_flakiness(self) -> None:
        assert detect_ranking_metric("get me the top 10 tests") == RankingMetric.FLAKINESS

    def test_empty_question_defaults_to_flakiness(self) -> None:
        assert detect_ranking_metric("") == RankingMetric.FLAKINESS


# ===========================================================================
# Secondary intent detection — detect_secondary_intent
# ===========================================================================


class TestDetectSecondaryIntent:
    def test_ranking_plus_diagnostic(self) -> None:
        """'rank the flaky tests and explain why they fail'"""
        q = "rank the flaky tests and explain why they fail"
        primary = AnswerIntent.RANKING_LIST
        secondary = detect_secondary_intent(q, primary)
        assert secondary == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    def test_comparison_plus_recommendation(self) -> None:
        q = "compare the last two runs and recommend what to fix first"
        secondary = detect_secondary_intent(q, AnswerIntent.COMPARISON_CHANGE)
        assert secondary == AnswerIntent.RECOMMENDATION_ACTION

    def test_diagnostic_plus_ranking(self) -> None:
        q = "why is testLogin failing and which tests are the worst offenders"
        secondary = detect_secondary_intent(q, AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        assert secondary == AnswerIntent.RANKING_LIST

    def test_no_secondary_returns_none(self) -> None:
        secondary = detect_secondary_intent("which tests are most flaky", AnswerIntent.RANKING_LIST)
        assert secondary is None

    def test_primary_not_returned_as_secondary(self) -> None:
        """Even if primary cue appears again, secondary must differ."""
        q = "rank the top flaky tests top failing tests"  # "top" fires RANKING twice
        secondary = detect_secondary_intent(q, AnswerIntent.RANKING_LIST)
        # Should not return RANKING_LIST as secondary
        assert secondary != AnswerIntent.RANKING_LIST


# ===========================================================================
# build_answer_plan — new fields propagated
# ===========================================================================


class TestBuildAnswerPlanNewFields:
    def test_ranking_resolves_metric_flakiness(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="which tests are most flaky")
        assert plan.ranking_metric == RankingMetric.FLAKINESS
        assert plan.secondary_intent is None

    def test_ranking_resolves_metric_duration(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="which tests are slowest")
        assert plan.ranking_metric == RankingMetric.DURATION
        assert "avg_duration" in (plan.ranking_basis or "")

    def test_ranking_resolves_metric_risk(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="which tests are most at risk")
        assert plan.ranking_metric == RankingMetric.RISK
        assert "risk" in (plan.ranking_basis or "").lower()

    def test_ranking_resolves_metric_failure_burden(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="which tests fail the most")
        assert plan.ranking_metric == RankingMetric.FAILURE_BURDEN
        assert "failure_count" in (plan.ranking_basis or "")

    def test_ranking_with_diagnostic_secondary(self) -> None:
        q = "rank the flaky tests and explain why they fail"
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question=q)
        assert plan.secondary_intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE
        assert plan.include_root_cause is True

    def test_ranking_no_question_defaults(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        assert plan.secondary_intent is None
        assert plan.ranking_metric is None  # not resolved without question

    def test_constraint_fields_ranking(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="top 10 flaky tests")
        assert plan.no_unsolicited_root_cause is True
        assert plan.no_unsolicited_recommendations is True

    def test_constraint_fields_diagnostic(self) -> None:
        plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        assert plan.no_unsolicited_root_cause is False
        assert plan.no_unsolicited_recommendations is False

    def test_constraint_fields_drilldown(self) -> None:
        plan = build_answer_plan(AnswerIntent.DRILL_DOWN_DETAIL)
        assert plan.no_unsolicited_root_cause is True
        assert plan.no_unsolicited_recommendations is True

    def test_answer_rules_contain_must_not_language(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        combined = "\n".join(plan.answer_rules)
        assert "MUST NOT" in combined

    def test_answer_rules_drilldown_must_not_language(self) -> None:
        plan = build_answer_plan(AnswerIntent.DRILL_DOWN_DETAIL)
        combined = "\n".join(plan.answer_rules)
        assert "MUST NOT" in combined


# ===========================================================================
# build_prompt — structured_facts parameter + secondary intent label
# ===========================================================================


class TestBuildPromptNewFeatures:
    def test_structured_facts_overrides_static_defs(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        custom_facts = "Rank  Test  Score\n1  testFoo  9.5"
        prompt = build_prompt("top tests", "ctx", answer_plan=plan, structured_facts=custom_facts)
        assert custom_facts in prompt
        # Static default should NOT appear when custom facts are provided
        assert "flip_score (number of pass" not in prompt

    def test_structured_facts_none_uses_static(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        prompt = build_prompt("top tests", "ctx", answer_plan=plan, structured_facts=None)
        assert "flip_score" in prompt.lower() or "ranking metric" in prompt.lower()

    def test_secondary_intent_label_in_prompt(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.RANKING_LIST,
            question="rank the flaky tests and explain why they fail",
        )
        assert plan.secondary_intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE
        prompt = build_prompt("rank and explain", "ctx", answer_plan=plan)
        assert "RANKING LIST" in prompt
        assert "DIAGNOSTIC" in prompt

    def test_single_intent_label_when_no_secondary(self) -> None:
        plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW)
        prompt = build_prompt("give me an overview", "ctx", answer_plan=plan)
        assert "SUMMARY / OVERVIEW" in prompt
        assert "+" not in prompt.split("[QUESTION INTENT:")[1].split("]")[0]

    def test_secondary_description_included(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.RANKING_LIST,
            question="rank the flaky tests and explain why they fail",
        )
        prompt = build_prompt("rank and explain", "ctx", answer_plan=plan)
        # Both primary and secondary descriptions should appear
        assert "ranked list" in prompt.lower()
        assert "root cause" in prompt.lower()


# ===========================================================================
# build_system_prompt — secondary intent addendum
# ===========================================================================


class TestBuildSystemPromptUpdate:
    def test_system_prompt_ranking_must_not_language(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        sys_prompt = build_system_prompt(plan)
        assert "MUST NOT" in sys_prompt

    def test_system_prompt_secondary_intent_mentioned(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.RANKING_LIST,
            question="rank the flaky tests and explain why they fail",
        )
        sys_prompt = build_system_prompt(plan)
        assert "secondary intent" in sys_prompt.lower() or "DIAGNOSTIC" in sys_prompt

    def test_system_prompt_no_secondary_when_none(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        sys_prompt = build_system_prompt(plan)
        assert "secondary intent" not in sys_prompt.lower()

    def test_comparison_system_prompt_must_not(self) -> None:
        plan = build_answer_plan(AnswerIntent.COMPARISON_CHANGE)
        sys_prompt = build_system_prompt(plan)
        assert "MUST NOT" in sys_prompt

    def test_drilldown_secondary_puts_answer_first(self) -> None:
        """When DRILL_DOWN_DETAIL is secondary, system prompt must instruct answer at top."""
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="which run ID had this issue",
        )
        sys_prompt = build_system_prompt(plan)
        assert "top" in sys_prompt.lower() or "first" in sys_prompt.lower()
        assert "secondary intent" not in sys_prompt.lower()  # not the generic addendum

    def test_drilldown_secondary_comparison_rules_prepend_instruction(self) -> None:
        """COMPARISON_CHANGE answer rules must have a leading 'answer first' rule when DRILL_DOWN secondary."""
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="which run ID had this issue",
        )
        if plan.secondary_intent == AnswerIntent.DRILL_DOWN_DETAIL:
            first_rule = plan.answer_rules[0]
            assert "top" in first_rule.lower() or "first" in first_rule.lower() or "follow-up" in first_rule.lower()

    def test_drilldown_intent_not_overridden_by_prior_comparison_context(self) -> None:
        """If the question has primary DRILLDOWN signals, prior COMPARISON context must not override it."""
        from qara.llm.context_history import ResolvedQueryContext
        prior_ctx = ResolvedQueryContext(
            prior_intent=AnswerIntent.COMPARISON_CHANGE,
            prior_ranking_metric=None,
            prior_max_results=None,
            prior_test_names=[],
            prior_time_window=None,
        )
        plan = build_answer_plan(
            AnswerIntent.DRILL_DOWN_DETAIL,
            question="which specific run id had this issue",
            prior_context=prior_ctx,
        )
        assert plan.intent == AnswerIntent.DRILL_DOWN_DETAIL

    def test_temporal_cues_route_to_drilldown(self) -> None:
        for cue in ["when did this issue first appear", "when was this first introduced"]:
            intent = detect_answer_intent(cue)
            assert intent == AnswerIntent.DRILL_DOWN_DETAIL, (
                f"Expected DRILL_DOWN_DETAIL for '{cue}', got {intent}"
            )


# ===========================================================================
# Gap A — Ranking-first mixed-intent detection
# ===========================================================================

from qara.llm.answer_plan import _is_ranking_first_mixed_query  # noqa: E402


class TestRankingFirstMixedQuery:
    """Tests for the ranking-first pre-pass in detect_answer_intent."""

    def test_ranking_first_mixed_most_flaky_tests(self) -> None:
        assert _is_ranking_first_mixed_query("Why are the most flaky tests failing?") is True

    def test_ranking_first_mixed_flakiest_tests(self) -> None:
        assert _is_ranking_first_mixed_query("Why are the flakiest tests always broken?") is True

    def test_ranking_first_mixed_top_tests(self) -> None:
        assert _is_ranking_first_mixed_query("Why do the top failing tests keep regressing?") is True

    def test_not_ranking_first_missing_list_orientation(self) -> None:
        # "Why is testCheckout flaky?" — no list-orientation cue, no ranking cue
        assert _is_ranking_first_mixed_query("Why is testCheckout flaky?") is False

    def test_not_ranking_first_no_diagnostic_cue(self) -> None:
        # Pure ranking question: no diagnostic cue
        assert _is_ranking_first_mixed_query("Which tests are the most flaky?") is False

    def test_not_ranking_first_most_tests_no_ranking_cue(self) -> None:
        # "Why are the most tests failing?" — "most tests failing" ≠ "most failing" substring
        assert _is_ranking_first_mixed_query("Why are the most tests failing?") is False

    def test_detect_intent_ranking_first_for_mixed_list_question(self) -> None:
        assert detect_answer_intent("Why are the most flaky tests failing?") == AnswerIntent.RANKING_LIST

    def test_detect_intent_ranking_first_for_flakiest_tests(self) -> None:
        assert detect_answer_intent("Why do the flakiest tests fail so often?") == AnswerIntent.RANKING_LIST

    def test_detect_intent_diagnostic_preserved_single_test(self) -> None:
        assert detect_answer_intent("Why is testCheckout failing?") == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    def test_detect_intent_diagnostic_preserved_without_ranking_cue(self) -> None:
        # No ranking cue match → DIAGNOSTIC wins
        assert detect_answer_intent("Why are the most tests failing?") == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    def test_build_plan_mixed_intent_secondary_is_diagnostic(self) -> None:
        q = "Why are the most flaky tests failing?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        assert plan.intent == AnswerIntent.RANKING_LIST
        assert plan.secondary_intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    def test_build_plan_mixed_intent_includes_root_cause(self) -> None:
        q = "Why are the most flaky tests failing?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        assert plan.include_root_cause is True

    def test_build_plan_mixed_intent_extra_rules_present(self) -> None:
        q = "Why are the most flaky tests failing?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        assert any("Why these tests fail" in r for r in plan.answer_rules)


# ===========================================================================
# Risk-prediction question routing — detect_answer_intent + RISK plan shape
# ===========================================================================


class TestRiskPredictionRouting:
    """'Most likely to fail next run' questions must route to RANKING_LIST + RISK."""

    def test_likely_to_fail_routes_to_ranking(self) -> None:
        assert detect_answer_intent("Which tests are most likely to fail next run?") == AnswerIntent.RANKING_LIST

    def test_likely_to_fail_no_qualifier_routes_to_ranking(self) -> None:
        assert detect_answer_intent("Which tests are likely to fail?") == AnswerIntent.RANKING_LIST

    def test_about_to_fail_routes_to_ranking(self) -> None:
        assert detect_answer_intent("Which tests are about to fail?") == AnswerIntent.RANKING_LIST

    def test_predicted_to_fail_routes_to_ranking(self) -> None:
        assert detect_answer_intent("Show me tests predicted to fail") == AnswerIntent.RANKING_LIST

    def test_fail_next_run_routes_to_ranking(self) -> None:
        assert detect_answer_intent("What will fail next run?") == AnswerIntent.RANKING_LIST

    def test_likely_to_fail_metric_is_risk(self) -> None:
        assert detect_ranking_metric("Which tests are most likely to fail next run?") == RankingMetric.RISK

    def test_about_to_fail_metric_is_risk(self) -> None:
        assert detect_ranking_metric("which tests are about to fail") == RankingMetric.RISK

    def test_full_pipeline_routes_to_risk_ranking(self) -> None:
        q = "Which tests are most likely to fail next run?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.intent == AnswerIntent.RANKING_LIST
        assert plan.ranking_metric == RankingMetric.RISK

    def test_risk_plan_basis_describes_signal_factors(self) -> None:
        q = "Which tests are most likely to fail next run?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        basis = plan.ranking_basis or ""
        assert "volatility" in basis
        assert "failure burden" in basis

    def test_risk_plan_rules_include_tier_format(self) -> None:
        q = "Which tests are most likely to fail next run?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        rules = "\n".join(plan.answer_rules)
        assert "HIGH risk" in rules or "TIER risk" in rules or "risk_tier" in rules

    def test_risk_plan_rules_include_how_i_ranked(self) -> None:
        q = "Which tests are most likely to fail next run?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        rules = "\n".join(plan.answer_rules)
        assert "How I ranked them" in rules

    def test_risk_plan_rules_include_why_these_rank(self) -> None:
        q = "Which tests are most likely to fail next run?"
        plan = build_answer_plan(detect_answer_intent(q), question=q)
        rules = "\n".join(plan.answer_rules)
        assert "Why these rank highly" in rules


# ===========================================================================
# Gap B — max_results threaded through context builders
# ===========================================================================


class TestMaxResultsThreading:
    def test_ranking_plan_max_results_is_10(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        assert plan.max_results == 10

    def test_ranking_plan_rules_reference_max_results(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        assert any(f"List at most {plan.max_results}" in r for r in plan.answer_rules)

    def test_recommendation_plan_max_results_is_5(self) -> None:
        plan = build_answer_plan(AnswerIntent.RECOMMENDATION_ACTION)
        assert plan.max_results == 5

    def test_diagnostic_plan_max_results_is_none(self) -> None:
        assert build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE).max_results is None

    def test_comparison_plan_max_results_is_none(self) -> None:
        assert build_answer_plan(AnswerIntent.COMPARISON_CHANGE).max_results is None

    def test_gather_context_routing_passes_max_results(self) -> None:
        from unittest.mock import patch
        from qara.llm.routing import gather_context_for_signals, detect_signals, normalize_query
        from qara.llm.answer_plan import AnswerPlan, AnswerType, RankingMetric

        plan = AnswerPlan(
            intent=AnswerIntent.RANKING_LIST,
            answer_type=AnswerType.FLAKINESS_RANKING,
            include_root_cause=False,
            include_recommendations=False,
            max_results=5,
            ranking_metric=RankingMetric.FLAKINESS,
            answer_rules=[],
        )
        signals = detect_signals(normalize_query("top flaky tests"))

        with patch("qara.llm.routing.gather_ranking_context", return_value=("ctx", "facts", [])) as mock_fn:
            gather_context_for_signals(
                signals, "top flaky tests", project="P", db_path=None, answer_plan=plan,
            )
            mock_fn.assert_called_once_with(
                project="P", db_path=None, metric=RankingMetric.FLAKINESS, top_n=5,
            )

    def test_gather_context_routing_recommendation_respects_cap(self) -> None:
        from unittest.mock import patch
        from qara.llm.routing import gather_context_for_signals, detect_signals, normalize_query
        from qara.llm.answer_plan import AnswerPlan, AnswerType

        plan = AnswerPlan(
            intent=AnswerIntent.RECOMMENDATION_ACTION,
            answer_type=AnswerType.RECOMMENDATION,
            include_root_cause=False,
            include_recommendations=True,
            max_results=3,
            answer_rules=[],
        )
        signals = detect_signals(normalize_query("what should I fix first"))

        with patch("qara.llm.routing.gather_recommendation_context", return_value=("ctx", "facts", [])) as mock_fn:
            gather_context_for_signals(
                signals, "what should I fix first", project="P", db_path=None, answer_plan=plan,
            )
            mock_fn.assert_called_once_with(
                project="P", db_path=None, top_n_risk=3, top_n_flaky=3,
            )


# ===========================================================================
# Gap C — ResolvedQueryContext and follow-up inheritance
# ===========================================================================

from qara.llm.context_history import (  # noqa: E402
    ResolvedQueryContext,
    extract_query_context_from_plan,
    has_followup_override,
    has_followup_reference,
    has_strong_new_topic_signal,
    is_followup_question,
    extract_max_results_override,
    extract_prior_context_from_history,
)
from qara.llm.answer_plan import RankingMetric as _RankingMetric  # noqa: E402


class TestResolvedQueryContext:
    def test_dataclass_defaults(self) -> None:
        ctx = ResolvedQueryContext()
        assert ctx.prior_intent is None
        assert ctx.prior_ranking_metric is None
        assert ctx.prior_max_results is None
        assert ctx.prior_test_names == []

    def test_extract_from_plan(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="top flaky tests")
        ctx = extract_query_context_from_plan(plan, test_names=["testFoo"])
        assert ctx.prior_intent == AnswerIntent.RANKING_LIST
        assert ctx.prior_max_results == 10
        assert "testFoo" in ctx.prior_test_names

    def test_extract_from_plan_no_tests(self) -> None:
        plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW)
        ctx = extract_query_context_from_plan(plan)
        assert ctx.prior_test_names == []


class TestHasFollowupReference:
    def test_explain_that(self) -> None:
        assert has_followup_reference("Can you explain that more?") is True

    def test_explain_those(self) -> None:
        assert has_followup_reference("Explain those failures please") is True

    def test_run_ids(self) -> None:
        assert has_followup_reference("Which run IDs?") is True

    def test_those_ones(self) -> None:
        assert has_followup_reference("Tell me more about those ones") is True

    def test_the_ones(self) -> None:
        assert has_followup_reference("Show me the ones that failed") is True

    def test_which_ones(self) -> None:
        assert has_followup_reference("Which ones are critical?") is True

    def test_drill_down(self) -> None:
        assert has_followup_reference("Can you drill down on that?") is True

    def test_what_about(self) -> None:
        assert has_followup_reference("What about the second one?") is True

    def test_no_reference(self) -> None:
        assert has_followup_reference("What failed yesterday?") is False

    def test_fresh_query_no_reference(self) -> None:
        assert has_followup_reference("Summarize the latest run") is False


class TestHasFollowupOverride:
    def test_numeric_top_n(self) -> None:
        assert has_followup_override("Show just the top 3") is True

    def test_numeric_only_n(self) -> None:
        assert has_followup_override("Only 5 please") is True

    def test_instead_cue(self) -> None:
        assert has_followup_override("What about in the last 10 runs instead?") is True

    def test_only_those(self) -> None:
        assert has_followup_override("Only those tests") is True

    def test_only_for(self) -> None:
        assert has_followup_override("Only for the checkout suite") is True

    def test_but_only(self) -> None:
        assert has_followup_override("But only the flaky ones") is True

    def test_no_override(self) -> None:
        assert has_followup_override("What are the top flaky tests?") is False

    def test_no_override_long(self) -> None:
        assert has_followup_override("Which tests fail most often across the last 20 runs?") is False


class TestHasStrongNewTopicSignal:
    _prior = ResolvedQueryContext(
        prior_intent=None,
        prior_test_names=["testLogin"],
    )

    def test_yesterday(self) -> None:
        assert has_strong_new_topic_signal("What failed yesterday?", self._prior) is True

    def test_today(self) -> None:
        assert has_strong_new_topic_signal("What broke today?", self._prior) is True

    def test_last_week(self) -> None:
        assert has_strong_new_topic_signal("Summary from last week", self._prior) is True

    def test_numeric_date(self) -> None:
        assert has_strong_new_topic_signal("Show me failures from 3/7/2026", self._prior) is True

    def test_iso_date(self) -> None:
        assert has_strong_new_topic_signal("Failures on 2026-03-07", self._prior) is True

    def test_summarize_latest(self) -> None:
        assert has_strong_new_topic_signal("Summarize the latest run", self._prior) is True

    def test_compare_the_last(self) -> None:
        assert has_strong_new_topic_signal("Compare the last two runs", self._prior) is True

    def test_what_failed(self) -> None:
        assert has_strong_new_topic_signal("What failed?", self._prior) is True

    def test_new_camelcase_entity(self) -> None:
        # testCheckout is NOT in prior_test_names (only testLogin is)
        assert has_strong_new_topic_signal("Why is testCheckout flaky?", self._prior) is True

    def test_known_camelcase_entity_not_new(self) -> None:
        # testLogin IS in prior — not a new entity
        assert has_strong_new_topic_signal("Tell me more about testLogin", self._prior) is False

    def test_prior_none_always_false(self) -> None:
        assert has_strong_new_topic_signal("What failed yesterday?", None) is False

    def test_explain_that_not_new_topic(self) -> None:
        assert has_strong_new_topic_signal("Can you explain that more?", self._prior) is False


class TestIsFollowupQuestion:
    def test_short_question_is_followup(self) -> None:
        # "show top 3" triggers a numeric max_results override
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST)
        assert is_followup_question("show top 3", prior) is True

    def test_long_question_is_not_followup(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST)
        long_q = "which tests are the most flaky across the entire project run history"
        assert is_followup_question(long_q, prior) is False

    def test_no_prior_is_not_followup(self) -> None:
        assert is_followup_question("top 3", None) is False

    def test_eight_word_question_is_followup(self) -> None:
        # "the ones" is a back-reference phrase
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST)
        assert is_followup_question("can you show me the ones", prior) is True

    def test_nine_word_question_is_not_followup(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST)
        q = "can you please show me just the top ranking tests"
        assert is_followup_question(q, prior) is False


class TestIsFollowupPrecise:
    """Spec-level integration tests covering the 8 documented scenarios."""

    _prior = ResolvedQueryContext(
        prior_intent=AnswerIntent.RANKING_LIST,
        prior_test_names=["testLogin", "testCheckoutFlow"],
    )

    # --- Should return True ---

    def test_explain_that_more_is_followup(self) -> None:
        assert is_followup_question("Can you explain that more?", self._prior) is True

    def test_which_run_ids_is_followup(self) -> None:
        assert is_followup_question("Which run IDs?", self._prior) is True

    def test_show_top_3_is_followup(self) -> None:
        assert is_followup_question("Show just the top 3", self._prior) is True

    def test_what_about_in_last_10_is_followup(self) -> None:
        assert is_followup_question("What about in the last 10 runs instead?", self._prior) is True

    # --- Should return False ---

    def test_what_failed_yesterday_not_followup(self) -> None:
        assert is_followup_question("What failed yesterday?", self._prior) is False

    def test_summarize_latest_run_not_followup(self) -> None:
        assert is_followup_question("Summarize the latest run", self._prior) is False

    def test_compare_last_two_runs_not_followup(self) -> None:
        assert is_followup_question("Compare the last two runs", self._prior) is False

    def test_new_test_entity_not_followup(self) -> None:
        # testPayment is not in prior_test_names
        assert is_followup_question("Why is testPayment flaky?", self._prior) is False


class TestExtractMaxResultsOverride:
    def test_top_n(self) -> None:
        assert extract_max_results_override("show just the top 3") == 3

    def test_only_n(self) -> None:
        assert extract_max_results_override("only 5 please") == 5

    def test_first_n(self) -> None:
        assert extract_max_results_override("first 7 results") == 7

    def test_just_n(self) -> None:
        assert extract_max_results_override("just 2") == 2

    def test_no_override_returns_none(self) -> None:
        assert extract_max_results_override("show me the ranking") is None


class TestFollowupInheritanceInBuildPlan:
    def test_followup_inherits_intent(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST)
        plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW, question="top 3", prior_context=prior)
        assert plan.intent == AnswerIntent.RANKING_LIST

    def test_followup_inherits_metric(self) -> None:
        prior = ResolvedQueryContext(
            prior_intent=AnswerIntent.RANKING_LIST,
            prior_ranking_metric=_RankingMetric.DURATION,
        )
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="top 3", prior_context=prior)
        assert plan.ranking_metric == _RankingMetric.DURATION

    def test_followup_numeric_override_wins(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST, prior_max_results=10)
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="show top 3", prior_context=prior)
        assert plan.max_results == 3

    def test_followup_inherits_prior_max_results_when_no_override(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST, prior_max_results=10)
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="show the list", prior_context=prior)
        assert plan.max_results == 10

    def test_no_prior_context_unchanged(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="top flaky tests")
        assert plan.intent == AnswerIntent.RANKING_LIST
        assert plan.max_results == 10

    def test_followup_rule_updated_to_match_override(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST, prior_max_results=10)
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question="show top 5", prior_context=prior)
        rules_text = "\n".join(plan.answer_rules)
        assert "List at most 5" in rules_text
        assert "List at most 10" not in rules_text

    def test_long_question_does_not_trigger_followup(self) -> None:
        prior = ResolvedQueryContext(prior_intent=AnswerIntent.RANKING_LIST, prior_max_results=10)
        q = "which tests are ranked highest by flakiness score across all recent runs"
        plan = build_answer_plan(AnswerIntent.RANKING_LIST, question=q, prior_context=prior)
        # Long question: does NOT inherit → fresh plan with standard max_results
        assert plan.max_results == 10


class TestExtractPriorContextFromHistory:
    def test_empty_history_returns_none(self) -> None:
        assert extract_prior_context_from_history([]) is None

    def test_no_user_message_returns_none(self) -> None:
        history = [{"role": "assistant", "content": "Here are the flaky tests..."}]
        assert extract_prior_context_from_history(history) is None

    def test_ranking_question_gives_ranking_intent(self) -> None:
        history = [{"role": "user", "content": "Which tests are the most flaky?"}]
        ctx = extract_prior_context_from_history(history)
        assert ctx is not None
        assert ctx.prior_intent == AnswerIntent.RANKING_LIST

    def test_propagates_time_window_from_history(self) -> None:
        history = [{"role": "user", "content": "top flaky tests in the last 5 runs"}]
        ctx = extract_prior_context_from_history(history)
        assert ctx is not None
        assert ctx.prior_time_window is not None
        assert "5" in ctx.prior_time_window

    def test_propagates_test_names_from_history(self) -> None:
        history = [
            {"role": "user", "content": "Why is testCreateOrder failing?"},
            {"role": "assistant", "content": "testCreateOrder has a NPE..."},
        ]
        ctx = extract_prior_context_from_history(history)
        assert ctx is not None
        assert "testCreateOrder" in ctx.prior_test_names


# ===========================================================================
# Gap D — Global "answer only what was asked" rule
# ===========================================================================

from qara.llm.prompts import _BASE_SYSTEM_PROMPT  # noqa: E402


class TestGlobalAnswerRule:
    def test_base_prompt_contains_answer_only_rule(self) -> None:
        assert "Answer only what the user asked" in _BASE_SYSTEM_PROMPT

    def test_base_prompt_no_extra_sections_rule(self) -> None:
        assert "Do not add extra sections" in _BASE_SYSTEM_PROMPT

    def test_build_system_prompt_none_contains_global_rule(self) -> None:
        assert "Answer only what the user asked" in build_system_prompt(None)

    def test_build_system_prompt_all_intents_contain_global_rule(self) -> None:
        for intent in AnswerIntent:
            plan = build_answer_plan(intent)
            sys_prompt = build_system_prompt(plan)
            assert "Answer only what the user asked" in sys_prompt, f"Missing for {intent}"

    def test_global_rule_precedes_intent_addendum(self) -> None:
        plan = build_answer_plan(AnswerIntent.RANKING_LIST)
        sys_prompt = build_system_prompt(plan)
        global_pos = sys_prompt.index("Answer only what the user asked")
        must_not_pos = sys_prompt.index("MUST NOT")
        assert global_pos < must_not_pos


# ===========================================================================
# Gap E — Premium format rules for comparison and summary answers
# ===========================================================================


class TestComparisonFormatRules:
    """Answer rules for COMPARISON_CHANGE (non-trend) must enforce premium format."""

    def _get_comparison_rules(self, question: str = "what new failures appeared") -> list[str]:
        plan = build_answer_plan(AnswerIntent.COMPARISON_CHANGE, question=question)
        return plan.answer_rules

    def test_comparison_rules_contain_h2_emoji_header(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "\U0001f4ca" in rules_text  # 📊

    def test_comparison_rules_contain_newly_failing_section(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "Newly Failing" in rules_text

    def test_comparison_rules_contain_recovered_section(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "Recovered" in rules_text

    def test_comparison_rules_enforce_grouping_by_root_cause(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "root cause" in rules_text.lower() or "grouped" in rules_text.lower()

    def test_comparison_rules_enforce_error_label(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "Error:" in rules_text

    def test_comparison_rules_prohibit_root_cause_speculation(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "MUST NOT speculate" in rules_text

    def test_comparison_rules_prohibit_recommendations(self) -> None:
        rules_text = " ".join(self._get_comparison_rules())
        assert "MUST NOT add recommendations" in rules_text


class TestSummaryFormatRules:
    """Answer rules for SUMMARY_OVERVIEW must enforce structured section headings."""

    def _get_summary_rules(self) -> list[str]:
        plan = build_answer_plan(AnswerIntent.SUMMARY_OVERVIEW)
        return plan.answer_rules

    def test_summary_rules_contain_h2_header(self) -> None:
        rules_text = " ".join(self._get_summary_rules())
        assert "\U0001f4ca" in rules_text  # 📊

    def test_summary_rules_contain_changes_section(self) -> None:
        rules_text = " ".join(self._get_summary_rules())
        assert "Changes" in rules_text

    def test_summary_rules_contain_watch_list(self) -> None:
        rules_text = " ".join(self._get_summary_rules())
        assert "Watch" in rules_text


class TestFixedKeywordsRouteToComparison:
    """Questions using 'fixed / recovered / regressed' must map to COMPARISON_CHANGE."""

    @pytest.mark.parametrize("cue", [
        "how many tests got fixed in the latest run",
        "which tests were fixed since last time",
        "show me tests that regressed",
        "which tests recovered in the last run",
    ])
    def test_fixed_cue_routes_to_comparison(self, cue: str) -> None:
        intent = detect_answer_intent(cue)
        assert intent == AnswerIntent.COMPARISON_CHANGE, (
            f"Expected COMPARISON_CHANGE for '{cue}', got {intent}"
        )


class TestSingleTestFixQueryRoutesToDrilldown:
    """'Has X been fixed?' questions must route to DRILL_DOWN_DETAIL, not COMPARISON_CHANGE."""

    @pytest.mark.parametrize("question", [
        "Has testAddItemToCart() been fixed in any recent run?",
        "Has this issue been fixed?",
        "Has the login test been fixed yet?",
        "Has testCreateOrder been fixed in the latest run?",
    ])
    def test_has_been_fixed_routes_to_drilldown(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DRILL_DOWN_DETAIL, (
            f"Expected DRILL_DOWN_DETAIL for '{question}', got {intent}"
        )


class TestNewRegressionsCanonicalIntent:
    """All semantically equivalent new-regression questions map to NEW_REGRESSIONS."""

    @pytest.mark.parametrize("question", [
        # Exact cue matches
        "which tests are newly failing",
        "what new failures appeared in the latest run",
        "how many new failures got introduced in the latest run, also list me the test cases",
        # First-time failure phrasings
        "Identify all first-time failures in the most recent run and provide a list.",
        "which tests failed for the first time in this run",
        # Was-passing-before phrasings (caught by _is_new_regressions_query)
        "What tests failed in the latest run that were passing in the previous execution?",
        "what tests were passing before but are now failing",
        "tests that passed in the previous execution but failed now",
        # Multi-word cue phrases
        "List all new regressions introduced in the latest run",
        "Summarize the delta between the last two runs: specifically, which new test cases failed for the first time?",
        "Which tests are newly failing compared with the previous run?",
    ])
    def test_positive_routes_to_new_regressions(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.NEW_REGRESSIONS, (
            f"Expected NEW_REGRESSIONS for '{question}', got {intent}"
        )

    @pytest.mark.parametrize("question,expected", [
        ("What failed in the latest run?", AnswerIntent.SUMMARY_OVERVIEW),
        ("Compare the last two runs", AnswerIntent.COMPARISON_CHANGE),
        ("Why did these tests fail?", AnswerIntent.DIAGNOSTIC_ROOT_CAUSE),
        ("Is the pass rate declining over time?", AnswerIntent.COMPARISON_CHANGE),
        ("show me tests that regressed", AnswerIntent.COMPARISON_CHANGE),
    ])
    def test_negative_does_not_route_to_new_regressions(self, question: str, expected: AnswerIntent) -> None:
        intent = detect_answer_intent(question)
        assert intent != AnswerIntent.NEW_REGRESSIONS, (
            f"Expected {expected} (not NEW_REGRESSIONS) for '{question}', got {intent}"
        )

    def test_new_regressions_plan_is_canonical_and_self_consistent(self) -> None:
        """Same intent + non-trend flag regardless of phrasing variant."""
        questions = [
            "new failures",
            "List all first-time failures in the latest run",
            "which tests are newly failing",
        ]
        for q in questions:
            plan = build_answer_plan(AnswerIntent.NEW_REGRESSIONS, question=q)
            assert plan.intent == AnswerIntent.NEW_REGRESSIONS, q
            assert plan.is_trend_question is False, q
            assert plan.needs_exact_records is True, q

    def test_new_regressions_plan_has_expected_sections_in_rules(self) -> None:
        plan = build_answer_plan(AnswerIntent.NEW_REGRESSIONS)
        rules_text = " ".join(plan.answer_rules)
        assert "New Regressions" in rules_text
        assert "Recovered" in rules_text
        assert "Consistently Failing" not in rules_text.split("OMIT")[0]


class TestHistoricalRecurrenceRouting:
    """'Has this happened before?' questions must route to DRILL_DOWN_DETAIL, not COMPARISON_CHANGE."""

    @pytest.mark.parametrize("question", [
        "Has this failure happened in previous runs too?",
        "Is this a recurring issue?",
        "Have we seen this before?",
        "Did this occur in earlier runs?",
        "Was this failure seen in past runs?",
        "Has it failed before?",
        "Is this a recurring failure?",
        "Has this happened before as well?",
        "Have we seen this failure before too?",
    ])
    def test_historical_question_routes_to_drilldown(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DRILL_DOWN_DETAIL, (
            f"Expected DRILL_DOWN_DETAIL for '{question}', got {intent}"
        )

    @pytest.mark.parametrize("question", [
        "compare the previous run with this one",
        "what changed in the previous run",
        "show tests that regressed",
        "what new failures appeared",
        "which tests are newly failing",
    ])
    def test_historical_guard_does_not_override_comparison_or_regressions(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent != AnswerIntent.DRILL_DOWN_DETAIL, (
            f"Expected non-DRILLDOWN for '{question}', got {intent}"
        )


# ===========================================================================
# Recovery question routing — COMPARISON_CHANGE sub-case
# ===========================================================================


class TestRecoveryQuestionRouting:
    """Recovery questions should produce a plan whose Recovered section leads."""

    @pytest.mark.parametrize("question", [
        "Which tests recovered compared to the previous run?",
        "which tests recovered since the last run",
        "show me tests that recovered",
        "which tests are passing again after the latest run?",
        "what tests are no longer failing",
        "tests back to passing",
        "what was fixed since the previous run",
    ])
    def test_recovery_phrases_lead_with_recovered_section(self, question: str) -> None:
        plan = build_answer_plan(AnswerIntent.COMPARISON_CHANGE, question=question)
        rules_text = " ".join(plan.answer_rules)
        assert "RECOVERED SECTION (lead section" in rules_text, (
            f"Expected recovery-lead plan for '{question}', but rules were:\n{rules_text}"
        )

    def test_generic_comparison_does_not_lead_with_recovered(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="What changed between the last two runs?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "RECOVERED SECTION (lead section" not in rules_text

    def test_newly_failing_question_does_not_lead_with_recovered(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="Which tests are newly failing?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "RECOVERED SECTION (lead section" not in rules_text

    def test_recovery_plan_still_includes_newly_failing_guidance(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="Which tests recovered compared to the previous run?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "NEWLY FAILING" in rules_text

    def test_recovery_plan_intent_is_comparison_change(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.COMPARISON_CHANGE,
            question="which tests recovered since last run",
        )
        assert plan.intent == AnswerIntent.COMPARISON_CHANGE


# ===========================================================================
# Flakiness-history question routing — pre-regression flakiness
# ===========================================================================


class TestFlakinessHistoryRouting:
    """Questions about prior flakiness of regressing tests → DIAGNOSTIC_ROOT_CAUSE."""

    @pytest.mark.parametrize("question", [
        "Were any of these tests flaky before this regression?",
        "Were these tests flaky prior to this failure?",
        "Did any of the failing tests have a flaky history?",
        "Had these tests been flaky in previous runs?",
        "Were any failing tests already unstable before they regressed?",
        "are any of these tests historically flaky?",
        "which of these tests were intermittent before?",
    ])
    def test_flakiness_history_routes_to_diagnostic(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, (
            f"Expected DIAGNOSTIC_ROOT_CAUSE for '{question}', got {intent}"
        )

    def test_flakiness_history_not_routed_to_comparison_change(self) -> None:
        # "regression" in question must NOT pull it into COMPARISON_CHANGE
        intent = detect_answer_intent(
            "Were any of these tests flaky before this regression?"
        )
        assert intent != AnswerIntent.COMPARISON_CHANGE

    def test_plan_uses_prebuilt_answer_verbatim_rule(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "PRE-BUILT ANSWER" in rules_text
        assert "verbatim" in rules_text.lower()

    def test_plan_prohibits_tier_classifications(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "tier classifications" in rules_text.lower()

    def test_plan_prohibits_error_messages(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were these tests flaky prior to this failure?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "error messages" in rules_text.lower()

    def test_ranking_flakiness_question_not_captured(self) -> None:
        # "most flaky tests" is a ranking question — must NOT route to diagnostic
        intent = detect_answer_intent("what are the most flaky tests in this project?")
        assert intent == AnswerIntent.RANKING_LIST

    def test_generic_diagnostic_unaffected(self) -> None:
        # Standard diagnostic question must still get the standard diagnostic plan
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Why did testLogin fail?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "Pre-Regression Flakiness Check" not in rules_text
        assert "Probable Root Cause" in rules_text

    def test_plan_rules_prohibit_recalculation(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "recalculate" in rules_text.lower() or "authoritative" in rules_text.lower()

    def test_plan_rules_use_prebuilt_answer(self) -> None:
        # Rules must reference the pre-built answer block
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "PRE-BUILT ANSWER" in rules_text

    def test_plan_rules_prohibit_tables(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT use tables" in rules_text

    def test_plan_rules_prohibit_additions(self) -> None:
        # Rules must prohibit adding content beyond the pre-built answer
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT add" in rules_text

    def test_plan_rules_verbatim_copy(self) -> None:
        # Rules must say to copy the pre-built answer verbatim
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "verbatim" in rules_text.lower()
        assert "copy" in rules_text.lower() or "Copy" in rules_text

    def test_plan_rules_prebuilt_answer_is_self_contained(self) -> None:
        # Rules should tell LLM not to add anything — the pre-built answer is complete
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT add any text before or after" in rules_text

    def test_flakiness_history_skips_followup_inheritance(self) -> None:
        """Reproduces the exact UI bug: asking "Were any of these tests flaky before
        this regression?" as a follow-up to a NEW_REGRESSIONS answer must NOT inherit
        the prior intent and must return a flakiness-history plan, not the regression
        summary again.

        The question contains "these tests" which fires has_followup_reference(), but the
        flakiness-history override should prevent intent inheritance.
        """
        from qara.llm.context_history import ResolvedQueryContext

        prior_ctx = ResolvedQueryContext(prior_intent=AnswerIntent.NEW_REGRESSIONS)

        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
            prior_context=prior_ctx,
        )
        rules_text = " ".join(plan.answer_rules)
        # Must use the flakiness-history plan, not the new-regressions plan
        assert "PRE-BUILT ANSWER" in rules_text, (
            "Expected flakiness-history plan but got: " + rules_text[:200]
        )
        assert "NEW REGRESSIONS" not in rules_text

    # ── New tests for "worst pre-existing flakiness" phrasing ─────────────

    @pytest.mark.parametrize("question", [
        "Which of the newly failing tests have the worst pre-existing flakiness?",
        "Do any of the newly failing tests have pre-existing flakiness?",
        "Which tests have the worst pre existing flakiness?",
        "Show me the pre-existing flakiness of the new failures",
    ])
    def test_pre_existing_flakiness_routes_to_diagnostic(self, question: str) -> None:
        """'pre-existing flakiness' queries must route to DIAGNOSTIC_ROOT_CAUSE,
        not NEW_REGRESSIONS (which 'newly failing' would otherwise trigger).
        """
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, (
            f"Expected DIAGNOSTIC_ROOT_CAUSE for '{question}', got {intent}"
        )

    def test_pre_existing_flakiness_not_routed_to_new_regressions(self) -> None:
        # "newly failing" in the question must NOT trigger NEW_REGRESSIONS when
        # "pre-existing flakiness" is also present.
        intent = detect_answer_intent(
            "Which of the newly failing tests have the worst pre-existing flakiness?"
        )
        assert intent != AnswerIntent.NEW_REGRESSIONS

    def test_pre_existing_flakiness_uses_flakiness_history_plan(self) -> None:
        """The plan for a 'worst pre-existing flakiness' question must be the
        flakiness RANKING sub-plan (ranked list), not the binary tier-grid plan.
        """
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        rules_text = " ".join(plan.answer_rules)
        # Ranking plan uses a different heading, not the binary plan's heading
        assert "Worst Pre-Existing Flakiness Among Newly Failing Tests" in rules_text
        assert "Pre-Regression Flakiness Check" not in rules_text

    def test_pre_existing_flakiness_plan_prohibits_reproducing_context(self) -> None:
        """The flakiness-history plan must explicitly forbid reproducing the run
        comparison context to prevent the LLM from re-outputting the full
        regression breakdown before the flakiness analysis.
        """
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT reproduce" in rules_text
        assert "comparison context" in rules_text

    def test_pre_existing_flakiness_skips_followup_inheritance(self) -> None:
        """When asked as a follow-up to a NEW_REGRESSIONS answer, the ranking plan
        must still produce the flakiness-RANKING format, not inherit NEW_REGRESSIONS.
        """
        from qara.llm.context_history import ResolvedQueryContext

        prior_ctx = ResolvedQueryContext(prior_intent=AnswerIntent.NEW_REGRESSIONS)
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
            prior_context=prior_ctx,
        )
        rules_text = " ".join(plan.answer_rules)
        assert "Worst Pre-Existing Flakiness Among Newly Failing Tests" in rules_text, (
            "Expected flakiness-ranking plan but got: " + rules_text[:200]
        )
        assert "NEW REGRESSIONS" not in rules_text

    # ── Tests for the binary / ranking split ──────────────────────────────

    def test_is_flakiness_ranking_query_detects_worst(self) -> None:
        assert _is_flakiness_ranking_query(
            "Which of the newly failing tests have the worst pre-existing flakiness?"
        )

    def test_is_flakiness_ranking_query_detects_flakiest(self) -> None:
        assert _is_flakiness_ranking_query(
            "Which of these were already the flakiest?"
        )

    def test_is_flakiness_ranking_query_detects_rank(self) -> None:
        assert _is_flakiness_ranking_query(
            "Rank the newly failing tests by prior flakiness"
        )

    def test_is_flakiness_ranking_query_detects_highest(self) -> None:
        assert _is_flakiness_ranking_query(
            "Which had the highest pre-existing flakiness?"
        )

    def test_is_flakiness_ranking_query_false_for_binary(self) -> None:
        assert not _is_flakiness_ranking_query(
            "Were any of these tests flaky before this regression?"
        )
        assert not _is_flakiness_ranking_query(
            "Did any of these have prior instability?"
        )

    def test_is_flakiness_history_query_false_for_ranking(self) -> None:
        assert not _is_flakiness_history_query(
            "Which of the newly failing tests have the worst pre-existing flakiness?"
        )
        assert not _is_flakiness_history_query(
            "Which of these were already the flakiest?"
        )
        assert not _is_flakiness_history_query(
            "Rank the newly failing tests by prior flakiness"
        )

    def test_is_flakiness_history_query_false_for_negated_prior(self) -> None:
        """Questions about tests WITH NO prior flakiness must NOT match the binary detector.
        They are asking for root cause, not a flakiness categorisation.
        """
        assert not _is_flakiness_history_query(
            "Why are the newly failing tests with no prior flakiness failing now?"
        )
        assert not _is_flakiness_history_query(
            "What is causing the tests with no flakiness history to fail?"
        )
        assert not _is_flakiness_history_query(
            "Why are the tests without prior flakiness suddenly failing?"
        )
        assert not _is_flakiness_history_query(
            "Why are these tests not flaky before failing?"
        )

    @pytest.mark.parametrize("question", [
        "Why are the newly failing tests with no prior flakiness failing now?",
        "What is causing the tests with no flakiness history to fail?",
        "Why are the tests without prior flakiness suddenly failing?",
    ])
    def test_negated_prior_flakiness_routes_to_root_cause(self, question: str) -> None:
        """Negated prior-flakiness questions must route to general DIAGNOSTIC_ROOT_CAUSE,
        not get intercepted by the flakiness binary sub-plan.
        """
        plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, question=question)
        rules_text = " ".join(plan.answer_rules)
        # Must use the generic root-cause plan, not the Pre-Regression Flakiness Check
        assert "Pre-Regression Flakiness Check" not in rules_text
        assert "Worst Pre-Existing Flakiness" not in rules_text

    @pytest.mark.parametrize("question", [
        "Which of the newly failing tests have the worst pre-existing flakiness?",
        "Which of these were already the flakiest?",
        "Rank the newly failing tests by prior flakiness",
        "Which had the highest pre-existing flakiness?",
    ])
    def test_ranking_variant_routes_to_diagnostic(self, question: str) -> None:
        """All ranking variants must route to DIAGNOSTIC_ROOT_CAUSE (not NEW_REGRESSIONS)."""
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, (
            f"Expected DIAGNOSTIC_ROOT_CAUSE for '{question}', got {intent}"
        )

    @pytest.mark.parametrize("question", [
        "Which of the newly failing tests have the worst pre-existing flakiness?",
        "Which of these were already the flakiest?",
        "Rank the newly failing tests by prior flakiness",
    ])
    def test_ranking_variant_not_new_regressions(self, question: str) -> None:
        """Ranking variants must NOT route to NEW_REGRESSIONS even though 'newly failing' appears."""
        assert detect_answer_intent(question) != AnswerIntent.NEW_REGRESSIONS

    @pytest.mark.parametrize("question", [
        "Which of the newly failing tests have the worst pre-existing flakiness?",
        "Which of these were already the flakiest?",
        "Rank the newly failing tests by prior flakiness",
    ])
    def test_ranking_variant_uses_ranking_plan(self, question: str) -> None:
        """Ranking variants must produce the ranked-list plan, not the binary tier-grid."""
        plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, question=question)
        rules_text = " ".join(plan.answer_rules)
        assert "Worst Pre-Existing Flakiness Among Newly Failing Tests" in rules_text
        assert "Pre-Regression Flakiness Check" not in rules_text

    def test_ranking_plan_has_no_tier_grid_rules(self) -> None:
        """Ranking plan must NOT include the 🔴/🟡/🔵 tier-block instructions."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT use 🔴/🟡/🔵 tier blocks" in rules_text

    def test_ranking_plan_has_numbered_list_rule(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "numbered list" in rules_text

    def test_ranking_plan_shows_percentage_not_raw_score(self) -> None:
        """Rules must instruct the LLM to use the pre-converted flakiness_% column directly."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        rules_text = " ".join(plan.answer_rules)
        # Must reference the pre-converted column name
        assert "flakiness_%" in rules_text
        # Must say values are already percentages (no arithmetic needed)
        assert "already" in rules_text and "%" in rules_text
        # Must show a concrete example with % symbol
        assert "%" in rules_text
        # Must NOT tell LLM to suppress scores any more
        assert "Do NOT show flip_score values" not in rules_text

    def test_binary_plan_uses_prebuilt_answer(self) -> None:
        """Binary plan must instruct LLM to copy pre-built answer verbatim."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "PRE-BUILT ANSWER" in rules_text
        assert "verbatim" in rules_text.lower()

    def test_binary_plan_prohibits_recalculation(self) -> None:
        """Binary plan must prohibit recalculating flip counts."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "recalculate" in rules_text.lower()
        assert "authoritative" in rules_text

    @pytest.mark.parametrize("question", [
        "Did any of these have prior instability?",
        "Were these already unstable before this run?",
        "are any of these tests historically unstable?",
    ])
    def test_negative_phrasing_variants_route_to_binary(self, question: str) -> None:
        """Alternative phrasings without superlatives must use the binary sub-plan."""
        plan = build_answer_plan(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, question=question)
        rules_text = " ".join(plan.answer_rules)
        assert "PRE-BUILT ANSWER" in rules_text
        assert "Worst Pre-Existing Flakiness" not in rules_text

    def test_binary_plan_prohibits_additions(self) -> None:
        """Binary plan must prohibit adding text before/after the pre-built answer."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "DO NOT add any text before or after" in rules_text

    def test_binary_plan_prohibits_error_messages(self) -> None:
        """Binary plan must prohibit error messages, root-cause groups, tier classifications."""
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before this regression?",
        )
        rules_text = " ".join(plan.answer_rules)
        assert "error messages" in rules_text
        assert "tier classifications" in rules_text


# ── detect_answer_type tests ─────────────────────────────────────────────


class TestDetectAnswerType:
    """Verify deterministic mapping from (intent, question) → AnswerType."""

    from qara.llm.answer_plan import detect_answer_type as _detect

    def test_new_regressions_maps_to_regression_diff(self) -> None:
        at = detect_answer_type(AnswerIntent.NEW_REGRESSIONS, "What new failures appeared?")
        assert at == AnswerType.REGRESSION_DIFF

    def test_flakiness_binary_from_diagnostic(self) -> None:
        at = detect_answer_type(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            "Were any of these tests flaky before this regression?",
        )
        assert at == AnswerType.FLAKINESS_BINARY

    def test_flakiness_ranking_from_diagnostic(self) -> None:
        at = detect_answer_type(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            "Which of the newly failing tests had the worst pre-existing flakiness?",
        )
        assert at == AnswerType.FLAKINESS_RANKING

    def test_risk_ranking_from_ranking_list(self) -> None:
        at = detect_answer_type(
            AnswerIntent.RANKING_LIST,
            "Which tests have the highest risk?",
        )
        assert at == AnswerType.RISK_RANKING

    def test_trend_from_comparison(self) -> None:
        at = detect_answer_type(
            AnswerIntent.COMPARISON_CHANGE,
            "Is the pass rate improving over time?",
        )
        assert at == AnswerType.TREND

    def test_root_cause_from_diagnostic(self) -> None:
        at = detect_answer_type(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            "Why is testCheckout failing?",
        )
        assert at == AnswerType.ROOT_CAUSE

    def test_detail_from_drill_down(self) -> None:
        at = detect_answer_type(
            AnswerIntent.DRILL_DOWN_DETAIL,
            "Show me details for testLogin",
        )
        assert at == AnswerType.DETAIL

    def test_recommendation_from_recommendation_action(self) -> None:
        at = detect_answer_type(
            AnswerIntent.RECOMMENDATION_ACTION,
            "What should I fix first?",
        )
        assert at == AnswerType.RECOMMENDATION

    def test_summary_from_summary_overview(self) -> None:
        at = detect_answer_type(
            AnswerIntent.SUMMARY_OVERVIEW,
            "Give me a project summary",
        )
        assert at == AnswerType.SUMMARY

    def test_flakiness_ranking_from_ranking_list_defaults(self) -> None:
        """RANKING_LIST without risk keywords → FLAKINESS_RANKING."""
        at = detect_answer_type(
            AnswerIntent.RANKING_LIST,
            "Show me the top flaky tests",
        )
        assert at == AnswerType.FLAKINESS_RANKING

    def test_comparison_without_trend_maps_to_regression_diff(self) -> None:
        at = detect_answer_type(
            AnswerIntent.COMPARISON_CHANGE,
            "What changed between run 5 and run 10?",
        )
        assert at == AnswerType.REGRESSION_DIFF

    def test_build_answer_plan_sets_answer_type(self) -> None:
        """build_answer_plan must set answer_type on the resulting plan."""
        plan = build_answer_plan(AnswerIntent.NEW_REGRESSIONS, question="What new failures?")
        assert plan.answer_type == AnswerType.REGRESSION_DIFF

    def test_build_answer_plan_binary_sets_answer_type(self) -> None:
        plan = build_answer_plan(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            question="Were any of these tests flaky before?",
        )
        assert plan.answer_type == AnswerType.FLAKINESS_BINARY


# ===========================================================================
# Concern B — Time-window phrases must NOT trigger RANKING_LIST alone
# ===========================================================================


class TestTimeWindowCueOverlaps:
    """Verify time-window phrases ('last 5 runs', etc.) do not trigger RANKING.

    After removing them from _RANKING_CUES, these questions should route
    to COMPARISON_CHANGE or SUMMARY_OVERVIEW — not RANKING_LIST — unless
    accompanied by genuine ranking language (most, top, worst, etc.).
    """

    @pytest.mark.parametrize("question", [
        "How has pass rate changed in the last 5 runs?",
        "What happened in the last 10 runs?",
        "Compare the last 3 runs",
        "Show me pass rate over the last 7 runs",
    ])
    def test_time_window_without_ranking_language_not_ranking(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent != AnswerIntent.RANKING_LIST, (
            f"'{question}' should NOT route to RANKING_LIST"
        )

    @pytest.mark.parametrize("question", [
        "Which tests are the most flaky in the last 5 runs?",
        "Show the top failing tests in the last 10 runs",
        "What are the worst tests in the last 3 runs?",
        "Which tests fail the most in the last 7 runs?",
    ])
    def test_time_window_with_ranking_language_is_ranking(self, question: str) -> None:
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.RANKING_LIST, (
            f"'{question}' should route to RANKING_LIST"
        )

    @pytest.mark.parametrize("question,expected_intent", [
        ("How has pass rate changed in the last 5 runs?", AnswerIntent.COMPARISON_CHANGE),
        ("What is the trend over the last 10 runs?", AnswerIntent.COMPARISON_CHANGE),
        ("Is the test suite improving over the last 5 runs?", AnswerIntent.COMPARISON_CHANGE),
    ])
    def test_time_window_trend_routes_to_comparison(
        self, question: str, expected_intent: AnswerIntent,
    ) -> None:
        intent = detect_answer_intent(question)
        assert intent == expected_intent
