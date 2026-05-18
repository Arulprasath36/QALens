"""Shared fixture builders for the LLM orchestration contract-test suite.

These helpers create deterministic in-memory DB scenarios that exercise
the five core answer families: REGRESSION_DIFF, FLAKINESS_BINARY,
FLAKINESS_RANKING, RISK_RANKING, TREND.

Usage::

    db_path = build_two_run_scenario(tmp_path)
    # then pass db_path into any routing / payload function
"""

from __future__ import annotations

from datetime import datetime, timezone

from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection, init_db
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------


def make_tc(
    name: str,
    status: str,
    *,
    error_type: str | None = None,
    message: str | None = None,
) -> TestCaseResult:
    """Create a minimal TestCaseResult."""
    from qalens.models.failure import FailureInfo

    failure = None
    if error_type or message:
        failure = FailureInfo(error_type=error_type or "", message=message or "")

    return TestCaseResult(
        test_id=f"tc-{name}",
        name=name,
        status=TestStatus(status),
        failure=failure,
    )


def make_run(
    run_id: str,
    project: str,
    tests: list[TestCaseResult],
    *,
    hour: int = 10,
) -> TestRun:
    """Create a minimal TestRun with the given tests."""
    meta = RunMetadata(
        run_id=run_id,
        report_format="extent",
        report_path=f"/tmp/fake_{run_id}.html",
        project=project,
        started_at=datetime(2026, 1, 1, hour, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, hour, 5, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


# ---------------------------------------------------------------------------
# Scenario: two-run regression (older passing, newer with failures)
# ---------------------------------------------------------------------------

# Test name constants for cross-test assertions
PROJECT = "ContractProject"

# ── Two-run scenario test groups ──────────────────────────────────────────
# These groups define the exact transition between run_001 (older) and
# run_002 (newer) in build_two_run_scenario().

# Newly failing in run_002 (passed in run_001, failed in run_002)
NEWLY_FAILING = [
    "testAddItemToCart",
    "testCreateOrder",
    "testProcessPayment",
]

# Recovered in run_002 (failed in run_001, passed in run_002)
RECOVERED = [
    "testPartialRefund",
    "testRememberMeToken",
    "testSearchReturnsRelevantProducts",
]

# Consistently failing (failed in both runs)
CONSISTENTLY_FAILING = [
    "testApplyCouponCode",
]

# Consistently passing (passed in both runs)
CONSISTENTLY_PASSING = [
    "testValidUserLogin",
    "testBrowseProductCatalog",
]

# ── Multi-run scenario test groups ────────────────────────────────────────
# These groups define the final-two-run transition in build_multi_run_scenario()
# (run_004 → run_005) which is what the payload builders see via list_runs(limit=2).

# Newly failing between run_004 and run_005
# (run_004=passed, run_005=failed)
MULTI_RUN_NEWLY_FAILING = [
    "testAddItemToCart",
    "testCreateOrder",
    "testProcessPayment",
]

# Recovered between run_004 and run_005
# (run_004=failed, run_005=passed)
MULTI_RUN_RECOVERED = [
    "testPartialRefund",
    "testRememberMeToken",
    "testSearchReturnsRelevantProducts",
]

# Stable controls — tests with no status changes across all runs.
# These must NEVER appear in newly-failing scope or flakiness payloads.
STABLE_CONTROLS = [
    "testValidUserLogin",       # always passing (5/5)
    "testApplyCouponCode",      # always failing (5/5) — stable but broken
]


def build_two_run_scenario(tmp_path) -> str:
    """Create a DB with two runs for regression-diff / scope testing.

    Run layout:
    - run_001 (older): NEWLY_FAILING=passed, RECOVERED=failed, CONSISTENTLY_FAILING=failed, CONSISTENTLY_PASSING=passed
    - run_002 (newer): NEWLY_FAILING=failed, RECOVERED=passed, CONSISTENTLY_FAILING=failed, CONSISTENTLY_PASSING=passed

    Returns the path to the DB file.
    """
    db_path = str(tmp_path / "contract.db")
    conn = get_connection(db_path)
    init_db(conn)
    repo = RunRepository(conn)

    # Older run
    older_tests = (
        [make_tc(n, "passed") for n in NEWLY_FAILING]
        + [make_tc(n, "failed", error_type="OldError", message="was broken") for n in RECOVERED]
        + [make_tc(n, "failed", error_type="PersistentError", message="still broken") for n in CONSISTENTLY_FAILING]
        + [make_tc(n, "passed") for n in CONSISTENTLY_PASSING]
    )
    repo.save_run(make_run("run_001", PROJECT, older_tests, hour=10))

    # Newer run
    newer_tests = (
        [make_tc(n, "failed", error_type="NewError", message="new breakage") for n in NEWLY_FAILING]
        + [make_tc(n, "passed") for n in RECOVERED]
        + [make_tc(n, "failed", error_type="PersistentError", message="still broken") for n in CONSISTENTLY_FAILING]
        + [make_tc(n, "passed") for n in CONSISTENTLY_PASSING]
    )
    repo.save_run(make_run("run_002", PROJECT, newer_tests, hour=11))

    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Scenario: multi-run history (for flakiness / trend / risk)
# ---------------------------------------------------------------------------


def build_multi_run_scenario(tmp_path, *, n_runs: int = 5) -> str:
    """Create a DB with *n_runs* runs for flakiness/trend analysis.

    Status patterns across 5 runs (oldest → newest):

    ====================================  =====  =====  =====  =====  =====  ===========================
    Test name                             Run 1  Run 2  Run 3  Run 4  Run 5  Role
    ====================================  =====  =====  =====  =====  =====  ===========================
    testAddItemToCart                        P      P      F      P      F    Flaky (2 flips)
    testCreateOrder                          P      P      P      P      F    Stable until last run
    testProcessPayment                       F      P      F      P      F    Very flaky (4 flips)
    testValidUserLogin                       P      P      P      P      P    Stable control (always pass)
    testApplyCouponCode                      F      F      F      F      F    Stable control (always fail)
    testPartialRefund                        P      P      P      F      P    Recovered in run_005
    testRememberMeToken                      P      P      P      F      P    Recovered in run_005
    testSearchReturnsRelevantProducts        P      P      P      F      P    Recovered in run_005
    ====================================  =====  =====  =====  =====  =====  ===========================

    The last two runs (run_004 → run_005) produce:
    - MULTI_RUN_NEWLY_FAILING: testAddItemToCart, testCreateOrder, testProcessPayment
    - MULTI_RUN_RECOVERED: testPartialRefund, testRememberMeToken, testSearchReturnsRelevantProducts
    - STABLE_CONTROLS: testValidUserLogin (always pass), testApplyCouponCode (always fail)

    Returns the path to the DB file.
    """
    db_path = str(tmp_path / "multi_run.db")
    conn = get_connection(db_path)
    init_db(conn)
    repo = RunRepository(conn)

    # Define per-test status patterns across n_runs runs
    patterns: dict[str, list[str]] = {
        "testAddItemToCart":                ["passed", "passed", "failed", "passed", "failed"],
        "testCreateOrder":                  ["passed", "passed", "passed", "passed", "failed"],
        "testProcessPayment":               ["failed", "passed", "failed", "passed", "failed"],
        "testValidUserLogin":               ["passed", "passed", "passed", "passed", "passed"],
        "testApplyCouponCode":              ["failed", "failed", "failed", "failed", "failed"],
        "testPartialRefund":                ["passed", "passed", "passed", "failed", "passed"],
        "testRememberMeToken":              ["passed", "passed", "passed", "failed", "passed"],
        "testSearchReturnsRelevantProducts": ["passed", "passed", "passed", "failed", "passed"],
    }

    for run_idx in range(n_runs):
        run_id = f"run_{run_idx + 1:03d}"
        tests = []
        for test_name, statuses in patterns.items():
            status = statuses[run_idx] if run_idx < len(statuses) else "passed"
            error_kw = {}
            if status == "failed":
                error_kw = {"error_type": "TestError", "message": f"failure in {run_id}"}
            tests.append(make_tc(test_name, status, **error_kw))
        repo.save_run(make_run(run_id, PROJECT, tests, hour=10 + run_idx))

    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_scope_contains_exactly(scope, expected_names: list[str]) -> None:
    """Assert scope.tests matches *expected_names* exactly (order-insensitive)."""
    assert sorted(scope.tests) == sorted(expected_names), (
        f"Scope mismatch.\n"
        f"  Expected: {sorted(expected_names)}\n"
        f"  Got:      {sorted(scope.tests)}"
    )


def assert_scope_excludes(scope, excluded_names: list[str]) -> None:
    """Assert none of *excluded_names* appear in scope.tests."""
    leaked = [n for n in excluded_names if n in scope.tests]
    assert not leaked, f"Scope leaked: {leaked}"


def assert_payload_has_sections(payload, expected_headings: list[str]) -> None:
    """Assert all *expected_headings* appear in non-empty payload sections."""
    actual = [s.heading for s in payload.sections if not s.empty]
    for h in expected_headings:
        # Check prefix match — headings may include counts like "Newly Failing (3)"
        found = any(h in actual_h for actual_h in actual)
        assert found, (
            f"Missing section '{h}' in payload.\n"
            f"  Actual non-empty sections: {actual}"
        )


def assert_payload_excludes_sections(payload, excluded_headings: list[str]) -> None:
    """Assert none of *excluded_headings* appear in non-empty payload sections."""
    actual = [s.heading for s in payload.sections if not s.empty]
    for h in excluded_headings:
        found = any(h in actual_h for actual_h in actual)
        assert not found, (
            f"Unexpected section '{h}' in payload.\n"
            f"  Actual non-empty sections: {actual}"
        )


def assert_ranking_order(items: list[str], expected_order: list[str]) -> None:
    """Assert test names appear in *expected_order* within the items list.

    Does NOT require exact item match — just that the relative ordering
    of expected_order names is preserved when scanning the items.
    """
    positions: dict[str, int] = {}
    for idx, item in enumerate(items):
        for name in expected_order:
            if name in item and name not in positions:
                positions[name] = idx

    missing = [n for n in expected_order if n not in positions]
    assert not missing, f"Missing from ranking: {missing}"

    actual_sequence = [positions[n] for n in expected_order]
    assert actual_sequence == sorted(actual_sequence), (
        f"Ranking order violated.\n"
        f"  Expected order: {expected_order}\n"
        f"  Actual positions: {positions}"
    )
