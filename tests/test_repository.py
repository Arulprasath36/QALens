"""Tests for ari.db.repository — RunRepository persistence and queries."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from qara.db.repository import RunRepository, TestHistoryEntry
from qara.db.schema import get_connection
from qara.models.attachment import Attachment, AttachmentKind
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    *,
    run_id: str = "run-001",
    project: str = "MyProject",
    format: str = "extent",
    tests: list[TestCaseResult] | None = None,
    started_hour: int = 10,
) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format=format,
        report_path=f"/tmp/fake_report_{run_id}.html",  # unique path per run
        project=project,
        started_at=datetime(2026, 3, 7, started_hour, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 3, 7, started_hour, 5, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests or [])


def _make_tc(
    *,
    tc_id: str = "tc-001",
    name: str = "testLogin",
    status: TestStatus = TestStatus.PASSED,
    failure: FailureInfo | None = None,
) -> TestCaseResult:
    return TestCaseResult(
        test_id=tc_id,
        name=name,
        status=status,
        failure=failure,
    )


def _make_failure(
    error_type: str = "AssertionError",
    message: str = "Expected true but was false",
    stack_trace: str | None = "    at com.example.Foo.bar(Foo.java:10)",
) -> FailureInfo:
    return FailureInfo(
        error_type=error_type,
        message=message,
        stack_trace=stack_trace,
    )


@pytest.fixture()
def repo() -> RunRepository:
    conn = get_connection(":memory:")
    r = RunRepository(conn)
    yield r
    conn.close()


# ---------------------------------------------------------------------------
# save_run
# ---------------------------------------------------------------------------


def test_save_run_returns_true_on_insert(repo):
    run = _make_run()
    inserted = repo.save_run(run)
    assert inserted is True


def test_save_run_returns_false_on_duplicate(repo):
    run = _make_run()
    repo.save_run(run)
    assert repo.save_run(run) is False


def test_run_sequence_increments_per_project(repo):
    repo.save_run(_make_run(run_id="r1", project="Proj"))
    repo.save_run(_make_run(run_id="r2", project="Proj"))
    repo.save_run(_make_run(run_id="r3", project="Proj"))

    r1 = repo.get_run("r1")
    r2 = repo.get_run("r2")
    r3 = repo.get_run("r3")
    assert r1.run_sequence == 1
    assert r2.run_sequence == 2
    assert r3.run_sequence == 3


def test_run_sequence_independent_across_projects(repo):
    repo.save_run(_make_run(run_id="a1", project="Alpha"))
    repo.save_run(_make_run(run_id="b1", project="Beta"))
    repo.save_run(_make_run(run_id="a2", project="Alpha"))

    assert repo.get_run("a1").run_sequence == 1
    assert repo.get_run("b1").run_sequence == 1
    assert repo.get_run("a2").run_sequence == 2


def test_save_run_stores_test_cases(repo):
    tc = _make_tc()
    run = _make_run(tests=[tc])
    repo.save_run(run)

    tcs = repo.get_test_cases_for_run("run-001")
    assert len(tcs) == 1
    assert tcs[0].name == "testLogin"
    assert tcs[0].status == "passed"


def test_save_run_stores_failure(repo):
    failure = _make_failure()
    tc = _make_tc(
        tc_id="tc-fail",
        name="testBroken",
        status=TestStatus.FAILED,
        failure=failure,
    )
    run = _make_run(tests=[tc])
    repo.save_run(run)

    tcs = repo.get_test_cases_for_run("run-001")
    assert len(tcs) == 1
    result = tcs[0]
    assert result.error_type == "AssertionError"
    assert result.fingerprint is not None
    assert len(result.fingerprint) == 16


def test_save_run_stores_canonical_name(repo):
    tc = _make_tc(name="TestVerifyLogin [data-set-2]")
    run = _make_run(tests=[tc])
    repo.save_run(run)

    tcs = repo.get_test_cases_for_run("run-001")
    assert tcs[0].canonical_name == "testverifylogin"


def test_save_run_stores_attachment(repo):
    att = Attachment(name="screenshot.png", kind=AttachmentKind.SCREENSHOT, path="screenshot.png")
    tc = _make_tc()
    tc.attachments = [att]
    run = _make_run(tests=[tc])
    repo.save_run(run)

    # Verify attachment row exists — query by run_id join since tc_id is now run-scoped
    conn = repo._conn
    rows = conn.execute(
        "SELECT a.* FROM attachments a JOIN test_cases tc ON tc.tc_id = a.tc_id"
        " WHERE tc.run_id = ?",
        ("run-001",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "screenshot"


# ---------------------------------------------------------------------------
# get_run / list_runs
# ---------------------------------------------------------------------------


def test_get_run_returns_none_for_missing(repo):
    assert repo.get_run("nonexistent") is None


def test_get_run_returns_correct_project(repo):
    repo.save_run(_make_run(project="OrangeHRM"))
    row = repo.get_run("run-001")
    assert row.project == "OrangeHRM"


def test_list_runs_returns_all(repo):
    repo.save_run(_make_run(run_id="r1"))
    repo.save_run(_make_run(run_id="r2"))
    assert len(repo.list_runs()) == 2


def test_list_runs_filters_by_project(repo):
    repo.save_run(_make_run(run_id="a1", project="Alpha"))
    repo.save_run(_make_run(run_id="b1", project="Beta"))
    assert len(repo.list_runs(project="Alpha")) == 1


# ---------------------------------------------------------------------------
# get_test_cases_for_run
# ---------------------------------------------------------------------------


def test_get_test_cases_filters_by_status(repo):
    pass_tc = _make_tc(tc_id="tc-p", name="testPass", status=TestStatus.PASSED)
    fail_tc = _make_tc(
        tc_id="tc-f",
        name="testFail",
        status=TestStatus.FAILED,
        failure=_make_failure(),
    )
    run = _make_run(tests=[pass_tc, fail_tc])
    repo.save_run(run)

    failed = repo.get_test_cases_for_run("run-001", status="failed")
    assert len(failed) == 1
    assert failed[0].name == "testFail"


# ---------------------------------------------------------------------------
# get_test_history
# ---------------------------------------------------------------------------


def test_get_test_history_across_runs(repo):
    for i, status in enumerate([TestStatus.PASSED, TestStatus.FAILED, TestStatus.PASSED], 1):
        failure = _make_failure() if status == TestStatus.FAILED else None
        tc = _make_tc(tc_id=f"tc-{i}", name="testLogin", status=status, failure=failure)
        repo.save_run(_make_run(run_id=f"run-{i:03d}", project="Proj", tests=[tc]))

    history = repo.get_test_history("testlogin", project="Proj")
    assert len(history) == 3
    statuses = [h.status for h in history]
    assert statuses == ["passed", "failed", "passed"]


def test_get_test_history_ordered_by_sequence(repo):
    for i, status in enumerate([TestStatus.FAILED, TestStatus.PASSED], 1):
        failure = _make_failure() if status == TestStatus.FAILED else None
        tc = _make_tc(tc_id=f"tc-{i}", name="testLogin", status=status, failure=failure)
        repo.save_run(_make_run(run_id=f"r-{i}", project="P", tests=[tc]))

    history = repo.get_test_history("testlogin", project="P")
    seqs = [h.run_sequence for h in history]
    assert seqs == sorted(seqs)


def test_get_test_history_respects_limit(repo):
    for i in range(5):
        tc = _make_tc(tc_id=f"tc-{i}", name="testLogin", status=TestStatus.PASSED)
        repo.save_run(_make_run(run_id=f"r-{i}", project="P", tests=[tc]))

    history = repo.get_test_history("testlogin", project="P", limit=3)
    assert len(history) == 3


def test_get_test_history_limit_returns_most_recent(repo):
    """limit=N must return the N *most recent* runs, not the N oldest.

    Regression: previously ORDER BY run_sequence ASC LIMIT N returned the
    oldest N entries, so recent failures were invisible to the LLM.
    """
    statuses = [
        TestStatus.FAILED,   # seq 1 — old failure (should be excluded by limit=3)
        TestStatus.PASSED,   # seq 2
        TestStatus.PASSED,   # seq 3
        TestStatus.FAILED,   # seq 4 — recent failure (must be included)
        TestStatus.FAILED,   # seq 5 — most recent failure (must be included)
    ]
    for i, status in enumerate(statuses, 1):
        failure = _make_failure() if status == TestStatus.FAILED else None
        tc = _make_tc(tc_id=f"tc-lim-{i}", name="testLogin", status=status, failure=failure)
        repo.save_run(_make_run(run_id=f"r-lim-{i}", project="P", tests=[tc]))

    history = repo.get_test_history("testlogin", project="P", limit=3)
    assert len(history) == 3
    # Must be the 3 most recent (sequences 3, 4, 5), still returned oldest→newest
    seqs = [h.run_sequence for h in history]
    assert seqs == sorted(seqs), "results must be ordered oldest→newest"
    assert seqs[-1] == max(seqs), "most recent run must be present"
    # The old seq-1 failure must NOT be present; seq-4 and seq-5 failures must be
    failure_seqs = [h.run_sequence for h in history if h.status == "failed"]
    assert 4 in failure_seqs, "recent failure at seq 4 must be included"
    assert 5 in failure_seqs, "recent failure at seq 5 must be included"


# ---------------------------------------------------------------------------
# run_exists / count_runs
# ---------------------------------------------------------------------------


def test_run_exists_true_after_save(repo):
    repo.save_run(_make_run())
    assert repo.run_exists("run-001") is True


def test_run_exists_false_for_unknown(repo):
    assert repo.run_exists("ghost") is False


def test_count_runs_total(repo):
    repo.save_run(_make_run(run_id="r1"))
    repo.save_run(_make_run(run_id="r2"))
    assert repo.count_runs() == 2


def test_count_runs_per_project(repo):
    repo.save_run(_make_run(run_id="a1", project="Alpha"))
    repo.save_run(_make_run(run_id="a2", project="Alpha"))
    repo.save_run(_make_run(run_id="b1", project="Beta"))
    assert repo.count_runs(project="Alpha") == 2
    assert repo.count_runs(project="Beta") == 1
