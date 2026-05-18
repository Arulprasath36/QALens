"""Tests for the ``qalens compare`` CLI command."""

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
    owner: str | None,
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


def _run(run_id: str, seq: int, tests: list[TestCaseResult]) -> TestRun:
    return TestRun(
        metadata=RunMetadata(
            run_id=run_id,
            report_format="allure",
            report_path=f"/tmp/{run_id}",
            project="CompareCLI",
            custom_fields={"suite": "Demo"},
        ),
        test_cases=tests,
    )


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "compare.db"
    conn = get_connection(db)
    repo = RunRepository(conn)
    repo.save_run(
        _run(
            "run-1",
            1,
            [
                _tc(
                    "testLogin",
                    TestStatus.PASSED,
                    owner="Alice",
                    suite="Auth",
                    tags=["auth-module"],
                ),
                _tc(
                    "testCheckout",
                    TestStatus.PASSED,
                    owner="Bob",
                    suite="Checkout",
                    tags=["checkout-module"],
                ),
            ],
        )
    )
    repo.save_run(
        _run(
            "run-2",
            2,
            [
                _tc(
                    "testLogin",
                    TestStatus.FAILED,
                    owner="Alice",
                    suite="Auth",
                    tags=["auth-module"],
                ),
                _tc(
                    "testCheckout",
                    TestStatus.PASSED,
                    owner="Bob",
                    suite="Checkout",
                    tags=["checkout-module"],
                ),
            ],
        )
    )
    conn.close()
    return db


def test_compare_runs_table(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(app, ["compare", "--db", str(db), "--by", "runs"])

    assert result.exit_code == 0, result.output
    assert "Run comparison" in result.output
    assert "testLogin" in result.output


def test_compare_empty_db_does_not_traceback(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"

    result = runner.invoke(app, ["compare", "--db", str(db), "--by", "suites"])

    assert result.exit_code == 0, result.output
    assert "No comparison groups found" in result.output


def test_compare_owners_json(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(
        app,
        ["compare", "--db", str(db), "--by", "owners", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert '"group_by": "owners"' in result.output
    assert '"Alice"' in result.output


def test_compare_modules_table(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(
        app,
        ["compare", "--db", str(db), "--by", "modules", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert '"group_by": "modules"' in result.output
    assert "auth-module" in result.output


def test_compare_suites_table(tmp_path: Path) -> None:
    db = _db(tmp_path)

    result = runner.invoke(app, ["compare", "--db", str(db), "--by", "suites"])

    assert result.exit_code == 0, result.output
    assert "Suites comparison" in result.output
    assert "Auth" in result.output
