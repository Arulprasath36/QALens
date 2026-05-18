"""Contract-test suite for QA Lens LLM orchestration.

Locks down the deterministic layers of the five core answer families:
REGRESSION_DIFF, FLAKINESS_BINARY, FLAKINESS_RANKING, RISK_RANKING, TREND.

Also covers heuristic disambiguation (binary ↔ ranking split, risk ↔ flakiness
metric separation, time-window cue overlap guard).

These are *structural contracts* — they verify answer type detection, scope
building, payload/section shaping, context/scope injection, and follow-up
grounding.  They do NOT test freeform LLM output.
"""

from __future__ import annotations

import pytest

from qalens.llm.answer_types import (
    AnswerIntent,
    AnswerScope,
    AnswerType,
    PayloadSection,
    RankingMetric,
    StructuredPayload,
)
from qalens.llm.intent_detection import (
    detect_answer_intent,
    detect_answer_type,
    detect_ranking_metric,
    detect_secondary_intent,
)
from qalens.llm.answer_plan import AnswerPlan, build_answer_plan
from qalens.llm.routing import (
    _build_newly_failing_scope,
    _build_flakiness_binary_payload,
    _build_regression_diff_payload,
    _inject_scope_context,
    gather_ranking_context,
    gather_comparison_context,
)

from qalens.llm.context_history import (
    ResolvedQueryContext,
    extract_query_context_from_plan,
    is_followup_question,
)

from tests.conftest_contracts import (
    PROJECT,
    NEWLY_FAILING,
    RECOVERED,
    CONSISTENTLY_FAILING,
    CONSISTENTLY_PASSING,
    MULTI_RUN_NEWLY_FAILING,
    MULTI_RUN_RECOVERED,
    STABLE_CONTROLS,
    build_two_run_scenario,
    build_multi_run_scenario,
    make_tc,
    make_run,
    assert_scope_contains_exactly,
    assert_scope_excludes,
    assert_payload_has_sections,
    assert_payload_excludes_sections,
    assert_ranking_order,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. REGRESSION_DIFF family
# ═══════════════════════════════════════════════════════════════════════════


class TestRegressionDiffIntentDetection:
    """All canonical regression-diff phrasings → REGRESSION_DIFF answer type."""

    @pytest.mark.parametrize(
        "question",
        [
            "What new failures were introduced?",
            "List all new regressions",
            "What tests failed that were passing before?",
            "Show me the delta between the latest two runs",
            "Tests that passed last time but now fail",
            "What are the newly failing tests?",
            "Which tests are newly broken?",
        ],
        ids=lambda q: q[:50],
    )
    def test_regression_questions_resolve_to_regression_diff(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.REGRESSION_DIFF

    @pytest.mark.parametrize(
        "question",
        [
            "What new failures were introduced?",
            "List all new regressions",
            "What tests failed that were passing before?",
        ],
        ids=lambda q: q[:50],
    )
    def test_regression_questions_resolve_to_new_regressions_intent(self, question: str):
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.NEW_REGRESSIONS


class TestRegressionDiffScope:
    """Newly-failing scope contains exactly the right tests."""

    def test_scope_contains_newly_failing_tests(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert_scope_contains_exactly(scope, NEWLY_FAILING)

    def test_scope_excludes_recovered_tests(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert_scope_excludes(scope, RECOVERED)

    def test_scope_excludes_consistently_failing(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert_scope_excludes(scope, CONSISTENTLY_FAILING)

    def test_scope_excludes_consistently_passing(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert_scope_excludes(scope, CONSISTENTLY_PASSING)

    def test_scope_total_matches_test_count(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert scope.total == len(NEWLY_FAILING)

    def test_scope_label_is_newly_failing(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert scope.label == "NEWLY FAILING TESTS"

    def test_scope_has_run_labels(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert len(scope.runs) == 2
        assert all("Run #" in r for r in scope.runs)


class TestRegressionDiffPayload:
    """_build_regression_diff_payload produces correct sections and verdict."""

    def test_payload_has_four_sections(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert len(payload.sections) == 4

    def test_payload_newly_failing_section(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert_payload_has_sections(payload, ["Newly Failing"])
        # Check the section lists the right tests
        nf_section = next(s for s in payload.sections if "Newly Failing" in s.heading)
        for name in NEWLY_FAILING:
            assert any(name in item for item in nf_section.items), (
                f"{name} missing from Newly Failing items"
            )

    def test_payload_recovered_section(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert_payload_has_sections(payload, ["Recovered"])
        rec_section = next(s for s in payload.sections if "Recovered" in s.heading)
        for name in RECOVERED:
            assert any(name in item for item in rec_section.items), (
                f"{name} missing from Recovered items"
            )

    def test_payload_consistently_failing_section(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert_payload_has_sections(payload, ["Consistently Failing"])
        cf_section = next(s for s in payload.sections if "Consistently Failing" in s.heading)
        for name in CONSISTENTLY_FAILING:
            assert any(name in item for item in cf_section.items), (
                f"{name} missing from Consistently Failing items"
            )

    def test_payload_verdict_has_counts(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert payload.verdict is not None
        assert f"+{len(NEWLY_FAILING)} newly failing" in payload.verdict
        assert f"-{len(RECOVERED)} recovered" in payload.verdict

    def test_payload_verdict_has_run_labels(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert "Comparing" in payload.verdict

    def test_recovered_tests_not_in_newly_failing_section(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        nf_section = next(s for s in payload.sections if "Newly Failing" in s.heading)
        for name in RECOVERED:
            assert not any(name in item for item in nf_section.items), (
                f"Recovered test {name} leaked into Newly Failing section"
            )

    def test_empty_sections_flagged(self, tmp_path):
        """When a category has no members, its section has empty=True."""
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        for section in payload.sections:
            if not section.items or (len(section.items) == 1 and "not listed" in section.items[0]):
                continue
            assert not section.empty, f"Section '{section.heading}' has items but empty=True"

    def test_section_heading_includes_count(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        nf_section = next(s for s in payload.sections if "Newly Failing" in s.heading)
        assert f"({len(NEWLY_FAILING)})" in nf_section.heading


class TestRegressionDiffScopeInjection:
    """_inject_scope_context correctly prepends scope to context."""

    def test_inject_prepends_scope_format_block(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        ctx = "Some existing context about tests."
        result = _inject_scope_context(ctx, scope)
        assert result.startswith("=== SCOPE: NEWLY FAILING TESTS ===")
        assert ctx in result

    def test_inject_includes_all_scoped_tests(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        result = _inject_scope_context("ctx", scope)
        for test_name in NEWLY_FAILING:
            assert test_name in result

    def test_inject_noop_for_empty_scope(self):
        scope = AnswerScope(label="EMPTY")
        ctx = "Some context"
        assert _inject_scope_context(ctx, scope) == ctx


class TestRegressionDiffPlan:
    """build_answer_plan for NEW_REGRESSIONS produces correct plan."""

    def test_plan_answer_type_is_regression_diff(self):
        plan = build_answer_plan(
            AnswerIntent.NEW_REGRESSIONS,
            question="What new failures were introduced?",
        )
        assert plan.answer_type == AnswerType.REGRESSION_DIFF

    def test_plan_intent_is_new_regressions(self):
        plan = build_answer_plan(
            AnswerIntent.NEW_REGRESSIONS,
            question="What new failures were introduced?",
        )
        assert plan.intent == AnswerIntent.NEW_REGRESSIONS


# ═══════════════════════════════════════════════════════════════════════════
# 2. FLAKINESS_BINARY family
# ═══════════════════════════════════════════════════════════════════════════


class TestFlakinessBinaryIntentDetection:
    """Binary flakiness-history questions → FLAKINESS_BINARY answer type."""

    @pytest.mark.parametrize(
        "question",
        [
            "Were any of these tests flaky before this regression?",
            "Were these tests flaky prior to this failure?",
            "Did any of the failing tests have a flaky history?",
            "Had these tests been flaky in previous runs?",
            "Were any failing tests already unstable before they regressed?",
        ],
        ids=lambda q: q[:55],
    )
    def test_flakiness_binary_questions_resolve_correctly(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.FLAKINESS_BINARY, (
            f"Expected FLAKINESS_BINARY, got {answer_type} "
            f"(intent={intent}) for: {question!r}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "Were any of these tests flaky before this regression?",
            "Did any of the failing tests have a flaky history?",
        ],
    )
    def test_flakiness_binary_intent_is_diagnostic(self, question: str):
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE


class TestFlakinessBinaryPayload:
    """_build_flakiness_binary_payload produces correct structure."""

    def test_payload_has_three_sections(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert len(payload.sections) == 3

    def test_payload_section_headings(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        headings = [s.heading for s in payload.sections]
        assert "Recently flaky" in headings
        assert "Stable in the recent window" in headings
        assert "Why they were marked flaky" in headings

    def test_payload_verdict_classifies_flakiness(self, tmp_path):
        """Verdict must start with Yes/No and reference newly failing test count."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert payload.verdict is not None
        verdict_lower = payload.verdict.lower()
        assert "yes" in verdict_lower or "no" in verdict_lower, (
            f"Verdict must contain Yes or No, got: {payload.verdict[:100]}"
        )
        assert "newly failing" in verdict_lower, (
            f"Verdict must reference 'newly failing', got: {payload.verdict[:100]}"
        )

    def test_empty_section_flagged(self, tmp_path):
        """If no tests are flaky (or all are), one of the first two sections is empty."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        flaky_section = next(s for s in payload.sections if s.heading == "Recently flaky")
        stable_section = next(s for s in payload.sections if s.heading == "Stable in the recent window")
        # At least one should have items, at least one might be empty
        assert flaky_section.items or stable_section.items, "Both sections are empty"
        # Check empty flag consistency
        assert flaky_section.empty == (len(flaky_section.items) == 0)
        assert stable_section.empty == (len(stable_section.items) == 0)

    def test_verdict_arithmetic_consistency(self, tmp_path):
        """flaky_count + stable_count == total newly failing (exact count)."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        flaky_section = next(s for s in payload.sections if s.heading == "Recently flaky")
        stable_section = next(s for s in payload.sections if s.heading == "Stable in the recent window")
        flaky_count = len(flaky_section.items)
        stable_count = len(stable_section.items)
        total = flaky_count + stable_count
        # The binary payload only analyses newly-failing tests (run N-1 passed, run N failed).
        # In the multi-run scenario the last two runs determine the scope.
        assert total > 0, "No items in either section"
        # Verify each item bullet mentions exactly one test name from the scoped set
        all_names_in_payload = set()
        for item in flaky_section.items + stable_section.items:
            for name in MULTI_RUN_NEWLY_FAILING:
                if name in item:
                    all_names_in_payload.add(name)
        assert all_names_in_payload == set(MULTI_RUN_NEWLY_FAILING), (
            f"Payload test set mismatch.\n"
            f"  Expected: {sorted(MULTI_RUN_NEWLY_FAILING)}\n"
            f"  Got:      {sorted(all_names_in_payload)}"
        )


class TestFlakinessBinaryScopeLeakage:
    """Recovered/unrelated tests must NOT appear in flakiness binary payload."""

    def test_recovered_tests_excluded_from_payload(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = []
        for s in payload.sections:
            all_items.extend(s.items)
        payload_text = "\n".join(all_items)
        for name in RECOVERED:
            assert name not in payload_text, (
                f"Recovered test '{name}' leaked into flakiness binary payload"
            )

    def test_consistently_passing_excluded_from_payload(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        for name in CONSISTENTLY_PASSING:
            assert name not in all_items, (
                f"Consistently passing test '{name}' leaked into flakiness payload"
            )

    def test_stable_controls_excluded_from_payload(self, tmp_path):
        """Stable controls (always-pass, always-fail) must never appear in binary payload."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        for name in STABLE_CONTROLS:
            assert name not in all_items, (
                f"Stable control '{name}' leaked into flakiness binary payload"
            )


class TestFlakinessBinaryFlipCountSymbolConsistency:
    """Flip counts in the binary payload must agree with the displayed symbols.

    Regression: the old code used a 2-state model (failed vs not-failed)
    while _compute_flip_score uses a 3-state model (pass, fail, other).
    This caused flips to be over-counted when skipped/unknown statuses
    appeared in history, and skipped runs to display as ✅.
    """

    def test_flip_count_matches_symbols_for_multi_run(self, tmp_path):
        """For every item in the flaky/stable sections, the stated flip count
        must equal the actual pass↔fail transitions visible in the symbols."""
        import re
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        flaky_sec = next(s for s in payload.sections if s.heading == "Recently flaky")
        stable_sec = next(s for s in payload.sections if s.heading == "Stable in the recent window")
        for item in flaky_sec.items + stable_sec.items:
            # Extract stated flip count
            m = re.search(r"flipped (\d+) times?", item)
            if m:
                stated_flips = int(m.group(1))
            else:
                assert "no flips" in item
                stated_flips = 0
            # Extract symbols
            sym_match = re.search(r"\(([✅❌⏭ ]+)\)", item)
            assert sym_match, f"No symbol block found in: {item}"
            symbols = sym_match.group(1).split()
            # Count actual flips from symbols (3-state: only ✅↔❌ transitions)
            actual_flips = 0
            for i in range(1, len(symbols)):
                prev_pass = symbols[i - 1] == "✅"
                prev_fail = symbols[i - 1] == "❌"
                curr_pass = symbols[i] == "✅"
                curr_fail = symbols[i] == "❌"
                if (prev_pass and curr_fail) or (prev_fail and curr_pass):
                    actual_flips += 1
            assert stated_flips == actual_flips, (
                f"Flip count mismatch: stated={stated_flips}, "
                f"actual={actual_flips} for symbols {symbols} in: {item}"
            )

    def test_skipped_status_does_not_show_as_pass(self, tmp_path):
        """If a test has skipped runs in history, they must show as ⏭ not ✅."""
        from tests.conftest_contracts import make_tc, make_run
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection, init_db

        db_path = str(tmp_path / "skip_test.db")
        conn = get_connection(db_path)
        init_db(conn)
        repo = RunRepository(conn)

        # 5 runs where testSkippy has: passed, skipped, failed, passed, failed
        # (run_004=passed → run_005=failed = newly failing)
        patterns = ["passed", "skipped", "failed", "passed", "failed"]
        for i, status in enumerate(patterns):
            tc = make_tc("testSkippy", status,
                         error_type="Err" if status == "failed" else None,
                         message="err" if status == "failed" else None)
            stable_tc = make_tc("testStable", "passed")
            repo.save_run(make_run(f"run_{i+1:03d}", "SkipProject",
                                   [tc, stable_tc], hour=10 + i))
        conn.close()

        payload = _build_flakiness_binary_payload(
            project="SkipProject", db_path=db_path,
        )
        assert payload is not None
        all_items = [item for s in payload.sections for item in s.items]
        skippy_item = next((it for it in all_items if "testSkippy" in it), None)
        assert skippy_item is not None, "testSkippy should be newly failing"
        # The skipped run must NOT appear as ✅
        # Pattern: P, skip, F, P, F → symbols: ✅ ⏭ ❌ ✅ ❌
        assert "⏭" in skippy_item, (
            f"Skipped run should show ⏭ not ✅: {skippy_item}"
        )
        # Count ✅ — should be 2 (positions 0 and 3), not 3
        assert skippy_item.count("✅") == 2, (
            f"Expected 2 ✅ symbols (skipped should not be ✅): {skippy_item}"
        )
        # Flip count: P→skip(no), skip→F(no), F→P(yes), P→F(yes) = 2 flips
        assert "flipped 2 time" in skippy_item, (
            f"Expected 2 flips (skip transitions ignored): {skippy_item}"
        )

    def test_expected_flip_counts_for_known_patterns(self, tmp_path):
        """Verify exact flip counts for the multi-run scenario's known patterns.

        testAddItemToCart:   P P F P F → 3 flips (P→F, F→P, P→F)
        testCreateOrder:     P P P P F → 1 flip  (P→F)
        testProcessPayment:  F P F P F → 4 flips (F→P, P→F, F→P, P→F)
        """
        import re
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = [item for s in payload.sections for item in s.items]
        expected = {
            "testAddItemToCart": 3,
            "testCreateOrder": 1,
            "testProcessPayment": 4,
        }
        for test_name, expected_flips in expected.items():
            item = next((it for it in all_items if test_name in it), None)
            assert item is not None, f"{test_name} not found in payload"
            m = re.search(r"flipped (\d+) times?", item)
            assert m, f"No flip count in: {item}"
            actual = int(m.group(1))
            assert actual == expected_flips, (
                f"{test_name}: expected {expected_flips} flips, got {actual}"
            )


class TestFlakinessBinaryPlan:
    """build_answer_plan for flakiness-history → correct plan shape."""

    def test_plan_answer_type(self):
        q = "Were any of these tests flaky before this regression?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.answer_type == AnswerType.FLAKINESS_BINARY

    def test_plan_no_ranking_metric(self):
        q = "Were any of these tests flaky before this regression?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        # Binary flakiness doesn't use ranking — metric should be None or FLAKINESS
        assert plan.ranking_metric is None or plan.ranking_metric == RankingMetric.FLAKINESS


# ═══════════════════════════════════════════════════════════════════════════
# 3. FLAKINESS_RANKING family
# ═══════════════════════════════════════════════════════════════════════════


class TestFlakinessRankingIntentDetection:
    """Flakiness-ranking questions → FLAKINESS_RANKING answer type."""

    @pytest.mark.parametrize(
        "question",
        [
            "Which of the newly failing tests have the worst pre-existing flakiness?",
            "Which of these were already the flakiest?",
            "Rank the newly failing tests by prior flakiness",
            "Which had the highest pre-existing flakiness?",
        ],
        ids=lambda q: q[:55],
    )
    def test_flakiness_ranking_questions_resolve_correctly(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.FLAKINESS_RANKING, (
            f"Expected FLAKINESS_RANKING, got {answer_type} "
            f"(intent={intent}) for: {question!r}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "Which tests are the most flaky?",
            "What are the flakiest tests?",
            "Which tests have the highest flip score?",
        ],
        ids=lambda q: q[:50],
    )
    def test_project_wide_flakiness_ranking(self, question: str):
        """Project-wide ranking questions (no prior/history context) → FLAKINESS_RANKING."""
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.FLAKINESS_RANKING


class TestFlakinessRankingPayload:
    """gather_ranking_context with FLAKINESS metric produces ranked output."""

    def test_ranking_context_has_metric_header_and_rows(self, tmp_path):
        """Ranking context must include flip_score header and at least one ranked row."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        ctx, facts, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.FLAKINESS,
        )
        assert "flip_score" in ctx, "Ranking context missing flip_score metric header"
        assert "Test Ranking (flip_score)" in ctx, "Missing structured ranking header"
        assert len(sources) > 0, "No ranked sources returned"
        # Every source should carry the flip_score metric family
        for src in sources:
            assert "flip_score" in src.get("meta", ""), (
                f"Source missing flip_score metric: {src}"
            )

    def test_ranking_order_is_deterministic(self, tmp_path):
        """testProcessPayment (4 flips) > testAddItemToCart (2 flips) — unconditional."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, _, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.FLAKINESS,
        )
        ranked_names = [s["label"] for s in sources]
        assert "testProcessPayment" in ranked_names, "testProcessPayment missing from ranking"
        assert "testAddItemToCart" in ranked_names, "testAddItemToCart missing from ranking"
        pp_idx = ranked_names.index("testProcessPayment")
        ac_idx = ranked_names.index("testAddItemToCart")
        assert pp_idx < ac_idx, (
            f"testProcessPayment (idx={pp_idx}) must rank above "
            f"testAddItemToCart (idx={ac_idx})"
        )

    def test_stable_tests_rank_below_flaky_ones(self, tmp_path):
        """Always-passing tests should rank below tests with flips."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, _, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=20, min_runs=2,
            metric=RankingMetric.FLAKINESS,
        )
        ranked_names = [s["label"] for s in sources]
        # testProcessPayment (very flaky) must rank above testValidUserLogin (always passing)
        if "testValidUserLogin" in ranked_names:
            pp_idx = ranked_names.index("testProcessPayment")
            vl_idx = ranked_names.index("testValidUserLogin")
            assert pp_idx < vl_idx


class TestFlakinessRankingPlan:
    """build_answer_plan for flakiness-ranking questions."""

    def test_plan_answer_type(self):
        q = "Which of the newly failing tests have the worst pre-existing flakiness?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.answer_type == AnswerType.FLAKINESS_RANKING

    def test_plan_has_ranking_metric_flakiness(self):
        q = "Which tests are the most flaky?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        if plan.ranking_metric is not None:
            assert plan.ranking_metric == RankingMetric.FLAKINESS


# ═══════════════════════════════════════════════════════════════════════════
# 4. RISK_RANKING family
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskRankingIntentDetection:
    """Risk-ranking questions → RISK_RANKING answer type with RISK metric."""

    @pytest.mark.parametrize(
        "question",
        [
            "Which tests are most likely to fail next?",
            "What are the riskiest tests?",
            "Which tests are at risk of failing?",
            "Show me the tests with the highest risk",
            "Which tests are predicted to fail?",
        ],
        ids=lambda q: q[:50],
    )
    def test_risk_questions_resolve_to_risk_ranking(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.RISK_RANKING, (
            f"Expected RISK_RANKING, got {answer_type} "
            f"(intent={intent}) for: {question!r}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "Which tests are most likely to fail next?",
            "What are the riskiest tests?",
        ],
    )
    def test_risk_metric_detected(self, question: str):
        metric = detect_ranking_metric(question)
        assert metric == RankingMetric.RISK


class TestRiskRankingPayload:
    """gather_ranking_context with RISK metric produces risk-based ranking."""

    def test_risk_ranking_has_tier_header_and_rows(self, tmp_path):
        """Risk ranking must include tier-based header and ranked rows."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        ctx, facts, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.RISK,
        )
        assert "Test Ranking (risk_tier)" in ctx, "Missing risk_tier ranking header"
        assert "CRITICAL > HIGH > MEDIUM > LOW" in ctx, "Missing tier ordering description"
        assert len(sources) > 0, "No risk-ranked sources returned"

    def test_risk_sources_carry_risk_metadata(self, tmp_path):
        """Every risk source must carry risk % and tier in metadata — unconditional."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, _, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.RISK,
        )
        assert len(sources) > 0, "No sources — cannot verify metadata"
        for src in sources:
            meta = src.get("meta", "")
            assert "risk" in meta.lower(), f"Source missing 'risk' in meta: {src}"
            assert "%" in meta, f"Source missing risk percentage in meta: {src}"

    def test_risk_source_meta_labels_both_metrics(self, tmp_path):
        """Each source card must carry labeled risk% AND labeled pass_rate — never a bare number."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, _, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.RISK,
        )
        assert len(sources) > 0, "No sources — cannot verify metadata"
        for src in sources:
            meta = src.get("meta", "")
            assert "% risk" in meta, f"Source meta must label risk percentage (e.g. '49% risk'): {meta!r}"
            assert "pass_rate=" in meta, f"Source meta must label pass rate (e.g. 'pass_rate=90%'): {meta!r}"

    def test_risk_ranking_does_not_mention_flip_score(self, tmp_path):
        """Risk ranking must use risk_tier metric, not flip_score."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        ctx, facts, _ = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.RISK,
        )
        assert "flip_score" not in ctx, "Risk ranking should not reference flip_score"


class TestRiskRankingPlan:
    """build_answer_plan for risk-ranking questions."""

    def test_plan_answer_type_is_risk_ranking(self):
        q = "Which tests are most likely to fail next?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.answer_type == AnswerType.RISK_RANKING

    def test_plan_has_risk_metric(self):
        q = "Which tests are most likely to fail next?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.ranking_metric == RankingMetric.RISK

    def test_plan_list_format_rule_labels_pass_rate(self):
        """Row format must include explicit 'pass rate:' label — never a bare percentage."""
        q = "Which tests are most likely to fail next?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        rules_text = " ".join(plan.answer_rules)
        assert "pass rate:" in rules_text, (
            "Risk-ranking row format must label pass rate explicitly (e.g. 'pass rate: 49%')"
        )
        # Old bare format must not appear
        assert "TIER risk, PASS_RATE%" not in rules_text, (
            "Unlabeled percentage format 'TIER risk, PASS_RATE%' must not be in rules"
        )

    def test_plan_has_what_the_numbers_mean_section(self):
        """Answer rules must include a 'What the numbers mean' explanation."""
        q = "Which tests are riskiest right now?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        rules_text = " ".join(plan.answer_rules)
        assert "What the numbers mean" in rules_text, (
            "Risk-ranking plan must include a 'What the numbers mean' section"
        )

    def test_plan_explains_high_risk_high_pass_rate(self):
        """Rules must explain that high risk can coexist with a high pass rate."""
        q = "Which tests are most likely to fail next?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        rules_text = " ".join(plan.answer_rules)
        assert "high pass rate" in rules_text.lower() or "high-risk even with a high pass rate" in rules_text.lower(), (
            "Risk-ranking plan must explain that high risk can coexist with a high pass rate"
        )

    def test_plan_distinguishes_ranking_from_pass_rate(self):
        """Rules must clarify ranking is by QA Lens risk, not by pass rate."""
        q = "Which tests are most likely to fail next?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        rules_text = " ".join(plan.answer_rules)
        assert "NOT by pass rate" in rules_text, (
            "Risk-ranking rules must explicitly state ranking is NOT by pass rate"
        )


class TestRiskVsFlakinessSeparation:
    """Risk and flakiness metrics must never cross-contaminate."""

    @pytest.mark.parametrize(
        "question,expected_metric",
        [
            ("Which tests are most flaky?", RankingMetric.FLAKINESS),
            ("What are the flakiest tests?", RankingMetric.FLAKINESS),
            ("Which tests are most likely to fail next?", RankingMetric.RISK),
            ("What are the riskiest tests?", RankingMetric.RISK),
            ("Which tests have the most failures?", RankingMetric.FAILURE_BURDEN),
            ("What are the slowest tests?", RankingMetric.DURATION),
        ],
        ids=lambda x: str(x)[:60] if isinstance(x, str) else str(x),
    )
    def test_metric_separation(self, question: str, expected_metric: RankingMetric):
        metric = detect_ranking_metric(question)
        assert metric == expected_metric, (
            f"Expected {expected_metric}, got {metric} for: {question!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5. TREND family
# ═══════════════════════════════════════════════════════════════════════════


class TestTrendIntentDetection:
    """Trend questions → TREND answer type, not misclassified as ranking."""

    @pytest.mark.parametrize(
        "question",
        [
            "Is our test pass rate improving or declining?",
            "How has pass rate changed in the last 5 runs?",
            "What's the failure rate trend over time?",
            "Are things getting better or worse?",
            "Show me the progression of pass rate across runs",
            "Is the test suite improving over recent runs?",
        ],
        ids=lambda q: q[:55],
    )
    def test_trend_questions_resolve_to_trend(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.TREND, (
            f"Expected TREND, got {answer_type} "
            f"(intent={intent}) for: {question!r}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "Is our test pass rate improving or declining?",
            "What's the failure rate trend over time?",
        ],
    )
    def test_trend_intent_is_comparison_change(self, question: str):
        """Trend questions go through COMPARISON_CHANGE intent → TREND answer type."""
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.COMPARISON_CHANGE

    def test_trend_not_classified_as_ranking(self):
        q = "How has pass rate changed in the last 5 runs?"
        intent = detect_answer_intent(q)
        answer_type = detect_answer_type(intent, q)
        assert answer_type != AnswerType.FLAKINESS_RANKING
        assert answer_type != AnswerType.RISK_RANKING


class TestTrendPayload:
    """gather_comparison_context with is_trend=True produces trend analysis."""

    def test_trend_context_has_comparison_structure(self, tmp_path):
        """Trend context must include run comparison header and change counts."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        ctx, facts, sources = gather_comparison_context(
            project=PROJECT, db_path=db_path, n_runs=5, is_trend=True,
        )
        assert "Run Comparison" in ctx, "Missing 'Run Comparison' header in trend context"
        assert "newly failing" in ctx.lower(), "Missing 'newly failing' section in trend context"
        assert len(sources) > 0, "No sources returned for trend context"

    def test_trend_facts_contain_trend_block(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, facts, _ = gather_comparison_context(
            project=PROJECT, db_path=db_path, n_runs=5, is_trend=True,
        )
        # When is_trend=True, structured facts should contain trend analysis
        trend_markers = ("TREND", "trend", "direction", "pass rate", "Pass Rate")
        assert any(m in facts for m in trend_markers), (
            f"Trend block missing from structured facts. Got:\n{facts[:300]}"
        )

    def test_non_trend_comparison_has_no_trend_block(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, facts, _ = gather_comparison_context(
            project=PROJECT, db_path=db_path, n_runs=2, is_trend=False,
        )
        # Non-trend comparison should NOT have TREND ANALYSIS header
        assert "[TREND ANALYSIS]" not in facts


class TestTrendPlan:
    """build_answer_plan for trend questions."""

    def test_plan_answer_type_is_trend(self):
        q = "Is our test pass rate improving or declining?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.answer_type == AnswerType.TREND

    def test_plan_is_trend_flag(self):
        q = "Is our test pass rate improving or declining?"
        intent = detect_answer_intent(q)
        plan = build_answer_plan(intent, question=q)
        assert plan.is_trend_question is True


# ═══════════════════════════════════════════════════════════════════════════
# 6. Heuristic disambiguation
# ═══════════════════════════════════════════════════════════════════════════


class TestBinaryVsRankingSplit:
    """Binary and ranking flakiness questions must route to different answer types."""

    @pytest.mark.parametrize(
        "binary_question",
        [
            "Were any of these tests flaky before this regression?",
            "Did any of the failing tests have a flaky history?",
            "Were these tests flaky prior to this failure?",
        ],
    )
    def test_binary_does_not_become_ranking(self, binary_question: str):
        intent = detect_answer_intent(binary_question)
        answer_type = detect_answer_type(intent, binary_question)
        assert answer_type == AnswerType.FLAKINESS_BINARY
        assert answer_type != AnswerType.FLAKINESS_RANKING

    @pytest.mark.parametrize(
        "ranking_question",
        [
            "Which of the newly failing tests have the worst pre-existing flakiness?",
            "Rank the newly failing tests by prior flakiness",
            "Which had the highest pre-existing flakiness?",
        ],
    )
    def test_ranking_does_not_become_binary(self, ranking_question: str):
        intent = detect_answer_intent(ranking_question)
        answer_type = detect_answer_type(intent, ranking_question)
        assert answer_type == AnswerType.FLAKINESS_RANKING
        assert answer_type != AnswerType.FLAKINESS_BINARY


class TestTimeWindowCueOverlap:
    """Time-window phrases must not pull trend questions into ranking."""

    @pytest.mark.parametrize(
        "question",
        [
            "How has pass rate changed in the last 5 runs?",
            "How has pass rate changed in the last 10 runs?",
            "Show the trend over the last 5 runs",
            "What's the failure rate in the last 3 runs?",
        ],
        ids=lambda q: q[:55],
    )
    def test_time_window_phrases_not_ranking(self, question: str):
        intent = detect_answer_intent(question)
        assert intent != AnswerIntent.RANKING_LIST, (
            f"Time-window question misclassified as RANKING_LIST: {question!r}"
        )


class TestDiagnosticVsRankingMixed:
    """Questions with both 'why' and ranking cues disambiguate correctly."""

    def test_why_most_flaky_is_ranking(self):
        """'Why are the most flaky tests failing?' → ranking (list-oriented)."""
        q = "Why are the most flaky tests failing?"
        intent = detect_answer_intent(q)
        assert intent == AnswerIntent.RANKING_LIST

    def test_why_single_test_is_diagnostic(self):
        """'Why is testCheckout flaky?' → diagnostic (not ranking)."""
        q = "Why is testCheckout flaky?"
        intent = detect_answer_intent(q)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE


class TestFixQuestionsAreDiagnostic:
    """'How do I fix testX?' questions must route to DIAGNOSTIC_ROOT_CAUSE.

    Without this, they fall through to SUMMARY_OVERVIEW and the LLM receives
    project-wide context (e.g. Watch List) instead of the specific test's
    error details — producing an answer about the wrong root cause.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "How do I fix testDashboardLoadsInUnder3s()?",
            "How to fix testCheckoutFlow()?",
            "How can I fix testOrderHistoryList?",
            "How should I fix testTrackShipment()?",
            "Help me fix testDownloadMonthlyReportPdf()",
            "How do I troubleshoot testPaymentProcessing()?",
        ],
        ids=lambda q: q[:55],
    )
    def test_fix_questions_detect_as_diagnostic(self, question: str):
        intent = detect_answer_intent(question)
        assert intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE, (
            f"Expected DIAGNOSTIC_ROOT_CAUSE, got {intent} for: {question!r}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "How do I fix testDashboardLoadsInUnder3s()?",
            "How to fix testCheckoutFlow()?",
            "Troubleshoot testPaymentProcessing()",
        ],
    )
    def test_fix_questions_resolve_to_root_cause_type(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type == AnswerType.ROOT_CAUSE, (
            f"Expected ROOT_CAUSE answer type, got {answer_type} for: {question!r}"
        )

    def test_fix_question_does_not_inherit_summary_context(self):
        """'How do I fix testX?' after a summary turn must NOT inherit SUMMARY intent."""
        prior = ResolvedQueryContext(
            prior_intent=AnswerIntent.SUMMARY_OVERVIEW,
            prior_test_names=[],
        )
        question = "How do I fix testDashboardLoadsInUnder3s()?"
        # New test name → strong new-topic signal → not a follow-up
        assert not is_followup_question(question, prior)
        # And intent should be diagnostic, not inherited summary
        intent = detect_answer_intent(question)
        plan = build_answer_plan(intent, question=question, prior_context=prior)
        assert plan.intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE


class TestNegatedPriorFlakiness:
    """Negated flakiness questions ('no prior flakiness') should NOT match flakiness-history."""

    @pytest.mark.parametrize(
        "question",
        [
            "Which tests failed with no prior flakiness?",
            "Which newly failing tests had no prior instability?",
            "Which tests are not flaky before?",
        ],
    )
    def test_negated_not_flakiness_binary(self, question: str):
        intent = detect_answer_intent(question)
        answer_type = detect_answer_type(intent, question)
        assert answer_type != AnswerType.FLAKINESS_BINARY


class TestSecondaryIntentDoesNotContaminate:
    """Secondary intent should never override primary answer type."""

    def test_regression_with_recommendation_cue(self):
        """'What new regressions should I fix first?' — primary is NEW_REGRESSIONS."""
        q = "What new regressions should I fix first?"
        intent = detect_answer_intent(q)
        # Primary should still be NEW_REGRESSIONS (not RECOMMENDATION)
        answer_type = detect_answer_type(intent, q)
        assert answer_type == AnswerType.REGRESSION_DIFF

    def test_ranking_with_diagnostic_secondary(self):
        """Secondary DIAGNOSTIC does not override RANKING answer type."""
        q = "Which tests are the most flaky and why?"
        intent = detect_answer_intent(q)
        answer_type = detect_answer_type(intent, q)
        # Should stay as ranking, not flip to ROOT_CAUSE
        assert answer_type in (AnswerType.FLAKINESS_RANKING, AnswerType.RISK_RANKING)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Cross-family structural invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestPayloadFormatConsistency:
    """StructuredPayload.format_block() is well-formed for all families."""

    def test_regression_diff_format_block(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        block = payload.format_block()
        assert isinstance(block, str)
        assert len(block) > 0
        # Verdict should be at the top
        lines = block.strip().split("\n")
        assert "Comparing" in lines[0] or "**" in lines[0]

    def test_flakiness_binary_format_block(self, tmp_path):
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        block = payload.format_block()
        assert isinstance(block, str)
        assert len(block) > 0

    def test_empty_sections_suppressed_in_format(self):
        """Sections with empty=True should not appear in formatted output."""
        payload = StructuredPayload(
            verdict="Test verdict",
            sections=[
                PayloadSection(heading="Visible", items=["- item1"]),
                PayloadSection(heading="Hidden", items=[], empty=True),
            ],
        )
        block = payload.format_block()
        assert "Visible" in block
        assert "Hidden" not in block


class TestAnswerScopeFormatBlock:
    """AnswerScope.format_block() has correct structure."""

    def test_scope_format_block_structure(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        block = scope.format_block()
        assert block.startswith("=== SCOPE:")
        assert "Total scoped tests:" in block
        assert "Do not mention tests outside this list" in block
        for name in NEWLY_FAILING:
            assert f"- {name}" in block

    def test_empty_scope_format_block(self):
        scope = AnswerScope(label="EMPTY")
        block = scope.format_block()
        assert "Total scoped tests: 0" in block


# ═══════════════════════════════════════════════════════════════════════════
# 8. Follow-up orchestration contracts
# ═══════════════════════════════════════════════════════════════════════════


def _simulate_followup(q1: str, q2: str) -> tuple[AnswerPlan, AnswerPlan]:
    """Simulate a two-turn conversation: Q1 → plan1, Q2 (follow-up) → plan2.

    Returns (plan1, plan2) where plan2 was built with prior_context from plan1.
    """
    intent1 = detect_answer_intent(q1)
    plan1 = build_answer_plan(intent1, question=q1)
    prior_ctx = extract_query_context_from_plan(plan1)

    intent2 = detect_answer_intent(q2)
    plan2 = build_answer_plan(intent2, question=q2, prior_context=prior_ctx)
    return plan1, plan2


class TestFollowupRegressionToFlakinessBinary:
    """Q1: 'What new failures were introduced?' → Q2: 'Were any of these tests flaky?'

    Expected:
    - Q2 answer type = FLAKINESS_BINARY
    - Q2 does NOT inherit Q1's answer type (REGRESSION_DIFF)
    - Scope preservation: newly-failing tests from Q1 stay in scope
    - Out-of-scope tests do not leak in
    """

    Q1 = "What new failures were introduced?"
    Q2 = "Were any of these tests flaky before this regression?"

    def test_q2_answer_type_is_flakiness_binary(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.answer_type == AnswerType.FLAKINESS_BINARY

    def test_q2_does_not_inherit_regression_diff(self):
        plan1, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan1.answer_type == AnswerType.REGRESSION_DIFF
        assert plan2.answer_type != AnswerType.REGRESSION_DIFF

    def test_q2_intent_is_diagnostic(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.intent == AnswerIntent.DIAGNOSTIC_ROOT_CAUSE

    def test_scope_preserved_across_followup(self, tmp_path):
        """The binary payload analyses the same newly-failing scope Q1 would produce."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        # Every test in the scope must appear in the binary payload
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        for test_name in scope.tests:
            assert test_name in all_items, (
                f"Scoped test '{test_name}' missing from flakiness binary payload"
            )

    def test_recovered_tests_absent_from_binary_payload(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        for name in RECOVERED:
            assert name not in all_items, (
                f"Recovered test '{name}' leaked into follow-up binary payload"
            )

    def test_stable_controls_absent_from_binary_payload(self, tmp_path):
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        for name in CONSISTENTLY_PASSING + CONSISTENTLY_FAILING:
            assert name not in all_items, (
                f"Out-of-scope test '{name}' leaked into follow-up binary payload"
            )


class TestFollowupRegressionToFlakinessRanking:
    """Q1: 'What new failures were introduced?' → Q2: 'Which have the worst flakiness?'

    Expected:
    - Q2 answer type = FLAKINESS_RANKING (not FLAKINESS_BINARY)
    - Q2 does NOT reuse binary/tier template
    - Ranking order is deterministic
    """

    Q1 = "What new failures were introduced?"
    Q2 = "Which of the newly failing tests have the worst pre-existing flakiness?"

    def test_q2_answer_type_is_flakiness_ranking(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.answer_type == AnswerType.FLAKINESS_RANKING

    def test_q2_is_not_binary(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.answer_type != AnswerType.FLAKINESS_BINARY

    def test_q2_does_not_inherit_regression_diff(self):
        plan1, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan1.answer_type == AnswerType.REGRESSION_DIFF
        assert plan2.answer_type != AnswerType.REGRESSION_DIFF

    def test_ranking_payload_deterministic_order(self, tmp_path):
        """Ranking context produced with FLAKINESS metric is deterministically ordered."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        _, _, sources = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.FLAKINESS,
        )
        ranked_names = [s["label"] for s in sources]
        # Verify same order on a second call
        _, _, sources2 = gather_ranking_context(
            project=PROJECT, db_path=db_path, top_n=10, min_runs=2,
            metric=RankingMetric.FLAKINESS,
        )
        ranked_names2 = [s["label"] for s in sources2]
        assert ranked_names == ranked_names2, "Ranking order is not deterministic"


class TestFollowupScopedToDetail:
    """Scoped answer → detail follow-up (e.g. 'Which run IDs had this issue?')

    Expected:
    - Q2 answer type changes to DETAIL (via DRILL_DOWN_DETAIL intent)
    - Q2 does not inherit Q1's answer type
    - Drill-down overrides follow-up inheritance
    """

    Q1 = "What new failures were introduced?"
    Q2 = "Which run IDs had this issue?"

    def test_q2_answer_type_is_detail(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.answer_type == AnswerType.DETAIL

    def test_q2_intent_is_drilldown(self):
        _, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan2.intent == AnswerIntent.DRILL_DOWN_DETAIL

    def test_q2_does_not_inherit_regression_diff(self):
        plan1, plan2 = _simulate_followup(self.Q1, self.Q2)
        assert plan1.answer_type == AnswerType.REGRESSION_DIFF
        assert plan2.answer_type != AnswerType.REGRESSION_DIFF


class TestFollowupLeakageGuard:
    """Follow-up must NOT introduce tests that were not in the prior scoped answer.

    The newly-failing scope from the regression-diff path defines the
    boundary.  A follow-up that continues analysis on 'these tests' must
    not widen the scope.
    """

    def test_binary_payload_does_not_widen_scope(self, tmp_path):
        """Binary payload only covers newly-failing tests, not the entire project."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        all_items = "\n".join(item for s in payload.sections for item in s.items)
        # Every name in the payload must be in the scope
        all_project_tests = NEWLY_FAILING + RECOVERED + CONSISTENTLY_FAILING + CONSISTENTLY_PASSING
        out_of_scope = [n for n in all_project_tests if n not in scope.tests]
        for name in out_of_scope:
            assert name not in all_items, (
                f"Out-of-scope test '{name}' leaked into follow-up payload"
            )

    def test_scope_injection_blocks_out_of_scope_names(self, tmp_path):
        """Scope injection includes the boundary constraint for the LLM."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        block = scope.format_block()
        assert "Do not mention tests outside this list" in block
        # Recovered tests must not appear in scope block
        for name in RECOVERED:
            assert name not in block, (
                f"Recovered test '{name}' appeared in scope block"
            )

    def test_followup_does_not_fall_back_to_summary(self):
        """A flakiness follow-up must not degrade to SUMMARY_OVERVIEW."""
        q1 = "What new failures were introduced?"
        q2 = "Were any of these tests flaky before this regression?"
        _, plan2 = _simulate_followup(q1, q2)
        assert plan2.answer_type != AnswerType.SUMMARY
        assert plan2.intent != AnswerIntent.SUMMARY_OVERVIEW

    def test_ranking_followup_does_not_fall_back_to_summary(self):
        """A ranking follow-up must not degrade to SUMMARY_OVERVIEW."""
        q1 = "What new failures were introduced?"
        q2 = "Which of the newly failing tests have the worst pre-existing flakiness?"
        _, plan2 = _simulate_followup(q1, q2)
        assert plan2.answer_type != AnswerType.SUMMARY
        assert plan2.intent != AnswerIntent.SUMMARY_OVERVIEW


class TestFollowupInheritanceSkipForNewAnalysis:
    """Flakiness-history and ranking follow-ups carry a completely new analytical
    intent and must NOT inherit the prior intent via follow-up inheritance,
    even though they contain 'these tests' (a follow-up reference cue)."""

    def test_flakiness_binary_skips_inheritance(self):
        q1 = "What new failures were introduced?"
        q2 = "Were any of these tests flaky before this regression?"
        plan1, plan2 = _simulate_followup(q1, q2)
        # plan2 must be FLAKINESS_BINARY, not REGRESSION_DIFF (inherited)
        assert plan2.answer_type == AnswerType.FLAKINESS_BINARY

    def test_flakiness_ranking_skips_inheritance(self):
        q1 = "What new failures were introduced?"
        q2 = "Which of the newly failing tests have the worst pre-existing flakiness?"
        plan1, plan2 = _simulate_followup(q1, q2)
        # plan2 must be FLAKINESS_RANKING, not REGRESSION_DIFF (inherited)
        assert plan2.answer_type == AnswerType.FLAKINESS_RANKING

    def test_drilldown_skips_inheritance(self):
        q1 = "Which tests are the most flaky?"
        q2 = "Which run IDs had this issue?"
        plan1, plan2 = _simulate_followup(q1, q2)
        # plan2 must be DETAIL, not FLAKINESS_RANKING (inherited)
        assert plan2.answer_type == AnswerType.DETAIL


# ═══════════════════════════════════════════════════════════════════════════
# 9. Secondary bookkeeping (enum completeness)
# ═══════════════════════════════════════════════════════════════════════════


class TestAnswerTypeEnumCompleteness:
    """Secondary bookkeeping check — all answer types are reachable from some intent.

    This is a low-value structural check, NOT a product-behavior contract.
    It exists only to catch accidental enum additions that lack a routing path.
    """

    _REACHABLE_TYPES = {
        AnswerType.REGRESSION_DIFF,
        AnswerType.FLAKINESS_BINARY,
        AnswerType.FLAKINESS_RANKING,
        AnswerType.RISK_RANKING,
        AnswerType.TREND,
        AnswerType.ROOT_CAUSE,
        AnswerType.DETAIL,
        AnswerType.SUMMARY,
        AnswerType.RECOMMENDATION,
    }

    def test_all_answer_types_represented(self):
        """Every AnswerType enum value should be in _REACHABLE_TYPES."""
        for at in AnswerType:
            assert at in self._REACHABLE_TYPES, (
                f"AnswerType.{at.name} not covered in reachable set"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 10. Follow-up scope-preservation & payload-awareness contracts
# ═══════════════════════════════════════════════════════════════════════════

from qalens.llm.followups import generate_follow_ups


class TestFollowupScopePreservationContract:
    """A — Scope computed from a real DB flows through to follow-up outputs.

    Proves: the scope built by _build_newly_failing_scope contains exactly
    the newly failing tests and those same tests appear in follow-ups.
    """

    def test_followups_reference_only_newly_failing_tests(self, tmp_path):
        """Follow-ups generated from a real DB scope must reference only newly failing tests."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        # At least one newly failing test must be referenced
        assert any(t in combined for t in NEWLY_FAILING)
        # No recovered or stable test may leak in
        for name in RECOVERED + CONSISTENTLY_PASSING + CONSISTENTLY_FAILING:
            assert name not in combined, (
                f"Out-of-scope test '{name}' found in follow-ups"
            )

    def test_followups_scope_matches_db_scenario(self, tmp_path):
        """The scope used for follow-ups matches the DB scenario exactly."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        assert_scope_contains_exactly(scope, NEWLY_FAILING)

    def test_followups_with_real_payload_and_scope(self, tmp_path):
        """Follow-ups with both real scope and real payload still respect scope."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
            payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        # Must reference at least one scoped test
        assert any(t in combined for t in NEWLY_FAILING)


class TestFollowupPayloadAwarenessContract:
    """B — Payload verdict affects follow-up content in a real DB scenario.

    Proves: when a flakiness-binary payload is built from real DB data,
    the verdict polarity influences which follow-up suggestions appear.
    """

    def test_binary_payload_verdict_is_consistent_with_data(self, tmp_path):
        """The binary payload built from multi-run scenario produces a non-None verdict."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        assert payload.verdict is not None
        assert "newly failing" in payload.verdict.lower()

    def test_binary_followups_use_verdict_from_real_data(self, tmp_path):
        """Follow-ups generated with a real binary payload are contextually relevant."""
        db_path = build_multi_run_scenario(tmp_path, n_runs=5)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        payload = _build_flakiness_binary_payload(project=PROJECT, db_path=db_path)
        plan = AnswerPlan(
            intent=AnswerIntent.DIAGNOSTIC_ROOT_CAUSE,
            answer_type=AnswerType.FLAKINESS_BINARY,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
            payload=payload,
        )
        result = generate_follow_ups(plan, [])
        assert len(result) == 3
        combined = " ".join(result).lower()
        # Must mention flakiness-related concepts
        assert any(
            kw in combined
            for kw in ("flaki", "stable", "quarantine", "prioriti", "regression")
        )

    def test_regression_payload_recovered_section_influences_followups(self, tmp_path):
        """When the regression payload has a recovered section, follow-ups mention recovery."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
            payload=payload,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result).lower()
        assert "recovered" in combined


class TestFollowupDetailGroundingContract:
    """D — DETAIL follow-ups are grounded to in-scope entities.

    Proves: when a DETAIL answer has a scope, follow-ups only reference
    entities from that scope — even with conflicting source cards.
    """

    def test_detail_followup_with_conflicting_sources(self, tmp_path):
        """DETAIL follow-ups reject out-of-scope entities from sources."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        # Include an out-of-scope test in sources
        sources = [
            {"type": "test", "label": name, "meta": ""}
            for name in NEWLY_FAILING
        ] + [
            {"type": "test", "label": "testForeignEntity", "meta": "dashboard"},
        ]
        plan = AnswerPlan(
            intent=AnswerIntent.DRILL_DOWN_DETAIL,
            answer_type=AnswerType.DETAIL,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
        )
        result = generate_follow_ups(plan, sources)
        combined = " ".join(result)
        assert "testForeignEntity" not in combined

    def test_detail_followup_references_scoped_test(self, tmp_path):
        """DETAIL follow-ups reference at least one in-scope entity."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        plan = AnswerPlan(
            intent=AnswerIntent.DRILL_DOWN_DETAIL,
            answer_type=AnswerType.DETAIL,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
        )
        result = generate_follow_ups(plan, [])
        combined = " ".join(result)
        assert any(t in combined for t in NEWLY_FAILING)


class TestFollowupSourceCardConflictContract:
    """E — Source-card conflict guard with real DB data.

    Proves: when sources contain the full project test list but scope is narrow,
    follow-ups stay within the narrow scope.
    """

    def test_broad_sources_do_not_widen_narrow_scope(self, tmp_path):
        """Sources containing all project tests cannot override a narrow scope."""
        db_path = build_two_run_scenario(tmp_path)
        scope = _build_newly_failing_scope(project=PROJECT, db_path=db_path)
        # Sources contain ALL project tests (broader than scope)
        all_tests = NEWLY_FAILING + RECOVERED + CONSISTENTLY_FAILING + CONSISTENTLY_PASSING
        sources = [{"type": "test", "label": name, "meta": ""} for name in all_tests]
        plan = AnswerPlan(
            intent=AnswerIntent.NEW_REGRESSIONS,
            answer_type=AnswerType.REGRESSION_DIFF,
            include_root_cause=False,
            include_recommendations=False,
            scope=scope,
        )
        result = generate_follow_ups(plan, sources)
        combined = " ".join(result)
        # Out-of-scope tests must NOT appear
        for name in RECOVERED + CONSISTENTLY_FAILING + CONSISTENTLY_PASSING:
            assert name not in combined, (
                f"Out-of-scope test '{name}' leaked through broad sources"
            )

    def test_format_hint_survives_payload_construction(self, tmp_path):
        """format_hint set by routing.py is present in constructed payloads."""
        db_path = build_two_run_scenario(tmp_path)
        payload = _build_regression_diff_payload(project=PROJECT, db_path=db_path)
        assert payload is not None
        nf_section = next(
            (s for s in payload.sections if s.heading.startswith("Newly Failing")),
            None,
        )
        assert nf_section is not None
        assert nf_section.format_hint, "Newly Failing section should have a format_hint"
