#!/usr/bin/env python
"""Seed incident-scenario test runs into ~/.ari/ari.db.

Adds three new runs for the existing "ShopNow E-Commerce" project.
Each run contains a realistic incident — one root cause causing multiple
test failures — alongside unrelated unique failures and passing tests.

Run A  — DB connection pool exhausted (6 tests share same error)
         + 2 unrelated unique failures
Run B  — NullPointerException in PaymentService (4 tests share same error)
         + 2 unrelated unique failures
Run C  — Two incidents fire simultaneously (3+3+3 tests across 3 incidents)
         + 2 unique failures

Usage::

    python scripts/seed_incident_runs.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ari.db.repository import RunRepository
from ari.db.schema import get_connection
from ari.models.failure import FailureInfo
from ari.models.run import RunMetadata, TestRun
from ari.models.test_case import TestCaseResult, TestStatus

DB_PATH = Path.home() / ".ari" / "ari.db"
PROJECT = "ShopNow E-Commerce"

# Full suite — same test names that exist in every existing run
ALL_TESTS: list[tuple[str, str]] = [
    ("testValidUserLogin()",               "Authentication Tests"),
    ("testLoginWithInvalidPassword()",     "Authentication Tests"),
    ("testLoginWithLockedAccount()",       "Authentication Tests"),
    ("testLogoutClearsSession()",          "Authentication Tests"),
    ("testPasswordResetEmail()",           "Authentication Tests"),
    ("testRememberMeToken()",              "Authentication Tests"),
    ("testTwoFactorAuthFlow()",            "Authentication Tests"),
    ("testAddItemToCart()",                "Cart & Checkout Tests"),
    ("testRemoveItemFromCart()",           "Cart & Checkout Tests"),
    ("testApplyCouponCode()",              "Cart & Checkout Tests"),
    ("testEnterShippingAddress()",         "Cart & Checkout Tests"),
    ("testPlaceOrderConfirmation()",       "Cart & Checkout Tests"),
    ("testSelectPaymentMethod()",          "Cart & Checkout Tests"),
    ("testCartPersistsAfterLogin()",       "Cart & Checkout Tests"),
    ("testCreditCardPayment()",            "Payment Tests"),
    ("testPayPalRedirect()",               "Payment Tests"),
    ("testRefundProcessing()",             "Payment Tests"),
    ("testPartialRefund()",                "Payment Tests"),
    ("testDebitCardDeclined()",            "Payment Tests"),
    ("testSearchWithFilters()",            "Search Tests"),
    ("testAutocompleteSuggestions()",      "Search Tests"),
    ("testSearchReturnsRelevantProducts()", "Search Tests"),
    ("testSearchNoResults()",              "Search Tests"),
    ("testProductDetailPage()",            "Product Tests"),
    ("testProductImageGallery()",          "Product Tests"),
    ("testOutOfStockBadge()",              "Product Tests"),
    ("testEnableEmailNotifications()",     "Notification Tests"),
    ("testOrderShippedEmail()",            "Notification Tests"),
    ("testDisableNotifications()",         "Notification Tests"),
    ("testCreateOrder()",                  "Order Tests"),
    ("testCancelOrder()",                  "Order Tests"),
    ("testOrderHistoryList()",             "Order Tests"),
    ("testTrackShipment()",                "Order Tests"),
    ("testRejectUnsupportedFileType()",    "Document Tests"),
    ("testUploadPdfAttachment()",          "Document Tests"),
    ("testDownloadInvoicePdf()",           "Document Tests"),
    ("testUpdatePhoneNumber()",            "Profile Tests"),
    ("testChangePassword()",               "Profile Tests"),
    ("testUploadProfilePicture()",         "Profile Tests"),
    ("testDownloadMonthlyReportPdf()",     "Dashboard Tests"),
    ("testDashboardLoadsInUnder3s()",      "Dashboard Tests"),
    ("testWidgetRefreshOnFilter()",        "Dashboard Tests"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(tc_prefix: str, name: str, suite: str) -> TestCaseResult:
    slug = name.replace("()", "").replace(" ", "_").lower()
    return TestCaseResult(
        test_id=f"{tc_prefix}_{slug}",
        name=name,
        status=TestStatus.PASSED,
        suite=suite,
    )


def _fail(
    tc_prefix: str,
    name: str,
    suite: str,
    error_type: str,
    message: str,
    status: TestStatus = TestStatus.FAILED,
) -> TestCaseResult:
    slug = name.replace("()", "").replace(" ", "_").lower()
    return TestCaseResult(
        test_id=f"{tc_prefix}_{slug}",
        name=name,
        status=status,
        suite=suite,
        failure=FailureInfo(error_type=error_type, message=message),
    )


def _make_run(
    run_id: str,
    ts: float,
    tests: list[TestCaseResult],
    branch: str = "main",
) -> TestRun:
    started  = datetime.fromtimestamp(ts,       tz=timezone.utc)
    finished = datetime.fromtimestamp(ts + 420, tz=timezone.utc)
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/ci/shopnow/{run_id}",
        project=PROJECT,
        environment="staging",
        branch=branch,
        started_at=started,
        finished_at=finished,
    )
    return TestRun(metadata=meta, test_cases=tests)


# ---------------------------------------------------------------------------
# Run A — database connection-pool exhaustion incident
#
# One shared root cause (ConnectionPoolException with an identical message)
# fans out across 6 tests in 4 different suites.  The incident tool should
# group all 6 into a single "critical" incident.
#
# Additionally two tests fail for completely unrelated reasons so the UI
# shows them as separate low-impact incidents.
# ---------------------------------------------------------------------------

_CONN_POOL_ERROR = (
    "ConnectionPoolException",
    "No connections available in pool (pool_size=10, active=10, waiting=0)",
)


def build_run_a() -> TestRun:
    prefix = "inca"
    overrides: dict[str, tuple] = {
        # ── shared incident: DB connection pool exhausted ──────────────────
        "testValidUserLogin()":          (*_CONN_POOL_ERROR, "Authentication Tests",     TestStatus.FAILED),
        "testAddItemToCart()":           (*_CONN_POOL_ERROR, "Cart & Checkout Tests",    TestStatus.FAILED),
        "testCreditCardPayment()":       (*_CONN_POOL_ERROR, "Payment Tests",            TestStatus.FAILED),
        "testCreateOrder()":             (*_CONN_POOL_ERROR, "Order Tests",              TestStatus.FAILED),
        "testProductDetailPage()":       (*_CONN_POOL_ERROR, "Product Tests",            TestStatus.FAILED),
        "testDashboardLoadsInUnder3s()": (*_CONN_POOL_ERROR, "Dashboard Tests",          TestStatus.FAILED),
        # ── unrelated unique failures ──────────────────────────────────────
        "testDebitCardDeclined()": (
            "NoSuchElementException",
            "Element not found: By.id: debit-card-number-field",
            "Payment Tests", TestStatus.FAILED,
        ),
        "testSearchNoResults()": (
            "AssertionError",
            "Expected empty-state label to be visible but found 0 matches for '.no-results-banner'",
            "Search Tests", TestStatus.FAILED,
        ),
    }
    tests = []
    for name, suite in ALL_TESTS:
        if name in overrides:
            et, msg, s, status = overrides[name]
            tests.append(_fail(prefix, name, s, et, msg, status))
        else:
            tests.append(_ok(prefix, name, suite))
    # ts ≈ June 2 2026 09:00 UTC  (1 day after last existing run)
    return _make_run("run-incident-a-shopnow", 1_771_578_000.0, tests, branch="main")


# ---------------------------------------------------------------------------
# Run B — NullPointerException in PaymentService incident
#
# A null payment_request object propagates through 4 tests across Payment
# and Checkout suites, all crashing with the same stack root.
# 2 additional unrelated failures keep things realistic.
# ---------------------------------------------------------------------------

_NPE_PAYMENT = (
    "NullPointerException",
    "Cannot invoke PaymentService.process() because payment_request is null",
)


def build_run_b() -> TestRun:
    prefix = "incb"
    overrides: dict[str, tuple] = {
        # ── shared incident: null payment_request ─────────────────────────
        "testCreditCardPayment()":       (*_NPE_PAYMENT, "Payment Tests",         TestStatus.FAILED),
        "testPayPalRedirect()":          (*_NPE_PAYMENT, "Payment Tests",         TestStatus.FAILED),
        "testPartialRefund()":           (*_NPE_PAYMENT, "Payment Tests",         TestStatus.FAILED),
        "testPlaceOrderConfirmation()":  (*_NPE_PAYMENT, "Cart & Checkout Tests", TestStatus.FAILED),
        # ── unrelated unique failures ──────────────────────────────────────
        "testSearchReturnsRelevantProducts()": (
            "HttpError",
            "HTTP 503 returned from GET /api/search?q=running+shoes&sort=relevance",
            "Search Tests", TestStatus.FAILED,
        ),
        "testRememberMeToken()": (
            "AssertionError",
            "Expected remember-me cookie to persist across sessions but cookie was absent after restart",
            "Authentication Tests", TestStatus.BROKEN,
        ),
    }
    tests = []
    for name, suite in ALL_TESTS:
        if name in overrides:
            et, msg, s, status = overrides[name]
            tests.append(_fail(prefix, name, s, et, msg, status))
        else:
            tests.append(_ok(prefix, name, suite))
    # ts ≈ June 3 2026 09:00 UTC
    return _make_run("run-incident-b-shopnow", 1_771_664_400.0, tests, branch="main")


# ---------------------------------------------------------------------------
# Run C — two incidents fire simultaneously
#
# Incident α: DB connection pool (same error as Run A) — 3 tests
# Incident β: NullPointerException in PaymentService (same as Run B) — 3 tests
# Incident γ: order-history service returns 503 — 3 tests
# Unique:     2 extra tests fail for one-off reasons
#
# The incidents panel should show 5 distinct incidents total (3 grouped + 2
# singles).
# ---------------------------------------------------------------------------

_SVC_DOWN = (
    "AssertionError",
    "Expected HTTP 200 but got 503 — ServiceUnavailable: order-history-service is down",
)


def build_run_c() -> TestRun:
    prefix = "incc"
    overrides: dict[str, tuple] = {
        # ── incident α: connection pool (3 tests) ─────────────────────────
        "testValidUserLogin()":         (*_CONN_POOL_ERROR, "Authentication Tests",  TestStatus.FAILED),
        "testAddItemToCart()":          (*_CONN_POOL_ERROR, "Cart & Checkout Tests", TestStatus.FAILED),
        "testCreateOrder()":            (*_CONN_POOL_ERROR, "Order Tests",           TestStatus.FAILED),
        # ── incident β: null payment_request (3 tests) ────────────────────
        "testCreditCardPayment()":      (*_NPE_PAYMENT, "Payment Tests",         TestStatus.FAILED),
        "testPayPalRedirect()":         (*_NPE_PAYMENT, "Payment Tests",         TestStatus.FAILED),
        "testPlaceOrderConfirmation()": (*_NPE_PAYMENT, "Cart & Checkout Tests", TestStatus.FAILED),
        # ── incident γ: order-history service 503 (3 tests) ───────────────
        "testOrderHistoryList()":       (*_SVC_DOWN, "Order Tests",     TestStatus.FAILED),
        "testTrackShipment()":          (*_SVC_DOWN, "Order Tests",     TestStatus.FAILED),
        "testDownloadMonthlyReportPdf()": (*_SVC_DOWN, "Dashboard Tests", TestStatus.FAILED),
        # ── unique one-off failures ────────────────────────────────────────
        "testTwoFactorAuthFlow()": (
            "JavaScriptException",
            "javascript error: Cannot read properties of undefined (reading 'otp')",
            "Authentication Tests", TestStatus.BROKEN,
        ),
        "testDashboardLoadsInUnder3s()": (
            "TimeoutException",
            "Dashboard did not load within 3000 ms SLA threshold (actual render time: 8421 ms)",
            "Dashboard Tests", TestStatus.FAILED,
        ),
    }
    tests = []
    for name, suite in ALL_TESTS:
        if name in overrides:
            et, msg, s, status = overrides[name]
            tests.append(_fail(prefix, name, s, et, msg, status))
        else:
            tests.append(_ok(prefix, name, suite))
    # ts ≈ June 4 2026 09:00 UTC
    return _make_run("run-incident-c-shopnow", 1_771_750_800.0, tests, branch="release/v2.1")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Database : {DB_PATH}")
    conn = get_connection(str(DB_PATH))
    repo = RunRepository(conn)

    for build_fn in (build_run_a, build_run_b, build_run_c):
        run = build_fn()
        inserted = repo.save_run(run)
        total  = len(run.test_cases)
        failed = sum(1 for tc in run.test_cases if tc.status.is_failing)
        flag   = "✔ inserted" if inserted else "⚠ already exists — skipped"
        print(
            f"  {run.metadata.run_id:<35}  {flag}"
            f"  ({total - failed} passed / {failed} failed / {total} total)"
        )

    conn.close()
    print("\nDone. Refresh the ARI UI to see the new runs in the Incidents tab.")


if __name__ == "__main__":
    main()
