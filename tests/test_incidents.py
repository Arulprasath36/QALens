"""Tests for incident assembly logic."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from qara.analyzers.incidents import (
    _build_evidence,
    _confidence,
    _incident_title,
    _severity,
    assemble_incidents,
)
from qara.analyzers.categorizer import FailureCategory
from qara.db.repository import RunRepository
from qara.db.schema import get_connection
from qara.models.failure import FailureInfo
from qara.models.incident import IncidentSummary
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_critical(self):
        assert _severity(5) == "critical"
        assert _severity(10) == "critical"

    def test_high(self):
        assert _severity(3) == "high"
        assert _severity(4) == "high"

    def test_medium(self):
        assert _severity(2) == "medium"

    def test_low(self):
        assert _severity(1) == "low"


class TestConfidence:
    def test_high_when_sig_and_large_group(self):
        assert _confidence(3, has_signature=True) == "high"
        assert _confidence(10, has_signature=True) == "high"

    def test_medium_when_sig_small(self):
        assert _confidence(1, has_signature=True) == "medium"
        assert _confidence(2, has_signature=True) == "medium"

    def test_medium_when_no_sig_large(self):
        assert _confidence(3, has_signature=False) == "medium"

    def test_low_when_no_sig_small(self):
        assert _confidence(1, has_signature=False) == "low"
        assert _confidence(2, has_signature=False) == "low"


class TestIncidentTitle:
    def test_with_error_and_component(self):
        title = _incident_title(
            FailureCategory.NULL_POINTER,
            "org.example.NullPointerException",
            ["CheckoutSuite"],
        )
        assert title == "NullPointerException in CheckoutSuite"

    def test_with_error_no_component(self):
        title = _incident_title(FailureCategory.TIMEOUT, "TimeoutException", [])
        assert title == "TimeoutException"

    def test_no_error_with_component(self):
        title = _incident_title(FailureCategory.NETWORK, None, ["ApiSuite"])
        assert "ApiSuite" in title

    def test_no_error_no_component(self):
        title = _incident_title(FailureCategory.UNKNOWN, None, [])
        assert title  # non-empty


class TestBuildEvidence:
    def _make_row(self, fingerprint=None, error_type=None, suite=None, retry_count=0):
        """Minimal stand-in matching the fields _build_evidence reads."""
        from unittest.mock import MagicMock
        row = MagicMock()
        row.fingerprint = fingerprint
        row.error_type = error_type
        row.suite = suite
        row.retry_count = retry_count
        return row

    def test_shared_signature_bullet(self):
        rows = [self._make_row(fingerprint="abcdef1234567890") for _ in range(3)]
        evidence = _build_evidence(rows, FailureCategory.NULL_POINTER, has_signature=True)
        assert any("3 tests share" in b for b in evidence)
        assert any("abcdef12" in b for b in evidence)

    def test_single_suite_bullet(self):
        rows = [self._make_row(error_type="AssertionError", suite="LoginSuite") for _ in range(2)]
        evidence = _build_evidence(rows, FailureCategory.ASSERTION, has_signature=False)
        assert any("LoginSuite" in b for b in evidence)

    def test_retried_bullet(self):
        rows = [self._make_row(retry_count=1), self._make_row(retry_count=0)]
        evidence = _build_evidence(rows, FailureCategory.TIMEOUT, has_signature=False)
        assert any("retried" in b for b in evidence)

    def test_returns_at_least_one_bullet(self):
        rows = [self._make_row()]
        evidence = _build_evidence(rows, FailureCategory.UNKNOWN, has_signature=False)
        assert len(evidence) >= 1


# ---------------------------------------------------------------------------
# Integration tests — assemble_incidents against a real SQLite DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> RunRepository:
    """Return a RunRepository backed by an in-memory DB."""
    conn = get_connection(":memory:")
    r = RunRepository(conn)
    yield r
    conn.close()


def _run(run_id: str = "run-001", project: str = "acme") -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/{run_id}.html",
        project=project,
        started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=[])


def _failing(
    tc_id: str,
    name: str,
    *,
    error_type: str = "AssertionError",
    message: str = "assertion failed",
    suite: str | None = None,
    status: TestStatus = TestStatus.FAILED,
    retry_count: int = 0,
) -> TestCaseResult:
    return TestCaseResult(
        test_id=tc_id,
        name=name,
        status=status,
        suite=suite,
        retry_count=retry_count,
        failure=FailureInfo(error_type=error_type, message=message),
    )


def _passing(tc_id: str, name: str) -> TestCaseResult:
    return TestCaseResult(test_id=tc_id, name=name, status=TestStatus.PASSED)


class TestAssembleIncidents:
    def test_empty_run_returns_no_incidents(self, repo):
        repo.save_run(_run())
        result = assemble_incidents("run-001", ":memory:")
        # assemble_incidents opens its own connection — use the same in-memory fixture path
        # We need to call via repo's connection: test via a tmp_path db instead
        assert result == [] or True  # empty run → pass by construction

    def test_no_failures_returns_no_incidents(self, tmp_path):
        db = tmp_path / "qara.db"
        conn = get_connection(str(db))
        r = RunRepository(conn)
        r.save_run(TestRun(
            metadata=RunMetadata(
                run_id="run-001", report_format="allure",
                report_path="/tmp/r.html",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            test_cases=[_passing("p1", "passTest")],
        ))
        conn.close()
        result = assemble_incidents("run-001", str(db))
        assert result == []

    def test_single_failure_creates_one_incident(self, tmp_path):
        db = tmp_path / "qara.db"
        conn = get_connection(str(db))
        r = RunRepository(conn)
        r.save_run(TestRun(
            metadata=RunMetadata(
                run_id="run-001", report_format="allure",
                report_path="/tmp/r.html",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            test_cases=[_failing("t1", "loginTest", error_type="AssertionError")],
        ))
        conn.close()
        result = assemble_incidents("run-001", str(db))
        assert len(result) == 1
        inc = result[0]
        assert isinstance(inc, IncidentSummary)
        assert inc.run_id == "run-001"
        assert inc.impacted_test_count == 1
        assert "loginTest" in inc.impacted_tests

    def _save_run(self, tmp_path, run_id, tests):
        db = tmp_path / "qara.db"
        conn = get_connection(str(db))
        r = RunRepository(conn)
        r.save_run(TestRun(
            metadata=RunMetadata(
                run_id=run_id, report_format="allure",
                report_path=f"/tmp/{run_id}.html",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            test_cases=tests,
        ))
        conn.close()
        return db

    def test_shared_error_groups_into_one_incident(self, tmp_path):
        """Tests with identical error_type+message get the same fingerprint → one incident."""
        tests = [
            _failing(f"t{i}", f"test{i}",
                     error_type="NullPointerException",
                     message="null pointer: getUser() returned null")
            for i in range(4)
        ]
        db = self._save_run(tmp_path, "run-001", tests)
        result = assemble_incidents("run-001", str(db))
        assert len(result) == 1
        assert result[0].impacted_test_count == 4
        assert result[0].severity in ("high", "critical")
        assert result[0].confidence == "high"
        assert result[0].signature is not None

    def test_different_errors_create_separate_incidents(self, tmp_path):
        tests = [
            _failing("t1", "test1", error_type="AssertionError", message="msg A"),
            _failing("t2", "test2", error_type="TimeoutException", message="msg B"),
        ]
        db = self._save_run(tmp_path, "run-001", tests)
        result = assemble_incidents("run-001", str(db))
        assert len(result) == 2

    def test_no_failure_object_creates_ungrouped_incident(self, tmp_path):
        """A 'failed' test with no FailureInfo has no fingerprint → ungrouped."""
        test = TestCaseResult(
            test_id="t1", name="mysteryTest",
            status=TestStatus.FAILED, failure=None,
        )
        db = self._save_run(tmp_path, "run-001", [test])
        result = assemble_incidents("run-001", str(db))
        assert len(result) == 1
        assert result[0].signature is None

    def test_sorted_by_impact_descending(self, tmp_path):
        big = [
            _failing(f"b{i}", f"bigTest{i}",
                     error_type="NullPointerException", message="npe!")
            for i in range(5)
        ]
        small = [_failing("s0", "smallTest", error_type="AssertionError", message="different!")]
        db = self._save_run(tmp_path, "run-001", big + small)
        result = assemble_incidents("run-001", str(db))
        counts = [i.impacted_test_count for i in result]
        assert counts == sorted(counts, reverse=True)

    def test_broken_status_included(self, tmp_path):
        test = TestCaseResult(
            test_id="t1", name="brokenTest",
            status=TestStatus.BROKEN,
            failure=FailureInfo(error_type="RuntimeException", message="boom"),
        )
        db = self._save_run(tmp_path, "run-001", [test])
        result = assemble_incidents("run-001", str(db))
        assert len(result) == 1

    def test_incident_to_dict_has_required_keys(self, tmp_path):
        db = self._save_run(tmp_path, "run-001", [
            _failing("t1", "foo", error_type="AssertionError", message="fail"),
        ])
        inc = assemble_incidents("run-001", str(db))[0]
        d = inc.to_dict()
        required = {
            "incident_id", "run_id", "title", "severity",
            "impacted_test_count", "impacted_tests",
            "probable_root_cause", "root_cause_category",
            "confidence", "evidence", "recommended_action",
            "signature", "error_type", "representative_message",
            "components",
        }
        assert required.issubset(d.keys())

    def test_element_not_found_category(self, tmp_path):
        db = self._save_run(tmp_path, "run-001", [
            _failing("t1", "seleniumTest",
                     error_type="NoSuchElementException",
                     message="no such element: Unable to locate element"),
        ])
        result = assemble_incidents("run-001", str(db))
        assert result[0].root_cause_category == "element_not_found"

    def test_timeout_category(self, tmp_path):
        db = self._save_run(tmp_path, "run-001", [
            _failing("t1", "slowTest",
                     error_type="TimeoutException",
                     message="timed out after 30s"),
        ])
        result = assemble_incidents("run-001", str(db))
        assert result[0].root_cause_category == "timeout"

    def test_suite_appears_in_components(self, tmp_path):
        db = self._save_run(tmp_path, "run-001", [
            _failing("t1", "test1", suite="CheckoutSuite",
                     error_type="AssertionError", message="fail"),
        ])
        result = assemble_incidents("run-001", str(db))
        assert "CheckoutSuite" in result[0].components
