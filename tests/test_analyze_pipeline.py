"""Tests for the Phase-8 analysis pipeline: QARAClient.analyze_report / summarize_report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qara.api.library import QARAClient
from qara.cli import app
from qara.models.failure import FailureInfo
from qara.models.insight import AnalysisSummary, InsightCategory
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JAVA_TRACE = """\
org.openqa.selenium.NoSuchElementException: Unable to locate element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:342)
    at com.example.LoginTest.testLogin(LoginTest.java:87)
"""

_ASSERTION_TRACE = """\
java.lang.AssertionError: Expected 200 but was 404
    at org.junit.Assert.fail(Assert.java:88)
    at com.example.ApiTest.testGetUser(ApiTest.java:55)
"""

_NETWORK_TRACE = """\
java.net.ConnectException: Connection refused (Connection refused)
    at java.net.PlainSocketImpl.socketConnect(Native Method)
    at com.example.ServiceTest.testConnect(ServiceTest.java:22)
"""

_TIMEOUT_TRACE = """\
org.openqa.selenium.TimeoutException: Expected condition failed
    at org.openqa.selenium.support.ui.WebDriverWait.timeoutException(WebDriverWait.java:95)
    at com.example.CartTest.testCheckout(CartTest.java:43)
"""


def _meta(run_id: str = "run-001") -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/{run_id}.html",
        project="PipelineTest",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _tc(
    name: str,
    status: TestStatus = TestStatus.FAILED,
    *,
    test_id: str | None = None,
    error_type: str | None = None,
    message: str | None = None,
    stack_trace: str | None = None,
    retry_count: int = 0,
) -> TestCaseResult:
    failure = None
    if status.is_failing:
        failure = FailureInfo(
            error_type=error_type,
            message=message or "Something went wrong",
            stack_trace=stack_trace,
        )
    return TestCaseResult(
        test_id=test_id or f"tc-{name.lower().replace(' ', '-')}",
        name=name,
        status=status,
        failure=failure,
        retry_count=retry_count,
    )


def _run(*test_cases: TestCaseResult, run_id: str = "run-001") -> TestRun:
    return TestRun(metadata=_meta(run_id), test_cases=list(test_cases))


# ---------------------------------------------------------------------------
# analyze_report — basic contract
# ---------------------------------------------------------------------------


class TestAnalyzeReportBasic:
    def test_returns_analysis_summary(self) -> None:
        run = _run(_tc("testFoo", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert isinstance(result, AnalysisSummary)

    def test_run_id_propagated(self) -> None:
        run = _run(_tc("testFoo", TestStatus.FAILED, stack_trace=_JAVA_TRACE), run_id="my-run")
        result = QARAClient().analyze_report(run)
        assert result.run_id == "my-run"

    def test_report_format_propagated(self) -> None:
        run = _run(_tc("testFoo", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert result.report_format == "allure"

    def test_engine_version_set(self) -> None:
        from qara.version import __version__

        run = _run(_tc("testFoo", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert result.analysis_engine_version == __version__

    def test_empty_run_produces_empty_insights(self) -> None:
        run = _run()
        result = QARAClient().analyze_report(run)
        assert result.insights == []
        assert result.clusters == []

    def test_all_passing_run_has_no_insights(self) -> None:
        run = _run(
            _tc("t1", TestStatus.PASSED),
            _tc("t2", TestStatus.PASSED),
            _tc("t3", TestStatus.SKIPPED),
        )
        result = QARAClient().analyze_report(run)
        assert result.insights == []

    def test_extraction_warning_count_matches_run(self) -> None:
        from qara.models.warnings import ExtractionWarning

        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        run.warnings.append(
            ExtractionWarning(field="FailureInfo.stack_trace", reason="truncated")
        )
        result = QARAClient().analyze_report(run)
        assert result.extraction_warning_count == 1


# ---------------------------------------------------------------------------
# analyze_report — StatusCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_total_count(self) -> None:
        run = _run(
            _tc("t1", TestStatus.PASSED),
            _tc("t2", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
            _tc("t3", TestStatus.SKIPPED),
        )
        result = QARAClient().analyze_report(run)
        assert result.status_counts.total == 3

    def test_passed_count(self) -> None:
        run = _run(
            _tc("t1", TestStatus.PASSED),
            _tc("t2", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
        )
        assert QARAClient().analyze_report(run).status_counts.passed == 1

    def test_failed_count(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.BROKEN, stack_trace=_JAVA_TRACE),
            _tc("t3", TestStatus.PASSED),
        )
        assert QARAClient().analyze_report(run).status_counts.failed == 2

    def test_skipped_count(self) -> None:
        run = _run(_tc("t1", TestStatus.SKIPPED), _tc("t2", TestStatus.SKIPPED))
        assert QARAClient().analyze_report(run).status_counts.skipped == 2

    def test_pass_rate_all_pass(self) -> None:
        run = _run(_tc("t1", TestStatus.PASSED), _tc("t2", TestStatus.PASSED))
        assert QARAClient().analyze_report(run).status_counts.pass_rate == 1.0

    def test_pass_rate_empty_run(self) -> None:
        run = _run()
        assert QARAClient().analyze_report(run).status_counts.pass_rate == 0.0


# ---------------------------------------------------------------------------
# analyze_report — Insight generation
# ---------------------------------------------------------------------------


class TestInsightGeneration:
    def test_one_insight_per_failing_test(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.FAILED, stack_trace=_ASSERTION_TRACE),
            _tc("t3", TestStatus.PASSED),
        )
        result = QARAClient().analyze_report(run)
        assert len(result.insights) == 2

    def test_broken_status_produces_insight(self) -> None:
        run = _run(_tc("t1", TestStatus.BROKEN, stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert len(result.insights) == 1

    def test_insight_test_id_matches_test_case(self) -> None:
        run = _run(_tc("myTest", TestStatus.FAILED, test_id="tc-123", stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert result.insights[0].test_id == "tc-123"

    def test_insight_test_name_matches(self) -> None:
        run = _run(_tc("loginTest", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        result = QARAClient().analyze_report(run)
        assert result.insights[0].test_name == "loginTest"

    def test_confidence_is_between_zero_and_one(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        ins = QARAClient().analyze_report(run).insights[0]
        assert 0.0 <= ins.confidence <= 1.0

    def test_explanation_is_non_empty(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        ins = QARAClient().analyze_report(run).insights[0]
        assert ins.explanation.strip()

    def test_evidence_contains_error_type(self) -> None:
        run = _run(
            _tc(
                "t",
                TestStatus.FAILED,
                error_type="java.lang.AssertionError",
                stack_trace=_ASSERTION_TRACE,
            )
        )
        ins = QARAClient().analyze_report(run).insights[0]
        evidence_text = " ".join(ins.evidence)
        assert "AssertionError" in evidence_text

    def test_evidence_contains_signature(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE))
        ins = QARAClient().analyze_report(run).insights[0]
        assert any("signature" in e for e in ins.evidence)

    def test_no_stack_trace_reduces_confidence(self) -> None:
        run_with = _run(_tc("t", TestStatus.FAILED, stack_trace=_ASSERTION_TRACE,
                            error_type="java.lang.AssertionError"))
        run_without = _run(_tc("t", TestStatus.FAILED, error_type="java.lang.AssertionError"))
        conf_with = QARAClient().analyze_report(run_with).insights[0].confidence
        conf_without = QARAClient().analyze_report(run_without).insights[0].confidence
        assert conf_with > conf_without

    def test_retry_count_in_evidence(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE, retry_count=2))
        ins = QARAClient().analyze_report(run).insights[0]
        assert any("2" in e and "retr" in e for e in ins.evidence)

    def test_passed_on_retry_in_evidence(self) -> None:
        # `passed_on_retry` is a computed property (status==PASSED && retry_count>0).
        # A failing test with retries shows the retry count in evidence.
        run = _run(
            _tc("t", TestStatus.FAILED, stack_trace=_JAVA_TRACE, retry_count=3)
        )
        ins = QARAClient().analyze_report(run).insights[0]
        assert any("retri" in e.lower() for e in ins.evidence)


# ---------------------------------------------------------------------------
# analyze_report — InsightCategory mapping
# ---------------------------------------------------------------------------


class TestInsightCategoryMapping:
    def test_no_such_element_maps_to_test_script_issue(self) -> None:
        run = _run(
            _tc(
                "t",
                TestStatus.FAILED,
                error_type="org.openqa.selenium.NoSuchElementException",
                stack_trace=_JAVA_TRACE,
            )
        )
        assert (
            QARAClient().analyze_report(run).insights[0].category
            == InsightCategory.LIKELY_TEST_SCRIPT_ISSUE
        )

    def test_assertion_maps_to_product_defect(self) -> None:
        run = _run(
            _tc(
                "t",
                TestStatus.FAILED,
                error_type="java.lang.AssertionError",
                stack_trace=_ASSERTION_TRACE,
            )
        )
        assert (
            QARAClient().analyze_report(run).insights[0].category
            == InsightCategory.LIKELY_PRODUCT_DEFECT
        )

    def test_timeout_maps_to_likely_flaky(self) -> None:
        run = _run(
            _tc(
                "t",
                TestStatus.FAILED,
                error_type="org.openqa.selenium.TimeoutException",
                stack_trace=_TIMEOUT_TRACE,
            )
        )
        assert (
            QARAClient().analyze_report(run).insights[0].category
            == InsightCategory.LIKELY_FLAKY
        )

    def test_connect_exception_maps_to_environment_issue(self) -> None:
        run = _run(
            _tc(
                "t",
                TestStatus.FAILED,
                error_type="java.net.ConnectException",
                stack_trace=_NETWORK_TRACE,
            )
        )
        assert (
            QARAClient().analyze_report(run).insights[0].category
            == InsightCategory.LIKELY_ENVIRONMENT_ISSUE
        )

    def test_unknown_error_type_maps_to_unknown(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED))
        assert (
            QARAClient().analyze_report(run).insights[0].category
            == InsightCategory.UNKNOWN
        )


# ---------------------------------------------------------------------------
# analyze_report — related_tests (shared signature cross-linking)
# ---------------------------------------------------------------------------


class TestRelatedTests:
    def test_related_tests_populated_when_same_signature(self) -> None:
        # Two tests with identical stack traces → same signature → related
        run = _run(
            _tc("t1", TestStatus.FAILED, test_id="tc-001",
                error_type="org.openqa.selenium.NoSuchElementException",
                stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.FAILED, test_id="tc-002",
                error_type="org.openqa.selenium.NoSuchElementException",
                stack_trace=_JAVA_TRACE),
        )
        result = QARAClient().analyze_report(run)
        related_for_t1 = result.insights[0].related_tests
        related_for_t2 = result.insights[1].related_tests
        # Each test points to the OTHER, not itself
        assert "tc-002" in related_for_t1
        assert "tc-001" not in related_for_t1
        assert "tc-001" in related_for_t2

    def test_related_tests_empty_for_unique_failures(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.FAILED, stack_trace=_ASSERTION_TRACE),
        )
        result = QARAClient().analyze_report(run)
        # Different traces → different signatures → no related tests
        assert result.insights[0].related_tests == []
        assert result.insights[1].related_tests == []


# ---------------------------------------------------------------------------
# analyze_report — CategoryCounts
# ---------------------------------------------------------------------------


class TestCategoryCountsIntegration:
    def test_category_counts_match_insights(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED,
                error_type="java.lang.AssertionError", stack_trace=_ASSERTION_TRACE),
            _tc("t2", TestStatus.FAILED,
                error_type="java.lang.AssertionError", stack_trace=_ASSERTION_TRACE),
            _tc("t3", TestStatus.FAILED,
                error_type="org.openqa.selenium.TimeoutException", stack_trace=_TIMEOUT_TRACE),
        )
        result = QARAClient().analyze_report(run)
        cc = result.category_counts
        total_counted = (
            cc.likely_product_defect
            + cc.likely_flaky
            + cc.likely_environment_issue
            + cc.likely_test_script_issue
            + cc.likely_test_data_issue
            + cc.unknown
        )
        assert total_counted == len(result.insights)

    def test_category_counts_all_zero_for_passing_run(self) -> None:
        run = _run(_tc("t", TestStatus.PASSED))
        cc = QARAClient().analyze_report(run).category_counts
        assert cc.likely_product_defect == 0
        assert cc.likely_flaky == 0
        assert cc.likely_environment_issue == 0


# ---------------------------------------------------------------------------
# analyze_report — clusters
# ---------------------------------------------------------------------------


class TestClustersIntegration:
    def test_clusters_populated_for_shared_signature(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED, test_id="tc-1",
                error_type="org.openqa.selenium.NoSuchElementException",
                stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.FAILED, test_id="tc-2",
                error_type="org.openqa.selenium.NoSuchElementException",
                stack_trace=_JAVA_TRACE),
        )
        result = QARAClient().analyze_report(run)
        assert len(result.clusters) >= 1
        assert result.clusters[0].size == 2

    def test_clusters_empty_for_no_failures(self) -> None:
        run = _run(_tc("t", TestStatus.PASSED))
        assert QARAClient().analyze_report(run).clusters == []


# ---------------------------------------------------------------------------
# analyze_report — recommended actions
# ---------------------------------------------------------------------------


class TestRecommendedActions:
    def test_recommended_actions_non_empty_for_failures(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED, stack_trace=_ASSERTION_TRACE,
                       error_type="java.lang.AssertionError"))
        result = QARAClient().analyze_report(run)
        assert len(result.recommended_actions) >= 1

    def test_no_recommended_actions_for_passing_run(self) -> None:
        run = _run(_tc("t", TestStatus.PASSED))
        result = QARAClient().analyze_report(run)
        assert result.recommended_actions == []

    def test_recommended_actions_mention_product_defect(self) -> None:
        run = _run(_tc("t", TestStatus.FAILED,
                       error_type="java.lang.AssertionError", stack_trace=_ASSERTION_TRACE))
        result = QARAClient().analyze_report(run)
        combined = " ".join(result.recommended_actions).lower()
        assert "defect" in combined or "reproducible" in combined


# ---------------------------------------------------------------------------
# analyze_report — flaky_test_ids
# ---------------------------------------------------------------------------


class TestFlakyTestIds:
    def test_flaky_test_id_populated_for_timeout(self) -> None:
        run = _run(
            _tc("t", TestStatus.FAILED,
                test_id="tc-flaky",
                error_type="org.openqa.selenium.TimeoutException",
                stack_trace=_TIMEOUT_TRACE)
        )
        result = QARAClient().analyze_report(run)
        assert "tc-flaky" in result.flaky_test_ids

    def test_non_flaky_test_not_in_flaky_ids(self) -> None:
        run = _run(
            _tc("t", TestStatus.FAILED,
                test_id="tc-defect",
                error_type="java.lang.AssertionError",
                stack_trace=_ASSERTION_TRACE)
        )
        result = QARAClient().analyze_report(run)
        assert "tc-defect" not in result.flaky_test_ids


# ---------------------------------------------------------------------------
# analyze_report — idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_calling_twice_gives_same_result(self) -> None:
        run = _run(
            _tc("t1", TestStatus.FAILED, stack_trace=_JAVA_TRACE),
            _tc("t2", TestStatus.PASSED),
        )
        client = QARAClient()
        r1 = client.analyze_report(run)
        r2 = client.analyze_report(run)
        assert r1.status_counts == r2.status_counts
        assert len(r1.insights) == len(r2.insights)
        assert r1.insights[0].category == r2.insights[0].category


# ---------------------------------------------------------------------------
# summarize_report — format outputs
# ---------------------------------------------------------------------------


class TestSummarizeReport:
    @pytest.fixture()
    def analysis(self) -> AnalysisSummary:
        run = _run(
            _tc("t1", TestStatus.FAILED,
                error_type="java.lang.AssertionError", stack_trace=_ASSERTION_TRACE),
            _tc("t2", TestStatus.PASSED),
        )
        return QARAClient().analyze_report(run)

    def test_json_format_is_valid_json(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="json")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_json_contains_run_id(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="json")
        parsed = json.loads(content)
        assert parsed["run_id"] == "run-001"

    def test_json_contains_insights(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="json")
        parsed = json.loads(content)
        assert "insights" in parsed
        assert isinstance(parsed["insights"], list)

    def test_markdown_format_is_string(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="markdown")
        assert isinstance(content, str)
        assert len(content) > 50

    def test_markdown_contains_heading(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="markdown")
        assert "# QARA Analysis Summary" in content

    def test_markdown_contains_status_section(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="markdown")
        assert "Status Overview" in content

    def test_markdown_contains_run_id(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="markdown")
        assert "run-001" in content

    def test_console_format_is_non_empty(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="console")
        assert isinstance(content, str)
        assert len(content) > 30

    def test_console_contains_status_info(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis, fmt="console")
        assert "Status" in content

    def test_default_format_is_console(self, analysis: AnalysisSummary) -> None:
        content = QARAClient().summarize_report(analysis)
        assert isinstance(content, str)
        assert len(content) > 0

    def test_all_passing_run_markdown(self) -> None:
        run = _run(_tc("t", TestStatus.PASSED))
        analysis = QARAClient().analyze_report(run)
        content = QARAClient().summarize_report(analysis, fmt="markdown")
        assert "# QARA Analysis Summary" in content

    def test_all_passing_run_json(self) -> None:
        run = _run(_tc("t", TestStatus.PASSED))
        analysis = QARAClient().analyze_report(run)
        content = QARAClient().summarize_report(analysis, fmt="json")
        parsed = json.loads(content)
        assert parsed["insights"] == []


# ---------------------------------------------------------------------------
# qara summarize CLI command
# ---------------------------------------------------------------------------


class TestSummarizeCLI:
    @pytest.fixture(scope="class")
    def allure_dir(self) -> Path:
        return Path(__file__).parent / "fixtures" / "allure_sample"

    def test_summarize_with_allure_report(self, allure_dir: Path) -> None:
        result = runner.invoke(
            app, ["summarize", str(allure_dir), "--format", "json"]
        )
        assert result.exit_code == 0
        # output should be valid JSON
        parsed = json.loads(result.output)
        assert "run_id" in parsed

    def test_summarize_console_format(self, allure_dir: Path) -> None:
        result = runner.invoke(app, ["summarize", str(allure_dir)])
        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_summarize_markdown_format(self, allure_dir: Path) -> None:
        result = runner.invoke(
            app, ["summarize", str(allure_dir), "--format", "markdown"]
        )
        assert result.exit_code == 0
        assert "# QARA Analysis Summary" in result.output

    def test_summarize_writes_to_file(self, allure_dir: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "summary.json"
        result = runner.invoke(
            app,
            ["summarize", str(allure_dir), "--format", "json", "--out", str(out_file)],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        parsed = json.loads(out_file.read_text())
        assert "run_id" in parsed

    def test_summarize_invalid_format_exits_nonzero(self, allure_dir: Path) -> None:
        result = runner.invoke(
            app, ["summarize", str(allure_dir), "--format", "xml"]
        )
        assert result.exit_code != 0
