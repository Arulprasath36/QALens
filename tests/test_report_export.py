"""Tests for deterministic shareable report exports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from qalens.cli import app
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.reports import build_report, render_html, render_json, render_markdown
from qalens.server.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _tc(
    name: str,
    status: TestStatus,
    *,
    idx: int,
    suite: str = "Checkout",
    owner: str = "payments",
    duration_ms: int = 1000,
    message: str = "Assertion failed",
) -> TestCaseResult:
    failure = None
    if status.is_failing:
        failure = FailureInfo(
            error_type="AssertionError",
            message=message,
            stack_trace="at tests.checkout.TestCheckout.test(TestCheckout.java:10)",
        )
    return TestCaseResult(
        test_id=f"{name}-{idx}",
        name=name,
        status=status,
        suite=suite,
        owner=owner,
        duration_ms=duration_ms,
        failure=failure,
    )


def _run(run_id: str, seq: int, tests: list[TestCaseResult]) -> TestRun:
    return TestRun(
        metadata=RunMetadata(
            run_id=run_id,
            report_format="allure",
            report_path=f"/tmp/{run_id}",
            project="ReportProject",
            branch="main",
            build_number=f"build-{seq}",
            started_at=datetime(2026, 5, seq, 10, 0, tzinfo=timezone.utc),
        ),
        test_cases=tests,
    )


def _seed_db(tmp_path: Path) -> Path:
    db = tmp_path / "qalens-report.db"
    conn = get_connection(db)
    repo = RunRepository(conn)
    repo.save_run(
        _run(
            "run-1",
            1,
            [
                _tc("testCheckout", TestStatus.PASSED, idx=1),
                _tc("testSearch", TestStatus.PASSED, idx=1, suite="Search", owner="search"),
                _tc("testFlaky", TestStatus.FAILED, idx=1, message="Timeout waiting for button"),
            ],
        )
    )
    repo.save_run(
        _run(
            "run-2",
            2,
            [
                _tc("testCheckout", TestStatus.FAILED, idx=2, message="Payment declined"),
                _tc("testSearch", TestStatus.PASSED, idx=2, suite="Search", owner="search"),
                _tc("testFlaky", TestStatus.PASSED, idx=2),
            ],
        )
    )
    repo.save_run(
        _run(
            "run-3",
            3,
            [
                _tc("testCheckout", TestStatus.FAILED, idx=3, message="Payment declined"),
                _tc("testSearch", TestStatus.PASSED, idx=3, suite="Search", owner="search"),
                _tc("testFlaky", TestStatus.FAILED, idx=3, message="Timeout waiting for button"),
            ],
        )
    )
    conn.close()
    return db


def test_build_report_includes_latest_comparison_and_recommendations(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)

    report = build_report(db_path=db, project="ReportProject")

    assert report.latest_run.run_sequence == 3
    assert report.latest_run.failed == 2
    assert report.comparison is not None
    assert len(report.comparison.persistent_failures) == 1
    assert report.failure_groups
    assert report.recommendations
    assert report.executive_summary
    assert report.trend_intelligence
    assert report.fix_first


def test_report_markdown_renderer_is_deterministic_content(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    report = build_report(db_path=db, project="ReportProject")

    markdown = render_markdown(report)

    assert "# QaLens Report" in markdown
    assert "## Latest Run" in markdown
    assert "## Fix First" in markdown
    assert "## Trend Intelligence" in markdown
    assert "testCheckout" in markdown
    assert "Failure Groups" in markdown


def test_report_html_escapes_report_content(tmp_path: Path) -> None:
    db = tmp_path / "unsafe.db"
    conn = get_connection(db)
    repo = RunRepository(conn)
    repo.save_run(
        _run(
            "unsafe-1",
            1,
            [
                _tc(
                    '<img src=x onerror="alert(1)">',
                    TestStatus.FAILED,
                    idx=1,
                    message="<script>alert(1)</script>",
                )
            ],
        )
    )
    conn.close()

    html = render_html(build_report(db_path=db, project="ReportProject", run_id="unsafe-1"))

    assert "<img src=x" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_json_renderer_contains_expected_sections(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)

    rendered = render_json(build_report(db_path=db, project="ReportProject"))

    assert '"latest_run"' in rendered
    assert '"failure_groups"' in rendered
    assert '"suite_impacts"' in rendered


def test_report_cli_writes_markdown_file(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    out = tmp_path / "report.md"

    result = runner.invoke(
        app,
        [
            "report",
            "--db",
            str(db),
            "--project",
            "ReportProject",
            "--format",
            "markdown",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "QaLens Report" in out.read_text(encoding="utf-8")


def test_report_export_api_downloads_html(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    client = TestClient(create_app(db_path=db))

    response = client.get("/api/report/export?project=ReportProject&format=html")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "text/html" in response.headers["content-type"]
    assert "QaLens Report" in response.text
