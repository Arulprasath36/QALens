"""Tests for the broad/underspecified-question default-scope feature.

Covers:
- has_explicit_scope: questions with / without explicit scope
- _is_threshold_filter_query: threshold routing detection
- detect_answer_intent routing for threshold queries (→ RANKING_LIST)
- AnswerPlan.default_scope annotation via build_answer_plan
- Scope disclosure rules injected into build_prompt output
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qara.llm.answer_types import AnswerIntent, DefaultScopeInfo
from qara.llm.answer_plan import build_answer_plan
from qara.llm.intent_detection import (
    has_explicit_scope,
    _is_threshold_filter_query,
    detect_answer_intent,
)
from qara.llm.prompts import build_prompt
from qara.server.routes_llm import (
    _build_stability_trend_result,
    _risk_ranking_result_from_fact_bundle,
    _trend_query_kind,
    _trend_threshold,
)


# ---------------------------------------------------------------------------
# has_explicit_scope
# ---------------------------------------------------------------------------

class TestHasExplicitScope:
    # --- Questions WITH explicit scope ---
    def test_specific_run_number_is_explicit(self):
        assert has_explicit_scope("Show failed tests in Run 18") is True

    def test_run_hash_is_explicit(self):
        assert has_explicit_scope("What happened in run #52?") is True

    def test_run_no_is_explicit(self):
        assert has_explicit_scope("List failures in run no. 7") is True

    def test_last_n_runs_is_explicit(self):
        assert has_explicit_scope("Show flaky tests in the last 5 runs") is True

    def test_last_week_is_explicit(self):
        assert has_explicit_scope("How has pass rate changed last week?") is True

    def test_this_sprint_is_explicit(self):
        assert has_explicit_scope("Which tests broke this sprint?") is True

    def test_since_is_explicit(self):
        assert has_explicit_scope("Find failures since Monday") is True

    # --- Questions WITHOUT explicit scope → defaults apply ---
    def test_broad_exception_query_is_unscoped(self):
        assert has_explicit_scope("Find tests failing with StaleElementReferenceException") is False

    def test_highest_failure_frequency_is_unscoped(self):
        assert has_explicit_scope("Which test has the highest failure frequency?") is False

    def test_pass_rate_threshold_is_unscoped(self):
        assert has_explicit_scope("Show tests with pass rate below 60%") is False

    def test_flakiest_tests_is_unscoped(self):
        assert has_explicit_scope("Which are the most flaky tests?") is False

    def test_broad_summary_is_unscoped(self):
        assert has_explicit_scope("Give me an overview of test health") is False

    def test_recommend_is_unscoped(self):
        assert has_explicit_scope("What should I fix first?") is False


# ---------------------------------------------------------------------------
# _is_threshold_filter_query
# ---------------------------------------------------------------------------

class TestIsThresholdFilterQuery:
    def test_pass_rate_below(self):
        assert _is_threshold_filter_query("Show tests with pass rate below 60%") is True

    def test_pass_rate_above(self):
        assert _is_threshold_filter_query("Find tests with pass rate above 80%") is True

    def test_pass_rate_less_than(self):
        assert _is_threshold_filter_query("Which tests have pass rate less than 50%?") is True

    def test_pass_rate_at_most(self):
        assert _is_threshold_filter_query("List tests with pass rate at most 30%") is True

    def test_failure_rate_above(self):
        assert _is_threshold_filter_query("Tests with failure rate above 40%") is True

    def test_failure_rate_greater_than(self):
        assert _is_threshold_filter_query("Failure rate greater than 50%") is True

    # --- Should NOT fire ---
    def test_pass_rate_trend_not_threshold(self):
        """'pass rate' without a comparison operator is not a threshold query."""
        assert _is_threshold_filter_query("How has pass rate changed over time?") is False

    def test_no_metric_not_threshold(self):
        assert _is_threshold_filter_query("Show tests that fail") is False

    def test_no_operator_not_threshold(self):
        assert _is_threshold_filter_query("Show pass rate for all tests") is False


# ---------------------------------------------------------------------------
# Routing: threshold queries → RANKING_LIST
# ---------------------------------------------------------------------------

class TestThresholdRoutingToRankingList:
    def test_pass_rate_below_routes_to_ranking(self):
        intent = detect_answer_intent("Show tests with pass rate below 60%")
        assert intent == AnswerIntent.RANKING_LIST

    def test_failure_rate_above_routes_to_ranking(self):
        intent = detect_answer_intent("Find tests with failure rate above 40%")
        assert intent == AnswerIntent.RANKING_LIST

    def test_pass_rate_trend_still_routes_to_comparison(self):
        """Trend questions with 'pass rate' must NOT be misrouted."""
        intent = detect_answer_intent("How has pass rate changed over time?")
        assert intent == AnswerIntent.COMPARISON_CHANGE

    def test_compare_two_runs_not_affected(self):
        intent = detect_answer_intent("Compare Run 52 with Run 53")
        assert intent == AnswerIntent.COMPARISON_CHANGE

    def test_highest_failure_frequency_routes_to_ranking(self):
        intent = detect_answer_intent("Which test has the highest failure frequency?")
        assert intent == AnswerIntent.RANKING_LIST


# ---------------------------------------------------------------------------
# Result-workspace stability query routing
# ---------------------------------------------------------------------------

class TestStabilityWorkspaceQueries:
    def _result(self, name: str, *, passed: int, failed: int, history: list[str]):
        run_count = passed + failed
        return SimpleNamespace(
            canonical_name=name.lower(),
            display_name=name,
            owner=None,
            suite=None,
            classification="stable" if failed == 0 else "consistently_broken",
            pass_rate=passed / run_count,
            flip_score=0.0,
            fail_count=failed,
            pass_count=passed,
            run_count=run_count,
            current_streak=passed if failed == 0 else -failed,
            last_passed_seq=run_count if passed else None,
            last_failed_seq=run_count if failed else None,
            history=history,
        )

    @pytest.mark.parametrize(
        ("question", "kind"),
        [
            ("Which tests failed in every run?", "failed_every_run"),
            ("Which tests never failed?", "never_failed"),
            ("What is the most reliable test?", "high_pass_rate"),
            ("Which tests are problematic?", "unstable_tests"),
            ("Show tests that need attention", "unstable_tests"),
        ],
    )
    def test_query_kind_for_result_workspace_questions(self, question: str, kind: str):
        assert _trend_query_kind(question) == kind

    def test_most_reliable_default_threshold_is_ninety_percent(self):
        assert _trend_threshold("What is the most reliable test?", default_threshold=0.90) == 0.90

    def test_failed_every_run_result_filters_to_consistently_failed_tests(self):
        result = _build_stability_trend_result(
            kind="failed_every_run",
            scope_label="Last 3 runs",
            run_count=3,
            query_threshold=None,
            fail_count_threshold=None,
            results=[
                self._result("testAlwaysFails", passed=0, failed=3, history=["failed", "failed", "failed"]),
                self._result("testSometimesFails", passed=1, failed=2, history=["passed", "failed", "failed"]),
                self._result("testNeverFails", passed=3, failed=0, history=["passed", "passed", "passed"]),
            ],
            total_evaluated=3,
            latest_run_label="Run #3",
        )

        assert result["type"] == "stability_trend"
        assert result["query"]["kind"] == "failed_every_run"
        assert [item["testName"] for item in result["tests"]] == ["testAlwaysFails"]

    def test_never_failed_result_filters_to_zero_failure_tests(self):
        result = _build_stability_trend_result(
            kind="never_failed",
            scope_label="Last 3 runs",
            run_count=3,
            query_threshold=None,
            fail_count_threshold=None,
            results=[
                self._result("testAlwaysFails", passed=0, failed=3, history=["failed", "failed", "failed"]),
                self._result("testNeverFails", passed=3, failed=0, history=["passed", "passed", "passed"]),
            ],
            total_evaluated=2,
            latest_run_label="Run #3",
        )

        assert result["type"] == "stability_trend"
        assert result["query"]["kind"] == "never_failed"
        assert [item["testName"] for item in result["tests"]] == ["testNeverFails"]


# ---------------------------------------------------------------------------
# Result-workspace recommendation routing
# ---------------------------------------------------------------------------

class TestRecommendationWorkspaceResult:
    def test_fix_first_intent_is_recommendation(self):
        assert detect_answer_intent("What should I fix first?") == AnswerIntent.RECOMMENDATION_ACTION

    def test_fix_first_can_render_as_risk_ranking_workspace(self):
        result = _risk_ranking_result_from_fact_bundle(
            {
                "scope_label": "Last 10 runs",
                "eligible_tests": 12,
                "high_risk": 1,
                "medium_risk": 1,
                "low_risk": 0,
                "top_tests": [
                    {
                        "rank": 1,
                        "name": "testCheckout",
                        "tier": "HIGH",
                        "risk_pct": 87,
                        "pass_rate": 0.42,
                        "driver": "fail streak + low pass rate",
                    },
                    {
                        "rank": 2,
                        "name": "testProfile",
                        "tier": "MEDIUM",
                        "risk_pct": 54,
                        "pass_rate": 0.67,
                        "driver": "recent decline",
                    },
                ],
            },
            title="What to fix first",
            subtitle="Prioritized by predicted failure risk and historical stability signals",
        )

        assert result["type"] == "risk_ranking"
        assert result["title"] == "What to fix first"
        assert result["scope"]["label"] == "Last 10 runs"
        assert result["summary"]["highRisk"] == 1
        assert result["ranking"][0]["testName"] == "testCheckout"
        assert "Prioritize this test first" in result["ranking"][0]["primaryReason"]


# ---------------------------------------------------------------------------
# AnswerPlan.default_scope annotation
# ---------------------------------------------------------------------------

class TestDefaultScopeAnnotation:
    def test_unscoped_ranking_question_gets_default_scope(self):
        intent = detect_answer_intent("Which test has the highest failure frequency?")
        plan = build_answer_plan(intent, question="Which test has the highest failure frequency?")
        assert plan.default_scope is not None
        assert isinstance(plan.default_scope, DefaultScopeInfo)
        assert plan.default_scope.window_runs == 10

    def test_unscoped_summary_question_gets_default_scope(self):
        intent = detect_answer_intent("Find tests failing with StaleElementReferenceException")
        plan = build_answer_plan(intent, question="Find tests failing with StaleElementReferenceException")
        assert plan.default_scope is not None

    def test_unscoped_diagnostic_question_gets_default_scope(self):
        intent = detect_answer_intent("Why is testCheckout failing?")
        plan = build_answer_plan(intent, question="Why is testCheckout failing?")
        assert plan.default_scope is not None

    def test_unscoped_recommendation_gets_default_scope(self):
        intent = detect_answer_intent("What should I fix first?")
        plan = build_answer_plan(intent, question="What should I fix first?")
        assert plan.default_scope is not None

    def test_explicit_run_number_has_no_default_scope(self):
        q = "Show failed tests in Run 18"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is None

    def test_explicit_last_n_runs_has_no_default_scope(self):
        q = "Show flaky tests in the last 5 runs"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is None

    def test_comparison_intent_has_no_default_scope(self):
        """COMPARISON_CHANGE has implicit last-2-runs scope — must not get default_scope."""
        q = "What changed between run 10 and run 11?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is None

    def test_new_regressions_has_no_default_scope(self):
        """NEW_REGRESSIONS has implicit last-run scope — must not get default_scope."""
        q = "What tests failed now but were passing before?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is None

    def test_default_scope_description(self):
        q = "Which are the most flaky tests?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is not None
        assert "10" in plan.default_scope.description


# ---------------------------------------------------------------------------
# Prompt injection: scope disclosure rules appear in [ANSWER RULES]
# ---------------------------------------------------------------------------

class TestScopeDisclosureInPrompt:
    def _make_plan_with_scope(self):
        q = "Which test has the highest failure frequency?"
        intent = detect_answer_intent(q)
        return build_answer_plan(intent, question=q)

    def _make_plan_without_scope(self):
        q = "Show failed tests in Run 18"
        intent = detect_answer_intent(q)
        return build_answer_plan(intent, question=q)

    def test_scope_disclosure_block_present_when_default_scope_set(self):
        plan = self._make_plan_with_scope()
        prompt = build_prompt(
            "Which test has the highest failure frequency?",
            "some context",
            answer_plan=plan,
        )
        assert "[DEFAULT SCOPE RULES]" in prompt

    def test_scope_disclosure_mentions_last_10_runs(self):
        plan = self._make_plan_with_scope()
        prompt = build_prompt(
            "Which test has the highest failure frequency?",
            "some context",
            answer_plan=plan,
        )
        assert "Last 10 runs" in prompt

    def test_scope_disclosure_includes_scope_used_instruction(self):
        plan = self._make_plan_with_scope()
        prompt = build_prompt(
            "Which test has the highest failure frequency?",
            "some context",
            answer_plan=plan,
        )
        assert "## Scope used" in prompt

    def test_scope_disclosure_includes_want_more_specific(self):
        plan = self._make_plan_with_scope()
        prompt = build_prompt(
            "Which test has the highest failure frequency?",
            "some context",
            answer_plan=plan,
        )
        assert "## Want something more specific?" in prompt

    def test_scope_disclosure_includes_refinement_options(self):
        plan = self._make_plan_with_scope()
        prompt = build_prompt(
            "Which test has the highest failure frequency?",
            "some context",
            answer_plan=plan,
        )
        assert "Run number" in prompt
        assert "Module or owner" in prompt
        assert "Environment" in prompt

    def test_no_scope_disclosure_when_explicit_run_specified(self):
        plan = self._make_plan_without_scope()
        prompt = build_prompt(
            "Show failed tests in Run 18",
            "some context",
            answer_plan=plan,
        )
        assert "[DEFAULT SCOPE RULES]" not in prompt
        assert "## Want something more specific?" not in prompt

    def test_no_scope_disclosure_when_plan_has_no_default_scope(self):
        """When answer_plan.default_scope is None the rules block is untouched."""
        q = "What tests failed now but were passing before?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.default_scope is None
        prompt = build_prompt(q, "some context", answer_plan=plan)
        assert "[DEFAULT SCOPE RULES]" not in prompt
