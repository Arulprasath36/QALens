"""Unit tests for ComparisonService._build() — facets regression test.

Focuses on the bug where later runs lacking owner/feature labels (e.g.
incident re-runs) would overwrite good metadata from earlier runs, causing
the compare screen's Owner and Feature dropdowns to become empty.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from qalens.analyzers.comparison import ComparisonService
from qalens.db.schema import init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def _insert_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    project: str = "TestProject",
    seq: int,
    report_format: str = "allure",
) -> None:
    conn.execute(
        """
        INSERT INTO runs (run_id, project, report_format, source_path, ingested_at,
                          run_sequence, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, project, report_format, "/tmp/fake", time.time(), seq, time.time()),
    )


def _insert_tc(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    tc_id: str,
    name: str,
    canonical_name: str,
    status: str = "passed",
    owner: str | None = None,
    feature: str | None = None,
    suite: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO test_cases
            (run_id, tc_id, name, canonical_name, status, owner, feature, suite,
             is_retry, retry_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (run_id, tc_id, name, canonical_name, status, owner, feature, suite),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFacetsPopulatedWhenLatestRunLacksLabels:
    """Regression: facets must not be empty when recent runs lack owner/feature.

    When a 'window' of N runs includes later runs that were ingested without
    owner/feature labels (e.g. incident re-runs), the facets should fall back
    to the labels captured by the earlier runs in the same window.
    """

    def test_owners_populated_from_earlier_run(self) -> None:
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)  # no labels (incident run)

        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testLogin()",
                   canonical_name="testlogin", owner="Alice", feature="Auth")
        # Latest run has NULL owner/feature for the same test
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testLogin()",
                   canonical_name="testlogin", owner=None, feature=None)
        conn.commit()

        svc = ComparisonService(conn)
        result = svc.compare_window(project="TestProject", limit=5)

        assert "Alice" in result.facets.owners, (
            "Owner from earlier run must appear in facets even when the latest "
            "run has NULL owner"
        )
        assert "Auth" in result.facets.features, (
            "Feature from earlier run must appear in facets even when the latest "
            "run has NULL feature"
        )

    def test_multiple_owners_across_window(self) -> None:
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)  # incident — no labels

        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testLogin()",
                   canonical_name="testlogin", owner="Alice", feature="Auth",
                   suite="LoginSuite")
        _insert_tc(conn, run_id="run-1", tc_id="tc-b-1", name="testCheckout()",
                   canonical_name="testcheckout", owner="Bob", feature="Cart",
                   suite="CartSuite")
        # Incident run: same tests, no labels
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testLogin()",
                   canonical_name="testlogin", owner=None, feature=None, suite=None)
        _insert_tc(conn, run_id="run-2", tc_id="tc-b-2", name="testCheckout()",
                   canonical_name="testcheckout", owner=None, feature=None, suite=None)
        conn.commit()

        svc = ComparisonService(conn)
        result = svc.compare_window(project="TestProject", limit=5)

        assert sorted(result.facets.owners) == ["Alice", "Bob"]
        assert sorted(result.facets.features) == ["Auth", "Cart"]
        assert sorted(result.facets.suites) == ["CartSuite", "LoginSuite"]

    def test_labels_from_latest_non_null_run_win(self) -> None:
        """When an intermediate run has labels and the latest doesn't, use intermediate."""
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)  # has updated labels
        _insert_run(conn, run_id="run-3", seq=3)  # incident — no labels

        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testLogin()",
                   canonical_name="testlogin", owner="OldOwner", feature="OldFeature")
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testLogin()",
                   canonical_name="testlogin", owner="NewOwner", feature="NewFeature")
        _insert_tc(conn, run_id="run-3", tc_id="tc-a-3", name="testLogin()",
                   canonical_name="testlogin", owner=None, feature=None)
        conn.commit()

        svc = ComparisonService(conn)
        result = svc.compare_window(project="TestProject", limit=5)

        # Should use run-2's labels (newest non-null), not run-1's
        assert result.facets.owners == ["NewOwner"]
        assert result.facets.features == ["NewFeature"]

        # Row-level meta should also reflect the non-null values
        row = next(r for r in result.rows if r.canonical_name == "testlogin")
        assert row.owner == "NewOwner"
        assert row.feature == "NewFeature"

    def test_all_runs_have_labels_no_regression(self) -> None:
        """Normal case: all runs have labels — behaviour unchanged."""
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)

        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testFoo()",
                   canonical_name="testfoo", owner="Carol", feature="Payments")
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testFoo()",
                   canonical_name="testfoo", owner="Carol", feature="Payments")
        conn.commit()

        svc = ComparisonService(conn)
        result = svc.compare_window(project="TestProject", limit=5)

        assert result.facets.owners == ["Carol"]
        assert result.facets.features == ["Payments"]

    def test_no_runs_returns_empty_facets(self) -> None:
        """Edge case: empty project returns empty facets (no crash)."""
        conn = _make_conn()
        svc = ComparisonService(conn)
        result = svc.compare_window(project="EmptyProject", limit=5)

        assert result.facets.owners == []
        assert result.facets.features == []
        assert result.facets.suites == []


class TestMetadataBackfillFromHistory:
    """Regression for 'Latest vs Previous' (2-run window) when BOTH queried
    runs are incident re-runs with NULL owner/suite/feature.

    The backfill must reach outside the current window into project history
    to restore the labels from older runs.
    """

    def test_both_window_runs_null_backfills_from_older_run(self) -> None:
        """The classic 'Latest vs Previous' failure mode:
        - run-1 (seq=1): has labels
        - run-2 (seq=2): NULL labels (incident)
        - run-3 (seq=3): NULL labels (incident)
        Window = last 2 = {run-2, run-3}. Both null → backfill from run-1.
        """
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)
        _insert_run(conn, run_id="run-3", seq=3)

        # run-1 has good labels
        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testLogin()",
                   canonical_name="testlogin", owner="Alice", feature="Auth",
                   suite="LoginSuite", status="passed")
        # run-2 and run-3 are incident reruns — no labels
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testLogin()",
                   canonical_name="testlogin", owner=None, feature=None,
                   suite=None, status="failed")
        _insert_tc(conn, run_id="run-3", tc_id="tc-a-3", name="testLogin()",
                   canonical_name="testlogin", owner=None, feature=None,
                   suite=None, status="failed")
        conn.commit()

        svc = ComparisonService(conn)
        # limit=2 → only sees run-2 and run-3 in the window
        result = svc.compare_window(project="TestProject", limit=2)

        assert result.runs[0].run_sequence in (2, 3)
        assert result.runs[1].run_sequence in (2, 3)
        assert "Alice" in result.facets.owners, (
            "Backfill must recover owner from run-1 even though it is outside "
            "the 2-run window"
        )
        assert "Auth" in result.facets.features
        assert "LoginSuite" in result.facets.suites

        row = result.rows[0]
        assert row.owner == "Alice"
        assert row.feature == "Auth"
        assert row.suite == "LoginSuite"

    def test_backfill_does_not_overwrite_partial_labels(self) -> None:
        """If the window run has owner but no suite, only suite is backfilled."""
        conn = _make_conn()
        _insert_run(conn, run_id="run-1", seq=1)
        _insert_run(conn, run_id="run-2", seq=2)

        _insert_tc(conn, run_id="run-1", tc_id="tc-a-1", name="testFoo()",
                   canonical_name="testfoo", owner="OldOwner", suite="OldSuite",
                   feature="OldFeature")
        # run-2 has owner but no suite/feature
        _insert_tc(conn, run_id="run-2", tc_id="tc-a-2", name="testFoo()",
                   canonical_name="testfoo", owner="NewOwner", suite=None,
                   feature=None)
        conn.commit()

        svc = ComparisonService(conn)
        result = svc.compare_window(project="TestProject", limit=1)

        # Window only contains run-2. Owner is present, suite/feature backfilled.
        row = result.rows[0]
        assert row.owner == "NewOwner"     # from run-2 (not overwritten)
        assert row.suite == "OldSuite"     # backfilled from run-1
        assert row.feature == "OldFeature" # backfilled from run-1
