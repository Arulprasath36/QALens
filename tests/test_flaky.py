"""Tests for qara.analyzers.flaky — FlakyScorer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from qara.analyzers.flaky import (
    FlakyClassification,
    FlakyResult,
    FlakyScorer,
    _compute_flip_score,
    _compute_streak,
    _classify,
)
from qara.db.repository import RunRepository
from qara.db.schema import get_connection
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(run_id: str, project: str, tests: list, sequence_hint: int = 0) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/report_{run_id}.html",
        project=project,
        started_at=datetime(2026, 3, sequence_hint or 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _make_tc(tc_id: str, name: str, status: TestStatus) -> TestCaseResult:
    failure = None
    if status in (TestStatus.FAILED, TestStatus.BROKEN):
        failure = FailureInfo(
            error_type="AssertionError",
            message="Expected true but was false",
            stack_trace="    at com.example.Test.run(Test.java:10)",
        )
    return TestCaseResult(test_id=tc_id, name=name, status=status, failure=failure)


@pytest.fixture()
def scorer_with_history():
    """Returns a FlakyScorer connected to an in-memory DB with 4 runs of
    'testLogin': pass, fail, pass, fail (highly flaky).
    And 'testLogout': pass, pass, pass, pass (stable).
    And 'testRegister': fail, fail, fail (consistently broken).
    """
    conn = get_connection(":memory:")
    repo = RunRepository(conn)

    statuses = {
        "testLogin": [TestStatus.PASSED, TestStatus.FAILED, TestStatus.PASSED, TestStatus.FAILED],
        "testLogout": [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
        "testRegister": [TestStatus.FAILED, TestStatus.FAILED, TestStatus.FAILED],
    }

    for i in range(1, 5):
        tests = []
        for name, history in statuses.items():
            if i <= len(history):
                tests.append(_make_tc(f"{name}-{i}", name, history[i - 1]))
        repo.save_run(_make_run(f"run-{i:03d}", "MyProject", tests, sequence_hint=i))

    return FlakyScorer(conn), conn


# ---------------------------------------------------------------------------
# _compute_flip_score
# ---------------------------------------------------------------------------


def test_flip_score_alternating_is_one():
    assert _compute_flip_score(["passed", "failed", "passed", "failed"]) == 1.0


def test_flip_score_stable_is_zero():
    assert _compute_flip_score(["passed", "passed", "passed"]) == 0.0


def test_flip_score_single_entry_is_zero():
    assert _compute_flip_score(["passed"]) == 0.0


def test_flip_score_empty_is_zero():
    assert _compute_flip_score([]) == 0.0


def test_flip_score_partial_flips():
    # pass, pass, fail, pass → 2 flips / 3 pairs = 0.666…
    score = _compute_flip_score(["passed", "passed", "failed", "passed"])
    assert abs(score - 2 / 3) < 0.001


def test_flip_score_skipped_does_not_count_as_flip():
    # pass, skip, fail — pass→skip and skip→fail are not flips;
    # neither adjacent pair is pass↔fail, so score = 0 / 2 = 0.0
    score = _compute_flip_score(["passed", "skipped", "failed"])
    assert score == 0.0  # no valid pass↔fail transitions


# ---------------------------------------------------------------------------
# _compute_streak
# ---------------------------------------------------------------------------


def test_streak_current_passes():
    assert _compute_streak(["failed", "passed", "passed"]) == 2


def test_streak_current_failures():
    assert _compute_streak(["passed", "failed", "failed"]) == -2


def test_streak_empty():
    assert _compute_streak([]) == 0


def test_streak_single_pass():
    assert _compute_streak(["passed"]) == 1


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


def test_classify_insufficient_data():
    assert _classify(1, 1.0, 0.0) == FlakyClassification.INSUFFICIENT_DATA


def test_classify_flaky():
    assert _classify(4, 0.5, 1.0) == FlakyClassification.FLAKY


def test_classify_consistently_broken():
    assert _classify(3, 0.0, 0.0) == FlakyClassification.CONSISTENTLY_BROKEN


def test_classify_stable():
    assert _classify(5, 1.0, 0.0) == FlakyClassification.STABLE


# ---------------------------------------------------------------------------
# FlakyScorer.score
# ---------------------------------------------------------------------------


def test_score_flaky_test(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogin", project="MyProject")
    assert result.classification == FlakyClassification.FLAKY
    assert result.flip_score == 1.0
    assert result.run_count == 4
    conn.close()


def test_score_stable_test(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogout", project="MyProject")
    assert result.classification == FlakyClassification.STABLE
    assert result.pass_rate == 1.0
    assert result.flip_score == 0.0
    conn.close()


def test_score_consistently_broken(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testregister", project="MyProject")
    assert result.classification == FlakyClassification.CONSISTENTLY_BROKEN
    assert result.pass_rate == 0.0
    conn.close()


def test_score_unknown_test_returns_insufficient(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("nonexistenttest", project="MyProject")
    assert result.classification == FlakyClassification.INSUFFICIENT_DATA
    assert result.run_count == 0
    conn.close()


def test_score_history_ordered_oldest_first(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogin", project="MyProject")
    assert result.history == ["passed", "failed", "passed", "failed"]
    conn.close()


def test_score_sparkline(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogin", project="MyProject")
    assert result.sparkline == "✓✗✓✗"
    conn.close()


def test_score_last_passed_seq(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogin", project="MyProject")
    # Last pass was run 3, last fail was run 4
    assert result.last_passed_seq == 3
    assert result.last_failed_seq == 4
    conn.close()


def test_score_stable_never_failed(scorer_with_history):
    scorer, conn = scorer_with_history
    result = scorer.score("testlogout", project="MyProject")
    assert result.last_failed_seq is None
    conn.close()


# ---------------------------------------------------------------------------
# FlakyScorer.get_all / get_all_flaky
# ---------------------------------------------------------------------------


def test_get_all_returns_all_with_min_runs(scorer_with_history):
    scorer, conn = scorer_with_history
    results = scorer.get_all(project="MyProject", min_runs=2)
    # testRegister only has 3 runs, testLogin 4, testLogout 4 → all qualify
    names = {r.canonical_name for r in results}
    assert "testlogin" in names
    assert "testlogout" in names
    assert "testregister" in names
    conn.close()


def test_get_all_flaky_returns_only_flaky(scorer_with_history):
    scorer, conn = scorer_with_history
    results = scorer.get_all_flaky(project="MyProject")
    assert all(r.classification == FlakyClassification.FLAKY for r in results)
    conn.close()


def test_get_all_sorted_by_flip_score_desc(scorer_with_history):
    scorer, conn = scorer_with_history
    results = scorer.get_all(project="MyProject", min_runs=2)
    scores = [r.flip_score for r in results]
    assert scores == sorted(scores, reverse=True)
    conn.close()


def test_get_consistently_broken(scorer_with_history):
    scorer, conn = scorer_with_history
    results = scorer.get_consistently_broken(project="MyProject")
    assert len(results) == 1
    assert results[0].canonical_name == "testregister"
    conn.close()
