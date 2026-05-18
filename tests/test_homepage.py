"""Tests for GET /api/homepage-cards — dynamic homepage card endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.server.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(
    run_id: str,
    tests: list[TestCaseResult],
    *,
    seq: int = 1,
    project: str = "HPTest",
) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/hp_{run_id}.html",
        project=project,
        started_at=datetime(2026, 4, seq, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _tc(
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
            message=f"{name} failed with {error_type}",
            stack_trace="   at com.example.Test.run(Test.java:1)",
        )
    return TestCaseResult(
        test_id=f"{name}-{idx}",
        name=name,
        status=status,
        failure=failure,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def empty_client(tmp_path: Path) -> TestClient:
    """Client with an empty (no runs) database."""
    db = tmp_path / "hp_empty.db"
    conn = get_connection(str(db))
    RunRepository(conn)  # initialises schema
    conn.close()
    appl = create_app(db_path=str(db), default_project="HPTest")
    return TestClient(appl, raise_server_exceptions=True)


@pytest.fixture()
def single_run_client(tmp_path: Path) -> TestClient:
    """Client with one run: 2 failures, 1 pass."""
    db = tmp_path / "hp_single.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)
    run = _make_run(
        "run-001",
        [
            _tc("testA", TestStatus.FAILED, idx=1, error_type="AssertionError"),
            _tc("testB", TestStatus.FAILED, idx=1, error_type="NullPointerException"),
            _tc("testC", TestStatus.PASSED, idx=1),
        ],
        seq=1,
    )
    repo.save_run(run)
    conn.close()
    appl = create_app(db_path=str(db), default_project="HPTest")
    return TestClient(appl, raise_server_exceptions=True)


@pytest.fixture()
def two_run_client(tmp_path: Path) -> TestClient:
    """Client with two runs so new-regressions can be computed.

    Run 1 (older): testA passes, testB fails.
    Run 2 (newer): testA fails (new regression), testB fails (consistent), testC passes.
    """
    db = tmp_path / "hp_two.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)
    run1 = _make_run(
        "run-001",
        [
            _tc("testA", TestStatus.PASSED, idx=1),
            _tc("testB", TestStatus.FAILED, idx=1, error_type="AssertionError"),
        ],
        seq=1,
    )
    run2 = _make_run(
        "run-002",
        [
            _tc("testA", TestStatus.FAILED, idx=2, error_type="NullPointerException"),
            _tc("testB", TestStatus.FAILED, idx=2, error_type="AssertionError"),
            _tc("testC", TestStatus.PASSED, idx=2),
        ],
        seq=2,
    )
    repo.save_run(run1)
    repo.save_run(run2)
    conn.close()
    appl = create_app(db_path=str(db), default_project="HPTest")
    return TestClient(appl, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Basic response structure
# ---------------------------------------------------------------------------

def test_homepage_cards_returns_200(single_run_client: TestClient) -> None:
    res = single_run_client.get("/api/homepage-cards?project=HPTest")
    assert res.status_code == 200


def test_homepage_cards_has_cards_key(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    assert "cards" in data
    assert isinstance(data["cards"], list)


def test_homepage_cards_returns_four_cards(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    assert len(data["cards"]) == 4


def test_homepage_cards_have_required_fields(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    for card in data["cards"]:
        for field in ("id", "icon", "title", "metric", "question", "available"):
            assert field in card, f"Field '{field}' missing from card {card.get('id')}"


def test_homepage_cards_ids_are_unique_and_known(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    ids = [c["id"] for c in data["cards"]]
    assert set(ids) == {"latest_run", "new_regressions", "risk", "root_cause"}


# ---------------------------------------------------------------------------
# Empty DB — unavailable cards
# ---------------------------------------------------------------------------

def test_empty_db_latest_run_unavailable(empty_client: TestClient) -> None:
    data = empty_client.get("/api/homepage-cards?project=HPTest").json()
    latest = next(c for c in data["cards"] if c["id"] == "latest_run")
    assert latest["available"] is False


def test_empty_db_new_regressions_unavailable(empty_client: TestClient) -> None:
    data = empty_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "new_regressions")
    assert card["available"] is False


def test_empty_db_root_cause_unavailable(empty_client: TestClient) -> None:
    data = empty_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "root_cause")
    assert card["available"] is False


# ---------------------------------------------------------------------------
# Single run — latest run card
# ---------------------------------------------------------------------------

def test_single_run_latest_card_available(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    latest = next(c for c in data["cards"] if c["id"] == "latest_run")
    assert latest["available"] is True


def test_single_run_latest_metric_shows_failures(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    latest = next(c for c in data["cards"] if c["id"] == "latest_run")
    # 2 failures were inserted; metric also includes the run number
    assert "2" in latest["metric"]
    assert "failure" in latest["metric"]
    assert "Run #" in latest["metric"]


def test_single_run_new_regressions_unavailable(single_run_client: TestClient) -> None:
    """Only 1 run — cannot compute new regressions."""
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "new_regressions")
    assert card["available"] is False


# ---------------------------------------------------------------------------
# Two runs — new regressions card
# ---------------------------------------------------------------------------

def test_two_runs_new_regressions_available(two_run_client: TestClient) -> None:
    data = two_run_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "new_regressions")
    assert card["available"] is True


def test_two_runs_new_regressions_metric_counts_correctly(two_run_client: TestClient) -> None:
    """testA is the only newly failing test (was passing, now failing)."""
    data = two_run_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "new_regressions")
    assert "1" in card["metric"]
    assert "new failure" in card["metric"]


def test_two_runs_root_cause_card_available(two_run_client: TestClient) -> None:
    data = two_run_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "root_cause")
    assert card["available"] is True


# ---------------------------------------------------------------------------
# Question strings are suitable for chat
# ---------------------------------------------------------------------------

def test_card_questions_are_non_empty(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    for card in data["cards"]:
        assert card["question"].strip(), f"Empty question on card {card['id']}"


def test_card_latest_run_question(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    latest = next(c for c in data["cards"] if c["id"] == "latest_run")
    assert "latest run" in latest["question"].lower()


def test_card_risk_question(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    risk = next(c for c in data["cards"] if c["id"] == "risk")
    assert "fail" in risk["question"].lower()


def test_card_root_cause_question(single_run_client: TestClient) -> None:
    data = single_run_client.get("/api/homepage-cards?project=HPTest").json()
    card = next(c for c in data["cards"] if c["id"] == "root_cause")
    assert "root cause" in card["question"].lower()
    assert "root cause" in card["question"].lower()


# ---------------------------------------------------------------------------
# No project filter — all-project scope
# ---------------------------------------------------------------------------

def test_cards_work_without_project_filter(single_run_client: TestClient) -> None:
    """Endpoint must not crash when no ?project= is supplied."""
    res = single_run_client.get("/api/homepage-cards")
    assert res.status_code == 200
    data = res.json()
    assert len(data["cards"]) == 4


# ---------------------------------------------------------------------------
# All-passed run — metric should say passes
# ---------------------------------------------------------------------------

def test_all_passed_run_latest_metric(tmp_path: Path) -> None:
    db = tmp_path / "hp_allpass.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)
    run = _make_run(
        "run-001",
        [_tc("testA", TestStatus.PASSED, idx=1), _tc("testB", TestStatus.PASSED, idx=1)],
        seq=1,
    )
    repo.save_run(run)
    conn.close()
    appl = create_app(db_path=str(db), default_project="HPTest")
    client = TestClient(appl, raise_server_exceptions=True)

    data = client.get("/api/homepage-cards?project=HPTest").json()
    latest = next(c for c in data["cards"] if c["id"] == "latest_run")
    assert latest["available"] is True
    assert "passed" in latest["metric"].lower()
