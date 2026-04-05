"""Integration tests for the ``qara analyze`` CLI command (Phase 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qara.analyzers.flaky import FlakyClassification
from qara.cli import app
from qara.db.repository import RunRepository
from qara.db.schema import get_connection
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(run_id: str, tests: list, seq: int = 1) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/r_{run_id}.html",
        project="AnalyzeProject",
        started_at=datetime(2026, 3, seq, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _make_tc(
    name: str,
    status: TestStatus,
    *,
    idx: int = 1,
    error_type: str | None = None,
) -> TestCaseResult:
    failure = None
    if status in (TestStatus.FAILED, TestStatus.BROKEN) and error_type:
        failure = FailureInfo(
            error_type=error_type,
            message="Something went wrong",
            stack_trace="    at com.example.Test.run(Test.java:10)",
        )
    return TestCaseResult(
        test_id=f"{name}-{idx}",
        name=name,
        status=status,
        failure=failure,
    )


@pytest.fixture()
def populated_db(tmp_path) -> Path:
    """Seed a temp DB with 3 runs of 3 tests for analyze tests."""
    db = tmp_path / "analyze_test.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)

    history = [
        # run1
        [
            _make_tc("testLogin", TestStatus.PASSED, idx=1),
            _make_tc("testSearch", TestStatus.FAILED, idx=1,
                     error_type="org.openqa.selenium.NoSuchElementException"),
            _make_tc("testLogout", TestStatus.PASSED, idx=1),
        ],
        # run2
        [
            _make_tc("testLogin", TestStatus.FAILED, idx=2,
                     error_type="org.openqa.selenium.NoSuchElementException"),
            _make_tc("testSearch", TestStatus.PASSED, idx=2),
            _make_tc("testLogout", TestStatus.PASSED, idx=2),
        ],
        # run3
        [
            _make_tc("testLogin", TestStatus.PASSED, idx=3),
            _make_tc("testSearch", TestStatus.FAILED, idx=3,
                     error_type="org.openqa.selenium.NoSuchElementException"),
            _make_tc("testLogout", TestStatus.PASSED, idx=3),
        ],
    ]
    for i, tests in enumerate(history, 1):
        repo.save_run(_make_run(f"run-{i:03d}", tests, seq=i))

    conn.close()
    return db


# ---------------------------------------------------------------------------
# Basic invocation
# ---------------------------------------------------------------------------


def test_analyze_exits_zero_with_data(populated_db):
    result = runner.invoke(app, ["analyze", "--db", str(populated_db)])
    assert result.exit_code == 0, result.output


def test_analyze_shows_stability_table(populated_db):
    result = runner.invoke(app, ["analyze", "--db", str(populated_db)])
    assert "Stability" in result.output or "stability" in result.output.lower()


def test_analyze_shows_test_names(populated_db):
    result = runner.invoke(app, ["analyze", "--db", str(populated_db)])
    assert "testLogin" in result.output or "testlogin" in result.output.lower()


def test_analyze_shows_flaky_classification(populated_db):
    result = runner.invoke(app, ["analyze", "--db", str(populated_db)])
    assert "Flaky" in result.output or "flaky" in result.output.lower()


def test_analyze_shows_failure_groups(populated_db):
    result = runner.invoke(app, ["analyze", "--db", str(populated_db)])
    assert "Recurring Failures" in result.output or "fingerprint" in result.output.lower()


# ---------------------------------------------------------------------------
# Project filter
# ---------------------------------------------------------------------------


def test_analyze_project_filter(populated_db):
    result = runner.invoke(
        app,
        ["analyze", "--db", str(populated_db), "--project", "AnalyzeProject"],
    )
    assert result.exit_code == 0


def test_analyze_unknown_project_shows_no_tests_message(populated_db):
    result = runner.invoke(
        app,
        ["analyze", "--db", str(populated_db), "--project", "NonExistentProject"],
    )
    assert result.exit_code == 0
    assert "No tests" in result.output or "no tests" in result.output.lower()


# ---------------------------------------------------------------------------
# --no-flaky / --no-failures flags
# ---------------------------------------------------------------------------


def test_analyze_no_flaky_hides_stability_table(populated_db):
    result = runner.invoke(
        app, ["analyze", "--db", str(populated_db), "--no-flaky"]
    )
    assert result.exit_code == 0
    assert "Stability" not in result.output


def test_analyze_no_failures_hides_failure_groups(populated_db):
    result = runner.invoke(
        app, ["analyze", "--db", str(populated_db), "--no-failures"]
    )
    assert result.exit_code == 0
    assert "Recurring Failures" not in result.output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_analyze_out_writes_json(populated_db, tmp_path):
    out = tmp_path / "analysis.json"
    result = runner.invoke(
        app,
        ["analyze", "--db", str(populated_db), "--out", str(out)],
    )
    assert result.exit_code == 0
    assert out.exists()

    import json
    data = json.loads(out.read_text())
    assert "flaky" in data
    assert "failure_groups" in data
    assert isinstance(data["flaky"], list)
