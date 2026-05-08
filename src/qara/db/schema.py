"""SQLite schema definition and connection management for QARA.

The default database lives at ``~/.qara/qara.db``.  Every function that
needs a connection should call :func:`get_connection` so the path can
be overridden uniformly (e.g. in tests or via the ``--db`` CLI flag).

Schema overview
---------------
``runs``
    One row per ingested report.  ``run_sequence`` is a per-project
    monotonically increasing integer that gives runs a stable ordinal for
    "last N runs" queries.

``test_cases``
    One row per test result inside a run.  ``canonical_name`` enables
    cross-run history queries for the same logical test regardless of
    parameterisation or capitalisation differences.

``failures``
    One row per test case that has failure information.  ``fingerprint``
    groups repeated occurrences of the same underlying bug.

``attachments``
    Screenshots, logs, or other files linked to a test case (legacy path).

``artifacts``
    Rich artifact records produced by the artifact ingestion policy.
    Stores metadata (hash, dimensions, MIME type) and an optional
    ``storage_uri`` that points to bytes on disk or in object storage.

Usage::

    from qara.db.schema import get_connection, init_db

    conn = get_connection()          # uses ~/.qara/qara.db
    conn = get_connection(":memory:") # in-memory (tests)
    init_db(conn)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from qara.security import validate_sqlite_db_path

# ---------------------------------------------------------------------------
# Default database location
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".qara"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "qara.db"


def default_db_path() -> Path:
    """Return the default path for the QARA SQLite database.

    Creates ``~/.qara/`` if it does not already exist.

    Returns:
        Absolute :class:`~pathlib.Path` to ``~/.qara/qara.db``.
    """
    _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and return) a SQLite connection.

    Args:
        db_path: Path to the ``.db`` file, or ``":memory:"`` for an
            in-memory database (useful in tests).  When ``None`` the
            default path ``~/.qara/qara.db`` is used.

    Returns:
        An open :class:`sqlite3.Connection` with ``row_factory`` set to
        :class:`sqlite3.Row` so columns are accessible by name, and
        ``foreign_keys`` pragma enabled.
    """
    if db_path is None:
        path: str | Path = default_db_path()
    else:
        path = validate_sqlite_db_path(db_path)

    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL UNIQUE,
    project        TEXT,
    suite          TEXT,
    report_format  TEXT    NOT NULL,
    report_version TEXT,
    source_path    TEXT    NOT NULL,
    environment    TEXT,
    branch         TEXT,
    build_number   TEXT,
    started_at     REAL,
    finished_at    REAL,
    total_ms       INTEGER,
    ingested_at    REAL    NOT NULL,
    run_sequence   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS test_cases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tc_id          TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    canonical_name TEXT    NOT NULL,
    status         TEXT    NOT NULL,
    duration_ms    INTEGER,
    suite          TEXT,
    feature        TEXT,
    story          TEXT,
    owner          TEXT,
    tags           TEXT,
    is_retry       INTEGER NOT NULL DEFAULT 0,
    retry_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tc_id       TEXT    NOT NULL REFERENCES test_cases(tc_id) ON DELETE CASCADE,
    error_type  TEXT,
    message     TEXT,
    stack_trace TEXT,
    fingerprint TEXT    NOT NULL,
    failed_step TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tc_id         TEXT    NOT NULL REFERENCES test_cases(tc_id) ON DELETE CASCADE,
    kind          TEXT,
    name          TEXT,
    resolved_path TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tc_id            TEXT    NOT NULL REFERENCES test_cases(tc_id) ON DELETE CASCADE,
    failure_id       INTEGER REFERENCES failures(id) ON DELETE SET NULL,
    artifact_type    TEXT    NOT NULL DEFAULT 'screenshot',
    storage_uri      TEXT,
    source_reference TEXT,
    file_name        TEXT,
    mime_type        TEXT,
    size_bytes       INTEGER,
    sha256           TEXT,
    width            INTEGER,
    height           INTEGER,
    sequence_no      INTEGER NOT NULL DEFAULT 0,
    step_name        TEXT,
    is_primary       INTEGER NOT NULL DEFAULT 0,
    metadata_json    TEXT,
    created_at       REAL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_tc  ON artifacts (tc_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts (sha256);

CREATE TABLE IF NOT EXISTS bug_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT    NOT NULL,
    bug_url     TEXT    NOT NULL,
    label       TEXT,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(fingerprint, bug_url)
);

-- Indexes for Phase-8 query performance
CREATE INDEX IF NOT EXISTS idx_tc_canonical      ON test_cases (canonical_name);
CREATE INDEX IF NOT EXISTS idx_tc_run_status     ON test_cases (run_id, status);
CREATE INDEX IF NOT EXISTS idx_fail_fp           ON failures   (fingerprint);
CREATE INDEX IF NOT EXISTS idx_runs_proj_ts      ON runs       (project, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_proj_seq     ON runs       (project, run_sequence);
CREATE INDEX IF NOT EXISTS idx_bug_links_fp      ON bug_links  (fingerprint);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not already exist.

    Safe to call multiple times — every statement uses
    ``CREATE TABLE/INDEX IF NOT EXISTS``.

    Args:
        conn: An open :class:`sqlite3.Connection` returned by
            :func:`get_connection`.
    """
    conn.executescript(_DDL)
    conn.commit()


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Return a sorted list of table names present in the database.

    Useful for schema-validation tests.

    Args:
        conn: An open connection to the target database.

    Returns:
        Sorted list of table name strings.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]
