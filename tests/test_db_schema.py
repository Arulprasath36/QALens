"""Tests for ari.db.schema — table creation and connection helpers."""

from __future__ import annotations

import sqlite3

import pytest

from qara.db.schema import get_connection, init_db, table_names


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Provide a fresh in-memory connection for each test."""
    c = get_connection(":memory:")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def test_get_connection_returns_connection():
    c = get_connection(":memory:")
    assert isinstance(c, sqlite3.Connection)
    c.close()


def test_row_factory_enabled():
    c = get_connection(":memory:")
    init_db(c)
    row = c.execute("SELECT 1 AS val").fetchone()
    assert row["val"] == 1
    c.close()


def test_foreign_keys_enabled():
    c = get_connection(":memory:")
    row = c.execute("PRAGMA foreign_keys").fetchone()
    # row_factory not yet set until init, but connection should have it on
    assert row[0] == 1
    c.close()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_init_db_creates_all_tables(conn):
    init_db(conn)
    names = table_names(conn)
    assert "runs" in names
    assert "test_cases" in names
    assert "failures" in names
    assert "attachments" in names


def test_init_db_is_idempotent(conn):
    init_db(conn)
    init_db(conn)  # must not raise
    names = table_names(conn)
    assert len([n for n in names if n in {"runs", "test_cases", "failures", "attachments"}]) == 4


def test_runs_table_has_expected_columns(conn):
    init_db(conn)
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    for expected in (
        "run_id", "project", "suite", "report_format", "source_path",
        "started_at", "finished_at", "ingested_at", "run_sequence",
    ):
        assert expected in cols, f"Missing column: {expected}"


def test_test_cases_table_has_expected_columns(conn):
    init_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(test_cases)").fetchall()}
    for expected in ("tc_id", "run_id", "name", "canonical_name", "status",
                     "is_retry", "retry_count"):
        assert expected in cols, f"Missing column: {expected}"


def test_failures_table_has_fingerprint_column(conn):
    init_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(failures)").fetchall()}
    assert "fingerprint" in cols


def test_attachments_table_has_resolved_path_column(conn):
    init_db(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(attachments)").fetchall()}
    assert "resolved_path" in cols


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def test_indexes_are_created(conn):
    init_db(conn)
    indexes = {
        row[1]
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_tc_canonical" in indexes
    assert "idx_fail_fp" in indexes
    assert "idx_runs_proj_ts" in indexes
