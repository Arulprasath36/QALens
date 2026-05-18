"""Tests for qalens.analyzers.predictor — RiskPredictor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from qalens.analyzers.predictor import (
    RiskPredictor,
    RiskPrediction,
    RiskSignals,
    RiskTier,
    _compute_risk,
    _duration_trend,
    _module_label,
)
from qalens.analyzers.flaky import FlakyResult, FlakyClassification
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(run_id: str, project: str, tests: list, sequence_hint: int = 1) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/report_{run_id}.html",
        project=project,
        started_at=datetime(2026, 3, sequence_hint, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _make_tc(
    tc_id: str,
    name: str,
    status: TestStatus,
    *,
    duration_ms: int | None = None,
    suite: str | None = None,
) -> TestCaseResult:
    failure = None
    if status in (TestStatus.FAILED, TestStatus.BROKEN):
        failure = FailureInfo(
            error_type="AssertionError",
            message="Expected value does not match",
            stack_trace="at com.example.Test.run(Test.java:42)",
        )
    return TestCaseResult(
        test_id=tc_id,
        name=name,
        status=status,
        failure=failure,
        duration_ms=duration_ms,
        suite=suite,
    )


@pytest.fixture()
def predictor_db():
    """In-memory DB with:
    - testLogin: pass, fail, pass, fail  (highly flaky, no streak)
    - testLogout: pass, pass, pass, pass (stable)
    - testRegister: fail, fail, fail     (consistently broken, streak=-3)
    - testDashboard: pass, pass, fail    (mildly declining)
    """
    conn = get_connection(":memory:")
    repo = RunRepository(conn)

    data = {
        "testLogin":    [TestStatus.PASSED, TestStatus.FAILED, TestStatus.PASSED, TestStatus.FAILED],
        "testLogout":   [TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED, TestStatus.PASSED],
        "testRegister": [TestStatus.FAILED, TestStatus.FAILED, TestStatus.FAILED],
        "testDashboard":[TestStatus.PASSED, TestStatus.PASSED, TestStatus.FAILED],
    }
    durations = {
        "testLogin":    [100, 110, 105, 115],
        "testLogout":   [200, 200, 200, 200],
        "testRegister": [300, 300, 300],
        "testDashboard":[150, 160, 400],  # big spike → high duration trend
    }
    suites = {
        "testLogin":    "AuthSuite",
        "testLogout":   "AuthSuite",
        "testRegister": "RegistrationSuite",
        "testDashboard": None,
    }

    for i in range(1, 5):
        tests = []
        for name, hist in data.items():
            if i <= len(hist):
                tests.append(_make_tc(
                    f"{name}-{i}",
                    name,
                    hist[i - 1],
                    duration_ms=durations[name][i - 1],
                    suite=suites[name],
                ))
        repo.save_run(_make_run(f"run-{i:03d}", "MyProject", tests, sequence_hint=i))

    return RiskPredictor(conn), conn


# ---------------------------------------------------------------------------
# _duration_trend — unit tests
# ---------------------------------------------------------------------------


def test_duration_trend_flat():
    assert _duration_trend([100.0, 100.0, 100.0]) == 0.0


def test_duration_trend_growing():
    score = _duration_trend([100.0, 200.0, 300.0, 400.0])
    assert score > 0.0
    assert score <= 1.0


def test_duration_trend_shrinking():
    # Getting faster should return 0.0 (clamped, not negative)
    assert _duration_trend([400.0, 300.0, 200.0, 100.0]) == 0.0


def test_duration_trend_too_few():
    assert _duration_trend([]) == 0.0
    assert _duration_trend([100.0]) == 0.0
    assert _duration_trend([100.0, 200.0]) == 0.0


def test_duration_trend_zero_mean():
    assert _duration_trend([0.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# _module_label — unit tests
# ---------------------------------------------------------------------------


def test_module_label_uses_suite():
    assert _module_label("AuthSuite", "testLogin") == "AuthSuite"


def test_module_label_strips_test_prefix():
    assert _module_label(None, "testLoginUser") == "Login"


def test_module_label_no_prefix():
    # "LoginTest" has no "test" prefix, first camelCase word is "Login"
    assert _module_label(None, "LoginTest") == "Login"


def test_module_label_fallback():
    assert _module_label(None, "test") == "(unclassified)"


def test_module_label_empty_suite():
    result = _module_label("", "testCheckout")
    assert result == "Checkout"


# ---------------------------------------------------------------------------
# _compute_risk — unit tests
# ---------------------------------------------------------------------------


def _make_result(history: list[str], current_streak: int = 0) -> FlakyResult:
    """Construct a minimal FlakyResult from a history list."""
    from qalens.analyzers.flaky import _compute_flip_score, _classify

    pass_count = sum(1 for s in history if s == "passed")
    fail_count = sum(1 for s in history if s in ("failed", "broken"))
    run_count = len(history)
    pass_rate = pass_count / run_count if run_count else 0.0
    flip_score = _compute_flip_score(history)
    classification = _classify(run_count, pass_rate, flip_score)
    return FlakyResult(
        canonical_name="testfoo",
        display_name="testFoo",
        project=None,
        run_count=run_count,
        pass_count=pass_count,
        fail_count=fail_count,
        skip_count=0,
        pass_rate=pass_rate,
        flip_score=flip_score,
        classification=classification,
        history=history,
        last_passed_seq=None,
        last_failed_seq=None,
        current_streak=current_streak,
    )


def test_compute_risk_stable():
    result = _make_result(["passed", "passed", "passed", "passed"])
    score, signals = _compute_risk(result, duration_trend=0.0)
    assert score == 0.0
    assert signals.volatility == 0.0
    assert signals.failure_burden == 0.0


def test_compute_risk_consistently_broken():
    result = _make_result(["failed", "failed", "failed"], current_streak=-3)
    score, signals = _compute_risk(result, duration_trend=0.0)
    # failure_burden = 1.0, streak = 1.0, no flip/recent_decline
    # 0.25 * 1.0 + 0.15 * 1.0 = 0.40
    assert score == pytest.approx(0.40, abs=0.01)
    assert signals.fail_streak == pytest.approx(1.0)


def test_compute_risk_highly_flaky():
    result = _make_result(["passed", "failed", "passed", "failed"], current_streak=-1)
    score, signals = _compute_risk(result, duration_trend=0.0)
    # flip_score = 1.0, failure_burden = 0.5, recent_decline should be 0
    # (last 3 = [p, f, f] → recent_fail = 0.67, all_fail= 0.5 → decline=0.17)
    # 0.30*1.0 + 0.25*0.5 + 0.25*0.17 + 0.15*0.33 = 0.30 + 0.125 + 0.042 + 0.05 ≈ 0.52
    assert score > 0.4
    assert signals.volatility == pytest.approx(1.0)


def test_compute_risk_with_duration_spike():
    result = _make_result(["passed", "passed", "passed"])
    score, signals = _compute_risk(result, duration_trend=1.0)
    assert score == pytest.approx(0.05)  # only duration_spike contribution
    assert signals.duration_spike == pytest.approx(1.0)


def test_compute_risk_clamped_to_one():
    # Worst possible: fully flaky, always failing, on streak, duration spike
    result = _make_result(
        ["failed", "passed"] * 5 + ["failed", "failed", "failed"],
        current_streak=-3,
    )
    score, _ = _compute_risk(result, duration_trend=1.0)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# RiskTier.from_score
# ---------------------------------------------------------------------------


def test_tier_from_score():
    assert RiskTier.from_score(0.75) == RiskTier.CRITICAL
    assert RiskTier.from_score(0.62) == RiskTier.CRITICAL
    assert RiskTier.from_score(0.61) == RiskTier.HIGH
    assert RiskTier.from_score(0.41) == RiskTier.HIGH
    assert RiskTier.from_score(0.40) == RiskTier.MEDIUM
    assert RiskTier.from_score(0.24) == RiskTier.MEDIUM
    assert RiskTier.from_score(0.23) == RiskTier.LOW
    assert RiskTier.from_score(0.00) == RiskTier.LOW


# ---------------------------------------------------------------------------
# RiskPredictor integration tests
# ---------------------------------------------------------------------------


def test_predict_all_returns_predictions(predictor_db):
    predictor, _ = predictor_db
    results = predictor.predict_all(project="MyProject")
    assert len(results) >= 1
    # All results should be valid RiskPrediction instances
    for r in results:
        assert isinstance(r, RiskPrediction)
        assert 0 <= r.risk_pct <= 100
        assert r.tier in list(RiskTier)


def test_predict_all_sorted_by_risk(predictor_db):
    predictor, _ = predictor_db
    results = predictor.predict_all(project="MyProject")
    scores = [r.risk_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_predict_stable_test_has_low_risk(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testLogout"), project="MyProject")
    assert p.tier == RiskTier.LOW
    assert p.risk_pct < 35


def test_predict_broken_test_has_elevated_risk(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testRegister"), project="MyProject")
    assert p.risk_pct >= 35  # at least Medium (has failure_burden + streak)


def test_predict_flaky_test_has_high_volatility(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testLogin"), project="MyProject")
    assert p.signals.volatility > 0


def test_predict_suite_populated_from_db(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testLogin"), project="MyProject")
    assert p.suite == "AuthSuite"
    assert p.module == "AuthSuite"


def test_predict_module_derived_from_name_when_no_suite(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testDashboard"), project="MyProject")
    assert p.suite is None
    assert p.module == "Dashboard"


def test_predict_min_runs_filter(predictor_db):
    predictor, _ = predictor_db
    # With min_runs=5 no test has 5 runs → empty list
    results = predictor.predict_all(project="MyProject", min_runs=5)
    assert results == []


def test_predict_sparkline_present(predictor_db):
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testLogin"), project="MyProject")
    assert p.sparkline
    # Should contain ✓ or ✗
    assert any(c in p.sparkline for c in ("✓", "✗"))


def test_predict_risk_signals_sum_reasonable(predictor_db):
    predictor, _ = predictor_db
    results = predictor.predict_all(project="MyProject")
    for p in results:
        sigs = p.signals
        assert 0.0 <= sigs.volatility <= 1.0
        assert 0.0 <= sigs.failure_burden <= 1.0
        assert 0.0 <= sigs.recent_decline <= 1.0
        assert 0.0 <= sigs.fail_streak <= 1.0
        assert 0.0 <= sigs.duration_spike <= 1.0


def test_predict_all_no_project_filter(predictor_db):
    predictor, _ = predictor_db
    results = predictor.predict_all()  # no project filter
    assert len(results) >= 1


def test_predict_duration_trend_growing(predictor_db):
    """testDashboard has a big duration spike on final run — should score > 0."""
    predictor, _ = predictor_db
    from qalens.analyzers.canonical import to_canonical_name
    p = predictor.predict(to_canonical_name("testDashboard"), project="MyProject")
    assert p.signals.duration_spike > 0.0
