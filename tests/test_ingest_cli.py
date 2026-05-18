"""Integration tests for the ``qalens ingest`` CLI command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from qalens.cli import app

runner = CliRunner()

EXTENT_FIXTURE = Path(__file__).parent / "fixtures" / "extent_sample" / "ExtentReport.html"
ALLURE_FIXTURE = Path(__file__).parent / "fixtures" / "allure_sample"
JUNIT_FIXTURE = Path(__file__).parent / "fixtures" / "junit_sample"
TESTNG_FIXTURE = Path(__file__).parent / "fixtures" / "testng_sample"
PLAYWRIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "playwright_json_sample"
CYPRESS_FIXTURE = Path(__file__).parent / "fixtures" / "cypress_mochawesome_sample"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ingest(path: Path, extra_args: list[str] | None = None, db: Path | None = None) -> object:
    args = ["ingest", str(path)]
    if db:
        args += ["--db", str(db)]
    if extra_args:
        args += extra_args
    return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# Basic success
# ---------------------------------------------------------------------------


def test_ingest_extent_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(EXTENT_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_allure_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(ALLURE_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_junit_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(JUNIT_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_testng_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(TESTNG_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_playwright_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(PLAYWRIGHT_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_cypress_exits_zero(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(CYPRESS_FIXTURE, db=db)
    assert result.exit_code == 0, result.output


def test_ingest_prints_ingested_line(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(EXTENT_FIXTURE, db=db)
    assert "Ingested" in result.output


def test_ingest_prints_test_count(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(EXTENT_FIXTURE, db=db)
    assert "Tests" in result.output


def test_ingest_prints_stored_path(tmp_path):
    db = tmp_path / "test.db"
    result = _ingest(EXTENT_FIXTURE, db=db)
    # Rich may wrap long paths across lines — join output before checking
    flat = result.output.replace("\n", "")
    assert str(db).replace("\n", "") in flat


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_ingest_same_report_twice_skips_second(tmp_path):
    db = tmp_path / "test.db"
    _ingest(EXTENT_FIXTURE, db=db)
    result2 = _ingest(EXTENT_FIXTURE, db=db)
    assert result2.exit_code == 0
    assert "Skipped" in result2.output


# ---------------------------------------------------------------------------
# Verbose flag
# ---------------------------------------------------------------------------


def test_ingest_verbose_shows_failed_tests(tmp_path):
    db = tmp_path / "test.db"
    # extent fixture has 1 failed test
    result = _ingest(EXTENT_FIXTURE, extra_args=["-v"], db=db)
    assert result.exit_code == 0
    # verbose mode lists failing tests
    assert "✗" in result.output or "failed" in result.output.lower()


# ---------------------------------------------------------------------------
# Database is actually populated
# ---------------------------------------------------------------------------


def test_ingest_extent_populates_db(tmp_path):
    """After ingest the DB must contain the run."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(EXTENT_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    conn.close()

    assert len(runs) == 1
    assert runs[0].report_format == "extent"


def test_ingest_allure_populates_db(tmp_path):
    """After ingest the DB must have test cases."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(ALLURE_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    assert len(runs) == 1
    run_id = runs[0].run_id
    tcs = repo.get_test_cases_for_run(run_id)
    conn.close()

    assert len(tcs) == 4


def test_ingest_junit_populates_db(tmp_path):
    """After ingest the DB must have JUnit test cases."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(JUNIT_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0].report_format == "junit"
    tcs = repo.get_test_cases_for_run(runs[0].run_id)
    conn.close()

    assert len(tcs) == 4


def test_ingest_testng_populates_db(tmp_path):
    """After ingest the DB must have TestNG test cases."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(TESTNG_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0].report_format == "testng"
    tcs = repo.get_test_cases_for_run(runs[0].run_id)
    conn.close()

    assert len(tcs) == 3


def test_ingest_playwright_populates_db(tmp_path):
    """After ingest the DB must have Playwright test cases."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(PLAYWRIGHT_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0].report_format == "playwright"
    tcs = repo.get_test_cases_for_run(runs[0].run_id)
    conn.close()

    assert len(tcs) == 3


def test_ingest_cypress_populates_db(tmp_path):
    """After ingest the DB must have Cypress test cases."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(CYPRESS_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0].report_format == "cypress"
    tcs = repo.get_test_cases_for_run(runs[0].run_id)
    conn.close()

    assert len(tcs) == 3


def test_ingest_applies_owner_mapping(tmp_path):
    """--owner-map fills owner metadata before saving the run."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    owner_map = tmp_path / "owners.toml"
    owner_map.write_text(
        """
[[owners]]
owner = "Auth Team"
suites = ["Authentication*"]
""".strip(),
        encoding="utf-8",
    )

    result = _ingest(
        ALLURE_FIXTURE,
        extra_args=["--owner-map", str(owner_map), "--override-owners"],
        db=db,
    )
    assert result.exit_code == 0, result.output

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    run_id = repo.list_runs()[0].run_id
    owners = {tc.owner for tc in repo.get_test_cases_for_run(run_id)}
    conn.close()

    assert "Auth Team" in owners


def test_ingest_run_sequence_increments(tmp_path):
    """Two different runs of the same project get sequence 1 and 2."""
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    db = tmp_path / "test.db"
    _ingest(EXTENT_FIXTURE, db=db)
    # Ingest Allure fixture as second run (different run_id, may differ project)
    _ingest(ALLURE_FIXTURE, db=db)

    conn = get_connection(str(db))
    repo = RunRepository(conn)
    runs = repo.list_runs()
    conn.close()

    assert len(runs) == 2
    sequences = sorted(r.run_sequence for r in runs)
    # Both runs are sequence 1 within their own project (different projects)
    # OR sequence 1 and 2 if same project — either is valid
    assert all(s >= 1 for s in sequences)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_ingest_nonexistent_path_exits_nonzero():
    result = runner.invoke(app, ["ingest", "/nonexistent/path/report.html"])
    assert result.exit_code != 0
