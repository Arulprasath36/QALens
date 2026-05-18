"""Tests for :mod:`qalens.llm.routing` — signal detection and context orchestration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from qalens.llm.routing import (
    QuerySignals,
    _build_signals_header,
    _build_newly_failing_scope,
    detect_signals,
    gather_context_for_signals,
    normalize_query,
)
from qalens.llm.context import _has_slowing_chip
from qalens.analyzers.predictor import RiskSignals


# ---------------------------------------------------------------------------
# Helpers for _build_newly_failing_scope tests
# ---------------------------------------------------------------------------


def _make_scope_run(
    run_id: str,
    project: str,
    tests: list,
    *,
    hour: int = 10,
):
    """Create a minimal TestRun for scope-builder tests."""
    from qalens.models.run import RunMetadata, TestRun

    meta = RunMetadata(
        run_id=run_id,
        report_format="extent",
        report_path=f"/tmp/fake_{run_id}.html",
        project=project,
        started_at=datetime(2026, 1, 1, hour, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, hour, 5, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _make_scope_tc(name: str, status: str):
    """Create a minimal TestCaseResult for scope-builder tests."""
    from qalens.models.test_case import TestCaseResult, TestStatus

    st = TestStatus(status)
    return TestCaseResult(test_id=f"tc-{name}", name=name, status=st)

# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------


class TestNormalizeQuery:
    def test_lowercases_input(self):
        assert normalize_query("Why Does TestFoo FAIL") == "why does testfoo fail"

    def test_collapses_whitespace(self):
        assert normalize_query("  too   many   spaces  ") == "too many spaces"

    def test_strips_straight_apostrophe(self):
        assert normalize_query("it's taking too long") == "its taking too long"

    def test_strips_curly_apostrophe(self):
        assert normalize_query("it\u2019s taking too long") == "its taking too long"

    def test_strips_backtick(self):
        assert normalize_query("`test`") == "test"

    def test_empty_string(self):
        assert normalize_query("") == ""

    def test_already_normalised_is_idempotent(self):
        q = "which tests are stable but slowing"
        assert normalize_query(normalize_query(q)) == normalize_query(q)


# ---------------------------------------------------------------------------
# detect_signals — individual signals
# ---------------------------------------------------------------------------


class TestDetectSignals:
    # -- risk ---------------------------------------------------

    def test_risk_signal_next_run(self):
        s = detect_signals("which tests will fail on the next run")
        assert s.asks_about_risk

    def test_risk_signal_prediction(self):
        s = detect_signals("give me a risk prediction for the project")
        assert s.asks_about_risk

    def test_risk_signal_likely_to_fail(self):
        s = detect_signals("which tests are likely to fail soon")
        assert s.asks_about_risk

    def test_risk_signal_forecast(self):
        s = detect_signals("forecast failures for the next sprint")
        assert s.asks_about_risk

    # -- duration -----------------------------------------------

    def test_duration_signal_taking_longer(self):
        s = detect_signals("which tests are taking longer than usual")
        assert s.asks_about_duration

    def test_duration_signal_slowing(self):
        s = detect_signals("tests that are slowing down")
        assert s.asks_about_duration

    def test_duration_signal_execution_time(self):
        s = detect_signals("show execution time trends")
        assert s.asks_about_duration

    def test_duration_signal_performance(self):
        s = detect_signals("are there any performance regressions")
        assert s.asks_about_duration

    def test_duration_signal_slower(self):
        s = detect_signals("these tests are getting slower over time")
        assert s.asks_about_duration

    # -- stability -----------------------------------------------

    def test_stability_signal_stable(self):
        s = detect_signals("which tests are stable this sprint")
        assert s.asks_about_stability

    def test_stability_signal_flaky(self):
        s = detect_signals("list all flaky tests in the project")
        assert s.asks_about_stability

    def test_stability_signal_volatile(self):
        s = detect_signals("show me volatile tests")
        assert s.asks_about_stability

    def test_stability_signal_streak(self):
        s = detect_signals("tests on a fail streak")
        assert s.asks_about_stability

    # -- failures ------------------------------------------------

    def test_failure_signal_failing(self):
        s = detect_signals("show me all failing tests")
        assert s.asks_about_failures

    def test_failure_signal_broken(self):
        s = detect_signals("which tests are broken right now")
        assert s.asks_about_failures

    def test_failure_signal_error(self):
        s = detect_signals("tests with an error in the last run")
        assert s.asks_about_failures

    # -- root cause -----------------------------------------------

    def test_root_cause_signal_why(self):
        s = detect_signals("why does testLogin keep failing")
        assert s.asks_about_root_cause

    def test_root_cause_signal_explain(self):
        s = detect_signals("explain the cause of this failure")
        assert s.asks_about_root_cause

    def test_root_cause_signal_investigate(self):
        s = detect_signals("investigate the broken tests")
        assert s.asks_about_root_cause

    # -- trend ---------------------------------------------------

    def test_trend_signal_over_time(self):
        s = detect_signals("how has pass rate changed over time")
        assert s.asks_about_trend

    def test_trend_signal_declining(self):
        s = detect_signals("tests declining in the past week")
        assert s.asks_about_trend

    def test_trend_signal_getting_worse(self):
        s = detect_signals("tests that are getting worse")
        assert s.asks_about_trend

    def test_trend_signal_improving(self):
        s = detect_signals("which tests are improving")
        assert s.asks_about_trend

    # -- history -------------------------------------------------

    def test_history_signal_over_time(self):
        s = detect_signals("show run history over time")
        assert s.asks_about_history

    def test_history_signal_past_runs(self):
        s = detect_signals("compare past runs for this test")
        assert s.asks_about_history

    # -- suite ---------------------------------------------------

    def test_suite_signal(self):
        s = detect_signals("which suite has the most failures")
        assert s.asks_about_suite

    def test_suite_signal_module(self):
        s = detect_signals("failures grouped by module")
        assert s.asks_about_suite

    # -- comparison ----------------------------------------------

    def test_comparison_signal_vs(self):
        s = detect_signals("compare run A vs run B")
        assert s.asks_about_comparison

    def test_comparison_signal_worse_than(self):
        s = detect_signals("is the pass rate worse than last week")
        assert s.asks_about_comparison

    # -- owner ---------------------------------------------------

    def test_owner_signal(self):
        s = detect_signals("who owns testCheckoutFlow")
        assert s.asks_about_owner

    def test_owner_signal_team(self):
        s = detect_signals("which team is responsible for this failure")
        assert s.asks_about_owner


# ---------------------------------------------------------------------------
# detect_signals — multi-signal combinations
# ---------------------------------------------------------------------------


class TestMultiSignalDetection:
    def test_duration_and_stability_together(self):
        s = detect_signals("stable tests that are slowing down")
        assert s.asks_about_duration
        assert s.asks_about_stability

    def test_duration_stability_and_trend(self):
        s = detect_signals("which stable tests are slowing down over time")
        assert s.asks_about_duration
        assert s.asks_about_stability
        assert s.asks_about_trend

    def test_risk_and_failure_together(self):
        s = detect_signals("predict which broken tests will fail next run")
        assert s.asks_about_risk
        assert s.asks_about_failures

    def test_root_cause_and_failure(self):
        s = detect_signals("why are so many tests failing today")
        assert s.asks_about_root_cause
        assert s.asks_about_failures


# ---------------------------------------------------------------------------
# QuerySignals properties
# ---------------------------------------------------------------------------


class TestQuerySignalsProperties:
    def test_needs_risk_context_when_risk_active(self):
        s = QuerySignals(asks_about_risk=True)
        assert s.needs_risk_context

    def test_needs_risk_context_when_duration_active(self):
        s = QuerySignals(asks_about_duration=True)
        assert s.needs_risk_context

    def test_needs_risk_context_when_stability_active(self):
        s = QuerySignals(asks_about_stability=True)
        assert s.needs_risk_context

    def test_needs_risk_context_when_trend_active(self):
        s = QuerySignals(asks_about_trend=True)
        assert s.needs_risk_context

    def test_not_needs_risk_context_when_only_root_cause(self):
        s = QuerySignals(asks_about_root_cause=True)
        assert not s.needs_risk_context

    def test_not_needs_risk_context_when_only_failures(self):
        # Failure questions without risk/duration/stability use project context
        s = QuerySignals(asks_about_failures=True)
        assert not s.needs_risk_context

    def test_not_needs_risk_context_when_only_comparison(self):
        s = QuerySignals(asks_about_comparison=True)
        assert not s.needs_risk_context

    def test_any_signal_false_when_empty(self):
        s = QuerySignals()
        assert not s.any_signal

    def test_any_signal_true_when_risk_set(self):
        s = QuerySignals(asks_about_risk=True)
        assert s.any_signal

    def test_any_signal_true_when_root_cause_only(self):
        s = QuerySignals(asks_about_root_cause=True)
        assert s.any_signal

    def test_needs_risk_context_false_when_all_false(self):
        s = QuerySignals()
        assert not s.needs_risk_context


# ---------------------------------------------------------------------------
# _build_signals_header
# ---------------------------------------------------------------------------


class TestBuildSignalsHeader:
    def test_empty_when_no_signals(self):
        assert _build_signals_header(QuerySignals()) == ""

    def test_contains_query_signals_heading(self):
        s = QuerySignals(asks_about_duration=True)
        header = _build_signals_header(s)
        assert "[QUERY SIGNALS]" in header

    def test_lists_duration_signal(self):
        s = QuerySignals(asks_about_duration=True)
        header = _build_signals_header(s)
        assert "Duration" in header or "duration" in header

    def test_lists_stability_signal(self):
        s = QuerySignals(asks_about_stability=True)
        header = _build_signals_header(s)
        assert "Stability" in header or "stability" in header

    def test_guardrail_note_present(self):
        s = QuerySignals(asks_about_duration=True)
        header = _build_signals_header(s)
        assert "duration_spike" in header or "duration" in header.lower()
        assert "not available" in header or "say so" in header or "explicitly" in header

    def test_multiple_signals_listed(self):
        s = QuerySignals(asks_about_risk=True, asks_about_duration=True, asks_about_stability=True)
        header = _build_signals_header(s)
        # Should have at least 3 bullet points
        assert header.count("  - ") >= 3


# ---------------------------------------------------------------------------
# gather_context_for_signals — unit (no DB required for empty-signals path)
# ---------------------------------------------------------------------------


class TestGatherContextForSignals:
    def test_returns_empty_when_no_signals(self):
        s = QuerySignals()
        ctx, _facts, sources, mode = gather_context_for_signals(s, "tell me about the project")
        assert ctx == ""
        assert sources == []
        assert mode == ""

    def test_returns_empty_when_only_root_cause(self):
        s = QuerySignals(asks_about_root_cause=True)
        ctx, _facts, sources, mode = gather_context_for_signals(s, "why does testLogin fail")
        assert ctx == ""
        assert mode == ""

    def test_returns_empty_when_only_failure_signal(self):
        s = QuerySignals(asks_about_failures=True)
        ctx, _facts, sources, mode = gather_context_for_signals(s, "show failing tests")
        assert ctx == ""
        assert mode == ""

    def test_mode_is_project_when_routed(self, tmp_path):
        """When signals require risk context, mode must be 'project'."""
        from qalens.db.schema import get_connection, init_db

        db = tmp_path / "r.db"
        conn = get_connection(str(db))
        init_db(conn)
        conn.close()

        s = QuerySignals(asks_about_duration=True)
        ctx, _facts, sources, mode = gather_context_for_signals(
            s, "which tests are slowing", db_path=str(db)
        )
        assert mode == "project"

    def test_context_contains_signals_header_when_routed(self, tmp_path):
        from qalens.db.schema import get_connection, init_db

        db = tmp_path / "r2.db"
        conn = get_connection(str(db))
        init_db(conn)
        conn.close()

        s = QuerySignals(asks_about_risk=True)
        ctx, _facts, _sources, _mode = gather_context_for_signals(
            s, "which tests will fail next run", db_path=str(db)
        )
        assert "[QUERY SIGNALS]" in ctx


# ---------------------------------------------------------------------------
# Regression tests (known failing cases from production)
# ---------------------------------------------------------------------------


class TestRegressions:
    def test_stable_but_taking_longer_detects_duration(self):
        """'which tests are stable but taking longer than usual' must fire duration."""
        normalized = normalize_query("which tests are stable but taking longer than usual")
        s = detect_signals(normalized)
        assert s.asks_about_duration, (
            "Duration signal must fire for 'taking longer than usual'"
        )

    def test_stable_but_taking_longer_detects_stability(self):
        """'stable but taking longer' must also fire stability signal."""
        normalized = normalize_query("which tests are stable but taking longer than usual")
        s = detect_signals(normalized)
        assert s.asks_about_stability, (
            "Stability signal must fire for 'stable' in the query"
        )

    def test_stable_but_taking_longer_needs_risk_context(self):
        """Duration signal means needs_risk_context is True."""
        normalized = normalize_query("which tests are stable but taking longer than usual")
        s = detect_signals(normalized)
        assert s.needs_risk_context, (
            "needs_risk_context must be True so gather_risk_context is called, "
            "which contains the LOW-tier duration_spike data"
        )

    def test_slowing_tests_route_to_risk_context(self):
        """'tests that are slowing down' must route to risk context."""
        normalized = normalize_query("are any tests slowing down in recent runs")
        s = detect_signals(normalized)
        assert s.asks_about_duration
        assert s.needs_risk_context

    def test_risk_prediction_does_not_also_trigger_failure(self):
        """Pure prediction question should not confusingly set asks_about_failures."""
        s = detect_signals(normalize_query("predict which tests will fail on the next run"))
        assert s.asks_about_risk
        # 'fail' is in the sentence but in a prediction context; the failure
        # keyword 'failing'/'failed'/'broken' should NOT fire.
        # Note: 'fail' alone is not in _FAILURE_KEYWORDS, so this should hold.
        assert not s.asks_about_failures

    def test_execution_time_fires_duration(self):
        """'execution time' is a duration keyword (regression from _RISK_PHRASES era)."""
        s = detect_signals(normalize_query("show me tests with increased execution time"))
        assert s.asks_about_duration

    def test_duration_trend_fires_duration_and_trend(self):
        """'duration trend' fires both duration and trend signals."""
        s = detect_signals(normalize_query("show the duration trend over time"))
        assert s.asks_about_duration
        assert s.asks_about_trend


# ---------------------------------------------------------------------------
# _build_newly_failing_scope — compact scope builder for flakiness-history context
# ---------------------------------------------------------------------------


class TestBuildNewlyFailingScope:
    """Tests for the helper that builds a compact newly-failing test list."""

    def test_returns_not_enough_runs_sentinel_on_empty_db(self, tmp_path):
        from qalens.db.schema import get_connection, init_db

        db = tmp_path / "empty.db"
        conn = get_connection(str(db))
        init_db(conn)
        conn.close()

        result = _build_newly_failing_scope(db_path=str(db))
        assert result.total == 0
        assert result.tests == []
        assert result.label == "NEWLY FAILING TESTS"

    def test_returns_bullet_list_for_newly_failing(self, tmp_path):
        """With two runs where testAlpha regressed, scope contains only testAlpha."""
        from qalens.db.schema import get_connection, init_db
        from qalens.db.repository import RunRepository

        db = tmp_path / "scope.db"
        conn = get_connection(str(db))
        init_db(conn)
        repo = RunRepository(conn)

        # run_a (older, hour=10) → testAlpha passes, testBeta passes
        run_a = _make_scope_run("run_a", "p", [
            _make_scope_tc("testAlpha", "passed"),
            _make_scope_tc("testBeta", "passed"),
        ], hour=10)
        # run_b (newer, hour=11) → testAlpha fails (newly failing), testBeta passes
        run_b = _make_scope_run("run_b", "p", [
            _make_scope_tc("testAlpha", "failed"),
            _make_scope_tc("testBeta", "passed"),
        ], hour=11)
        repo.save_run(run_a)
        repo.save_run(run_b)
        conn.close()

        result = _build_newly_failing_scope(project="p", db_path=str(db))
        assert "testAlpha" in result.tests
        assert "testBeta" not in result.tests

    def test_returns_no_newly_failing_sentinel_when_all_pass(self, tmp_path):
        from qalens.db.schema import get_connection, init_db
        from qalens.db.repository import RunRepository

        db = tmp_path / "allpass.db"
        conn = get_connection(str(db))
        init_db(conn)
        repo = RunRepository(conn)

        run_a = _make_scope_run("run_a", "p", [_make_scope_tc("testAlpha", "passed")], hour=10)
        run_b = _make_scope_run("run_b", "p", [_make_scope_tc("testAlpha", "passed")], hour=11)
        repo.save_run(run_a)
        repo.save_run(run_b)
        conn.close()

        result = _build_newly_failing_scope(project="p", db_path=str(db))
        assert result.total == 0
        assert result.tests == []


class TestAnswerScopeFormatBlock:
    """Tests for AnswerScope.format_block() rendering."""

    def test_format_block_contains_scope_label(self):
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=["testA"], total=1, label="NEWLY FAILING TESTS")
        block = scope.format_block()
        assert "=== SCOPE: NEWLY FAILING TESTS ===" in block

    def test_format_block_lists_tests(self):
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=["testA", "testB"], total=2, label="X")
        block = scope.format_block()
        assert "- testA" in block
        assert "- testB" in block

    def test_format_block_enforces_only_instruction(self):
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=["testA"], total=1, label="X")
        block = scope.format_block()
        assert "Use ONLY these tests" in block

    def test_format_block_shows_total(self):
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=["a", "b", "c"], total=3, label="X")
        block = scope.format_block()
        assert "Total scoped tests: 3" in block

    def test_format_block_includes_runs_when_set(self):
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=["a"], runs=["Run #50", "Run #51"], total=1, label="X")
        block = scope.format_block()
        assert "Run #50" in block
        assert "Run #51" in block

    def test_empty_scope_still_has_enforcement(self):
        """Even an empty scope must tell the LLM not to fabricate tests."""
        from qalens.llm.answer_plan import AnswerScope

        scope = AnswerScope(tests=[], total=0, label="EMPTY")
        block = scope.format_block()
        assert "Use ONLY these tests" in block
        assert "Total scoped tests: 0" in block


# ---------------------------------------------------------------------------
# _has_slowing_chip — mirrors the JS _topSignals top-2 ranking
# ---------------------------------------------------------------------------


def _sig(volatility=0.0, failure_burden=0.0, recent_decline=0.0,
         fail_streak=0.0, duration_spike=0.0) -> RiskSignals:
    return RiskSignals(
        volatility=volatility,
        failure_burden=failure_burden,
        recent_decline=recent_decline,
        fail_streak=fail_streak,
        duration_spike=duration_spike,
    )


class TestHasSlowingChip:
    def test_true_when_duration_spike_is_only_signal(self):
        """If duration_spike is the only positive signal it's always top-2."""
        assert _has_slowing_chip(_sig(duration_spike=0.86))

    def test_true_when_duration_spike_is_rank_1(self):
        assert _has_slowing_chip(_sig(volatility=0.3, duration_spike=0.7))

    def test_true_when_duration_spike_is_rank_2(self):
        assert _has_slowing_chip(_sig(volatility=0.9, duration_spike=0.7, failure_burden=0.1))

    def test_false_when_duration_spike_is_rank_3(self):
        """duration_spike outscored by two other signals → chip not shown."""
        assert not _has_slowing_chip(
            _sig(volatility=0.95, failure_burden=0.90, duration_spike=0.86)
        )

    def test_false_when_duration_spike_is_zero(self):
        assert not _has_slowing_chip(_sig(volatility=0.5))

    def test_false_when_all_signals_zero(self):
        assert not _has_slowing_chip(_sig())

    def test_true_when_duration_spike_ties_rank_2(self):
        """Ties are resolved by sort stability; if duration_spike ties for #2 it still qualifies."""
        # Two signals: volatility=0.5, duration_spike=0.5 — both positive, sort gives top 2
        assert _has_slowing_chip(_sig(volatility=0.5, duration_spike=0.5))

    def test_regression_outscored_test_not_slowing(self):
        """Regression: tests with duration_spike=0.86 but volatility+failure_burden > 0.86
        should NOT be tagged as slowing (they get Volatile/Failing chips instead)."""
        assert not _has_slowing_chip(
            _sig(volatility=0.92, failure_burden=0.88, duration_spike=0.86)
        )

    def test_regression_pure_slowing_test(self):
        """Regression: stable LOW test with duration_spike as dominant signal IS slowing."""
        assert _has_slowing_chip(
            _sig(volatility=0.05, failure_burden=0.02, duration_spike=0.75)
        )


# ---------------------------------------------------------------------------
# StructuredPayload tests
# ---------------------------------------------------------------------------


class TestStructuredPayloadFormatBlock:
    """Tests for StructuredPayload.format_block() rendering."""

    def test_verdict_appears_first(self):
        from qalens.llm.answer_plan import PayloadSection, StructuredPayload

        p = StructuredPayload(
            verdict="**Summary: 3 newly failing**",
            sections=[PayloadSection(heading="Details", items=["- testA"])],
        )
        block = p.format_block()
        assert block.startswith("**Summary: 3 newly failing**")

    def test_empty_sections_suppressed(self):
        from qalens.llm.answer_plan import PayloadSection, StructuredPayload

        p = StructuredPayload(
            sections=[
                PayloadSection(heading="Has items", items=["- x"]),
                PayloadSection(heading="Empty", items=[], empty=True),
            ],
        )
        block = p.format_block()
        assert "Has items" in block
        assert "Empty" not in block

    def test_deterministic_ordering(self):
        from qalens.llm.answer_plan import PayloadSection, StructuredPayload

        p = StructuredPayload(
            sections=[
                PayloadSection(heading="First", items=["- a"]),
                PayloadSection(heading="Second", items=["- b"]),
            ],
        )
        block = p.format_block()
        assert block.index("First") < block.index("Second")

    def test_backend_counts_in_output(self):
        from qalens.llm.answer_plan import PayloadSection, StructuredPayload

        p = StructuredPayload(
            verdict="**3 newly failing, 2 recovered**",
            sections=[
                PayloadSection(heading="Newly Failing (3)", items=["- a", "- b", "- c"]),
                PayloadSection(heading="Recovered (2)", items=["- d", "- e"]),
            ],
        )
        block = p.format_block()
        assert "Newly Failing (3)" in block
        assert "Recovered (2)" in block


# ---------------------------------------------------------------------------
# _build_regression_diff_payload tests
# ---------------------------------------------------------------------------


class TestBuildRegressionDiffPayload:
    """Tests for _build_regression_diff_payload backend structure builder."""

    def test_returns_none_on_empty_db(self, tmp_path):
        from qalens.db.schema import get_connection, init_db
        from qalens.llm.routing import _build_regression_diff_payload

        db = tmp_path / "empty.db"
        conn = get_connection(str(db))
        init_db(conn)
        conn.close()

        result = _build_regression_diff_payload(db_path=str(db))
        assert result is None

    def test_produces_sections_with_counts(self, tmp_path):
        from qalens.db.schema import get_connection, init_db
        from qalens.db.repository import RunRepository
        from qalens.llm.routing import _build_regression_diff_payload

        db = tmp_path / "diff.db"
        conn = get_connection(str(db))
        init_db(conn)
        repo = RunRepository(conn)

        run_a = _make_scope_run("run_a", "p", [
            _make_scope_tc("testAlpha", "passed"),
            _make_scope_tc("testBeta", "passed"),
        ], hour=10)
        run_b = _make_scope_run("run_b", "p", [
            _make_scope_tc("testAlpha", "failed"),
            _make_scope_tc("testBeta", "passed"),
        ], hour=11)
        repo.save_run(run_a)
        repo.save_run(run_b)
        conn.close()

        payload = _build_regression_diff_payload(project="p", db_path=str(db))
        assert payload is not None
        block = payload.format_block()
        assert "Newly Failing (1)" in block
        assert "testAlpha" in block

    def test_empty_newly_failing_section_suppressed(self, tmp_path):
        from qalens.db.schema import get_connection, init_db
        from qalens.db.repository import RunRepository
        from qalens.llm.routing import _build_regression_diff_payload

        db = tmp_path / "nochange.db"
        conn = get_connection(str(db))
        init_db(conn)
        repo = RunRepository(conn)

        run_a = _make_scope_run("run_a", "p", [
            _make_scope_tc("testAlpha", "passed"),
        ], hour=10)
        run_b = _make_scope_run("run_b", "p", [
            _make_scope_tc("testAlpha", "passed"),
        ], hour=11)
        repo.save_run(run_a)
        repo.save_run(run_b)
        conn.close()

        payload = _build_regression_diff_payload(project="p", db_path=str(db))
        assert payload is not None
        block = payload.format_block()
        assert "Newly Failing (0)" not in block
        assert "Consistently Passing" in block


# ---------------------------------------------------------------------------
# _inject_scope_context tests
# ---------------------------------------------------------------------------


class TestInjectScopeContext:
    """Tests for the _inject_scope_context helper."""

    def test_prepends_scope_block_when_tests_present(self):
        from qalens.llm.answer_plan import AnswerScope
        from qalens.llm.routing import _inject_scope_context

        scope = AnswerScope(
            tests=["testA()", "testB()"],
            runs=["Run #5", "Run #6"],
            total=2,
            label="NEWLY FAILING TESTS",
        )
        result = _inject_scope_context("some context", scope)
        assert result.startswith("=== SCOPE: NEWLY FAILING TESTS ===")
        assert "some context" in result
        assert "testA()" in result

    def test_returns_context_unchanged_when_scope_empty(self):
        from qalens.llm.answer_plan import AnswerScope
        from qalens.llm.routing import _inject_scope_context

        scope = AnswerScope(label="NEWLY FAILING TESTS")
        result = _inject_scope_context("some context", scope)
        assert result == "some context"

    def test_scope_block_ends_before_context(self):
        from qalens.llm.answer_plan import AnswerScope
        from qalens.llm.routing import _inject_scope_context

        scope = AnswerScope(tests=["testX()"], total=1, label="TEST SCOPE")
        result = _inject_scope_context("original data", scope)
        # Scope block should be separated from context by double newline
        assert "\n\noriginal data" in result
