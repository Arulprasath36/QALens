#!/usr/bin/env python3
"""Synthetic Allure report generator for QARA load testing.

Creates a configurable number of Allure v2 report directories under a
given output folder, then optionally ingests them all into a QARA database
so you can exercise the Risk, Analysis, Compare, and Chat tabs with
realistic, varied data.

Usage
-----
# Generate 20 runs for one project and ingest them:
    python scripts/generate_test_data.py --runs 20 --ingest

# Generate 40 runs across three projects, custom output dir:
    python scripts/generate_test_data.py --runs 40 --projects 3 --out /tmp/qara-data --ingest

# Just create the report folders without ingesting:
    python scripts/generate_test_data.py --runs 10

# See all options:
    python scripts/generate_test_data.py --help
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

# ---------------------------------------------------------------------------
# Test catalogue  — realistic suite / test / error data
# ---------------------------------------------------------------------------

PROJECTS = [
    "ShopNow E-Commerce",
    "FinTrack Banking",
    "HealthHub Portal",
]

# Each entry: (suite, class_prefix, test_name, feature, story, severity)
TEST_CATALOGUE: list[tuple[str, str, str, str, str, str]] = [
    # Auth
    ("Authentication Tests", "AuthTest",    "testValidUserLogin",          "Authentication", "Login",            "critical"),
    ("Authentication Tests", "AuthTest",    "testLoginWithInvalidPassword", "Authentication", "Login",            "critical"),
    ("Authentication Tests", "AuthTest",    "testLoginWithLockedAccount",   "Authentication", "Login",            "critical"),
    ("Authentication Tests", "AuthTest",    "testLogoutClearsSession",      "Authentication", "Logout",           "normal"),
    ("Authentication Tests", "AuthTest",    "testRememberMeToken",          "Authentication", "Remember Me",      "minor"),
    ("Authentication Tests", "AuthTest",    "testPasswordResetEmail",       "Authentication", "Password Reset",   "normal"),
    ("Authentication Tests", "AuthTest",    "testTwoFactorAuthFlow",        "Authentication", "2FA",              "critical"),
    # Cart
    ("Cart & Checkout Tests", "CartTest",   "testAddItemToCart",            "Shopping Cart",  "Add Item",         "normal"),
    ("Cart & Checkout Tests", "CartTest",   "testRemoveItemFromCart",       "Shopping Cart",  "Remove Item",      "normal"),
    ("Cart & Checkout Tests", "CartTest",   "testCartPersistsAfterLogin",   "Shopping Cart",  "Persistence",      "normal"),
    ("Cart & Checkout Tests", "CartTest",   "testApplyCouponCode",          "Shopping Cart",  "Discounts",        "minor"),
    ("Cart & Checkout Tests", "CheckoutTest","testEnterShippingAddress",    "Checkout",       "Shipping",         "critical"),
    ("Cart & Checkout Tests", "CheckoutTest","testSelectPaymentMethod",     "Checkout",       "Payment",          "critical"),
    ("Cart & Checkout Tests", "CheckoutTest","testPlaceOrderConfirmation",  "Checkout",       "Order Confirm",    "critical"),
    # Payment
    ("Payment Tests",         "PaymentTest","testCreditCardPayment",        "Payments",       "Credit Card",      "critical"),
    ("Payment Tests",         "PaymentTest","testDebitCardDeclined",        "Payments",       "Declined",         "critical"),
    ("Payment Tests",         "PaymentTest","testPayPalRedirect",           "Payments",       "PayPal",           "normal"),
    ("Payment Tests",         "PaymentTest","testRefundProcessing",         "Payments",       "Refunds",          "critical"),
    ("Payment Tests",         "PaymentTest","testPartialRefund",            "Payments",       "Refunds",          "normal"),
    # Search & Products
    ("Search Tests",          "SearchTest", "testSearchReturnsRelevantProducts","Search",     "Keyword Search",   "normal"),
    ("Search Tests",          "SearchTest", "testSearchWithFilters",        "Search",         "Filters",          "normal"),
    ("Search Tests",          "SearchTest", "testSearchNoResults",          "Search",         "Empty State",      "minor"),
    ("Search Tests",          "SearchTest", "testAutocompleteSuggestions",  "Search",         "Autocomplete",     "minor"),
    ("Product Tests",         "ProductTest","testProductDetailPage",        "Products",       "Detail View",      "normal"),
    ("Product Tests",         "ProductTest","testProductImageGallery",      "Products",       "Image Gallery",    "minor"),
    ("Product Tests",         "ProductTest","testOutOfStockBadge",          "Products",       "Stock Status",     "normal"),
    # Notifications
    ("Notification Tests",    "NotificationTest","testEnableEmailNotifications","Notifications","Email",          "normal"),
    ("Notification Tests",    "NotificationTest","testDisableNotifications","Notifications",  "Preferences",      "minor"),
    ("Notification Tests",    "NotificationTest","testOrderShippedEmail",   "Notifications",  "Transactional",    "normal"),
    # Orders
    ("Order Tests",           "OrderApiTest","testCreateOrder",             "Orders",         "Create",           "critical"),
    ("Order Tests",           "OrderApiTest","testCancelOrder",             "Orders",         "Cancel",           "critical"),
    ("Order Tests",           "OrderApiTest","testOrderHistoryList",        "Orders",         "History",          "normal"),
    ("Order Tests",           "OrderApiTest","testTrackShipment",           "Orders",         "Tracking",         "normal"),
    # Document / File
    ("Document Tests",        "DocumentUploadTest","testRejectUnsupportedFileType","Documents","Validation",      "normal"),
    ("Document Tests",        "DocumentUploadTest","testUploadPdfAttachment","Documents",     "Upload",           "normal"),
    ("Document Tests",        "DocumentUploadTest","testDownloadInvoicePdf",     "Documents","Download",         "normal"),
    # Profile
    ("Profile Tests",         "ProfileTest","testUpdatePhoneNumber",        "Profile",        "Edit Profile",     "minor"),
    ("Profile Tests",         "ProfileTest","testChangePassword",           "Profile",        "Security",         "normal"),
    ("Profile Tests",         "ProfileTest","testUploadProfilePicture",     "Profile",        "Avatar",           "minor"),
    # Dashboard / Reports
    ("Dashboard Tests",       "ReportTest", "testDownloadMonthlyReportPdf","Reports",         "Export",           "normal"),
    ("Dashboard Tests",       "ReportTest", "testDashboardLoadsInUnder3s", "Dashboard",       "Performance",      "normal"),
    ("Dashboard Tests",       "DashboardTest","testWidgetRefreshOnFilter", "Dashboard",       "Filters",          "minor"),
]

# Maps each suite to the team members responsible for those tests
SUITE_OWNERS: dict[str, list[str]] = {
    "Authentication Tests":  ["Priya Sharma",    "James Carter"],
    "Cart & Checkout Tests": ["Sofia Nguyen",    "Arjun Patel"],
    "Payment Tests":         ["Mei Lin",         "Tom Kowalski"],
    "Search Tests":          ["Fatima Al-Rashid","Lucas Ferreira"],
    "Product Tests":         ["Fatima Al-Rashid","Sofia Nguyen"],
    "Notification Tests":    ["James Carter",    "Priya Sharma"],
    "Order Tests":           ["Arjun Patel",     "Mei Lin"],
    "Document Tests":        ["Tom Kowalski",    "Lucas Ferreira"],
    "Profile Tests":         ["Lucas Ferreira",  "Priya Sharma"],
    "Dashboard Tests":       ["Mei Lin",         "James Carter"],
}

_ERRORS: list[tuple[str, str]] = [
    ("AssertionError",                "Expected status code 200 but was 500"),
    ("TimeoutException",              "Element not found within timeout: button[data-testid='submit']"),
    ("NoSuchElementException",        "Unable to locate element: #order-confirm-btn — page may not have loaded"),
    ("AssertionError",                "Expected redirect to /dashboard but got /error?code=403"),
    ("ConnectionResetError",          "Connection reset by peer during POST /api/payments/charge"),
    ("AssertionError",                "Cart total mismatch: expected 149.99 but was 0.00"),
    ("StaleElementReferenceException","Stale element reference: element is not attached to the page document"),
    ("AssertionError",                "Email not received within 30 s timeout for testOrderShippedEmail"),
    ("HttpError",                     "HTTP 503 Service Unavailable — payment gateway unreachable"),
    ("AssertionError",                "PDF download response was empty (Content-Length: 0)"),
    ("AssertionError",                "Search result count was 0, expected ≥1 for query 'laptop'"),
    ("JavaScriptException",           "Cannot read properties of undefined (reading 'price') at ProductPage.js:87"),
]

_STACK_TEMPLATE = """\
{err_type}: {msg}
\tat com.example.tests.{cls}.{method}(Test.java:{line})
\tat com.example.framework.TestRunner.runTest(TestRunner.java:42)
\tat sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
\tat org.testng.TestRunner.runTestMethods(TestRunner.java:{line2})
"""


# ---------------------------------------------------------------------------
# Behaviour profiles — control how tests fail across runs
# ---------------------------------------------------------------------------

# Maps test name → behaviour type that stays constant across all runs for that test
# Behaviour is seeded per-project so different projects have different bad actors.

class BehaviourProfile:
    """Encapsulates a test's failure behaviour across runs."""

    STABLE              = "stable"              # always passes
    FLAKY               = "flaky"               # alternates or random flip
    RECENTLY_BROKEN     = "recently_broken"     # passes early, breaks later
    CONSISTENTLY_BROKEN = "consistently_broken" # always fails
    RECOVERING          = "recovering"          # was broken, now stabilising
    SLOW_DEGRADING      = "slow_degrading"      # stable but getting slower
    # ── High / Critical producers ──────────────────────────────────────
    AT_RISK   = "at_risk"    # stable → rapid flip → locked fail streak
                             # hits volatility + recent_decline + streak together → HIGH tier
    CRITICAL  = "critical"   # passes first 20%, flips wildly to ~60%, then locks fails
                             # maximises all four main signals → CRITICAL tier


def _assign_behaviours(
    test_names: list[str],
    rng: random.Random,
) -> dict[str, str]:
    """Assign a behaviour profile to each test in the catalogue."""
    n = len(test_names)
    # Distribute: ~45% stable, ~17% flaky, ~10% recently broken,
    #             ~7% consistently broken, ~5% recovering, ~3% slow degrading,
    #             ~8% at_risk (→ HIGH),  ~5% critical (→ CRITICAL)
    weights = [
        (BehaviourProfile.STABLE,              0.45),
        (BehaviourProfile.FLAKY,               0.17),
        (BehaviourProfile.RECENTLY_BROKEN,     0.10),
        (BehaviourProfile.CONSISTENTLY_BROKEN, 0.07),
        (BehaviourProfile.RECOVERING,          0.05),
        (BehaviourProfile.SLOW_DEGRADING,      0.03),
        (BehaviourProfile.AT_RISK,             0.08),
        (BehaviourProfile.CRITICAL,            0.05),
    ]
    profiles: list[str] = []
    for kind, frac in weights:
        profiles.extend([kind] * max(1, round(n * frac)))
    rng.shuffle(profiles)
    return {name: profiles[i % len(profiles)] for i, name in enumerate(test_names)}


def _test_status(
    behaviour: str,
    run_index: int,       # 0-based index in the series
    total_runs: int,
    rng: random.Random,
) -> str:
    """Return 'passed', 'failed', 'broken', or 'skipped' for one run."""
    midpoint = total_runs // 2

    if behaviour == BehaviourProfile.STABLE:
        return "passed"

    if behaviour == BehaviourProfile.CONSISTENTLY_BROKEN:
        return rng.choice(["failed", "broken"])

    if behaviour == BehaviourProfile.FLAKY:
        # Higher flip probability (~60 % chance of a different outcome each run)
        if run_index % 2 == 0:
            return "passed" if rng.random() < 0.65 else rng.choice(["failed", "broken"])
        else:
            return rng.choice(["failed", "broken"]) if rng.random() < 0.65 else "passed"

    if behaviour == BehaviourProfile.RECENTLY_BROKEN:
        if run_index < midpoint:
            return "passed"
        # After midpoint, increasingly likely to fail
        fail_p = (run_index - midpoint) / max(1, total_runs - midpoint)
        return rng.choice(["failed", "broken"]) if rng.random() < fail_p else "passed"

    if behaviour == BehaviourProfile.RECOVERING:
        if run_index < midpoint:
            return rng.choice(["failed", "broken"]) if rng.random() < 0.7 else "passed"
        # After midpoint improving
        pass_p = (run_index - midpoint) / max(1, total_runs - midpoint)
        return "passed" if rng.random() < pass_p else rng.choice(["failed", "broken"])

    if behaviour == BehaviourProfile.SLOW_DEGRADING:
        return "passed"  # always passes; duration grows separately

    if behaviour == BehaviourProfile.AT_RISK:
        # Designed for a 30-run predictor lookback window.
        # Phase 1 (0-40%): mostly passes — outside the lookback window
        # Phase 2 (40-90%): strict alternating — fills most of the window
        # Phase 3 (90-100%): locked failures — tail of window drives
        #   high recent_decline + fail streak  →  HIGH or CRITICAL tier
        phase2_start = int(total_runs * 0.40)
        phase3_start = int(total_runs * 0.90)
        if run_index < phase2_start:
            return "passed" if rng.random() < 0.92 else rng.choice(["failed", "broken"])
        if run_index < phase3_start:
            return "passed" if run_index % 2 == 0 else rng.choice(["failed", "broken"])
        return rng.choice(["failed", "broken"])  # locked fail streak

    if behaviour == BehaviourProfile.CRITICAL:
        # Designed for a 30-run predictor lookback window.
        # Phase 1 (0-40%): stable passes — outside the lookback window
        # Phase 2 (40-94%): rapid alternating — nearly the entire window
        #   → maximises flip_score while keeping failure_burden low
        # Phase 3 (last 3 runs): locked failures — sharpest possible
        #   recent_decline (all recent = fail vs ~50 % baseline)  →  CRITICAL tier
        phase2_start = int(total_runs * 0.40)
        phase3_start = max(total_runs - 3, phase2_start + 1)
        if run_index < phase2_start:
            return "passed" if rng.random() < 0.95 else rng.choice(["failed", "broken"])
        if run_index < phase3_start:
            return "passed" if run_index % 2 == 0 else rng.choice(["failed", "broken"])
        return rng.choice(["failed", "broken"])  # final lock-in

    # fallback
    return "passed" if rng.random() < 0.8 else "failed"


def _test_duration_ms(
    behaviour: str,
    run_index: int,
    total_runs: int,
    base_ms: int,
    rng: random.Random,
) -> int:
    """Return a realistic duration for the test."""
    jitter = rng.gauss(0, base_ms * 0.08)
    if behaviour == BehaviourProfile.SLOW_DEGRADING:
        # Grows by ~15 % over the full series
        growth = base_ms * 0.15 * (run_index / max(1, total_runs - 1))
        return max(50, int(base_ms + growth + jitter))
    if behaviour == BehaviourProfile.RECENTLY_BROKEN and run_index >= total_runs // 2:
        # Gets slower when breaking
        return max(50, int(base_ms * 1.4 + jitter))
    return max(50, int(base_ms + jitter))


# ---------------------------------------------------------------------------
# Allure v2 report file builder
# ---------------------------------------------------------------------------

def _tc_json(
    uid: str,
    catalogue_entry: tuple,
    status: str,
    duration_ms: int,
    run_ts_ms: int,
    rng: random.Random,
) -> dict:
    suite, cls, name, feature, story, severity = catalogue_entry
    full_name = f"com.example.tests.{cls}#{name}"
    err_type, err_msg = rng.choice(_ERRORS) if status in ("failed", "broken") else (None, None)
    stack = None
    if err_type:
        stack = _STACK_TEMPLATE.format(
            err_type=err_type,
            msg=err_msg,
            cls=cls,
            method=name,
            line=rng.randint(20, 200),
            line2=rng.randint(100, 400),
        )

    tc: dict = {
        "uid": uid,
        "name": f"{name}()",
        "fullName": full_name,
        "historyId": f"hist-{uid}",
        "testId": full_name,
        "status": status,
        "time": {
            "start": run_ts_ms,
            "stop": run_ts_ms + duration_ms,
            "duration": duration_ms,
        },
        "description": f"Verify {name} behaves as expected.",
        "descriptionHtml": f"<p>Verify {name} behaves as expected.</p>",
        "flaky": False,
        "newFailed": status in ("failed", "broken"),
        "newBroken": False,
        "newPassed": False,
        "retriesCount": 0,
        "retriesStatusChange": False,
        "steps": [],
        "attachments": [],
        "parameters": [],
        "labels": [
            {"name": "suite",    "value": suite},
            {"name": "feature",  "value": feature},
            {"name": "story",    "value": story},
            {"name": "severity", "value": severity},
            {"name": "owner",    "value": rng.choice(SUITE_OWNERS.get(suite, ["Priya Sharma"]))},
        ],
        "links": [],
        "statusMessage": err_msg,
        "statusTrace": stack,
    }
    return tc


def _suites_json(tc_groups: dict[str, list[dict]]) -> dict:
    children = []
    for suite_name, tcs in tc_groups.items():
        children.append({
            "uid": f"suite-{suite_name.replace(' ', '-').lower()[:20]}",
            "name": suite_name,
            "children": [
                {
                    "uid": tc["uid"],
                    "name": tc["name"],
                    "status": tc["status"],
                    "time": tc["time"],
                    "flaky": False,
                    "newFailed": tc["newFailed"],
                    "newBroken": False,
                    "newPassed": False,
                }
                for tc in tcs
            ],
        })
    return {"uid": "suites-root", "name": "suites", "children": children}


def _summary_json(
    project: str,
    tcs: list[dict],
    start_ms: int,
    stop_ms: int,
) -> dict:
    counts: dict[str, int] = {"passed": 0, "failed": 0, "broken": 0, "skipped": 0, "unknown": 0}
    for tc in tcs:
        counts[tc["status"]] = counts.get(tc["status"], 0) + 1
    return {
        "reportName": project,
        "testRuns": [],
        "statistic": {
            "failed":  counts["failed"],
            "broken":  counts["broken"],
            "skipped": counts["skipped"],
            "passed":  counts["passed"],
            "unknown": counts["unknown"],
            "total":   len(tcs),
        },
        "time": {
            "start":       start_ms,
            "stop":        stop_ms,
            "duration":    stop_ms - start_ms,
            "minDuration": min(tc["time"]["duration"] for tc in tcs),
            "maxDuration": max(tc["time"]["duration"] for tc in tcs),
            "sumDuration": sum(tc["time"]["duration"] for tc in tcs),
        },
    }


def build_report_dir(
    out_dir: Path,
    run_index: int,
    total_runs: int,
    project: str,
    behaviours: dict[str, str],
    base_durations: dict[str, int],
    base_ts: datetime,
    rng: random.Random,
) -> Path:
    """Write one Allure v2 report directory and return its path."""
    run_dt = base_ts + timedelta(days=run_index)
    run_ts_ms = int(run_dt.timestamp() * 1000)

    report_dir = out_dir / f"run_{run_index + 1:03d}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "data" / "test-cases").mkdir(parents=True, exist_ok=True)
    (report_dir / "widgets").mkdir(parents=True, exist_ok=True)

    tcs: list[dict] = []
    tc_groups: dict[str, list[dict]] = {}
    offset_ms = 0

    for entry in TEST_CATALOGUE:
        suite, cls, name, feature, story, severity = entry
        uid = f"tc-{name.lower()[:20]}-{run_index + 1:03d}"
        behaviour = behaviours.get(name, BehaviourProfile.STABLE)
        base_ms = base_durations.get(name, 500)
        duration_ms = _test_duration_ms(behaviour, run_index, total_runs, base_ms, rng)
        status = _test_status(behaviour, run_index, total_runs, rng)

        tc = _tc_json(uid, entry, status, duration_ms, run_ts_ms + offset_ms, rng)
        tcs.append(tc)
        tc_groups.setdefault(suite, []).append(tc)
        offset_ms += duration_ms + rng.randint(10, 100)

        (report_dir / "data" / "test-cases" / f"{uid}.json").write_text(
            json.dumps(tc, indent=2), encoding="utf-8"
        )

    stop_ms = run_ts_ms + offset_ms
    (report_dir / "data" / "suites.json").write_text(
        json.dumps(_suites_json(tc_groups), indent=2), encoding="utf-8"
    )
    (report_dir / "widgets" / "summary.json").write_text(
        json.dumps(_summary_json(project, tcs, run_ts_ms, stop_ms), indent=2), encoding="utf-8"
    )

    # Minimal index.html so the file-based detector works
    (report_dir / "index.html").write_text(
        "<html><head><title>Allure Report</title></head><body></body></html>",
        encoding="utf-8",
    )
    # Minimal app.js so the content detector recognises allure
    (report_dir / "app.js").write_text("/* allure */", encoding="utf-8")

    return report_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Allure reports and optionally ingest them into QARA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--runs",     type=int, default=20,   help="Number of runs to generate per project (default: 20).")
    parser.add_argument("--projects", type=int, default=1,    help="Number of projects to generate (1–3, default: 1).")
    parser.add_argument("--out",      type=Path, default=Path("tmp_test_data"), help="Output directory for report folders.")
    parser.add_argument("--ingest",   action="store_true",    help="Ingest every generated report into QARA after creation.")
    parser.add_argument("--db",       type=Path, default=None, help="QARA database path (default: ~/.qara/qara.db).")
    parser.add_argument("--seed",     type=int, default=42,   help="Random seed for reproducibility (default: 42).")
    parser.add_argument("--clean",    action="store_true",    help="Delete the output directory first if it exists.")
    args = parser.parse_args()

    n_projects = max(1, min(args.projects, len(PROJECTS)))
    chosen_projects = PROJECTS[:n_projects]

    if args.clean and args.out.exists():
        print(f"Removing existing output directory: {args.out}")
        shutil.rmtree(args.out)

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Output directory : {args.out.resolve()}")
    print(f"Projects         : {chosen_projects}")
    print(f"Runs per project : {args.runs}")
    print(f"Total runs       : {args.runs * n_projects}")
    print()

    base_ts = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    all_report_dirs: list[Path] = []

    for proj_idx, project in enumerate(chosen_projects):
        rng = random.Random(args.seed + proj_idx * 1000)
        test_names = [e[2] for e in TEST_CATALOGUE]
        behaviours = _assign_behaviours(test_names, rng)
        base_durations = {name: rng.randint(200, 3000) for name in test_names}

        print(f"  [{project}]")
        # Print behaviour summary
        from collections import Counter
        bcount = Counter(behaviours.values())
        for beh, cnt in sorted(bcount.items()):
            print(f"    {beh:<25s} {cnt} tests")
        print()

        proj_dir = args.out / project.replace(" ", "_").replace("/", "-")
        proj_dir.mkdir(exist_ok=True)

        for run_i in range(args.runs):
            report_dir = build_report_dir(
                proj_dir,
                run_index=run_i,
                total_runs=args.runs,
                project=project,
                behaviours=behaviours,
                base_durations=base_durations,
                base_ts=base_ts,
                rng=rng,
            )
            all_report_dirs.append(report_dir)
            print(f"    Created run {run_i + 1:3d}/{args.runs}  →  {report_dir}", end="\r")

        print(f"    Created {args.runs} runs for '{project}'        ")
        print()

    print(f"Done. {len(all_report_dirs)} report directories created under {args.out.resolve()}")

    # -----------------------------------------------------------------
    # Optional ingestion
    # -----------------------------------------------------------------
    if not args.ingest:
        print()
        print("Tip: re-run with --ingest to load everything into QARA:")
        print(f"     python {sys.argv[0]} --runs {args.runs} --projects {n_projects} --ingest")
        return

    print()
    print("Ingesting into QARA …")
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from qara.api.library import QARAClient  # noqa: PLC0415

    client = QARAClient()
    inserted = 0
    skipped = 0
    failed  = 0
    total   = len(all_report_dirs)
    t0 = time.monotonic()

    for i, report_dir in enumerate(all_report_dirs, 1):
        try:
            _, was_inserted = client.ingest_report(report_dir, db_path=args.db)
            if was_inserted:
                inserted += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"\n  ✗ {report_dir.name}: {exc}")

        elapsed = time.monotonic() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta  = (total - i) / rate if rate > 0 else 0
        print(
            f"  [{i:4d}/{total}]  inserted={inserted}  skipped={skipped}"
            f"  failed={failed}  {rate:.1f} runs/s  ETA {eta:.0f}s   ",
            end="\r",
        )

    elapsed = time.monotonic() - t0
    print()
    print(f"\nIngestion complete in {elapsed:.1f}s")
    print(f"  Inserted : {inserted}")
    print(f"  Skipped  : {skipped}  (already in DB)")
    print(f"  Failed   : {failed}")
    print()
    print("Start the server to explore your data:")
    db_flag = f" --db {args.db}" if args.db else ""
    print(f"  qara serve{db_flag}")


if __name__ == "__main__":
    main()
