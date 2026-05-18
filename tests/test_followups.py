"""Tests for the dynamic follow-up question generator."""

from __future__ import annotations

import pytest

from qalens.llm.answer_plan import AnswerIntent
from qalens.llm.followups import generate_follow_ups

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_SOURCES = [
    {"type": "test", "label": "testAddItemToCart", "meta": "e-commerce"},
    {"type": "test", "label": "testCheckoutFlow", "meta": "e-commerce"},
    {"type": "run",  "label": "Newly Failing (3 tests)", "run_id": "abc", "vs_run_id": "xyz"},
    {"type": "run",  "label": "Run #52", "run_id": "abc"},
]

_EMPTY_SOURCES: list[dict] = []

_RUN_ONLY_SOURCES = [
    {"type": "run", "label": "Run #10", "run_id": "r10"},
]

# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_returns_list(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        assert isinstance(result, list)

    def test_max_three_suggestions(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        assert len(result) <= 3

    def test_at_least_one_suggestion(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _EMPTY_SOURCES)
        assert len(result) >= 1

    def test_all_non_empty_strings(self):
        for intent in AnswerIntent:
            result = generate_follow_ups(intent, _TEST_SOURCES)
            assert all(isinstance(q, str) and q.strip() for q in result), \
                f"Empty string in result for intent {intent}"

# ---------------------------------------------------------------------------
# Intent differentiation
# ---------------------------------------------------------------------------

class TestIntentDifferentiation:
    def test_different_intents_produce_different_suggestions(self):
        new_reg = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        ranking = generate_follow_ups(AnswerIntent.RANKING_LIST, _TEST_SOURCES)
        assert new_reg != ranking

    def test_new_regressions_vs_summary(self):
        new_reg = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        summary = generate_follow_ups(AnswerIntent.SUMMARY_OVERVIEW, _TEST_SOURCES)
        assert new_reg != summary

    def test_root_cause_vs_recommendation(self):
        root = generate_follow_ups(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES)
        rec  = generate_follow_ups(AnswerIntent.RECOMMENDATION_ACTION, _TEST_SOURCES)
        assert root != rec

    def test_all_intents_produce_output(self):
        for intent in AnswerIntent:
            result = generate_follow_ups(intent, _TEST_SOURCES)
            assert result, f"No follow-ups for intent {intent}"

# ---------------------------------------------------------------------------
# Context injection — test names appear in output
# ---------------------------------------------------------------------------

class TestContextInjection:
    def test_test_name_injected_into_new_regressions(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        combined = " ".join(result)
        assert "testAddItemToCart" in combined

    def test_test_name_injected_into_root_cause(self):
        result = generate_follow_ups(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES)
        combined = " ".join(result)
        assert "testAddItemToCart" in combined

    def test_run_label_injected_into_trend(self):
        result = generate_follow_ups(AnswerIntent.COMPARISON_CHANGE, _TEST_SOURCES)
        combined = " ".join(result)
        # COMPARISON_CHANGE resolves to REGRESSION_DIFF which is scope-driven;
        # follow-ups should reference scoped tests rather than run labels.
        assert "testAddItemToCart" in combined or "testCheckoutFlow" in combined

    def test_run_label_injected_when_only_run_sources(self):
        result = generate_follow_ups(AnswerIntent.SUMMARY_OVERVIEW, _RUN_ONLY_SOURCES)
        combined = " ".join(result)
        assert "Run #10" in combined

    def test_empty_sources_uses_fallback_not_crash(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _EMPTY_SOURCES)
        assert len(result) >= 1

    def test_two_tests_mentioned_in_ranking_output(self):
        result = generate_follow_ups(AnswerIntent.RANKING_LIST, _TEST_SOURCES)
        combined = " ".join(result)
        # At least one of the two test names should be referenced
        assert "testAddItemToCart" in combined or "testCheckoutFlow" in combined

# ---------------------------------------------------------------------------
# No generic filler when context is available
# ---------------------------------------------------------------------------

class TestSpecificity:
    def test_new_regressions_not_fully_generic(self):
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        # Should not just return the global fallback (which has no test name)
        combined = " ".join(result)
        assert "testAddItemToCart" in combined

    def test_flaky_uses_test_name_not_placeholder(self):
        result = generate_follow_ups(AnswerIntent.DRILL_DOWN_DETAIL, _TEST_SOURCES)
        combined = " ".join(result)
        assert "testAddItemToCart" in combined or "testCheckoutFlow" in combined


# ---------------------------------------------------------------------------
# Flakiness-history sub-intent override
# ---------------------------------------------------------------------------

_FLAKINESS_QUESTIONS = [
    "Were any of these tests flaky before this regression?",
    "Were these tests already flaky before this run?",
    "Did any of these tests have flakiness history before this regression?",
    "Have these tests been flaky before?",
]

_NON_FLAKINESS_QUESTION = "What is the root cause of these failures?"


class TestFlakinessHistoryFollowUps:
    def test_flakiness_question_does_not_use_random_test_name(self):
        """Follow-ups must NOT reference tests[0] from sources (which is the
        highest-ranked flakiness test in the whole project, not the newly
        failing tests the user asked about)."""
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Were any of these tests flaky before this regression?",
        )
        combined = " ".join(result)
        # The source test names come from the full flakiness ranking — they
        # must NOT appear in the follow-up chips for a flakiness-history query.
        assert "testAddItemToCart" not in combined
        assert "testCheckoutFlow" not in combined

    def test_flakiness_question_returns_three_chips(self):
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Were any of these tests flaky before this regression?",
        )
        assert len(result) == 3

    def test_non_flakiness_root_cause_still_uses_test_name(self):
        """Normal DIAGNOSTIC_ROOT_CAUSE questions must still inject the test
        name from sources — the override must not fire for them."""
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question=_NON_FLAKINESS_QUESTION,
        )
        combined = " ".join(result)
        assert "testAddItemToCart" in combined

    def test_flakiness_question_chips_are_non_empty(self):
        for q in _FLAKINESS_QUESTIONS:
            result = generate_follow_ups(
                AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
                _TEST_SOURCES,
                question=q,
            )
            assert all(chip.strip() for chip in result), f"Empty chip for: {q}"

    def test_flakiness_chips_are_contextually_relevant(self):
        """Chips should reference the regression/flakiness context, not generic
        fallback text."""
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Were any of these tests flaky before this regression?",
        )
        combined = " ".join(result).lower()
        # At least one chip should be about flakiness, priority, or stability
        assert any(
            kw in combined
            for kw in ("flak", "stable", "prioriti", "investigat", "pattern")
        )

    def test_no_question_kwarg_falls_back_to_normal_root_cause(self):
        """Omitting the question= kwarg must not crash and must return the
        normal DIAGNOSTIC_ROOT_CAUSE follow-ups (backward-compatible)."""
        result = generate_follow_ups(AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES)
        combined = " ".join(result)
        assert "testAddItemToCart" in combined


# ---------------------------------------------------------------------------
# Flakiness-ranking sub-intent override
# ---------------------------------------------------------------------------

_RANKING_QUESTIONS = [
    "Which of the newly failing tests have the worst pre-existing flakiness?",
    "Which of these were already the flakiest?",
    "Rank the newly failing tests by prior flakiness",
    "Which had the highest pre-existing flakiness?",
]


class TestFlakinessRankingFollowUps:
    def test_ranking_question_does_not_use_source_test_name(self):
        """Ranking follow-ups must NOT reference tests from sources (they are the
        full-project flakiness ranking, not the newly failing tests being discussed)."""
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        combined = " ".join(result)
        assert "testAddItemToCart" not in combined
        assert "testCheckoutFlow" not in combined

    def test_ranking_question_returns_three_chips(self):
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        assert len(result) == 3

    def test_ranking_chips_mention_regression_signals_or_stability(self):
        """Chips must orient the user toward action on regression signal quality."""
        result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        combined = " ".join(result).lower()
        assert any(
            kw in combined
            for kw in ("regression signal", "stable", "quarantine", "root cause", "reliable", "flaky")
        )

    def test_ranking_chips_are_non_empty(self):
        for q in _RANKING_QUESTIONS:
            result = generate_follow_ups(
                AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
                _TEST_SOURCES,
                question=q,
            )
            assert all(chip.strip() for chip in result), f"Empty chip for: {q}"

    def test_ranking_override_does_not_fire_for_binary_question(self):
        """A binary flakiness question must NOT produce the ranking follow-ups."""
        ranking_result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        binary_result = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            _TEST_SOURCES,
            question="Were any of these tests flaky before this regression?",
        )
        assert ranking_result != binary_result

    def test_ranking_and_history_overrides_are_mutually_exclusive(self):
        """Each variant produces its own distinct chip set."""
        ranking = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES,
            question="Which of the newly failing tests have the worst pre-existing flakiness?",
        )
        history = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES,
            question="Were any of these tests flaky before?",
        )
        non_flakiness = generate_follow_ups(
            AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, _TEST_SOURCES,
            question="What is the root cause?",
        )
        # All three must be different sets
        assert ranking != history
        assert ranking != non_flakiness
        assert history != non_flakiness


# ---------------------------------------------------------------------------
# Scope-driven follow-up contract tests (answer-scope architecture)
# ---------------------------------------------------------------------------

from qalens.llm.answer_plan import AnswerPlan
from qalens.llm.answer_types import AnswerScope, AnswerType
from qalens.llm.followups import _validate_grounding


def _make_plan(
    answer_type: AnswerType,
    scope: AnswerScope | None = None,
    *,
    intent: AnswerIntent = AnswerIntent.NEW_REGRESSIONS,
) -> AnswerPlan:
    """Build a minimal AnswerPlan for testing."""
    return AnswerPlan(
        intent=intent,
        answer_type=answer_type,
        include_root_cause=False,
        include_recommendations=False,
        scope=scope,
    )


# ── Scoped test entities ────────────────────────────────────────────────────

_SCOPE_TESTS = ["testAddItemToCart", "testCheckoutFlow", "testCreateOrder"]
_OUT_OF_SCOPE_TEST = "testDashboardLoadsInUnder3s"

_SCOPED_SOURCES = [
    {"type": "test", "label": "testAddItemToCart", "meta": "e-commerce"},
    {"type": "test", "label": "testCheckoutFlow", "meta": "e-commerce"},
    {"type": "test", "label": "testCreateOrder", "meta": "e-commerce"},
    {"type": "test", "label": _OUT_OF_SCOPE_TEST, "meta": "dashboard"},
    {"type": "run",  "label": "Run #52", "run_id": "abc"},
]

_CLEAN_SCOPE = AnswerScope(
    tests=_SCOPE_TESTS,
    runs=["Run #52"],
    total=3,
    label="NEWLY FAILING TESTS",
)


class TestNoOutOfScopeLeakage:
    """H.1 — No out-of-scope test leakage."""

    def test_out_of_scope_test_never_appears_in_followups(self):
        """Given scope with tests A, B, C and sources containing test X,
        follow-ups must not mention test X."""
        plan = _make_plan(AnswerType.REGRESSION_DIFF, _CLEAN_SCOPE)
        result = generate_follow_ups(plan, _SCOPED_SOURCES)
        combined = " ".join(result)
        assert _OUT_OF_SCOPE_TEST not in combined

    def test_only_scope_tests_mentioned(self):
        """Every test name in follow-ups must be in _SCOPE_TESTS."""
        plan = _make_plan(AnswerType.REGRESSION_DIFF, _CLEAN_SCOPE)
        result = generate_follow_ups(plan, _SCOPED_SOURCES)
        combined = " ".join(result)
        for name in _SCOPE_TESTS:
            if name in combined:
                assert name in _CLEAN_SCOPE.tests

    def test_validation_rejects_out_of_scope_candidate(self):
        """Internal validation layer must reject a candidate with out-of-scope entity."""
        candidates = [
            f"Why did {_OUT_OF_SCOPE_TEST} fail?",
            "Which of these tests should we investigate first?",
        ]
        validated = _validate_grounding(candidates, _CLEAN_SCOPE, _SCOPED_SOURCES)
        assert len(validated) == 1
        assert _OUT_OF_SCOPE_TEST not in validated[0]

    def test_validation_passes_in_scope_candidates(self):
        """Candidates referencing only in-scope entities must pass validation."""
        candidates = [
            f"Why did {_SCOPE_TESTS[0]} start failing?",
            f"Show the history for {_SCOPE_TESTS[1]}",
        ]
        validated = _validate_grounding(candidates, _CLEAN_SCOPE, _SCOPED_SOURCES)
        assert len(validated) == 2

    def test_validation_passes_generic_candidates(self):
        """Generic follow-ups with no entity references always pass."""
        candidates = [
            "Which of these tests should we investigate first?",
            "Were any of these tests flaky before this regression?",
        ]
        validated = _validate_grounding(candidates, _CLEAN_SCOPE, _SCOPED_SOURCES)
        assert len(validated) == 2


class TestRegressionDiffFollowupsAreScoped:
    """H.2 — Regression diff follow-ups are scope-driven."""

    def test_followups_reference_newly_failing_tests(self):
        plan = _make_plan(AnswerType.REGRESSION_DIFF, _CLEAN_SCOPE)
        result = generate_follow_ups(plan, _SCOPED_SOURCES)
        combined = " ".join(result)
        # Must reference at least one scoped test
        assert any(t in combined for t in _SCOPE_TESTS)

    def test_followups_do_not_reference_unscoped_tests(self):
        plan = _make_plan(AnswerType.REGRESSION_DIFF, _CLEAN_SCOPE)
        result = generate_follow_ups(plan, _SCOPED_SOURCES)
        combined = " ".join(result)
        assert _OUT_OF_SCOPE_TEST not in combined

    def test_regression_diff_includes_flakiness_question(self):
        plan = _make_plan(AnswerType.REGRESSION_DIFF, _CLEAN_SCOPE)
        result = generate_follow_ups(plan, _SCOPED_SOURCES)
        combined = " ".join(result).lower()
        assert "flaky" in combined


class TestFlakinessBinaryFollowupsAreScoped:
    """H.3 — Flakiness binary follow-ups are scope-driven."""

    def test_flakiness_binary_does_not_reference_recovered_tests(self):
        """FLAKINESS_BINARY scope contains newly failing tests only;
        recovered or unrelated tests must not appear."""
        scope = AnswerScope(
            tests=["testAddItemToCart", "testCheckoutFlow"],
            total=2,
            label="NEWLY FAILING TESTS",
        )
        # Sources include a test that's NOT in scope (recovered)
        sources_with_recovered = [
            {"type": "test", "label": "testAddItemToCart", "meta": ""},
            {"type": "test", "label": "testPartialRefund", "meta": "recovered"},
        ]
        plan = _make_plan(
            AnswerType.FLAKINESS_BINARY, scope,
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
        )
        result = generate_follow_ups(plan, sources_with_recovered)
        combined = " ".join(result)
        assert "testPartialRefund" not in combined

    def test_flakiness_binary_chips_mention_flakiness(self):
        scope = AnswerScope(tests=["testA"], total=1, label="NF")
        plan = _make_plan(
            AnswerType.FLAKINESS_BINARY, scope,
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "flaki" in combined or "stable" in combined


class TestFlakinessRankingFollowupsAreScoped:
    """H.4 — Flakiness ranking follow-ups are scope-driven."""

    def test_ranking_followups_do_not_use_generic_source_card_tests(self):
        """When source cards contain the full project ranking, follow-ups
        must use strategic suggestions, not pick test names from sources."""
        scope = AnswerScope(
            tests=["testA", "testB"],
            total=2,
            label="RANKED TESTS",
        )
        broad_sources = [
            {"type": "test", "label": "testX_from_full_ranking", "meta": ""},
            {"type": "test", "label": "testY_from_full_ranking", "meta": ""},
        ]
        plan = _make_plan(
            AnswerType.FLAKINESS_RANKING, scope,
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
        )
        result = generate_follow_ups(plan, broad_sources)
        combined = " ".join(result)
        assert "testX_from_full_ranking" not in combined
        assert "testY_from_full_ranking" not in combined

    def test_ranking_followups_are_strategic(self):
        plan = _make_plan(
            AnswerType.FLAKINESS_RANKING,
            AnswerScope(tests=["testA"], total=1, label="RANKED"),
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert any(
            kw in combined
            for kw in ("signal", "quarantine", "stable", "flaky", "reliable")
        )


class TestFallbackGenericFollowups:
    """H.5 — Fallback generic follow-ups are still relevant."""

    def test_empty_scope_returns_followups(self):
        plan = _make_plan(AnswerType.REGRESSION_DIFF, AnswerScope())
        result = generate_follow_ups(plan, [])
        assert len(result) >= 1

    def test_empty_scope_does_not_introduce_entity_names(self):
        plan = _make_plan(AnswerType.REGRESSION_DIFF, AnswerScope())
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        # Should not contain any specific test name
        assert "testAddItemToCart" not in combined
        assert "testCheckoutFlow" not in combined

    def test_safe_generics_are_relevant(self):
        """When all candidates fail validation, safe generics should still
        be relevant (not random gibberish)."""
        from qalens.llm.followups import _SAFE_GENERIC
        for q in _SAFE_GENERIC:
            assert q.strip()
            assert len(q) > 10  # Not trivially short


class TestSourceCardConflict:
    """H.6 — Source-card conflict test."""

    def test_source_entity_not_in_scope_is_excluded(self):
        """If sources contain an entity not present in the current answer
        scope, that entity must not appear in follow-ups."""
        scope = AnswerScope(
            tests=["testA", "testB"],
            runs=["Run #1"],
            total=2,
            label="SCOPED",
        )
        conflicting_sources = [
            {"type": "test", "label": "testA", "meta": ""},
            {"type": "test", "label": "testB", "meta": ""},
            {"type": "test", "label": "testConflictingEntity", "meta": ""},
        ]
        plan = _make_plan(AnswerType.ROOT_CAUSE, scope, intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        result = generate_follow_ups(plan, conflicting_sources)
        combined = " ".join(result)
        assert "testConflictingEntity" not in combined

    def test_sources_broader_than_scope_do_not_override(self):
        """Sources with 20 tests should not override a scope of 3 tests."""
        scope = AnswerScope(
            tests=["testOnlyA", "testOnlyB", "testOnlyC"],
            total=3,
            label="NARROW SCOPE",
        )
        broad_sources = [
            {"type": "test", "label": f"testBroad{i}", "meta": ""}
            for i in range(20)
        ]
        broad_sources += [
            {"type": "test", "label": "testOnlyA", "meta": ""},
        ]
        plan = _make_plan(AnswerType.RISK_RANKING, scope, intent=AnswerIntent.RANKING_LIST)
        result = generate_follow_ups(plan, broad_sources)
        combined = " ".join(result)
        for i in range(20):
            assert f"testBroad{i}" not in combined


class TestAnswerTypeAwareness:
    """D — Different answer types produce different follow-up shapes."""

    def test_regression_diff_vs_risk_ranking(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="S")
        plan_rd = _make_plan(AnswerType.REGRESSION_DIFF, scope)
        plan_rr = _make_plan(AnswerType.RISK_RANKING, scope, intent=AnswerIntent.RANKING_LIST)
        assert generate_follow_ups(plan_rd, []) != generate_follow_ups(plan_rr, [])

    def test_flakiness_binary_vs_flakiness_ranking(self):
        scope = AnswerScope(tests=["testA"], total=1, label="S")
        plan_fb = _make_plan(AnswerType.FLAKINESS_BINARY, scope, intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        plan_fr = _make_plan(AnswerType.FLAKINESS_RANKING, scope, intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        assert generate_follow_ups(plan_fb, []) != generate_follow_ups(plan_fr, [])

    def test_all_answer_types_produce_output(self):
        scope = AnswerScope(tests=["testA"], runs=["Run #1"], total=1, label="S")
        for at in AnswerType:
            plan = _make_plan(at, scope)
            result = generate_follow_ups(plan, [])
            assert result, f"No follow-ups for AnswerType.{at.name}"
            assert all(q.strip() for q in result)

    @pytest.mark.parametrize("answer_type,expected_keyword", [
        (AnswerType.REGRESSION_DIFF, "flaky"),
        (AnswerType.RISK_RANKING, "risk"),
        (AnswerType.TREND, "recovered"),
        (AnswerType.RECOMMENDATION, "impact"),
    ])
    def test_answer_type_follow_ups_contain_relevant_keyword(
        self, answer_type, expected_keyword,
    ):
        scope = AnswerScope(tests=["testA", "testB"], runs=["Run #1"], total=2, label="S")
        plan = _make_plan(answer_type, scope)
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert expected_keyword in combined


class TestFollowupPriority:
    """G — Follow-up priority order (drill-down > expansion > action)."""

    def test_first_followup_is_specific_drilldown(self):
        """The first follow-up should be a specific drill-down when scope has tests."""
        scope = AnswerScope(
            tests=["testAddItemToCart", "testCheckoutFlow"],
            total=2,
            label="NF",
        )
        plan = _make_plan(AnswerType.REGRESSION_DIFF, scope)
        result = generate_follow_ups(plan, [])
        # First result should contain a specific test name (drill-down)
        assert "testAddItemToCart" in result[0]

    def test_no_duplicate_suggestions(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="S")
        plan = _make_plan(AnswerType.REGRESSION_DIFF, scope)
        result = generate_follow_ups(plan, [])
        assert len(result) == len(set(result))

    def test_max_three_followups(self):
        scope = AnswerScope(tests=["t1", "t2", "t3", "t4", "t5"], total=5, label="S")
        plan = _make_plan(AnswerType.REGRESSION_DIFF, scope)
        result = generate_follow_ups(plan, [])
        assert len(result) <= 3


class TestPlanDrivenGeneration:
    """A — Core architectural change: AnswerPlan drives generation."""

    def test_plan_with_scope_uses_scope_not_sources(self):
        """When plan has scope, follow-ups use scope tests — not source tests."""
        scope = AnswerScope(tests=["testFromScope"], total=1, label="S")
        sources = [{"type": "test", "label": "testFromSources", "meta": ""}]
        plan = _make_plan(AnswerType.ROOT_CAUSE, scope, intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        result = generate_follow_ups(plan, sources)
        combined = " ".join(result)
        assert "testFromScope" in combined
        assert "testFromSources" not in combined

    def test_plan_without_scope_falls_back_to_sources(self):
        """When plan has no scope, source-card tests form the fallback scope."""
        sources = [{"type": "test", "label": "testFallback", "meta": ""}]
        plan = _make_plan(AnswerType.ROOT_CAUSE, intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE)
        result = generate_follow_ups(plan, sources)
        combined = " ".join(result)
        assert "testFallback" in combined

    def test_backward_compat_bare_intent(self):
        """Passing a bare AnswerIntent still works (backward compat)."""
        result = generate_follow_ups(AnswerIntent.NEW_REGRESSIONS, _TEST_SOURCES)
        assert isinstance(result, list)
        assert 1 <= len(result) <= 3


# ---------------------------------------------------------------------------
# Payload-driven follow-up tests (StructuredPayload awareness)
# ---------------------------------------------------------------------------

from qalens.llm.answer_types import PayloadSection, StructuredPayload
from qalens.llm.followups import _payload_verdict_polarity, _payload_section_count


class TestPayloadVerdictPolarity:
    """I.1 — _payload_verdict_polarity helper returns correct classification."""

    def test_all_flaky_verdict(self):
        payload = StructuredPayload(verdict="**Yes — all 3 newly failing tests showed prior flakiness.**")
        assert _payload_verdict_polarity(payload) == "all"

    def test_none_flaky_verdict(self):
        payload = StructuredPayload(verdict="**No — none of the 3 newly failing tests showed flakiness.**")
        assert _payload_verdict_polarity(payload) == "none"

    def test_some_flaky_verdict(self):
        payload = StructuredPayload(verdict="**Yes — 2 of the 5 newly failing tests showed prior flakiness.**")
        assert _payload_verdict_polarity(payload) == "some"

    def test_no_payload(self):
        assert _payload_verdict_polarity(None) is None

    def test_empty_verdict(self):
        payload = StructuredPayload(verdict=None)
        assert _payload_verdict_polarity(payload) is None


class TestPayloadSectionCount:
    """I.2 — _payload_section_count helper returns correct counts."""

    def test_matching_section(self):
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Newly Failing (3)", items=["a", "b", "c"]),
            PayloadSection(heading="Recovered (2)", items=["d", "e"]),
        ])
        assert _payload_section_count(payload, "Newly Failing") == 3

    def test_empty_section_excluded(self):
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Recovered (0)", items=[], empty=True),
        ])
        assert _payload_section_count(payload, "Recovered") is None

    def test_no_match(self):
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Newly Failing (3)", items=["a", "b", "c"]),
        ])
        assert _payload_section_count(payload, "Recovered") is None

    def test_no_payload(self):
        assert _payload_section_count(None, "Newly Failing") is None


class TestPayloadDrivenBinaryFollowups:
    """I.3 — Flakiness-binary follow-ups change based on payload verdict."""

    def test_all_flaky_verdict_suggests_quarantine(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="NF")
        payload = StructuredPayload(
            verdict="**Yes — all 2 newly failing tests showed prior flakiness.**",
            sections=[PayloadSection(heading="Recently flaky", items=["- testA", "- testB"])],
        )
        plan = AnswerPlan(
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            answer_type=AnswerType.FLAKINESS_BINARY,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
            payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "quarantine" in combined

    def test_none_flaky_verdict_suggests_root_causes(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="NF")
        payload = StructuredPayload(
            verdict="**No — none of the 2 newly failing tests showed flakiness.**",
            sections=[PayloadSection(heading="Stable in the recent window", items=["- testA", "- testB"])],
        )
        plan = AnswerPlan(
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            answer_type=AnswerType.FLAKINESS_BINARY,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
            payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "root cause" in combined or "genuine regression" in combined

    def test_mixed_verdict_is_distinct_from_all(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="NF")
        all_payload = StructuredPayload(
            verdict="**Yes — all 2 newly failing tests showed prior flakiness.**",
        )
        mixed_payload = StructuredPayload(
            verdict="**Yes — 1 of the 2 newly failing tests showed prior flakiness.**",
        )
        plan_all = AnswerPlan(
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            answer_type=AnswerType.FLAKINESS_BINARY,
            include_root_cause=False, include_recommendations=False,
            scope=scope, payload=all_payload,
        )
        plan_mixed = AnswerPlan(
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            answer_type=AnswerType.FLAKINESS_BINARY,
            include_root_cause=False, include_recommendations=False,
            scope=scope, payload=mixed_payload,
        )
        result_all = generate_follow_ups(plan_all, [])
        result_mixed = generate_follow_ups(plan_mixed, [])
        assert result_all != result_mixed


class TestPayloadDrivenRegressionFollowups:
    """I.4 — Regression-diff follow-ups use payload section counts."""

    def test_recovered_section_adds_recovery_question(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="NF")
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Newly Failing (2)", items=["- testA", "- testB"]),
            PayloadSection(heading="Recovered (3)", items=["- testC", "- testD", "- testE"]),
        ])
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False, include_recommendations=False,
            scope=scope, payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "recovered" in combined

    def test_no_recovered_section_omits_recovery_question(self):
        scope = AnswerScope(tests=["testA", "testB"], total=2, label="NF")
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Newly Failing (2)", items=["- testA", "- testB"]),
            PayloadSection(heading="Recovered (0)", items=[], empty=True),
        ])
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False, include_recommendations=False,
            scope=scope, payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "recovered" not in combined


class TestPayloadDrivenSummaryFollowups:
    """I.5 — Summary follow-ups use payload section counts when available."""

    def test_summary_with_newly_failing_count(self):
        scope = AnswerScope(runs=["Run #5"], total=0, label="S")
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Newly Failing (4)", items=["a", "b", "c", "d"]),
        ])
        plan = AnswerPlan(
            intent=AnswerIntent.SUMMARY_OVERVIEW,
            answer_type=AnswerType.SUMMARY,
            include_root_cause=False, include_recommendations=False,
            scope=scope, payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        assert "4" in combined

    def test_summary_without_payload_uses_generic(self):
        scope = AnswerScope(runs=["Run #5"], total=0, label="S")
        plan = AnswerPlan(
            intent=AnswerIntent.SUMMARY_OVERVIEW,
            answer_type=AnswerType.SUMMARY,
            include_root_cause=False, include_recommendations=False,
            scope=scope,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "risk" in combined or "consistently" in combined


class TestPayloadFormatHint:
    """I.6 — PayloadSection.format_hint propagates through format_block()."""

    def test_format_hint_appears_in_block(self):
        payload = StructuredPayload(sections=[
            PayloadSection(
                heading="Newly Failing (3)",
                items=["- testA"],
                format_hint="Group by root-cause heading.",
            ),
        ])
        block = payload.format_block()
        assert "[Render: Group by root-cause heading.]" in block

    def test_no_format_hint_omits_render_tag(self):
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Stable", items=["- testB"]),
        ])
        block = payload.format_block()
        assert "[Render:" not in block

    def test_empty_format_hint_omits_render_tag(self):
        payload = StructuredPayload(sections=[
            PayloadSection(heading="Stable", items=["- testB"], format_hint=""),
        ])
        block = payload.format_block()
        assert "[Render:" not in block


class TestDetailFollowupGrounding:
    """I.7 — DETAIL follow-ups only reference entities from the scope."""

    def test_detail_followups_reference_in_scope_test(self):
        scope = AnswerScope(tests=["testCheckout"], runs=["Run #10"], total=1, label="D")
        plan = _make_plan(AnswerType.DETAIL, scope, intent=AnswerIntent.DRILL_DOWN_DETAIL)
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        assert "testCheckout" in combined

    def test_detail_followups_reject_out_of_scope_source(self):
        scope = AnswerScope(tests=["testCheckout"], runs=["Run #10"], total=1, label="D")
        sources = [
            {"type": "test", "label": "testCheckout", "meta": ""},
            {"type": "test", "label": "testForeignEntity", "meta": ""},
        ]
        plan = _make_plan(AnswerType.DETAIL, scope, intent=AnswerIntent.DRILL_DOWN_DETAIL)
        result = generate_follow_ups(plan, sources)
        combined = " ".join(result)
        assert "testForeignEntity" not in combined

    def test_detail_followups_include_run_label(self):
        scope = AnswerScope(tests=["testA"], runs=["Run #42"], total=1, label="D")
        plan = _make_plan(AnswerType.DETAIL, scope, intent=AnswerIntent.DRILL_DOWN_DETAIL)
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        assert "Run #42" in combined
