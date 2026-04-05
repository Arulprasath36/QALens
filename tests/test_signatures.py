"""Tests for the failure signature engine (Phase 4)."""

from __future__ import annotations

import pytest

from qara.analyzers.fingerprint import compute_fingerprint
from qara.analyzers.signatures import SignatureEngine, normalize_message
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import StepResult, TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_failure(
    *,
    error_type: str | None = "org.example.SomeException",
    message: str | None = "something went wrong",
    stack_trace: str | None = None,
    signature: str | None = None,
) -> FailureInfo:
    return FailureInfo(
        error_type=error_type,
        message=message,
        stack_trace=stack_trace,
        failure_signature=signature,
    )


def _make_tc(
    name: str,
    status: TestStatus = TestStatus.FAILED,
    failure: FailureInfo | None = None,
    steps: list[StepResult] | None = None,
) -> TestCaseResult:
    if failure is None and status.is_failing:
        failure = _make_failure()
    return TestCaseResult(
        test_id=f"id-{name}",
        name=name,
        status=status,
        failure=failure,
        steps=steps or [],
    )


def _make_run(test_cases: list[TestCaseResult]) -> TestRun:
    return TestRun(
        metadata=RunMetadata(report_format="allure", report_path="/tmp/report"),
        test_cases=test_cases,
    )


JAVA_TRACE = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:342)
    at com.example.LoginTest.testLogin(LoginTest.java:87)
"""

JAVA_TRACE_DIFFERENT_LINES = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:399)
    at com.example.LoginTest.testLogin(LoginTest.java:91)
"""


# ---------------------------------------------------------------------------
# normalize_message
# ---------------------------------------------------------------------------


class TestNormalizeMessage:
    def test_none_returns_none(self):
        assert normalize_message(None) is None

    def test_blank_string_returned_as_is(self):
        assert normalize_message("   ") == "   "

    def test_uuid_replaced(self):
        msg = "Session 550e8400-e29b-41d4-a716-446655440000 not found"
        result = normalize_message(msg)
        assert "<UUID>" in result
        assert "550e8400" not in result

    def test_iso_timestamp_replaced(self):
        msg = "Failure at 2026-01-15T10:30:45.123Z in pipeline"
        result = normalize_message(msg)
        assert "<TIMESTAMP>" in result
        assert "2026-01-15" not in result

    def test_time_only_replaced(self):
        msg = "Timeout waiting at 14:32:01.456"
        result = normalize_message(msg)
        assert "<TIME>" in result

    def test_hex_address_replaced(self):
        msg = "Object@0x1a2b3c4d is null"
        result = normalize_message(msg)
        assert "<ADDR>" in result
        assert "0x1a2b3c4d" not in result

    def test_long_hex_session_id_replaced(self):
        msg = "Token abcdef1234567890abcdef12 invalid"
        result = normalize_message(msg)
        assert "<HEX_ID>" in result

    def test_ip_address_replaced(self):
        msg = "Connection refused: 192.168.1.100:5432"
        result = normalize_message(msg)
        assert "<IP>" in result
        assert "192.168.1.100" not in result

    def test_localhost_port_replaced(self):
        msg = "Cannot connect to localhost:4444"
        result = normalize_message(msg)
        assert "localhost:<PORT>" in result
        assert "4444" not in result

    def test_absolute_path_reduced_to_basename(self):
        msg = "File not found: /home/runner/work/project/data/fixture.json"
        result = normalize_message(msg)
        assert "/home/runner/work/project/data/" not in result
        assert "fixture.json" in result

    def test_only_first_line_returned(self):
        msg = "Error on line 1\ndetails on line 2\nmore on line 3"
        result = normalize_message(msg)
        assert "\n" not in result  # type: ignore[operator]
        assert "line 1" in result  # type: ignore[operator]

    def test_plain_message_unchanged(self):
        msg = "Expected true but was false"
        assert normalize_message(msg) == msg

    def test_multiple_noise_tokens_in_one_message(self):
        msg = (
            "Session 550e8400-e29b-41d4-a716-446655440000 timed out at "
            "2026-03-08T09:00:00Z on localhost:4444"
        )
        result = normalize_message(msg)
        assert "<UUID>" in result
        assert "<TIMESTAMP>" in result
        assert "localhost:<PORT>" in result


# ---------------------------------------------------------------------------
# SignatureEngine._enrich_failure_info / enrich_failure_info
# ---------------------------------------------------------------------------


class TestEnrichFailureInfo:
    def setup_method(self):
        self.engine = SignatureEngine()

    def test_sets_failure_signature(self):
        f = _make_failure()
        self.engine.enrich_failure_info(f)
        assert f.failure_signature is not None
        assert len(f.failure_signature) == 16

    def test_sets_normalized_message(self):
        f = _make_failure(message="Error at 2026-01-01T00:00:00Z")
        self.engine.enrich_failure_info(f)
        assert f.normalized_message is not None
        assert "2026-01-01" not in f.normalized_message

    def test_normalized_stack_trace_set_when_trace_present(self):
        f = _make_failure(stack_trace=JAVA_TRACE)
        self.engine.enrich_failure_info(f)
        assert f.normalized_stack_trace is not None
        assert ":87" not in f.normalized_stack_trace
        assert ":LINE" in f.normalized_stack_trace

    def test_normalized_stack_trace_none_when_no_trace(self):
        f = _make_failure(stack_trace=None)
        self.engine.enrich_failure_info(f)
        assert f.normalized_stack_trace is None

    def test_idempotent_does_not_overwrite_existing_signature(self):
        pre_sig = "aabbccdd11223344"
        f = _make_failure(signature=pre_sig)
        self.engine.enrich_failure_info(f)
        assert f.failure_signature == pre_sig

    def test_idempotent_does_not_touch_normalized_fields_if_sig_set(self):
        f = _make_failure(signature="aabbccdd11223344", message="original")
        f.normalized_message = "already set"
        self.engine.enrich_failure_info(f)
        assert f.normalized_message == "already set"

    def test_returns_same_object(self):
        f = _make_failure()
        result = self.engine.enrich_failure_info(f)
        assert result is f

    def test_same_trace_different_lines_same_signature(self):
        f1 = _make_failure(error_type="NSE", stack_trace=JAVA_TRACE)
        f2 = _make_failure(error_type="NSE", stack_trace=JAVA_TRACE_DIFFERENT_LINES)
        self.engine.enrich_failure_info(f1)
        self.engine.enrich_failure_info(f2)
        assert f1.failure_signature == f2.failure_signature

    def test_different_traces_different_signatures(self):
        f1 = _make_failure(
            error_type="NSE",
            stack_trace=JAVA_TRACE,
        )
        f2 = _make_failure(
            error_type="NPE",
            stack_trace=(
                "java.lang.NullPointerException\n"
                "    at com.example.Checkout.process(Checkout.java:55)\n"
            ),
        )
        self.engine.enrich_failure_info(f1)
        self.engine.enrich_failure_info(f2)
        assert f1.failure_signature != f2.failure_signature

    def test_signature_matches_compute_fingerprint_directly(self):
        f = _make_failure(
            error_type="org.openqa.selenium.TimeoutException",
            message="wait exceeded",
            stack_trace=JAVA_TRACE,
        )
        self.engine.enrich_failure_info(f)
        expected = compute_fingerprint(
            error_type=f.error_type,
            stack_trace=JAVA_TRACE,
            message=f.message,
        )
        assert f.failure_signature == expected


# ---------------------------------------------------------------------------
# SignatureEngine.enrich (full TestRun)
# ---------------------------------------------------------------------------


class TestEnrichRun:
    def setup_method(self):
        self.engine = SignatureEngine()

    def test_returns_same_run_object(self):
        run = _make_run([_make_tc("t1")])
        result = self.engine.enrich(run)
        assert result is run

    def test_failing_tests_get_signature(self):
        run = _make_run([_make_tc("t1", TestStatus.FAILED)])
        self.engine.enrich(run)
        assert run.test_cases[0].failure.failure_signature is not None

    def test_broken_tests_get_signature(self):
        run = _make_run([_make_tc("t1", TestStatus.BROKEN)])
        self.engine.enrich(run)
        assert run.test_cases[0].failure.failure_signature is not None

    def test_passing_tests_not_modified(self):
        tc = _make_tc("p1", TestStatus.PASSED, failure=None)
        run = _make_run([tc])
        self.engine.enrich(run)
        assert tc.failure is None

    def test_skipped_tests_not_modified(self):
        tc = _make_tc("s1", TestStatus.SKIPPED, failure=None)
        run = _make_run([tc])
        self.engine.enrich(run)
        assert tc.failure is None

    def test_multiple_tests_all_enriched(self):
        tcs = [_make_tc(f"t{i}", TestStatus.FAILED) for i in range(5)]
        run = _make_run(tcs)
        self.engine.enrich(run)
        for tc in run.test_cases:
            assert tc.failure.failure_signature is not None

    def test_empty_run_no_error(self):
        run = _make_run([])
        self.engine.enrich(run)  # should not raise

    def test_step_failure_is_also_enriched(self):
        step_failure = _make_failure(message="step failed badly")
        step = StepResult(name="Click submit", failure=step_failure)
        tc = _make_tc("t1", TestStatus.FAILED, steps=[step])
        run = _make_run([tc])
        self.engine.enrich(run)
        assert step.failure.failure_signature is not None

    def test_step_failure_on_passing_test_enriched(self):
        """A passing test can still have failed steps; enrich them too."""
        step_failure = _make_failure(message="step boom")
        step = StepResult(name="Verify element", failure=step_failure)
        tc = _make_tc("p1", TestStatus.PASSED, failure=None, steps=[step])
        run = _make_run([tc])
        self.engine.enrich(run)
        assert step.failure.failure_signature is not None

    def test_idempotent_second_call_no_change(self):
        run = _make_run([_make_tc("t1")])
        self.engine.enrich(run)
        sig_first = run.test_cases[0].failure.failure_signature
        self.engine.enrich(run)
        assert run.test_cases[0].failure.failure_signature == sig_first

    def test_mixed_run_only_fails_get_enriched(self):
        passed = _make_tc("pass1", TestStatus.PASSED, failure=None)
        failed = _make_tc("fail1", TestStatus.FAILED)
        skipped = _make_tc("skip1", TestStatus.SKIPPED, failure=None)
        run = _make_run([passed, failed, skipped])
        self.engine.enrich(run)
        assert passed.failure is None
        assert failed.failure.failure_signature is not None
        assert skipped.failure is None

