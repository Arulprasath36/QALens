"""Run Comparison service for QaLens.

Computes per-test history matrices and summary statistics across an
arbitrary set of runs selected by the caller.

Design decisions
----------------
* **Stable test identity** uses ``canonical_name`` (normalised + lowercased
  display name) as the cross-run key.  ``tc_id`` is per-run-per-test and is
  never used as a stable identifier here.
* **Absent** means a test was not executed in a given run — distinct from
  *skipped* (the test was present but deliberately skipped by the framework).
* **New failure** in the latest run: the latest run is failed/broken *and*
  the immediately preceding selected run was NOT failed/broken (passed,
  skipped, or absent).
* **Fixed** in the latest run: the latest run is passed *and* the immediately
  preceding selected run was failed/broken.
* **Flaky** detection inside the selected window reuses :func:`_compute_flip_score`
  from :mod:`qalens.analyzers.flaky` with the same 0.35 threshold.
* Only non-retry test cases are included in the matrix (``is_retry = 0``).
* When a test appears multiple times in one run (retriggered), the last
  (highest ``id``) occurrence is used.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------

_FAILING = frozenset({"failed", "broken"})
_PASSING = frozenset({"passed"})
_FLAKY_THRESHOLD = 0.35
_BROKEN_THRESHOLD = 0.20


@dataclass
class RunMeta:
    """Lightweight run descriptor included in comparison responses."""

    run_id: str
    run_sequence: int
    display_name: str          # e.g. "Run #7"
    started_at: float | None
    branch: str | None
    build_number: str | None
    report_format: str
    status_summary: dict[str, int]  # {"passed": N, "failed": N, ...}


@dataclass
class CellData:
    """Status of one test in one run."""

    run_id: str
    state: str                 # passed | failed | broken | skipped | absent
    fingerprint: str | None
    error_type: str | None
    message: str | None        # first line only — kept short for grid display
    stack_trace: str | None
    root_cause_category: str | None
    is_latest_change: bool     # True when state differs from previous run
    tooltip: str               # pre-built summary for hover


@dataclass
class RowHealth:
    pass_rate: float
    flip_score: float
    classification: str        # flaky | consistently_broken | stable | insufficient_data


@dataclass
class MatrixRow:
    """One test's full history across the selected runs."""

    canonical_name: str
    display_name: str
    suite: str | None
    feature: str | None
    owner: str | None
    tags: list[str]
    health: RowHealth
    cells: list[CellData]      # ordered to match ComparisonResult.runs


@dataclass
class ComparisonSummary:
    window_size: int
    unique_tests: int
    flaky_tests: int
    consistently_broken: int
    stable_tests: int
    new_failures_latest: int
    fixed_latest: int
    insufficient_history: int


@dataclass
class ComparisonFacets:
    suites: list[str]
    owners: list[str]
    features: list[str]
    modules: list[str]


@dataclass
class ComparisonResult:
    """Full comparison response: runs + matrix + summary + facets."""

    project: str | None
    runs: list[RunMeta]
    summary: ComparisonSummary
    rows: list[MatrixRow]
    facets: ComparisonFacets
    report_format: str  # dominant format across selected runs (e.g. 'allure', 'extent')


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@dataclass
class ComparisonFilters:
    """Optional filters applied to matrix rows before returning."""

    suite: str | None = None
    owner: str | None = None
    feature: str | None = None
    # Status-based row filters (each is a mutually exclusive boolean trigger):
    flaky_only: bool = False
    broken_only: bool = False
    # "changed" = state differs between the latest and the previous run
    changed_only: bool = False
    # "latest_failed" = failed/broken in the most recent run
    latest_failed_only: bool = False
    # free-text search (prefix/substring match on display_name)
    search: str | None = None


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class ComparisonService:
    """Builds run comparison matrices from the QaLens SQLite database.

    Args:
        conn: An open :class:`sqlite3.Connection` to the QaLens database.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare_window(
        self,
        *,
        project: str | None,
        limit: int = 5,
        before_run_id: str | None = None,
        filters: ComparisonFilters | None = None,
    ) -> ComparisonResult:
        """Return a comparison for the ``limit`` most recent runs.

        Args:
            project: Project to scope the query to (``None`` = all projects).
            limit: Number of runs to include; clipped to [1, 50].
            before_run_id: When set, only runs *older* than (run_sequence of)
                this run are considered — used for "Load more" pagination.
            filters: Optional row-level filters.

        Returns:
            A :class:`ComparisonResult` with runs in ascending date order
            (oldest column first, newest column last).
        """
        limit = max(1, min(limit, 50))
        run_ids = self._resolve_window_run_ids(
            project=project, limit=limit, before_run_id=before_run_id
        )
        return self._build(project=project, run_ids=run_ids, filters=filters)

    def compare_custom(
        self,
        *,
        project: str | None,
        run_ids: list[str],
        filters: ComparisonFilters | None = None,
    ) -> ComparisonResult:
        """Return a comparison for an explicit list of run IDs.

        Args:
            project: Project context (used for display; rows are scoped to
                run_ids so cross-project is technically supported).
            run_ids: Ordered or unordered list of run IDs.  The result will
                sort them by ``run_sequence`` ascending (oldest → newest).
            filters: Optional row-level filters.

        Returns:
            A :class:`ComparisonResult`.
        """
        if not run_ids:
            # Return an empty comparison rather than raising.
            return self._empty(project)
        return self._build(project=project, run_ids=run_ids, filters=filters)

    def available_runs(
        self,
        *,
        project: str | None,
        limit: int = 50,
        before_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a lightweight list of runs suitable for a run-picker dropdown.

        Args:
            project: Project filter.
            limit: Maximum results.
            before_run_id: If set, return only runs older than this one.

        Returns:
            List of dicts with keys: run_id, run_sequence, display_name,
            started_at, branch, build_number, total_tests, passed_count,
            failed_count, skipped_count.
        """
        before_seq: int | None = None
        if before_run_id:
            row = self._conn.execute(
                "SELECT run_sequence FROM runs WHERE run_id = ?", (before_run_id,)
            ).fetchone()
            if row:
                before_seq = row["run_sequence"]

        clauses = []
        params: list[Any] = []
        if project is not None:
            clauses.append("r.project = ?")
            params.append(project)
        if before_seq is not None:
            clauses.append("r.run_sequence < ?")
            params.append(before_seq)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = self._conn.execute(
            f"""
            SELECT r.run_id, r.run_sequence, r.started_at, r.branch, r.build_number,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id) AS total_tests,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id
                    AND status = 'passed') AS passed_count,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id
                    AND status IN ('failed','broken')) AS failed_count,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id
                    AND status = 'skipped') AS skipped_count
            FROM runs r
            {where}
            ORDER BY r.run_sequence DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [
            {
                "run_id": r["run_id"],
                "run_sequence": r["run_sequence"],
                "display_name": f"Run #{r['run_sequence']}",
                "started_at": r["started_at"],
                "branch": r["branch"],
                "build_number": r["build_number"],
                "total_tests": r["total_tests"],
                "passed_count": r["passed_count"],
                "failed_count": r["failed_count"],
                "skipped_count": r["skipped_count"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_window_run_ids(
        self,
        *,
        project: str | None,
        limit: int,
        before_run_id: str | None,
    ) -> list[str]:
        """Fetch the ``limit`` most recent run IDs (optionally paginated)."""
        before_seq: int | None = None
        if before_run_id:
            row = self._conn.execute(
                "SELECT run_sequence FROM runs WHERE run_id = ?", (before_run_id,)
            ).fetchone()
            if row:
                before_seq = row["run_sequence"]

        clauses: list[str] = []
        params: list[Any] = []
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if before_seq is not None:
            clauses.append("run_sequence < ?")
            params.append(before_seq)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT run_id FROM runs {where} ORDER BY run_sequence DESC LIMIT ?",
            params,
        ).fetchall()
        # Return in ascending order (oldest first → newest last column)
        return list(reversed([r["run_id"] for r in rows]))

    def _build(
        self,
        *,
        project: str | None,
        run_ids: list[str],
        filters: ComparisonFilters | None,
    ) -> ComparisonResult:
        """Core builder — fetches data and assembles the ComparisonResult."""
        if not run_ids:
            return self._empty(project)

        # Sort run_ids by run_sequence ascending so columns are chronological
        seq_map = self._fetch_run_sequences(run_ids)
        ordered_ids = sorted(run_ids, key=lambda rid: seq_map.get(rid, 0))

        # Fetch run metadata
        run_metas = self._fetch_run_metas(ordered_ids)

        # Fetch all test-case rows for these runs in one query
        tc_rows = self._fetch_tc_data(ordered_ids)

        # Build matrix: canonical_name → {run_id → best row}
        # "best" = last occurrence (highest rowid) when retries exist
        matrix: dict[str, dict[str, Any]] = {}
        meta_by_name: dict[str, dict[str, Any]] = {}  # canonical_name → display meta
        format_counts: dict[str, int] = {}

        for row in tc_rows:
            cname = row["canonical_name"]
            rid = row["run_id"]
            if cname not in matrix:
                matrix[cname] = {}
            # Keep last occurrence within same run (handles retries / dupes)
            existing = matrix[cname].get(rid)
            if existing is None or row["tc_row_id"] > existing["tc_row_id"]:
                matrix[cname][rid] = row
            # Track dominant report format
            fmt = row["report_format"] or "unknown"
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            # Update display meta with latest seen values.
            # Preserve non-null fields from older runs so that runs lacking
            # owner/feature labels (e.g. incident re-runs) don't wipe out the
            # metadata that was captured during normal runs.
            if cname not in meta_by_name or meta_by_name[cname]["seq"] < row["run_sequence"]:
                import json as _json
                raw_tags = row["tags"]
                tags: list[str] = []
                if raw_tags:
                    try:
                        tags = _json.loads(raw_tags)
                    except Exception:
                        pass
                prev = meta_by_name.get(cname, {})
                meta_by_name[cname] = {
                    "display_name": row["name"],
                    "suite": row["suite"] or prev.get("suite"),
                    "feature": row["feature"] or prev.get("feature"),
                    "owner": row["owner"] or prev.get("owner"),
                    "tags": tags or prev.get("tags", []),
                    "seq": row["run_sequence"],
                }

        dominant_format = max(format_counts, key=lambda f: format_counts[f]) if format_counts else "unknown"

        # Backfill owner/suite/feature from full project history for any tests
        # that are missing them in the current window (e.g. 2-run windows where
        # both recent runs are incident re-runs with NULL metadata in the DB).
        names_missing = [
            cname for cname, m in meta_by_name.items()
            if not m.get("owner") or not m.get("suite") or not m.get("feature")
        ]
        if names_missing:
            fallback = self._fetch_metadata_fallback(names_missing, project)
            for cname, fb in fallback.items():
                m = meta_by_name[cname]
                if not m.get("owner"):   m["owner"]   = fb.get("owner")
                if not m.get("suite"):   m["suite"]   = fb.get("suite")
                if not m.get("feature"): m["feature"] = fb.get("feature")

        # Build rows
        matrix_rows: list[MatrixRow] = []
        for cname, runs_map in matrix.items():
            cells = self._build_cells(cname, runs_map, ordered_ids)
            health = self._compute_health(cells, ordered_ids)
            dmeta = meta_by_name.get(cname, {})
            matrix_rows.append(MatrixRow(
                canonical_name=cname,
                display_name=dmeta.get("display_name", cname),
                suite=dmeta.get("suite"),
                feature=dmeta.get("feature"),
                owner=dmeta.get("owner"),
                tags=dmeta.get("tags", []),
                health=health,
                cells=cells,
            ))

        # Sort rows: failing/flaky first, then alphabetical
        matrix_rows.sort(key=lambda r: (
            r.health.classification not in ("flaky", "consistently_broken"),
            r.display_name.lower(),
        ))

        # Apply filters
        if filters:
            matrix_rows = self._apply_filters(matrix_rows, filters)

        # Compute summary
        summary = self._compute_summary(matrix_rows, ordered_ids)

        # Facets
        all_modules: set[str] = set()
        for r in matrix_rows:
            for tag in r.tags:
                if tag:
                    all_modules.add(tag)
        facets = ComparisonFacets(
            suites=sorted({r.suite for r in matrix_rows if r.suite}),
            owners=sorted({r.owner for r in matrix_rows if r.owner}),
            features=sorted({r.feature for r in matrix_rows if r.feature}),
            modules=sorted(all_modules),
        )

        return ComparisonResult(
            project=project,
            runs=run_metas,
            summary=summary,
            rows=matrix_rows,
            facets=facets,
            report_format=dominant_format,
        )

    def _fetch_run_sequences(self, run_ids: list[str]) -> dict[str, int]:
        ph = ",".join("?" * len(run_ids))
        rows = self._conn.execute(
            f"SELECT run_id, run_sequence FROM runs WHERE run_id IN ({ph})", run_ids
        ).fetchall()
        return {r["run_id"]: r["run_sequence"] for r in rows}

    def _fetch_run_metas(self, run_ids: list[str]) -> list[RunMeta]:
        ph = ",".join("?" * len(run_ids))
        rows = self._conn.execute(
            f"""
            SELECT run_id, run_sequence, started_at, branch, build_number, report_format,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id) AS total,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'passed') AS n_pass,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id
                    AND status IN ('failed','broken')) AS n_fail,
                (SELECT COUNT(*) FROM test_cases WHERE run_id = r.run_id AND status = 'skipped') AS n_skip
            FROM runs r
            WHERE run_id IN ({ph})
            ORDER BY run_sequence ASC
            """,
            run_ids,
        ).fetchall()
        return [
            RunMeta(
                run_id=r["run_id"],
                run_sequence=r["run_sequence"],
                display_name=f"Run #{r['run_sequence']}",
                started_at=r["started_at"],
                branch=r["branch"],
                build_number=r["build_number"],
                report_format=r["report_format"],
                status_summary={
                    "passed": r["n_pass"] or 0,
                    "failed": r["n_fail"] or 0,
                    "skipped": r["n_skip"] or 0,
                    "total": r["total"] or 0,
                },
            )
            for r in rows
        ]

    def _fetch_tc_data(self, run_ids: list[str]) -> list[Any]:
        """Fetch all test case rows (+ failure info) for the given run IDs."""
        ph = ",".join("?" * len(run_ids))
        return self._conn.execute(
            f"""
            SELECT
                tc.id        AS tc_row_id,
                tc.run_id,
                tc.canonical_name,
                tc.name,
                tc.status,
                tc.suite,
                tc.feature,
                tc.owner,
                tc.tags,
                tc.is_retry,
                r.run_sequence,
                r.report_format,
                f.fingerprint,
                f.error_type,
                f.message,
                f.stack_trace,
                f.failed_step
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            LEFT JOIN failures f ON f.tc_id = tc.tc_id
            WHERE tc.run_id IN ({ph})
              AND tc.is_retry = 0
            ORDER BY tc.id ASC
            """,
            run_ids,
        ).fetchall()

    def _fetch_metadata_fallback(
        self, canonical_names: list[str], project: str | None
    ) -> dict[str, dict]:
        """Return the most-recent non-null owner/suite/feature from the full
        project history for the given canonical names.  Fired only when the
        current comparison window lacks metadata (e.g. small windows that
        only cover incident re-runs with NULL owner/suite/feature)."""
        if not canonical_names:
            return {}
        ph = ",".join("?" * len(canonical_names))
        params: list[Any] = list(canonical_names)
        proj_clause = ""
        if project is not None:
            proj_clause = "AND r.project = ?"
            params.append(project)
        rows = self._conn.execute(
            f"""
            SELECT tc.canonical_name, tc.owner, tc.suite, tc.feature,
                   r.run_sequence
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            WHERE tc.canonical_name IN ({ph})
              {proj_clause}
              AND (tc.owner IS NOT NULL OR tc.suite IS NOT NULL
                   OR tc.feature IS NOT NULL)
            ORDER BY r.run_sequence DESC
            """,
            params,
        ).fetchall()

        result: dict[str, dict] = {}
        for row in rows:
            cname = row["canonical_name"]
            if cname not in result:
                result[cname] = {
                    "owner": row["owner"],
                    "suite": row["suite"],
                    "feature": row["feature"],
                }
            else:
                fb = result[cname]
                if fb["owner"]   is None: fb["owner"]   = row["owner"]
                if fb["suite"]   is None: fb["suite"]   = row["suite"]
                if fb["feature"] is None: fb["feature"] = row["feature"]
        return result

    def _build_cells(
        self,
        cname: str,
        runs_map: dict[str, Any],
        ordered_ids: list[str],
    ) -> list[CellData]:
        """Build one :class:`CellData` per run column (including absent)."""
        cells: list[CellData] = []
        prev_state: str | None = None

        for i, rid in enumerate(ordered_ids):
            row = runs_map.get(rid)
            if row is None:
                state = "absent"
                fp = error_type = message = stack_trace = category = None
            else:
                state = row["status"]
                fp = row["fingerprint"]
                error_type = row["error_type"]
                # Keep only first line of message for grid display
                raw_msg = row["message"] or ""
                stack_trace = row["stack_trace"] or None
                message = raw_msg.splitlines()[0][:120] if raw_msg else None
                category = self._categorize(error_type, raw_msg)

            # is_latest_change: True when this run's state differs from the
            # prior run's state (absent counts as a "state" here)
            is_change = (prev_state is not None) and (state != prev_state)

            # Build a concise tooltip
            parts: list[str] = [state.upper()]
            if error_type:
                parts.append(error_type.split(".")[-1])
            if message:
                parts.append(message[:80])
            if fp:
                parts.append(f"fp:{fp[:8]}")
            tooltip = " · ".join(parts)

            cells.append(CellData(
                run_id=rid,
                state=state,
                fingerprint=fp,
                error_type=error_type,
                message=message,
                stack_trace=stack_trace,
                root_cause_category=category,
                is_latest_change=is_change,
                tooltip=tooltip,
            ))
            prev_state = state

        return cells

    @staticmethod
    def _categorize(error_type: str | None, message: str | None) -> str | None:
        """Return a root-cause category string, or None if unable to classify."""
        try:
            from qalens.analyzers.categorizer import FailureCategory, categorize_failure
            cat = categorize_failure(error_type=error_type, message=message)
            return None if cat == FailureCategory.UNKNOWN else cat.value
        except Exception:
            return None

    @staticmethod
    def _compute_health(cells: list[CellData], ordered_ids: list[str]) -> RowHealth:
        """Compute pass-rate, flip-score, and classification for one test row."""
        # Only consider "active" states (exclude absent from denominator)
        active = [c for c in cells if c.state != "absent"]
        n = len(active)
        if n == 0:
            return RowHealth(0.0, 0.0, "insufficient_data")

        statuses = [c.state for c in active]
        pass_count = sum(1 for s in statuses if s == "passed")
        pass_rate = pass_count / n

        # Flip score (only consecutive pass↔fail transitions)
        flips = 0
        for i in range(1, len(statuses)):
            p, c = statuses[i - 1], statuses[i]
            if (p in _PASSING and c in _FAILING) or (p in _FAILING and c in _PASSING):
                flips += 1
        flip_score = flips / (n - 1) if n > 1 else 0.0

        if n < 2:
            classification = "insufficient_data"
        elif flip_score >= _FLAKY_THRESHOLD:
            classification = "flaky"
        elif pass_rate <= _BROKEN_THRESHOLD:
            classification = "consistently_broken"
        else:
            classification = "stable"

        return RowHealth(pass_rate=pass_rate, flip_score=flip_score, classification=classification)

    @staticmethod
    def _apply_filters(
        rows: list[MatrixRow], f: ComparisonFilters
    ) -> list[MatrixRow]:
        result = rows
        if f.search:
            needle = f.search.lower()
            result = [r for r in result if needle in r.display_name.lower()]
        if f.suite:
            result = [r for r in result if r.suite == f.suite]
        if f.owner:
            result = [r for r in result if r.owner == f.owner]
        if f.feature:
            result = [r for r in result if r.feature == f.feature]
        if f.flaky_only:
            result = [r for r in result if r.health.classification == "flaky"]
        if f.broken_only:
            result = [r for r in result if r.health.classification == "consistently_broken"]
        if f.latest_failed_only:
            # Latest run is the last cell
            result = [r for r in result if r.cells and r.cells[-1].state in _FAILING]
        if f.changed_only:
            # Any cell with is_latest_change=True in the last column
            result = [r for r in result if r.cells and r.cells[-1].is_latest_change]
        return result

    @staticmethod
    def _compute_summary(
        rows: list[MatrixRow], ordered_ids: list[str]
    ) -> ComparisonSummary:
        """Summarise the whole matrix relative to the latest run column."""
        flaky = consistently_broken = stable = insufficient = 0
        new_failures = fixed = 0

        for row in rows:
            cls = row.health.classification
            if cls == "flaky":
                flaky += 1
            elif cls == "consistently_broken":
                consistently_broken += 1
            elif cls == "stable":
                stable += 1
            else:
                insufficient += 1

            # Determine "new failure" and "fixed" relative to latest vs prior run
            # Need at least 2 columns to compute deltas
            if len(row.cells) >= 2:
                latest = row.cells[-1].state
                prior = row.cells[-2].state
                # "new failure": latest=failed/broken AND prior NOT failed/broken
                if latest in _FAILING and prior not in _FAILING:
                    new_failures += 1
                # "fixed": latest=passed AND prior=failed/broken
                if latest in _PASSING and prior in _FAILING:
                    fixed += 1

        return ComparisonSummary(
            window_size=len(ordered_ids),
            unique_tests=len(rows),
            flaky_tests=flaky,
            consistently_broken=consistently_broken,
            stable_tests=stable,
            new_failures_latest=new_failures,
            fixed_latest=fixed,
            insufficient_history=insufficient,
        )

    @staticmethod
    def _empty(project: str | None) -> ComparisonResult:
        return ComparisonResult(
            project=project,
            runs=[],
            summary=ComparisonSummary(0, 0, 0, 0, 0, 0, 0, 0),
            rows=[],
            facets=ComparisonFacets([], [], [], []),
            report_format="unknown",
        )


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def comparison_to_dict(result: ComparisonResult) -> dict[str, Any]:
    """Convert a :class:`ComparisonResult` to a JSON-serialisable dict."""
    def run_meta_dict(m: RunMeta) -> dict[str, Any]:
        return {
            "run_id": m.run_id,
            "run_sequence": m.run_sequence,
            "display_name": m.display_name,
            "started_at": m.started_at,
            "branch": m.branch,
            "build_number": m.build_number,
            "report_format": m.report_format,
            "status_summary": m.status_summary,
        }

    def cell_dict(c: CellData) -> dict[str, Any]:
        return {
            "run_id": c.run_id,
            "state": c.state,
            "fingerprint": c.fingerprint,
            "error_type": c.error_type,
            "message": c.message,
            "stack_trace": c.stack_trace,
            "root_cause_category": c.root_cause_category,
            "is_latest_change": c.is_latest_change,
            "tooltip": c.tooltip,
        }

    def row_dict(r: MatrixRow) -> dict[str, Any]:
        return {
            "canonical_name": r.canonical_name,
            "display_name": r.display_name,
            "suite": r.suite,
            "feature": r.feature,
            "owner": r.owner,
            "tags": r.tags,
            "health": {
                "pass_rate": round(r.health.pass_rate, 4),
                "flip_score": round(r.health.flip_score, 4),
                "classification": r.health.classification,
            },
            "cells": [cell_dict(c) for c in r.cells],
        }

    return {
        "project": result.project,
        "runs": [run_meta_dict(m) for m in result.runs],
        "summary": {
            "window_size": result.summary.window_size,
            "unique_tests": result.summary.unique_tests,
            "flaky_tests": result.summary.flaky_tests,
            "consistently_broken": result.summary.consistently_broken,
            "stable_tests": result.summary.stable_tests,
            "new_failures_latest": result.summary.new_failures_latest,
            "fixed_latest": result.summary.fixed_latest,
            "insufficient_history": result.summary.insufficient_history,
        },
        "rows": [row_dict(r) for r in result.rows],
        "report_format": result.report_format,
        "facets": {
            "suites": result.facets.suites,
            "owners": result.facets.owners,
            "features": result.facets.features,
            "modules": result.facets.modules,
        },
    }
