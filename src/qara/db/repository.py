"""High-level repository for persisting and querying QARA data.

:class:`RunRepository` wraps all SQL operations so no other module
needs to write raw SQL.  It is intentionally narrow: it only exposes
what Phases 4–8 actually need.

Usage::

    from qara.db.schema import get_connection, init_db
    from qara.db.repository import RunRepository

    conn = get_connection()
    init_db(conn)
    repo = RunRepository(conn)

    # Persist a parsed run
    repo.save_run(test_run)

    # Query
    history = repo.get_test_history("verifyadminusersearch", project="OrangeHRM", limit=10)
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from qara.analyzers.canonical import to_canonical_name
from qara.analyzers.fingerprint import compute_fingerprint
from qara.db.schema import get_connection, init_db
from qara.db.models import RunRow, TestCaseRow, TestHistoryEntry  # noqa: F401


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class RunRepository:
    """Persists and queries QARA run data in SQLite.

    Args:
        conn: An open :class:`sqlite3.Connection`.  The caller is
            responsible for closing it.  ``init_db`` is called
            automatically if the schema tables do not yet exist.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        init_db(conn)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_run(self, test_run: Any, *, skip_if_exists: bool = True) -> bool:
        """Persist a :class:`~qara.models.run.TestRun` to the database.

        Computes ``run_sequence`` automatically (max existing sequence for
        the same project + 1, starting at 1).

        Args:
            test_run: A fully parsed ``TestRun`` instance.
            skip_if_exists: When ``True`` (default), silently skips the
                insert if a run with the same ``run_id`` already exists and
                returns ``False``.  When ``False``, deletes the existing run
                (and all cascading test cases, failures, and attachments) and
                re-inserts — useful for ``--force`` re-ingestion.

        Returns:
            ``True`` if the run was inserted; ``False`` if it was skipped
            because it already existed.
        """
        from qara.models.run import TestRun  # local import to avoid circular

        if not isinstance(test_run, TestRun):
            raise TypeError(f"Expected TestRun, got {type(test_run).__name__}")

        meta = test_run.metadata

        # Check for existing run — by run_id first, then by source_path+started_at
        # (same report re-parsed gets a new UUID each time, so we need the latter)
        existing = self._conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?", (meta.run_id,)
        ).fetchone()
        if not existing:
            started_ts = _to_ts(meta.started_at)
            if started_ts is not None:
                existing = self._conn.execute(
                    "SELECT run_id FROM runs WHERE source_path = ? AND started_at = ?",
                    (meta.report_path, started_ts),
                ).fetchone()
        if existing:
            if skip_if_exists:
                return False
            # Force re-ingest: delete the old run and all cascading rows, then re-insert.
            # foreign_keys=ON ensures test_cases → failures/attachments cascade automatically.
            self._conn.execute("DELETE FROM runs WHERE run_id = ?", (existing["run_id"],))

        # Compute run_sequence
        row = self._conn.execute(
            "SELECT MAX(run_sequence) AS max_seq FROM runs WHERE project = ?",
            (meta.project,),
        ).fetchone()
        next_seq = (row["max_seq"] or 0) + 1

        # Insert run
        self._conn.execute(
            """
            INSERT INTO runs
                (run_id, project, suite, report_format, report_version,
                 source_path, environment, branch, build_number,
                 started_at, finished_at, total_ms, ingested_at, run_sequence)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.run_id,
                meta.project,
                meta.custom_fields.get("suite") or _suite_from_tests(test_run),
                meta.report_format,
                meta.report_version,
                meta.report_path,
                meta.environment,
                meta.branch,
                meta.build_number,
                _to_ts(meta.started_at),
                _to_ts(meta.finished_at),
                meta.total_duration_ms,
                time.time(),
                next_seq,
            ),
        )

        # Insert test cases, failures, and attachments.
        # tc_id is stored as "<run_id>::<original_test_id>[::N]" to guarantee
        # global uniqueness even when the same UID appears in multiple runs
        # (common in Allure history datasets) or is duplicated within one run
        # (common with retry configurations).
        seen_tc_ids: dict[str, int] = {}  # original_id → occurrence counter

        for tc in test_run.test_cases:
            canonical = to_canonical_name(tc.name)
            tags_json = json.dumps(tc.tags) if tc.tags else "[]"

            # Build a globally-unique storage key
            base_key = f"{meta.run_id}::{tc.test_id}"
            count = seen_tc_ids.get(base_key, 0)
            seen_tc_ids[base_key] = count + 1
            stored_tc_id = base_key if count == 0 else f"{base_key}::{count}"

            self._conn.execute(
                """
                INSERT INTO test_cases
                    (run_id, tc_id, name, canonical_name, status,
                     duration_ms, suite, feature, story, owner,
                     tags, is_retry, retry_count)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.run_id,
                    stored_tc_id,
                    tc.name,
                    canonical,
                    tc.status.value,
                    tc.duration_ms,
                    tc.suite,
                    tc.feature,
                    tc.story,
                    tc.owner,
                    tags_json,
                    int(tc.is_retry),
                    tc.retry_count,
                ),
            )

            if tc.failure is not None:
                fp = compute_fingerprint(
                    error_type=tc.failure.error_type,
                    stack_trace=tc.failure.stack_trace,
                    message=tc.failure.message,
                )
                self._conn.execute(
                    """
                    INSERT INTO failures
                        (tc_id, error_type, message, stack_trace,
                         fingerprint, failed_step)
                    VALUES
                        (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored_tc_id,
                        tc.failure.error_type,
                        tc.failure.message,
                        tc.failure.stack_trace,
                        fp,
                        tc.failure.failed_step,
                    ),
                )

            for att in tc.attachments:
                self._conn.execute(
                    """
                    INSERT INTO attachments (tc_id, kind, name, resolved_path)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        stored_tc_id,
                        att.kind.value if hasattr(att.kind, "value") else str(att.kind),
                        att.name,
                        str(att.resolved_path) if att.resolved_path else None,
                    ),
                )

        self._conn.commit()
        return True

    def list_tc_ids_for_run(self, run_id: str) -> list[str]:
        """Return the stored ``tc_id`` values for *run_id* in insertion order.

        Used by :meth:`~qara.api.library.QARAClient.ingest_report` to match
        :class:`~qara.models.test_case.TestCaseResult` objects (whose
        ``raw_artifact_refs`` carry the parsed refs) to their DB ``tc_id``
        keys after :meth:`save_run` returns.

        Args:
            run_id: The run to query.

        Returns:
            List of ``tc_id`` strings ordered by database insertion sequence.
        """
        rows = self._conn.execute(
            "SELECT tc_id FROM test_cases WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [row["tc_id"] for row in rows]

    def save_artifacts(self, records: "list[Any]") -> None:
        """Bulk-insert :class:`~qara.artifacts.models.ArtifactRecord` objects.

        All records are committed in a single transaction.  Existing records
        for the same ``tc_id`` are **not** replaced — callers should only call
        this once per run (after :meth:`save_run`).

        Args:
            records: List of
                :class:`~qara.artifacts.models.ArtifactRecord` dataclass
                instances produced by
                :class:`~qara.artifacts.policy.ArtifactIngestionPolicy`.
        """
        if not records:
            return
        for rec in records:
            self._conn.execute(
                """
                INSERT INTO artifacts
                    (tc_id, failure_id, artifact_type, storage_uri,
                     source_reference, file_name, mime_type, size_bytes,
                     sha256, width, height, sequence_no, step_name,
                     is_primary, metadata_json, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.tc_id,
                    rec.failure_id,
                    rec.artifact_type,
                    rec.storage_uri,
                    rec.source_reference,
                    rec.file_name,
                    rec.mime_type,
                    rec.size_bytes,
                    rec.sha256,
                    rec.width,
                    rec.height,
                    rec.sequence_no,
                    rec.step_name,
                    1 if rec.is_primary else 0,
                    rec.metadata_json,
                    rec.created_at,
                ),
            )
        self._conn.commit()

    def get_artifacts_for_tc(self, tc_id: str) -> list[dict[str, Any]]:
        """Return artifact records for *tc_id* ordered by sequence number.

        Args:
            tc_id: The DB-stored ``tc_id`` to query.

        Returns:
            List of dicts with all ``artifacts`` table columns.
        """
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE tc_id = ? ORDER BY sequence_no, id",
            (tc_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> RunRow | None:
        """Fetch a single run by its ``run_id``.

        Args:
            run_id: The UUID string of the run.

        Returns:
            A :class:`RunRow` or ``None`` if not found.
        """
        row = self._conn.execute(
            """
            SELECT r.*,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id) AS total_tests,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'passed') AS passed_count,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status IN ('failed','broken')) AS failed_count,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'skipped') AS skipped_count
            FROM runs r
            WHERE r.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return _row_to_run(row) if row else None

    def get_run_by_sequence(
        self,
        sequence: int,
        *,
        project: str | None = None,
    ) -> "RunRow | None":
        """Fetch a single run by its ``run_sequence`` number.

        Args:
            sequence: The 1-based run sequence number displayed to users
                (e.g. 18 for "Run No 18" / "Run #18").
            project:  Optional project filter; when given only that project's
                runs are searched.

        Returns:
            A :class:`RunRow` or ``None`` if no run with that sequence exists.
        """
        if project is not None:
            row = self._conn.execute(
                """
                SELECT r.*,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id) AS total_tests,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'passed') AS passed_count,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status IN ('failed','broken')) AS failed_count,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'skipped') AS skipped_count
                FROM runs r
                WHERE r.run_sequence = ? AND r.project = ?
                """,
                (sequence, project),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT r.*,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id) AS total_tests,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'passed') AS passed_count,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status IN ('failed','broken')) AS failed_count,
                    (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'skipped') AS skipped_count
                FROM runs r
                WHERE r.run_sequence = ?
                """,
                (sequence,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(
        self,
        *,
        project: str | None = None,
        limit: int = 50,
    ) -> list[RunRow]:
        """List runs ordered by ``started_at`` descending.

        Args:
            project: When given, restricts results to this project.
            limit: Maximum number of rows to return.

        Returns:
            List of :class:`RunRow` objects, newest first.
        """
        if project is not None:
            rows = self._conn.execute(
                """
                WITH selected_runs AS (
                    SELECT *
                    FROM runs
                    WHERE project = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                ),
                counts AS (
                    SELECT
                        tc.run_id,
                        COUNT(*) AS total_tests,
                        SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passed_count,
                        SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS failed_count,
                        SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
                    FROM test_cases tc
                    JOIN selected_runs sr ON sr.run_id = tc.run_id
                    GROUP BY tc.run_id
                )
                SELECT
                    sr.*,
                    COALESCE(c.total_tests, 0) AS total_tests,
                    COALESCE(c.passed_count, 0) AS passed_count,
                    COALESCE(c.failed_count, 0) AS failed_count,
                    COALESCE(c.skipped_count, 0) AS skipped_count
                FROM selected_runs sr
                LEFT JOIN counts c ON c.run_id = sr.run_id
                ORDER BY sr.started_at DESC
                """,
                (project, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                WITH selected_runs AS (
                    SELECT *
                    FROM runs
                    ORDER BY started_at DESC
                    LIMIT ?
                ),
                counts AS (
                    SELECT
                        tc.run_id,
                        COUNT(*) AS total_tests,
                        SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passed_count,
                        SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS failed_count,
                        SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
                    FROM test_cases tc
                    JOIN selected_runs sr ON sr.run_id = tc.run_id
                    GROUP BY tc.run_id
                )
                SELECT
                    sr.*,
                    COALESCE(c.total_tests, 0) AS total_tests,
                    COALESCE(c.passed_count, 0) AS passed_count,
                    COALESCE(c.failed_count, 0) AS failed_count,
                    COALESCE(c.skipped_count, 0) AS skipped_count
                FROM selected_runs sr
                LEFT JOIN counts c ON c.run_id = sr.run_id
                ORDER BY sr.started_at DESC
                """,
                (limit,),
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def get_test_cases_for_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        include_details: bool = True,
    ) -> list[TestCaseRow]:
        """Return all test cases for a run, optionally filtered by status.

        Args:
            run_id: The run to query.
            status: When given, only tests with this status are returned
                (e.g. ``"failed"``).

        Returns:
            List of :class:`TestCaseRow` objects.
        """
        failure_columns = (
            "f.error_type, f.message, f.stack_trace, f.fingerprint, f.failed_step"
            if include_details
            else "f.error_type, substr(f.message, 1, 240) AS message, NULL AS stack_trace, f.fingerprint, f.failed_step"
        )
        base = f"""
            SELECT tc.*, {failure_columns}
            FROM test_cases tc
            LEFT JOIN failures f ON f.tc_id = tc.tc_id
            WHERE tc.run_id = ?
        """
        if status:
            rows = self._conn.execute(
                base + " AND tc.status = ?", (run_id, status)
            ).fetchall()
        else:
            rows = self._conn.execute(base, (run_id,)).fetchall()
        results = [_row_to_tc(r) for r in rows]
        if results and include_details:
            placeholders = ",".join("?" * len(results))
            tc_ids = [tc.tc_id for tc in results]
            att_rows = self._conn.execute(
                f"SELECT tc_id, kind, name, resolved_path FROM attachments"
                f" WHERE tc_id IN ({placeholders}) ORDER BY id",
                tc_ids,
            ).fetchall()
            att_map: dict[str, list[dict]] = {}
            for a in att_rows:
                att_map.setdefault(a["tc_id"], []).append(
                    {"kind": a["kind"], "name": a["name"], "resolved_path": a["resolved_path"]}
                )

            # Also load policy-ingested artifacts from the artifacts table.
            # Entries with a storage_uri map resolved_path → local path so
            # the existing attachment-serving endpoint works for both tables.
            art_rows = self._conn.execute(
                f"SELECT tc_id, artifact_type, file_name, storage_uri, sha256,"
                f" mime_type, width, height, sequence_no, is_primary, id AS artifact_id"
                f" FROM artifacts"
                f" WHERE tc_id IN ({placeholders}) ORDER BY sequence_no, id",
                tc_ids,
            ).fetchall()
            for a in art_rows:
                # Resolve file:// URI to a local path that the existing endpoint can serve
                storage_uri = a["storage_uri"] or ""
                resolved = storage_uri[len("file://"):] if storage_uri.startswith("file://") else None
                att_map.setdefault(a["tc_id"], []).append({
                    "kind": a["artifact_type"],
                    "name": a["file_name"],
                    "resolved_path": resolved,
                    "artifact_id": a["artifact_id"],
                    "sha256": a["sha256"],
                    "mime_type": a["mime_type"],
                    "width": a["width"],
                    "height": a["height"],
                    "is_primary": bool(a["is_primary"]),
                })

            for tc in results:
                tc.attachments = att_map.get(tc.tc_id, [])
        return results

    def get_test_history(
        self,
        canonical_name: str,
        *,
        project: str | None = None,
        limit: int = 30,
    ) -> list[TestHistoryEntry]:
        """Return cross-run history for a test identified by its canonical name.

        Results are ordered oldest → newest so callers can easily compute
        run streaks or flip counts.

        Args:
            canonical_name: The normalised test name (use
                :func:`~qara.analyzers.canonical.to_canonical_name` first).
            project: Restrict to runs belonging to this project.
            limit: Maximum number of history entries to return.

        Returns:
            List of :class:`TestHistoryEntry` objects ordered by
            ``run_sequence`` ascending.
        """
        if project is not None:
            rows = self._conn.execute(
                """
                SELECT * FROM (
                    SELECT r.run_id, r.run_sequence, r.started_at,
                           tc.status, f.fingerprint,
                           f.error_type, f.message, f.stack_trace
                    FROM test_cases tc
                    JOIN runs r     ON r.run_id  = tc.run_id
                    LEFT JOIN failures f ON f.tc_id = tc.tc_id
                    WHERE tc.canonical_name = ?
                      AND r.project = ?
                    ORDER BY r.run_sequence DESC
                    LIMIT ?
                ) ORDER BY run_sequence ASC
                """,
                (canonical_name, project, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM (
                    SELECT r.run_id, r.run_sequence, r.started_at,
                           tc.status, f.fingerprint,
                           f.error_type, f.message, f.stack_trace
                    FROM test_cases tc
                    JOIN runs r     ON r.run_id  = tc.run_id
                    LEFT JOIN failures f ON f.tc_id = tc.tc_id
                    WHERE tc.canonical_name = ?
                    ORDER BY r.run_sequence DESC
                    LIMIT ?
                ) ORDER BY run_sequence ASC
                """,
                (canonical_name, limit),
            ).fetchall()
        return [
            TestHistoryEntry(
                run_id=r["run_id"],
                run_sequence=r["run_sequence"],
                started_at=r["started_at"],
                status=r["status"],
                fingerprint=r["fingerprint"],
                error_type=r["error_type"],
                message=r["message"],
                stack_trace=r["stack_trace"],
            )
            for r in rows
        ]

    def run_exists(self, run_id: str) -> bool:
        """Return ``True`` if a run with *run_id* is already stored.

        Args:
            run_id: UUID string to check.

        Returns:
            ``True`` if present, ``False`` otherwise.
        """
        row = self._conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row is not None

    def count_runs(self, *, project: str | None = None) -> int:
        """Return the total number of stored runs, optionally per project.

        Args:
            project: When given, counts only runs for this project.

        Returns:
            Integer count.
        """
        if project:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE project = ?", (project,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()
        return row["n"]

    def get_failure_groups(
        self,
        *,
        project: str | None = None,
        limit: int = 50,
        run_ids: list[str] | None = None,
    ) -> list[dict]:
        """Return failures grouped by fingerprint, ranked by occurrence count.

        When ``run_ids`` is provided all counts are scoped to those runs only
        and each row carries ``scope="window"``.  Without ``run_ids`` the query
        is all-time and rows carry ``scope="all_time"``.

        Each returned dict contains:
        - ``fingerprint``: the 16-char hash
        - ``occurrence_count``: failures in scope
        - ``affected_tests``: distinct canonical names in scope
        - ``affected_runs``: distinct runs in scope
        - ``window_size``: len(run_ids) when scoped, else None
        - ``scope``: "window" | "all_time"
        - ``error_type``, ``message``, ``first_seen_seq``, ``last_seen_seq``
        """
        base_select = """
            SELECT
                f.fingerprint,
                COUNT(*)                          AS occurrence_count,
                COUNT(DISTINCT tc.canonical_name) AS affected_tests,
                COUNT(DISTINCT r.run_id)          AS affected_runs,
                MIN(f.error_type)                 AS error_type,
                MIN(f.message)                    AS message,
                MIN(r.run_sequence)               AS first_seen_seq,
                MAX(r.run_sequence)               AS last_seen_seq,
                GROUP_CONCAT(DISTINCT tc.canonical_name) AS canonical_names
            FROM failures f
            JOIN test_cases tc ON tc.tc_id = f.tc_id
            JOIN runs r        ON r.run_id = tc.run_id
        """

        conditions: list[str] = []
        params: list = []

        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            conditions.append(f"r.run_id IN ({placeholders})")
            params.extend(run_ids)

        if project is not None:
            conditions.append("r.project = ?")
            params.append(project)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = self._conn.execute(
            f"{base_select} {where} GROUP BY f.fingerprint ORDER BY occurrence_count DESC LIMIT ?",
            params,
        ).fetchall()

        scope = "window" if run_ids else "all_time"
        window_size = len(run_ids) if run_ids else None

        result = []
        for r in rows:
            d = dict(r)
            raw = d.pop("canonical_names", None)
            d["affected_canonical_names"] = raw.split(",") if raw else []
            d["bug_links"] = self.get_bug_links(d["fingerprint"])
            d["scope"] = scope
            d["window_size"] = window_size
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Bug link operations
    # ------------------------------------------------------------------

    def get_bug_links(self, fingerprint: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, bug_url, label FROM bug_links WHERE fingerprint = ? ORDER BY id",
            (fingerprint,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_bug_link(self, fingerprint: str, bug_url: str, label: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO bug_links (fingerprint, bug_url, label) VALUES (?,?,?)",
            (fingerprint, bug_url, label),
        )
        self._conn.commit()
        return cur.lastrowid

    def remove_bug_link(self, bug_link_id: int) -> None:
        self._conn.execute("DELETE FROM bug_links WHERE id = ?", (bug_link_id,))
        self._conn.commit()

    def get_latest_suite_per_canonical_name(
        self,
        *,
        project: str | None = None,
    ) -> dict[str, str]:
        """Return the most-recently-seen suite name for each canonical test name.

        Args:
            project: Restrict to this project, or ``None`` for all.

        Returns:
            Dict mapping ``canonical_name`` → ``suite`` string.  Tests with
            no suite set in any run are omitted.
        """
        if project is not None:
            rows = self._conn.execute(
                """
                SELECT tc.canonical_name, tc.suite
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                JOIN (
                    SELECT tc2.canonical_name, MAX(r2.run_sequence) AS max_seq
                    FROM test_cases tc2
                    JOIN runs r2 ON r2.run_id = tc2.run_id
                    WHERE tc2.suite IS NOT NULL
                      AND r2.project = ?
                    GROUP BY tc2.canonical_name
                ) latest
                  ON latest.canonical_name = tc.canonical_name
                 AND r.run_sequence = latest.max_seq
                WHERE tc.suite IS NOT NULL
                  AND r.project = ?
                GROUP BY tc.canonical_name
                """,
                [project, project],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT tc.canonical_name, tc.suite
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                JOIN (
                    SELECT tc2.canonical_name, MAX(r2.run_sequence) AS max_seq
                    FROM test_cases tc2
                    JOIN runs r2 ON r2.run_id = tc2.run_id
                    WHERE tc2.suite IS NOT NULL
                    GROUP BY tc2.canonical_name
                ) latest
                  ON latest.canonical_name = tc.canonical_name
                 AND r.run_sequence = latest.max_seq
                WHERE tc.suite IS NOT NULL
                GROUP BY tc.canonical_name
                """,
                [],
            ).fetchall()
        return {r["canonical_name"]: r["suite"] for r in rows}

    def get_all_canonical_names(
        self,
        *,
        project: str | None = None,
        min_runs: int = 1,
    ) -> list[dict]:
        """Return all canonical test names with their run-count statistics.

        Each returned dict contains:
        - ``canonical_name``
        - ``display_name``: most recently seen raw name
        - ``run_count``: distinct runs this test appeared in
        - ``pass_count``, ``fail_count``, ``skip_count``

        Args:
            project: Project filter, or ``None`` for all.
            min_runs: Minimum number of runs the test must appear in.

        Returns:
            List of dicts ordered by ``run_count`` descending.
        """
        if project is not None:
            rows = self._conn.execute(
                """
                SELECT
                    tc.canonical_name,
                    MAX(tc.name)                                      AS display_name,
                    COUNT(DISTINCT r.run_id)                          AS run_count,
                    SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS pass_count,
                    SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS fail_count,
                    SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skip_count
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.is_retry = 0
                  AND r.project = ?
                GROUP BY tc.canonical_name
                HAVING COUNT(DISTINCT r.run_id) >= ?
                ORDER BY run_count DESC
                """,
                [project, min_runs],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT
                    tc.canonical_name,
                    MAX(tc.name)                                      AS display_name,
                    COUNT(DISTINCT r.run_id)                          AS run_count,
                    SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS pass_count,
                    SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS fail_count,
                    SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skip_count
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.is_retry = 0
                GROUP BY tc.canonical_name
                HAVING COUNT(DISTINCT r.run_id) >= ?
                ORDER BY run_count DESC
                """,
                [min_runs],
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _to_ts(dt: Any) -> float | None:
    """Convert a ``datetime`` (or ``None``) to a Unix timestamp float."""
    if dt is None:
        return None
    try:
        return dt.timestamp()
    except AttributeError:
        return None


def _suite_from_tests(test_run: Any) -> str | None:
    """Derive a suite name from the most common test suite in the run."""
    suites: dict[str, int] = {}
    for tc in test_run.test_cases:
        if tc.suite:
            suites[tc.suite] = suites.get(tc.suite, 0) + 1
    if not suites:
        return None
    return max(suites, key=lambda s: suites[s])


def _row_to_run(row: sqlite3.Row) -> RunRow:
    keys = row.keys()
    return RunRow(
        run_id=row["run_id"],
        project=row["project"],
        suite=row["suite"],
        report_format=row["report_format"],
        report_version=row["report_version"],
        source_path=row["source_path"],
        environment=row["environment"],
        branch=row["branch"],
        build_number=row["build_number"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        total_ms=row["total_ms"],
        ingested_at=row["ingested_at"],
        run_sequence=row["run_sequence"],
        total_tests=row["total_tests"] if "total_tests" in keys else None,
        passed_count=row["passed_count"] if "passed_count" in keys else None,
        failed_count=row["failed_count"] if "failed_count" in keys else None,
        skipped_count=row["skipped_count"] if "skipped_count" in keys else None,
    )


def _row_to_tc(row: sqlite3.Row) -> TestCaseRow:
    tags_raw = row["tags"] or "[]"
    try:
        tags = json.loads(tags_raw)
    except json.JSONDecodeError:
        tags = []
    return TestCaseRow(
        tc_id=row["tc_id"],
        run_id=row["run_id"],
        name=row["name"],
        canonical_name=row["canonical_name"],
        status=row["status"],
        duration_ms=row["duration_ms"],
        suite=row["suite"],
        feature=row["feature"],
        story=row["story"],
        owner=row["owner"],
        tags=tags,
        is_retry=bool(row["is_retry"]),
        retry_count=row["retry_count"],
        error_type=row["error_type"],
        message=row["message"],
        stack_trace=row["stack_trace"],
        fingerprint=row["fingerprint"],
        failed_step=row["failed_step"],
    )
