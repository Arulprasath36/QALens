"""Tests for qalens.analyzers.clustering."""

from __future__ import annotations

import pytest

from qalens.analyzers.clustering import (
    _build_label,
    _cluster_confidence,
    _dominant_category,
    _resolve_signature,
    cluster_failures,
)
from qalens.analyzers.fingerprint import compute_fingerprint
from qalens.models.failure import FailureInfo
from qalens.models.insight import FailureCluster, InsightCategory
from qalens.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tc(
    *,
    name: str,
    status: TestStatus = TestStatus.FAILED,
    error_type: str | None = None,
    message: str | None = None,
    stack_trace: str | None = None,
    signature: str | None = None,
) -> TestCaseResult:
    """Build a minimal TestCaseResult for clustering tests."""
    failure: FailureInfo | None = None
    if status.is_failing:
        failure = FailureInfo(
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            failure_signature=signature,
        )
    return TestCaseResult(
        test_id=f"test-{name.replace(' ', '-').lower()}",
        name=name,
        status=status,
        failure=failure,
    )


JAVA_TRACE_A = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:342)
    at com.example.LoginTest.testLogin(LoginTest.java:87)
"""

JAVA_TRACE_B_DIFF_LINES = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:399)
    at com.example.LoginTest.testLogin(LoginTest.java:91)
"""

DIFFERENT_TRACE = """\
java.lang.NullPointerException
    at com.example.CheckoutService.process(CheckoutService.java:47)
    at com.example.CheckoutTest.testCheckout(CheckoutTest.java:22)
"""


# ---------------------------------------------------------------------------
# _resolve_signature
# ---------------------------------------------------------------------------


class TestResolveSignature:
    def test_uses_existing_signature_when_present(self):
        tc = _make_tc(name="t1", signature="abcd1234abcd1234")
        assert _resolve_signature(tc) == "abcd1234abcd1234"

    def test_computes_signature_when_missing(self):
        tc = _make_tc(
            name="t1",
            error_type="org.openqa.selenium.NoSuchElementException",
            message="no such element",
            stack_trace=JAVA_TRACE_A,
        )
        sig = _resolve_signature(tc)
        assert len(sig) == 16
        assert sig == compute_fingerprint(
            error_type="org.openqa.selenium.NoSuchElementException",
            stack_trace=JAVA_TRACE_A,
            message="no such element",
        )

    def test_same_trace_different_lines_same_signature(self):
        tc_a = _make_tc(name="a", error_type="NSE", stack_trace=JAVA_TRACE_A)
        tc_b = _make_tc(name="b", error_type="NSE", stack_trace=JAVA_TRACE_B_DIFF_LINES)
        assert _resolve_signature(tc_a) == _resolve_signature(tc_b)


# ---------------------------------------------------------------------------
# _cluster_confidence
# ---------------------------------------------------------------------------


class TestClusterConfidence:
    def test_unknown_category_always_low(self):
        for size in (1, 2, 5, 10):
            assert _cluster_confidence(size, InsightCategory.UNKNOWN) == 0.3

    def test_single_member_moderate(self):
        conf = _cluster_confidence(1, InsightCategory.LIKELY_PRODUCT_DEFECT)
        assert conf == 0.5

    def test_two_members(self):
        assert _cluster_confidence(2, InsightCategory.LIKELY_PRODUCT_DEFECT) == 0.65

    def test_three_members(self):
        assert _cluster_confidence(3, InsightCategory.LIKELY_PRODUCT_DEFECT) == 0.75

    def test_five_or_more_members_high(self):
        for size in (5, 10, 100):
            assert _cluster_confidence(size, InsightCategory.LIKELY_PRODUCT_DEFECT) == 0.85


# ---------------------------------------------------------------------------
# _dominant_category
# ---------------------------------------------------------------------------


class TestDominantCategory:
    def test_empty_returns_unknown(self):
        assert _dominant_category([]) is InsightCategory.UNKNOWN

    def test_single_element(self):
        assert _dominant_category([InsightCategory.LIKELY_FLAKY]) is InsightCategory.LIKELY_FLAKY

    def test_majority_wins(self):
        cats = [
            InsightCategory.LIKELY_PRODUCT_DEFECT,
            InsightCategory.LIKELY_PRODUCT_DEFECT,
            InsightCategory.LIKELY_FLAKY,
        ]
        assert _dominant_category(cats) is InsightCategory.LIKELY_PRODUCT_DEFECT

    def test_tie_is_deterministic(self):
        # When counts are equal the result is deterministic (max of dict keys)
        cats = [InsightCategory.LIKELY_FLAKY, InsightCategory.UNKNOWN]
        result = _dominant_category(cats)
        assert result in (InsightCategory.LIKELY_FLAKY, InsightCategory.UNKNOWN)


# ---------------------------------------------------------------------------
# _build_label
# ---------------------------------------------------------------------------


class TestBuildLabel:
    def test_uses_simple_class_name_from_error_type(self):
        label = _build_label(
            error_type="org.openqa.selenium.NoSuchElementException",
            message="no such element",
            category=None,  # type: ignore[arg-type]
        )
        assert label == "NoSuchElementException"

    def test_falls_back_to_message_when_no_error_type(self):
        from qalens.analyzers.categorizer import FailureCategory
        label = _build_label(error_type=None, message="Database connection refused", category=FailureCategory.NETWORK)
        assert label == "Database connection refused"

    def test_strips_java_inner_class_dollar(self):
        label = _build_label(
            error_type="com.example.Outer$InnerException",
            message="oops",
            category=None,  # type: ignore[arg-type]
        )
        assert label == "InnerException"

    def test_truncates_long_message(self):
        from qalens.analyzers.categorizer import FailureCategory
        long_msg = "x" * 100
        label = _build_label(error_type=None, message=long_msg, category=FailureCategory.UNKNOWN)
        assert len(label) <= 60


# ---------------------------------------------------------------------------
# cluster_failures — core integration
# ---------------------------------------------------------------------------


class TestClusterFailures:
    def test_empty_input_returns_empty(self):
        assert cluster_failures([]) == []

    def test_all_passing_returns_empty(self):
        tcs = [
            _make_tc(name="p1", status=TestStatus.PASSED),
            _make_tc(name="p2", status=TestStatus.SKIPPED),
        ]
        assert cluster_failures(tcs) == []

    def test_single_failure_creates_one_cluster(self):
        tcs = [_make_tc(name="fail1", error_type="NullPointerException", message="boom")]
        clusters = cluster_failures(tcs)
        assert len(clusters) == 1
        assert clusters[0].size == 1

    def test_two_failures_same_trace_grouped_together(self):
        tcs = [
            _make_tc(name="t1", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="t2", error_type="NSE", stack_trace=JAVA_TRACE_B_DIFF_LINES),
        ]
        clusters = cluster_failures(tcs)
        assert len(clusters) == 1
        assert clusters[0].size == 2

    def test_different_traces_create_separate_clusters(self):
        tcs = [
            _make_tc(name="t1", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="t2", error_type="NPE", stack_trace=DIFFERENT_TRACE),
        ]
        clusters = cluster_failures(tcs)
        assert len(clusters) == 2

    def test_returns_failurecluster_instances(self):
        tcs = [_make_tc(name="t1", error_type="TimeoutException", message="wait exceeded")]
        clusters = cluster_failures(tcs)
        assert all(isinstance(c, FailureCluster) for c in clusters)

    def test_cluster_membership_is_complete(self):
        """Every failing test_id must appear in exactly one cluster."""
        tcs = [
            _make_tc(name="t1", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="t2", error_type="NSE", stack_trace=JAVA_TRACE_B_DIFF_LINES),
            _make_tc(name="t3", error_type="NPE", stack_trace=DIFFERENT_TRACE),
            _make_tc(name="p1", status=TestStatus.PASSED),
        ]
        clusters = cluster_failures(tcs)
        all_ids = [tid for c in clusters for tid in c.member_test_ids]
        assert sorted(all_ids) == sorted(
            ["test-t1", "test-t2", "test-t3"]
        )

    def test_sorted_by_size_descending(self):
        tcs = [
            _make_tc(name="a1", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="a2", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="a3", error_type="NSE", stack_trace=JAVA_TRACE_A),
            _make_tc(name="b1", error_type="NPE", stack_trace=DIFFERENT_TRACE),
        ]
        clusters = cluster_failures(tcs)
        assert clusters[0].size >= clusters[-1].size

    def test_broken_status_included(self):
        tcs = [_make_tc(name="b1", status=TestStatus.BROKEN, error_type="Error", message="broken")]
        clusters = cluster_failures(tcs)
        assert len(clusters) == 1

    def test_skipped_and_pending_excluded(self):
        tcs = [
            _make_tc(name="s1", status=TestStatus.SKIPPED),
            _make_tc(name="pend", status=TestStatus.PENDING),
        ]
        assert cluster_failures(tcs) == []

    def test_precomputed_signature_respected(self):
        """Tests with a pre-set failure_signature should be grouped by it."""
        sig = "aabbccdd11223344"
        tcs = [
            _make_tc(name="t1", signature=sig),
            _make_tc(name="t2", signature=sig),
            _make_tc(name="t3", signature="0011223344556677"),
        ]
        clusters = cluster_failures(tcs)
        big = next(c for c in clusters if c.failure_signature == sig)
        assert big.size == 2

    def test_cluster_has_failure_signature(self):
        tcs = [_make_tc(name="t1", error_type="NPE", message="null")]
        clusters = cluster_failures(tcs)
        assert clusters[0].failure_signature is not None
        assert len(clusters[0].failure_signature) == 16

    def test_category_mapped_correctly_for_environment_issue(self):
        tcs = [
            _make_tc(name="t1", error_type="SessionNotCreatedException", message="grid error"),
            _make_tc(name="t2", error_type="SessionNotCreatedException", message="grid error"),
        ]
        clusters = cluster_failures(tcs)
        assert clusters[0].category == InsightCategory.LIKELY_ENVIRONMENT_ISSUE

    def test_large_cluster_gets_high_confidence(self):
        tcs = [
            _make_tc(name=f"t{i}", error_type="AssertionError", message="expected true was false")
            for i in range(7)
        ]
        clusters = cluster_failures(tcs)
        assert clusters[0].confidence == 0.85

    def test_rationale_mentions_count(self):
        tcs = [
            _make_tc(name="t1", error_type="NPE", message="bad"),
            _make_tc(name="t2", error_type="NPE", message="bad"),
        ]
        clusters = cluster_failures(tcs)
        assert "2" in clusters[0].rationale

    def test_representative_message_populated(self):
        tcs = [_make_tc(name="t1", error_type="NPE", message="null ref at line 5")]
        clusters = cluster_failures(tcs)
        assert clusters[0].representative_message == "null ref at line 5"

    def test_mixed_pass_fail_only_fails_clustered(self):
        tcs = [
            _make_tc(name="pass1", status=TestStatus.PASSED),
            _make_tc(name="fail1", error_type="NPE", message="oops"),
            _make_tc(name="skip1", status=TestStatus.SKIPPED),
        ]
        clusters = cluster_failures(tcs)
        assert len(clusters) == 1
        assert clusters[0].member_test_ids == ["test-fail1"]

