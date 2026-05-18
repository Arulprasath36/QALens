"""Tests for the ``qalens history`` CLI command."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from typer.testing import CliRunner

from qalens.cli import app
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus

runner = CliRunner()


def _tc(
    name: str,
    status: TestStatus,
    *,
    owner: str,
    suite: str,
    tags: list[str],
) -> TestCaseResult:
    failure = None
    if status.is_failing:
        failure = FailureInfo(error_type="AssertionError", message=f"{name} failed")
    return TestCaseResult(
        test_id=name,
        name=name,
        status=status,
        owner=owner,
        suite=suite,
        tags=tags,
        failure=failure,
    )


def _run(run_id: str, tests: list[TestCaseResult]) -> TestRun:
    return TestRun(
        metadata=RunMetadata(
            run_id=run_id,
            report_format="allure",
            report_path=f"/tmp/{run_id}",
            project="HistoryCLI",
        ),
        test_cases=tests,
    )


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "history.db"
    conn = get_connection(db)
    repo = RunRepository(conn)
    repo.save_run(
        _run(
            "run-1",
            [
                _tc(
                    "testLogin",
                    TestStatus.PASSED,
                    owner="Alice",
                    suite="Auth",
                    tags=["auth-module"],
                )
            ],
        )
    )
    repo.save_run(
        _run(
            "run-2",
            [
                _tc(
                    "testLogin",
                    TestStatus.FAILED,
                    owner="Alice",
                    suite="Auth",
                    tags=["auth-module"],
                )
            ],
        )
    )
    conn.close()
    return db


def test_history_test_table(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(app, ["history", "test", "testLogin()", "--db", str(db)])

    assert result.exit_code == 0, result.output
    assert "Test history" in result.output
    assert "flaky" in result.output


def test_history_owner_json(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(
        app,
        ["history", "owner", "Alice", "--db", str(db), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert '"kind": "owner"' in result.output
    assert '"failed_executions": 1' in result.output


def test_history_module_table(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(app, ["history", "module", "auth-module", "--db", str(db)])

    assert result.exit_code == 0, result.output
    assert "Module history" in result.output
    assert "failed executions" in result.output


def test_history_failure_json(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(
        app,
        ["history", "failure", "not-a-real-fingerprint", "--db", str(db), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert '"kind": "failure"' in result.output
    assert '"occurrences": 0' in result.output


def test_history_empty_db_does_not_traceback(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"

    result = runner.invoke(app, ["history", "suite", "Auth", "--db", str(db)])

    assert result.exit_code == 0, result.output
    assert "No matching history found" in result.output
