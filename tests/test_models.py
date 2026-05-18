"""Tests for QALens canonical data models (Phase 1).

Covers: Attachment, ExtractionWarning, FailureInfo, StepResult,
        TestCaseResult, TestStatus, RunMetadata, TestRun,
        InsightCategory, Insight, FailureCluster, AnalysisSummary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from qalens.models.attachment import Attachment, AttachmentKind
from qalens.models.failure import FailureInfo
from qalens.models.insight import (
    AnalysisSummary,
    CategoryCounts,
    FailureCluster,
    Insight,
    InsightCategory,
    StatusCounts,
)
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import StepResult, TestCaseResult, TestStatus
from qalens.models.warnings import ExtractionWarning, WarningSeverity


# ---------------------------------------------------------------------------
# AttachmentKind helpers
# ---------------------------------------------------------------------------


class TestAttachmentKindFromMime:
    def test_image_png(self) -> None:
        assert AttachmentKind.from_mime("image/png") == AttachmentKind.SCREENSHOT

    def test_image_jpeg(self) -> None:
        assert AttachmentKind.from_mime("image/jpeg") == AttachmentKind.SCREENSHOT

    def test_video_mp4(self) -> None:
        assert AttachmentKind.from_mime("video/mp4") == AttachmentKind.VIDEO

    def test_application_json(self) -> None:
        assert AttachmentKind.from_mime("application/json") == AttachmentKind.JSON

    def test_text_plain(self) -> None:
        assert AttachmentKind.from_mime("text/plain") == AttachmentKind.TEXT

    def test_text_html(self) -> None:
        assert AttachmentKind.from_mime("text/html") == AttachmentKind.HTML

    def test_unknown_mime(self) -> None:
        assert AttachmentKind.from_mime("application/octet-stream") == AttachmentKind.UNKNOWN


class TestAttachmentKindFromPath:
    def test_png(self) -> None:
        assert AttachmentKind.from_path("screenshot.png") == AttachmentKind.SCREENSHOT

    def test_jpg(self) -> None:
        assert AttachmentKind.from_path("/path/to/image.JPG") == AttachmentKind.SCREENSHOT

    def test_log(self) -> None:
        assert AttachmentKind.from_path("output.log") == AttachmentKind.LOG

    def test_json(self) -> None:
        assert AttachmentKind.from_path("data.json") == AttachmentKind.JSON

    def test_har(self) -> None:
        assert AttachmentKind.from_path("network.har") == AttachmentKind.HAR

    def test_unknown_extension(self) -> None:
        assert AttachmentKind.from_path("mystery.xyz") == AttachmentKind.UNKNOWN

    def test_path_object(self) -> None:
        assert AttachmentKind.from_path(Path("video.mp4")) == AttachmentKind.VIDEO


# ---------------------------------------------------------------------------
# Attachment model
# ---------------------------------------------------------------------------


class TestAttachment:
    def test_minimal_construction(self) -> None:
        a = Attachment(name="screenshot", path="attachments/a.png")
        assert a.name == "screenshot"
        assert a.path == "attachments/a.png"
        assert a.kind == AttachmentKind.UNKNOWN
        assert a.resolved_path is None
        assert a.size_bytes is None

    def test_full_construction(self) -> None:
        a = Attachment(
            name="failure screenshot",
            kind=AttachmentKind.SCREENSHOT,
            path="attachments/f1.png",
            resolved_path=Path("/reports/attachments/f1.png"),
            mime_type="image/png",
            size_bytes=102400,
            source="allure",
        )
        assert a.kind == AttachmentKind.SCREENSHOT
        assert a.size_bytes == 102400
        assert a.source == "allure"

    def test_frozen(self) -> None:
        a = Attachment(name="x", path="x.png")
        with pytest.raises(ValidationError):
            a.name = "changed"  # type: ignore[misc]

    def test_size_bytes_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Attachment(name="x", path="x.png", size_bytes=-1)


# ---------------------------------------------------------------------------
# ExtractionWarning model
# ---------------------------------------------------------------------------


class TestExtractionWarning:
    def test_minimal(self) -> None:
        w = ExtractionWarning(field="FailureInfo.stack_trace", reason="field absent")
        assert w.severity == WarningSeverity.LOW
        assert w.test_name is None

    def test_full(self) -> None:
        w = ExtractionWarning(
            field="TestCaseResult.duration_ms",
            test_name="LoginTest#testLogin",
            reason="time.stop absent",
            severity=WarningSeverity.MEDIUM,
            raw_value="null",
        )
        assert w.severity == WarningSeverity.MEDIUM
        assert "medium" in str(w).lower()

    def test_str_representation_includes_field(self) -> None:
        w = ExtractionWarning(field="TestRun.metadata.project", reason="not found")
        s = str(w)
        assert "TestRun.metadata.project" in s

    def test_str_representation_includes_test_name(self) -> None:
        w = ExtractionWarning(
            field="FailureInfo.message",
            test_name="SomeTest#doThing",
            reason="missing",
        )
        assert "SomeTest#doThing" in str(w)

    def test_frozen(self) -> None:
        w = ExtractionWarning(field="f", reason="r")
        with pytest.raises(ValidationError):
            w.reason = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FailureInfo model
# ---------------------------------------------------------------------------


class TestFailureInfo:
    def test_empty_construction(self) -> None:
        f = FailureInfo()
        assert f.error_type is None
        assert f.message is None
        assert not f.has_stack_trace()
        assert not f.has_signature()

    def test_has_stack_trace(self) -> None:
        f = FailureInfo(stack_trace="java.lang.NullPointerException\n\tat Foo.bar(Foo.java:10)")
        assert f.has_stack_trace()

    def test_has_stack_trace_whitespace_only(self) -> None:
        f = FailureInfo(stack_trace="   ")
        assert not f.has_stack_trace()

    def test_has_signature_when_set(self) -> None:
        f = FailureInfo(failure_signature="abc123")
        assert f.has_signature()

    def test_summary_line_both_fields(self) -> None:
        f = FailureInfo(
            error_type="java.lang.AssertionError",
            message="expected: <200> but was: <404>",
        )
        assert "AssertionError" in f.summary_line()
        assert "expected" in f.summary_line()

    def test_summary_line_error_only(self) -> None:
        f = FailureInfo(error_type="RuntimeException")
        assert "RuntimeException" in f.summary_line()

    def test_summary_line_neither(self) -> None:
        f = FailureInfo()
        assert f.summary_line() == "(no failure detail)"

    def test_summary_line_truncation(self) -> None:
        f = FailureInfo(message="A" * 200)
        result = f.summary_line(max_length=50)
        assert len(result) <= 51  # 50 chars + ellipsis character

    def test_mutable(self) -> None:
        """FailureInfo must be mutable because the signature engine writes to it."""
        f = FailureInfo(message="original")
        f.failure_signature = "abc"
        assert f.failure_signature == "abc"


# ---------------------------------------------------------------------------
# TestStatus enum
# ---------------------------------------------------------------------------


class TestTestStatus:
    def test_is_failing_failed(self) -> None:
        assert TestStatus.FAILED.is_failing is True

    def test_is_failing_broken(self) -> None:
        assert TestStatus.BROKEN.is_failing is True

    def test_is_failing_passed(self) -> None:
        assert TestStatus.PASSED.is_failing is False

    def test_is_failing_skipped(self) -> None:
        assert TestStatus.SKIPPED.is_failing is False

    def test_from_string_allure_passed(self) -> None:
        assert TestStatus.from_string("passed") == TestStatus.PASSED

    def test_from_string_allure_failed(self) -> None:
        assert TestStatus.from_string("failed") == TestStatus.FAILED

    def test_from_string_allure_broken(self) -> None:
        assert TestStatus.from_string("broken") == TestStatus.BROKEN

    def test_from_string_extent_pass(self) -> None:
        assert TestStatus.from_string("pass") == TestStatus.PASSED

    def test_from_string_extent_fail(self) -> None:
        assert TestStatus.from_string("fail") == TestStatus.FAILED

    def test_from_string_extent_skip(self) -> None:
        assert TestStatus.from_string("skip") == TestStatus.SKIPPED

    def test_from_string_case_insensitive(self) -> None:
        assert TestStatus.from_string("PASSED") == TestStatus.PASSED
        assert TestStatus.from_string("Failed") == TestStatus.FAILED

    def test_from_string_unknown(self) -> None:
        assert TestStatus.from_string("nonexistent") == TestStatus.UNKNOWN


# ---------------------------------------------------------------------------
# StepResult model
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_minimal(self) -> None:
        step = StepResult(name="Click login button")
        assert step.name == "Click login button"
        assert step.status == TestStatus.UNKNOWN
        assert step.depth == 0
        assert step.attachments == []
        assert step.failure is None

    def test_with_failure(self) -> None:
        failure = FailureInfo(message="Not found")
        step = StepResult(name="Assert page title", status=TestStatus.FAILED, failure=failure)
        assert step.failure is not None
        assert step.failure.message == "Not found"

    def test_auto_generated_id(self) -> None:
        s1 = StepResult(name="step A")
        s2 = StepResult(name="step B")
        assert s1.step_id != s2.step_id

    def test_depth_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepResult(name="bad", depth=-1)


# ---------------------------------------------------------------------------
# TestCaseResult model
# ---------------------------------------------------------------------------


class TestTestCaseResult:
    def _make_passed(self) -> TestCaseResult:
        return TestCaseResult(
            test_id="com.example.LoginTest#testLogin",
            name="Login test",
            status=TestStatus.PASSED,
        )

    def _make_failed_with_retry(self) -> TestCaseResult:
        return TestCaseResult(
            test_id="com.example.FlakeyTest#testFlakey",
            name="Flakey test",
            status=TestStatus.PASSED,
            retry_count=2,
        )

    def _make_failed(self) -> TestCaseResult:
        return TestCaseResult(
            test_id="com.example.BrokenTest#testBroken",
            name="Broken test",
            status=TestStatus.FAILED,
            failure=FailureInfo(error_type="AssertionError", message="wrong value"),
        )

    def test_is_failed_false_for_passed(self) -> None:
        assert self._make_passed().is_failed is False

    def test_is_failed_true_for_failed(self) -> None:
        assert self._make_failed().is_failed is True

    def test_was_retried(self) -> None:
        assert self._make_failed_with_retry().was_retried is True
        assert self._make_passed().was_retried is False

    def test_passed_on_retry(self) -> None:
        t = self._make_failed_with_retry()
        assert t.passed_on_retry is True

    def test_not_passed_on_retry_when_failed(self) -> None:
        t = self._make_failed()
        assert t.passed_on_retry is False

    def test_flaky_score_bounds(self) -> None:
        t = self._make_passed()
        t.flaky_score = 0.5
        assert t.flaky_score == 0.5

    def test_flaky_score_out_of_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TestCaseResult(
                test_id="x",
                name="x",
                status=TestStatus.PASSED,
                flaky_score=1.5,
            )

    def test_default_collections_are_empty(self) -> None:
        t = self._make_passed()
        assert t.tags == []
        assert t.parameters == {}
        assert t.links == []
        assert t.steps == []
        assert t.attachments == []

    def test_mutable(self) -> None:
        t = self._make_passed()
        t.flaky_score = 0.7
        assert t.flaky_score == 0.7


# ---------------------------------------------------------------------------
# RunMetadata and TestRun models
# ---------------------------------------------------------------------------


def _make_run() -> TestRun:
    meta = RunMetadata(
        report_format="allure",
        report_path="/reports/allure-report",
        project="TestProject",
        environment="staging",
        started_at=datetime(2026, 3, 6, 6, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 3, 6, 7, 0, 0, tzinfo=timezone.utc),
        total_duration_ms=3600000,
    )
    tests = [
        TestCaseResult(test_id="t1", name="T1", status=TestStatus.PASSED),
        TestCaseResult(test_id="t2", name="T2", status=TestStatus.PASSED),
        TestCaseResult(test_id="t3", name="T3", status=TestStatus.FAILED),
        TestCaseResult(test_id="t4", name="T4", status=TestStatus.SKIPPED),
        TestCaseResult(test_id="t5", name="T5", status=TestStatus.BROKEN),
    ]
    return TestRun(metadata=meta, test_cases=tests)


class TestRunMetadata:
    def test_auto_run_id(self) -> None:
        m1 = RunMetadata(report_format="allure", report_path="/x")
        m2 = RunMetadata(report_format="allure", report_path="/x")
        assert m1.run_id != m2.run_id

    def test_custom_fields(self) -> None:
        m = RunMetadata(
            report_format="extent",
            report_path="/r",
            custom_fields={"executor": "jenkins"},
        )
        assert m.custom_fields["executor"] == "jenkins"


class TestTestRun:
    def test_total_count(self) -> None:
        run = _make_run()
        assert run.total_count == 5

    def test_passed_count(self) -> None:
        run = _make_run()
        assert run.passed_count == 2

    def test_failed_count_includes_broken(self) -> None:
        run = _make_run()
        assert run.failed_count == 2  # FAILED + BROKEN

    def test_skipped_count(self) -> None:
        run = _make_run()
        assert run.skipped_count == 1

    def test_pass_rate(self) -> None:
        run = _make_run()
        assert run.pass_rate == pytest.approx(2 / 5)

    def test_pass_rate_empty_run(self) -> None:
        run = TestRun(
            metadata=RunMetadata(report_format="allure", report_path="/r"),
        )
        assert run.pass_rate == 0.0

    def test_failed_tests(self) -> None:
        run = _make_run()
        failed = run.failed_tests()
        assert len(failed) == 2
        assert all(t.status.is_failing for t in failed)

    def test_tests_by_status(self) -> None:
        run = _make_run()
        skipped = run.tests_by_status(TestStatus.SKIPPED)
        assert len(skipped) == 1
        assert skipped[0].test_id == "t4"

    def test_has_warnings_false(self) -> None:
        run = _make_run()
        assert run.has_warnings() is False

    def test_has_warnings_true(self) -> None:
        run = _make_run()
        run.warnings.append(
            ExtractionWarning(field="FailureInfo.message", reason="missing")
        )
        assert run.has_warnings() is True

    def test_serialization_round_trip(self) -> None:
        run = _make_run()
        data = run.model_dump()
        restored = TestRun.model_validate(data)
        assert restored.total_count == run.total_count
        assert restored.metadata.run_id == run.metadata.run_id


# ---------------------------------------------------------------------------
# InsightCategory and Insight models
# ---------------------------------------------------------------------------


class TestInsightCategory:
    def test_display_name_flaky(self) -> None:
        assert InsightCategory.LIKELY_FLAKY.display_name == "Likely Flaky"

    def test_display_name_unknown(self) -> None:
        assert InsightCategory.UNKNOWN.display_name == "Unknown"

    def test_all_categories_have_display_name(self) -> None:
        for cat in InsightCategory:
            dn = cat.display_name
            assert isinstance(dn, str) and len(dn) > 0


class TestInsight:
    def _base(self) -> Insight:
        return Insight(
            test_id="t1",
            test_name="LoginTest#testLogin",
            category=InsightCategory.LIKELY_FLAKY,
            confidence=0.85,
            explanation="Passed on retry; timeout exception pattern.",
            evidence=["passed on retry #2", "TimeoutException in stack trace"],
        )

    def test_construction(self) -> None:
        i = self._base()
        assert i.category == InsightCategory.LIKELY_FLAKY
        assert i.confidence == 0.85

    def test_confidence_label_high(self) -> None:
        assert self._base().confidence_label == "high"

    def test_confidence_label_medium(self) -> None:
        i = Insight(
            test_id="t1",
            test_name="T",
            category=InsightCategory.UNKNOWN,
            confidence=0.6,
            explanation="medium",
            evidence=["a"],
        )
        assert i.confidence_label == "medium"

    def test_confidence_label_low(self) -> None:
        i = Insight(
            test_id="t1",
            test_name="T",
            category=InsightCategory.UNKNOWN,
            confidence=0.4,
            explanation="low",
            evidence=["a"],
        )
        assert i.confidence_label == "low"

    def test_confidence_label_very_low(self) -> None:
        i = Insight(
            test_id="t1",
            test_name="T",
            category=InsightCategory.UNKNOWN,
            confidence=0.2,
            explanation="low",
            evidence=[],
        )
        assert i.confidence_label == "very low"

    def test_confidence_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            Insight(
                test_id="t1",
                test_name="T",
                category=InsightCategory.UNKNOWN,
                confidence=1.1,
                explanation="x",
                evidence=[],
            )

    def test_auto_id_unique(self) -> None:
        i1 = self._base()
        i2 = self._base()
        assert i1.insight_id != i2.insight_id

    def test_frozen(self) -> None:
        i = self._base()
        with pytest.raises(ValidationError):
            i.confidence = 0.5  # type: ignore[misc]

    def test_serialization(self) -> None:
        i = self._base()
        data = i.model_dump()
        assert data["category"] == "likely_flaky"
        assert data["confidence"] == 0.85


# ---------------------------------------------------------------------------
# FailureCluster model
# ---------------------------------------------------------------------------


class TestFailureCluster:
    def test_size_property(self) -> None:
        c = FailureCluster(
            label="NullPointerException in CheckoutService",
            member_test_ids=["t1", "t2", "t3"],
        )
        assert c.size == 3

    def test_empty_cluster(self) -> None:
        c = FailureCluster(label="empty")
        assert c.size == 0

    def test_defaults(self) -> None:
        c = FailureCluster(label="x")
        assert c.category == InsightCategory.UNKNOWN
        assert c.confidence == 0.0


# ---------------------------------------------------------------------------
# StatusCounts and CategoryCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_pass_rate(self) -> None:
        s = StatusCounts(total=10, passed=7, failed=3)
        assert s.pass_rate == pytest.approx(0.7)

    def test_pass_rate_pct(self) -> None:
        s = StatusCounts(total=10, passed=7, failed=3)
        assert s.pass_rate_pct == 70.0

    def test_pass_rate_empty(self) -> None:
        s = StatusCounts(total=0)
        assert s.pass_rate == 0.0


class TestCategoryCounts:
    def test_for_category(self) -> None:
        c = CategoryCounts(likely_flaky=5, likely_product_defect=3)
        assert c.for_category(InsightCategory.LIKELY_FLAKY) == 5
        assert c.for_category(InsightCategory.LIKELY_PRODUCT_DEFECT) == 3
        assert c.for_category(InsightCategory.UNKNOWN) == 0


# ---------------------------------------------------------------------------
# AnalysisSummary model
# ---------------------------------------------------------------------------


class TestAnalysisSummary:
    def _make(self) -> AnalysisSummary:
        insights = [
            Insight(
                test_id=f"t{i}",
                test_name=f"Test {i}",
                category=InsightCategory.LIKELY_FLAKY,
                confidence=0.8,
                explanation="flaky",
                evidence=["timeout"],
            )
            for i in range(3)
        ]
        clusters = [
            FailureCluster(
                label=f"Cluster {i}",
                member_test_ids=[f"t{j}" for j in range(i + 1)],
            )
            for i in range(4)
        ]
        return AnalysisSummary(
            run_id="run-1",
            report_format="allure",
            report_path="/reports/allure",
            status_counts=StatusCounts(total=10, passed=7, failed=3),
            category_counts=CategoryCounts(likely_flaky=3),
            insights=insights,
            clusters=clusters,
        )

    def test_insights_by_category(self) -> None:
        s = self._make()
        flaky = s.insights_by_category(InsightCategory.LIKELY_FLAKY)
        assert len(flaky) == 3

    def test_insights_by_category_empty(self) -> None:
        s = self._make()
        defects = s.insights_by_category(InsightCategory.LIKELY_PRODUCT_DEFECT)
        assert defects == []

    def test_top_clusters_limited(self) -> None:
        s = self._make()
        top = s.top_clusters(n=2)
        assert len(top) == 2

    def test_top_clusters_ordered_by_size(self) -> None:
        s = self._make()
        top = s.top_clusters()
        sizes = [c.size for c in top]
        assert sizes == sorted(sizes, reverse=True)

    def test_serialization_round_trip(self) -> None:
        s = self._make()
        data = s.model_dump()
        restored = AnalysisSummary.model_validate(data)
        assert restored.run_id == s.run_id
        assert len(restored.insights) == 3
