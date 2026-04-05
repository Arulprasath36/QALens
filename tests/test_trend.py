"""Tests for the trend computation module (ari.llm.trend).

Covers:
- compute_trend Direction detection (declining / improving / stable / insufficient_data)
- compute_trend Confidence assignment (high / medium / low)
- render_trend_facts output format (no placeholders, real values, evidence bullets)
- Integration: is_trend_question routing + answer_plan.is_trend_question flag
- Integration: gather_comparison_context injects [TREND ANALYSIS] when is_trend=True
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from qara.llm.trend import RunRate, TrendResult, compute_trend, render_trend_facts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DECLINING = [
    RunRate("Run #51", 0.80, 32, 8, 40),
    RunRate("Run #52", 0.78, 31, 9, 40),
    RunRate("Run #53", 0.72, 29, 11, 40),
]

_IMPROVING = [
    RunRate("Run #51", 0.60, 24, 16, 40),
    RunRate("Run #52", 0.68, 27, 13, 40),
    RunRate("Run #53", 0.76, 30, 10, 40),
]

_STABLE = [
    RunRate("Run #51", 0.80, 32, 8, 40),
    RunRate("Run #52", 0.81, 32, 8, 40),
    RunRate("Run #53", 0.80, 32, 8, 40),
]

_VOLATILE = [
    RunRate("Run #51", 0.90, 36, 4, 40),
    RunRate("Run #52", 0.50, 20, 20, 40),
    RunRate("Run #53", 0.85, 34, 6, 40),
    RunRate("Run #54", 0.45, 18, 22, 40),
]

_TWO_POINT = [
    RunRate("Run #52", 0.80, 32, 8, 40),
    RunRate("Run #53", 0.72, 29, 11, 40),
]

_FOUR_CONSISTENT_DECLINE = [
    RunRate("Run #50", 0.90, 36, 4, 40),
    RunRate("Run #51", 0.86, 34, 6, 40),
    RunRate("Run #52", 0.80, 32, 8, 40),
    RunRate("Run #53", 0.72, 29, 11, 40),
]


# ===========================================================================
# compute_trend — direction
# ===========================================================================

class TestComputeTrendDirection:

    def test_declining_direction(self) -> None:
        result = compute_trend(_DECLINING)
        assert result.direction == "declining"

    def test_improving_direction(self) -> None:
        result = compute_trend(_IMPROVING)
        assert result.direction == "improving"

    def test_stable_direction(self) -> None:
        result = compute_trend(_STABLE)
        assert result.direction == "stable"

    def test_insufficient_data_single_run(self) -> None:
        result = compute_trend([RunRate("Run #53", 0.72, 29, 11, 40)])
        assert result.direction == "insufficient_data"

    def test_insufficient_data_empty(self) -> None:
        result = compute_trend([])
        assert result.direction == "insufficient_data"

    def test_two_points_declining(self) -> None:
        result = compute_trend(_TWO_POINT)
        assert result.direction == "declining"

    def test_two_points_improving(self) -> None:
        result = compute_trend([RunRate("a", 0.60), RunRate("b", 0.80)])
        assert result.direction == "improving"

    def test_volatile_no_clear_direction(self) -> None:
        """High-variance series with sign reversals should not confidently claim improving/declining."""
        result = compute_trend(_VOLATILE)
        # Either stable or reflects heavy volatility — must not be "insufficient_data"
        assert result.has_data
        assert result.confidence in ("low", "medium")


# ===========================================================================
# compute_trend — confidence
# ===========================================================================

class TestComputeTrendConfidence:

    def test_low_confidence_two_data_points(self) -> None:
        result = compute_trend(_TWO_POINT)
        assert result.confidence == "low"

    def test_medium_confidence_three_points(self) -> None:
        result = compute_trend(_DECLINING)
        assert result.confidence == "medium"

    def test_high_confidence_four_consistent_points(self) -> None:
        result = compute_trend(_FOUR_CONSISTENT_DECLINE)
        assert result.confidence == "high"

    def test_volatile_lowers_confidence(self) -> None:
        result = compute_trend(_VOLATILE)
        assert result.confidence in ("low", "medium")

    def test_insufficient_data_is_low(self) -> None:
        result = compute_trend([])
        assert result.confidence == "low"


# ===========================================================================
# compute_trend — delta
# ===========================================================================

class TestComputeTrendDelta:

    def test_delta_is_negative_for_declining(self) -> None:
        result = compute_trend(_DECLINING)
        assert result.delta_pct is not None
        assert result.delta_pct < 0

    def test_delta_is_positive_for_improving(self) -> None:
        result = compute_trend(_IMPROVING)
        assert result.delta_pct is not None
        assert result.delta_pct > 0

    def test_delta_near_zero_for_stable(self) -> None:
        result = compute_trend(_STABLE)
        assert result.delta_pct is not None
        assert abs(result.delta_pct) < 3.0

    def test_delta_is_none_for_insufficient_data(self) -> None:
        result = compute_trend([])
        assert result.delta_pct is None

    def test_runs_preserved_oldest_first(self) -> None:
        result = compute_trend(_DECLINING)
        assert result.runs[0].label == "Run #51"
        assert result.runs[-1].label == "Run #53"


# ===========================================================================
# render_trend_facts — output format
# ===========================================================================

class TestRenderTrendFacts:

    def test_insufficient_data_message(self) -> None:
        trend = compute_trend([RunRate("Run #53", 0.72)])
        text = render_trend_facts(trend)
        assert "Not enough data" in text

    def test_output_starts_with_trend_analysis_header(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert text.startswith("[TREND ANALYSIS]")

    def test_direction_present_in_output(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert "declining" in text

    def test_confidence_present_in_output(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert "confidence" in text

    def test_no_placeholder_run_n_in_output(self) -> None:
        """The rendered text must never contain the literal placeholder 'Run #N'."""
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert "Run #N" not in text
        assert "PASS_RATE" not in text

    def test_real_labels_appear_in_output(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert "Run #51" in text
        assert "Run #52" in text
        assert "Run #53" in text

    def test_real_percentages_appear_in_output(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        # 0.80 → 80%, 0.78 → 78%, 0.72 → 72%
        assert "80%" in text
        assert "78%" in text
        assert "72%" in text

    def test_evidence_bullets_appear_when_provided(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend, newly_failing=8, recovered=3, consistently_failing=3)
        assert "8" in text
        assert "3" in text
        assert "Supporting evidence" in text

    def test_evidence_section_absent_when_zeros(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        assert "Supporting evidence" not in text

    def test_passed_failed_totals_in_output_when_available(self) -> None:
        trend = compute_trend(_DECLINING)
        text = render_trend_facts(trend)
        # First run: 32 passed, 8 failed of 40
        assert "32 passed" in text or "32" in text

    def test_improving_direction_rendered(self) -> None:
        trend = compute_trend(_IMPROVING)
        text = render_trend_facts(trend)
        assert "improving" in text


# ===========================================================================
# Integration: is_trend_question routing
# ===========================================================================

class TestIsTrendQuestionRouting:
    """Verify detect_answer_intent + build_answer_plan sets is_trend_question."""

    def _plan(self, question: str):
        from qara.llm.answer_plan import AnswerIntent, build_answer_plan, detect_answer_intent
        intent = detect_answer_intent(question)
        return intent, build_answer_plan(intent, question=question)

    def test_pass_rate_improving_declining_is_comparison(self) -> None:
        intent, plan = self._plan("Is our test pass rate improving or declining over time?")
        from qara.llm.answer_plan import AnswerIntent
        assert intent == AnswerIntent.COMPARISON_CHANGE

    def test_is_trend_question_flag_set(self) -> None:
        _, plan = self._plan("Is our test pass rate improving or declining over time?")
        assert plan.is_trend_question is True

    def test_getting_worse_sets_trend(self) -> None:
        _, plan = self._plan("Is stability getting worse?")
        assert plan.is_trend_question is True

    def test_over_time_sets_trend(self) -> None:
        _, plan = self._plan("How has the failure rate changed over time?")
        assert plan.is_trend_question is True

    def test_declining_keyword_sets_trend(self) -> None:
        _, plan = self._plan("Is the pass rate declining?")
        assert plan.is_trend_question is True

    def test_run_vs_run_comparison_not_trend(self) -> None:
        """'compare the last two runs' is a comparison but NOT a trend question."""
        _, plan = self._plan("Compare the last two runs")
        assert plan.is_trend_question is False

    def test_trend_plan_has_no_root_cause(self) -> None:
        _, plan = self._plan("Is our pass rate improving over time?")
        assert plan.include_root_cause is False
        assert plan.no_unsolicited_root_cause is True

    def test_trend_plan_has_no_recommendations(self) -> None:
        _, plan = self._plan("Is the failure rate declining?")
        assert plan.include_recommendations is False
        assert plan.no_unsolicited_recommendations is True

    def test_trend_plan_confidence_style_is_explicit(self) -> None:
        _, plan = self._plan("Is stability getting better or worse?")
        assert plan.confidence_style == "explicit"

    def test_trend_plan_answer_rules_reference_trend_analysis(self) -> None:
        _, plan = self._plan("Is our pass rate declining over time?")
        rules_text = " ".join(plan.answer_rules)
        assert "[TREND ANALYSIS]" in rules_text

    def test_trend_plan_answer_rules_forbid_placeholders(self) -> None:
        _, plan = self._plan("Is our pass rate declining over time?")
        rules_text = " ".join(plan.answer_rules)
        # Rules must forbid inventing values
        assert "Never invent" in rules_text or "NEVER invent" in rules_text or "Never" in rules_text


# ===========================================================================
# Integration: gather_comparison_context with trend=True
# ===========================================================================

class TestGatherComparisonContextTrend:
    """End-to-end: populate a temp DB and verify trend facts are injected."""

    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> str:
        from datetime import datetime, timezone

        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection
        from qara.models.failure import FailureInfo
        from qara.models.run import RunMetadata, TestRun
        from qara.models.test_case import TestCaseResult, TestStatus

        db = tmp_path / "trend_test.db"
        conn = get_connection(str(db))
        repo = RunRepository(conn)

        def _run(run_id: str, seq: int, tests: list) -> TestRun:
            meta = RunMetadata(
                run_id=run_id,
                report_format="allure",
                report_path=f"/tmp/{run_id}.html",
                project="TrendProject",
                started_at=datetime(2026, 3, seq, 10, 0, 0, tzinfo=timezone.utc),
            )
            return TestRun(metadata=meta, test_cases=tests)

        def _tc(name, status, *, idx=1):
            return TestCaseResult(
                test_id=f"{name}-{idx}",
                name=name,
                status=status,
            )

        # 5 runs with a clear declining pass-rate trend
        # Run 51: 4/5 pass (80%)
        repo.save_run(_run("run-051", 1, [
            _tc("tA", TestStatus.PASSED, idx=1),
            _tc("tB", TestStatus.PASSED, idx=1),
            _tc("tC", TestStatus.PASSED, idx=1),
            _tc("tD", TestStatus.PASSED, idx=1),
            _tc("tE", TestStatus.FAILED, idx=1),
        ]))
        # Run 52: 3/5 pass (60%)
        repo.save_run(_run("run-052", 2, [
            _tc("tA", TestStatus.PASSED, idx=2),
            _tc("tB", TestStatus.PASSED, idx=2),
            _tc("tC", TestStatus.PASSED, idx=2),
            _tc("tD", TestStatus.FAILED, idx=2),
            _tc("tE", TestStatus.FAILED, idx=2),
        ]))
        # Run 53: 2/5 pass (40%)
        repo.save_run(_run("run-053", 3, [
            _tc("tA", TestStatus.PASSED, idx=3),
            _tc("tB", TestStatus.PASSED, idx=3),
            _tc("tC", TestStatus.FAILED, idx=3),
            _tc("tD", TestStatus.FAILED, idx=3),
            _tc("tE", TestStatus.FAILED, idx=3),
        ]))

        conn.close()
        return str(db)

    def test_trend_facts_injected_when_is_trend_true(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=True
        )
        assert "[TREND ANALYSIS]" in facts

    def test_trend_facts_direction_declining(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=True
        )
        assert "declining" in facts

    def test_trend_facts_contain_real_percentages(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=True
        )
        # 4/5=80%, 3/5=60%, 2/5=40%
        assert "80%" in facts
        assert "60%" in facts
        assert "40%" in facts

    def test_trend_facts_no_placeholder_run_n(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=True
        )
        assert "Run #N" not in facts
        assert "PASS_RATE%" not in facts

    def test_no_trend_facts_when_is_trend_false(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=False
        )
        assert "[TREND ANALYSIS]" not in facts

    def test_trend_facts_contain_confidence(self, db_path: str) -> None:
        from qara.llm.routing import gather_comparison_context
        _, facts, _ = gather_comparison_context(
            project="TrendProject", db_path=db_path, is_trend=True
        )
        assert "confidence" in facts

    def test_insufficient_data_message_when_only_one_run(self, tmp_path: Path) -> None:
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection
        from qara.models.run import RunMetadata, TestRun
        from qara.models.test_case import TestCaseResult, TestStatus

        db = tmp_path / "one_run.db"
        conn = get_connection(str(db))
        repo = RunRepository(conn)
        meta = RunMetadata(
            run_id="solo-001",
            report_format="allure",
            report_path="/tmp/solo.html",
            project="Solo",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        repo.save_run(TestRun(
            metadata=meta,
            test_cases=[TestCaseResult(test_id="t1", name="t1", status=TestStatus.PASSED)],
        ))
        conn.close()

        from qara.llm.routing import gather_comparison_context
        ctx, facts, _ = gather_comparison_context(
            project="Solo", db_path=str(db), is_trend=True
        )
        # With only 1 run the function returns an early "Not enough runs" message
        assert "Not enough" in ctx or "Not enough" in facts
