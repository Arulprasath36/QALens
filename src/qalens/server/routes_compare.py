"""Run-comparison route handlers for the QA Lens FastAPI server.

Factory function :func:`make_compare_router` registers all
``/api/compare/*`` endpoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from qalens.server.models import CompareRequest, EntityCompareRequest


def _parse_compare_filters(params: dict[str, Any]):
    """Convert a flat filter dict into a :class:`~qalens.analyzers.comparison.ComparisonFilters`."""
    from qalens.analyzers.comparison import ComparisonFilters
    return ComparisonFilters(
        suite=params.get("suite") or None,
        owner=params.get("owner") or None,
        feature=params.get("feature") or None,
        flaky_only=bool(params.get("flaky_only")),
        broken_only=bool(params.get("broken_only")),
        changed_only=bool(params.get("changed_only")),
        latest_failed_only=bool(params.get("latest_failed_only")),
        search=params.get("search") or None,
    )


def make_compare_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with all comparison endpoints."""
    router = APIRouter()

    @router.get("/api/compare/history", tags=["comparison"])
    async def compare_history(
        project: str | None = Query(None, max_length=200),
        limit: int = Query(5, ge=1, le=50, description="Window size (1-50 runs)."),
        before_run_id: str | None = Query(None, max_length=128, description="Paginate: runs older than this run_id."),
    ) -> dict[str, Any]:
        """Return a sliding-window comparison for the N most recent runs.

        Use ``before_run_id`` to append older runs (Add-more-runs workflow).
        """
        from qalens.analyzers.comparison import ComparisonService, comparison_to_dict
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            svc = ComparisonService(conn)
            result = svc.compare_window(
                project=project,
                limit=limit,
                before_run_id=before_run_id,
            )
            return comparison_to_dict(result)
        finally:
            conn.close()

    @router.post("/api/compare/custom", tags=["comparison"])
    async def compare_custom(body: CompareRequest) -> dict[str, Any]:
        """Return a comparison for an explicit, user-selected set of run IDs."""
        from qalens.analyzers.comparison import ComparisonService, comparison_to_dict
        from qalens.db.schema import get_connection

        if not body.run_ids:
            raise HTTPException(status_code=400, detail="run_ids must not be empty.")
        if len(body.run_ids) > 50:
            raise HTTPException(status_code=400, detail="At most 50 run IDs allowed.")

        conn = get_connection(db_path)
        try:
            svc = ComparisonService(conn)
            filters = _parse_compare_filters(body.filters)
            result = svc.compare_custom(
                project=None,   # run_ids already scope the query
                run_ids=list(dict.fromkeys(body.run_ids)),  # deduplicate, preserve order
                filters=filters,
            )
            return comparison_to_dict(result)
        finally:
            conn.close()

    @router.get("/api/compare/runs", tags=["comparison"])
    async def compare_available_runs(
        project: str | None = Query(None, max_length=200),
        limit: int = Query(50, ge=1, le=200),
        before_run_id: str | None = Query(None, max_length=128),
    ) -> list[dict[str, Any]]:
        """Return a lightweight run list for the run-picker dropdown."""
        from qalens.analyzers.comparison import ComparisonService
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return ComparisonService(conn).available_runs(
                project=project, limit=limit, before_run_id=before_run_id
            )
        finally:
            conn.close()

    @router.get("/api/compare/facets", tags=["comparison"])
    async def compare_facets(
        project: str | None = Query(None, max_length=200),
        limit: int = Query(3, ge=1, le=50, description="Recent run window used for picker facets."),
    ) -> dict[str, Any]:
        """Return owner/suite picker facets without building a full comparison matrix."""
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return _build_compare_facets(conn, project=project, limit=limit)
        finally:
            conn.close()

    @router.post("/api/compare/owners", tags=["comparison"])
    async def compare_owners(body: EntityCompareRequest) -> dict[str, Any]:
        """Compare test results between two or three owners across a run window.

        Request body::

            {
                "owner_a":  "Arjun Patel",
                "owner_b":  "Fatima Al-Rashid",
                "owner_c":  "Lucas Ferreira",   // optional third owner
                "limit":    5,               // optional when run_ids provided
                "run_ids":  ["...", "..."],  // optional explicit custom range
                "project":  "OrangeHRM"          // optional
            }

        Response ``metrics_a`` / ``metrics_b`` (and optional ``metrics_c``) reflect
        each owner's aggregate in the **latest run**.  Each row carries the test's
        status in the latest run (``status_a``) vs the baseline run (``status_b``).
        """
        owner_a = (body.owner_a or "").strip()
        owner_b = (body.owner_b or "").strip()
        owner_c = (body.owner_c or "").strip() or None
        if not owner_a or not owner_b:
            raise HTTPException(status_code=400, detail="owner_a and owner_b are required.")
        if owner_a == owner_b:
            raise HTTPException(status_code=400, detail="owner_a and owner_b must be different.")
        if owner_c and owner_c in (owner_a, owner_b):
            raise HTTPException(
                status_code=400,
                detail="owner_c must be different from owner_a and owner_b.",
            )

        limit = body.limit if "limit" in body.model_fields_set else 5
        run_ids = list(dict.fromkeys(body.run_ids)) if body.run_ids else None
        if run_ids is not None and not run_ids:
            raise HTTPException(status_code=400, detail="run_ids must not be empty.")
        if run_ids is not None and len(run_ids) > 50:
            raise HTTPException(status_code=400, detail="At most 50 run IDs allowed.")
        project = body.project or None

        from qalens.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            return _build_entity_comparison(
                conn, column="owner",
                entity_a=owner_a, entity_b=owner_b, entity_c=owner_c,
                limit=limit, project=project, run_ids=run_ids,
            )
        finally:
            conn.close()

    @router.post("/api/compare/suites", tags=["comparison"])
    async def compare_suites(body: EntityCompareRequest) -> dict[str, Any]:
        """Compare test results between two or three suites across a run window.

        Request body::

            {
                "suite_a":  "Authentication",
                "suite_b":  "Checkout",
                "suite_c":  "Payments",   // optional third suite
                "limit":    10,              // optional when run_ids provided
                "run_ids":  ["...", "..."],  // optional explicit custom range
                "project":  "OrangeHRM"   // optional
            }
        """
        suite_a = (body.suite_a or "").strip()
        suite_b = (body.suite_b or "").strip()
        suite_c = (body.suite_c or "").strip() or None
        if not suite_a or not suite_b:
            raise HTTPException(status_code=400, detail="suite_a and suite_b are required.")
        if suite_a == suite_b:
            raise HTTPException(status_code=400, detail="suite_a and suite_b must be different.")
        if suite_c and suite_c in (suite_a, suite_b):
            raise HTTPException(
                status_code=400,
                detail="suite_c must be different from suite_a and suite_b.",
            )

        limit = body.limit if "limit" in body.model_fields_set else 10
        run_ids = list(dict.fromkeys(body.run_ids)) if body.run_ids else None
        if run_ids is not None and not run_ids:
            raise HTTPException(status_code=400, detail="run_ids must not be empty.")
        if run_ids is not None and len(run_ids) > 50:
            raise HTTPException(status_code=400, detail="At most 50 run IDs allowed.")
        project = body.project or None

        from qalens.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            return _build_entity_comparison(
                conn, column="suite",
                entity_a=suite_a, entity_b=suite_b, entity_c=suite_c,
                limit=limit, project=project, run_ids=run_ids,
            )
        finally:
            conn.close()

    @router.get("/api/compare/breakdown", tags=["comparison"])
    async def compare_breakdown(
        project: str | None = Query(None, max_length=200, description="Filter by project name."),
        group_by: str = Query("owner", max_length=16, description="Dimension to group by: 'owner' or 'suite'."),
        limit: int = Query(10, ge=1, le=50, description="Number of most recent runs to include."),
        run_ids: list[str] | None = Query(None, description="Explicit run IDs (overrides limit)."),
    ) -> dict[str, Any]:
        """Compare test pass rates across runs, broken down by owner or suite.

        Returns a matrix where each row is an owner/suite and each column is a run,
        with pass/fail counts and pass rates per cell.  Useful for spotting which
        owner's tests are degrading or which suite is consistently broken.

        ``group_by`` must be ``"owner"`` or ``"suite"``.
        """
        _ALLOWED_GROUP_BY = {"owner", "suite"}
        if group_by not in _ALLOWED_GROUP_BY:
            raise HTTPException(
                status_code=400,
                detail=f"group_by must be one of {sorted(_ALLOWED_GROUP_BY)!r}.",
            )

        if run_ids is not None and len(run_ids) > 50:
            raise HTTPException(status_code=400, detail="At most 50 run IDs allowed.")

        from qalens.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            result = _build_breakdown(
                conn,
                group_by=group_by,
                project=project,
                limit=limit,
                run_ids=list(dict.fromkeys(run_ids)) if run_ids else None,
            )
        finally:
            conn.close()

        return result

    return router


# ---------------------------------------------------------------------------
# Lightweight compare catalogue helper
# ---------------------------------------------------------------------------

def _build_compare_facets(conn: Any, *, project: str | None, limit: int) -> dict[str, Any]:
    """Build picker facets from recent runs without row/cell comparison work."""
    params: list[Any] = []
    project_clause = ""
    if project:
        project_clause = "WHERE project = ?"
        params.append(project)

    run_rows = conn.execute(
        f"SELECT run_id FROM runs {project_clause} ORDER BY run_sequence DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    run_ids = [r["run_id"] for r in run_rows]
    if not run_ids:
        return {"owners": [], "suites": []}

    ph = ",".join("?" * len(run_ids))
    rows = conn.execute(
        f"""
        SELECT tc.canonical_name, tc.owner, tc.suite, r.run_sequence
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        WHERE tc.run_id IN ({ph})
          AND tc.is_retry = 0
        ORDER BY r.run_sequence DESC
        """,
        run_ids,
    ).fetchall()

    latest_by_name: dict[str, dict[str, str | None]] = {}
    for row in rows:
        cname = row["canonical_name"]
        current = latest_by_name.setdefault(cname, {"owner": None, "suite": None})
        if current["owner"] is None and row["owner"]:
            current["owner"] = row["owner"]
        if current["suite"] is None and row["suite"]:
            current["suite"] = row["suite"]

    owner_counts: dict[str, int] = {}
    suite_counts: dict[str, int] = {}
    for meta in latest_by_name.values():
        owner = meta["owner"]
        suite = meta["suite"]
        if owner:
            owner_counts[owner] = owner_counts.get(owner, 0) + 1
        if suite:
            suite_counts[suite] = suite_counts.get(suite, 0) + 1

    return {
        "owners": [
            {"name": name, "test_count": owner_counts[name]}
            for name in sorted(owner_counts)
        ],
        "suites": [
            {"name": name, "test_count": suite_counts[name]}
            for name in sorted(suite_counts)
        ],
    }


# ---------------------------------------------------------------------------
# Entity comparison helper (owner / suite)
# ---------------------------------------------------------------------------

def _build_entity_comparison(
    conn: Any,
    *,
    column: str,        # "owner" or "suite" — validated by caller, never user-supplied
    entity_a: str,
    entity_b: str,
    entity_c: str | None = None,
    limit: int,
    project: str | None,
    run_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the owner-vs-owner or suite-vs-suite comparison payload.

    Strategy
    --------
    * **Latest run** = the most recent run in the window.
    * **Baseline run** = the oldest run in the window.
    * ``metrics_a`` / ``metrics_b`` aggregate the latest run only so the
      summary cards give an apples-to-apples point-in-time comparison.
    * Each test row carries ``status_a`` (latest) vs ``status_b`` (baseline)
      so the table-level delta shows temporal regression/improvement.
    * The ``owner`` field on every row tells the UI which entity owns it.
    """
    # 1. Resolve run window
    if run_ids:
        placeholders = ",".join("?" * len(run_ids))
        run_rows = conn.execute(
            f"SELECT run_id, run_sequence, started_at FROM runs"
            f" WHERE run_id IN ({placeholders})"
            f" ORDER BY run_sequence DESC",
            run_ids,
        ).fetchall()
    else:
        params: list = []
        project_clause = ""
        if project:
            project_clause = "AND project = ?"
            params.append(project)

        run_rows = conn.execute(
            f"SELECT run_id, run_sequence, started_at FROM runs WHERE 1=1 {project_clause}"
            f" ORDER BY run_sequence DESC LIMIT ?",
            params + [limit],
        ).fetchall()

    if not run_rows:
        return _empty_entity_result(column, entity_a, entity_b, entity_c)

    latest_run_id   = run_rows[0]["run_id"]
    baseline_run_id = run_rows[-1]["run_id"]
    run_count       = len(run_rows)
    all_run_ids     = [r["run_id"] for r in run_rows]

    # run sequences oldest→newest (for history pills in the UI)
    run_seqs_asc = sorted(r["run_sequence"] for r in run_rows)
    runs_ordered = [
        {
            "run_sequence": r["run_sequence"],
            "display_name": f"Run #{r['run_sequence']}",
            "started_at": r["started_at"],
        }
        for r in sorted(run_rows, key=lambda x: x["run_sequence"])
    ]

    # 2. Resolve which canonical names currently belong to entity_a / entity_b (/ entity_c).
    #
    #    Tests often have owner/suite = NULL in recent runs because the report
    #    format only emits that metadata occasionally.  We use the same
    #    "current owner" CTE pattern as /api/owner-stats: for each canonical
    #    name, look at the highest run_sequence where the column was non-NULL,
    #    and use that assignment as the authoritative owner/suite.
    entities = [e for e in [entity_a, entity_b, entity_c] if e]
    ph_entities = ",".join("?" * len(entities))
    assignment_project_clause = "AND r.project = ?" if project else ""
    assignment_params: list[Any] = list(entities)
    if project:
        assignment_params.append(project)
    owned_rows = conn.execute(
        f"""
        WITH latest_assignment AS (
            SELECT tc.canonical_name, MAX(r.run_sequence) AS run_sequence
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            WHERE tc.{column} IN ({ph_entities})
              AND tc.{column} IS NOT NULL
              {assignment_project_clause}
            GROUP BY tc.canonical_name
        )
        SELECT tc.canonical_name,
               tc.{column}       AS entity,
               MAX(tc.name)      AS display_name,
               MAX(tc.suite)     AS suite
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        JOIN latest_assignment la
          ON la.canonical_name = tc.canonical_name
         AND la.run_sequence = r.run_sequence
        WHERE tc.{column} IN ({ph_entities})
          AND tc.{column} IS NOT NULL
        GROUP BY tc.canonical_name
        ORDER BY tc.{column}, tc.canonical_name
        """,
        assignment_params + entities,
    ).fetchall()

    if not owned_rows:
        return _empty_entity_result(column, entity_a, entity_b, entity_c)

    canonical_names = [r["canonical_name"] for r in owned_rows]
    # entity_map: canonical_name → entity_a or entity_b
    entity_map  = {r["canonical_name"]: r["entity"]       for r in owned_rows}
    display_map = {r["canonical_name"]: r["display_name"] for r in owned_rows}
    suite_map   = {r["canonical_name"]: r["suite"]        for r in owned_rows}

    ph          = ",".join("?" * len(canonical_names))
    ph_all_runs = ",".join("?" * len(all_run_ids))

    # 3. Full run history across the whole window (for per-test history pills + flaky detection)
    history_map: dict[str, dict[int, str]] = {}
    for r in conn.execute(
        f"""
        SELECT tc.canonical_name, r.run_sequence, tc.status
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        WHERE r.run_id IN ({ph_all_runs})
          AND tc.canonical_name IN ({ph})
          AND tc.is_retry = 0
        ORDER BY r.run_sequence ASC
        """,
        all_run_ids + canonical_names,
    ).fetchall():
        history_map.setdefault(r["canonical_name"], {})[r["run_sequence"]] = r["status"]

    # 4. Status in the latest run for those canonical names (may be absent)
    latest_status_map: dict[str, str] = {}
    latest_error_map:  dict[str, str | None] = {}
    for r in conn.execute(
        f"""
        SELECT tc.canonical_name, tc.status, f.message
        FROM test_cases tc
        LEFT JOIN failures f ON f.tc_id = tc.tc_id
        WHERE tc.run_id = ?
          AND tc.canonical_name IN ({ph})
          AND tc.is_retry = 0
        """,
        [latest_run_id] + canonical_names,
    ).fetchall():
        latest_status_map[r["canonical_name"]] = r["status"]
        latest_error_map[r["canonical_name"]]  = r["message"]

    # 5. Status in the baseline run (may be absent)
    baseline_map: dict[str, str] = {}
    if baseline_run_id != latest_run_id:
        for r in conn.execute(
            f"SELECT canonical_name, status FROM test_cases"
            f" WHERE run_id = ? AND canonical_name IN ({ph}) AND is_retry = 0",
            [baseline_run_id] + canonical_names,
        ).fetchall():
            baseline_map[r["canonical_name"]] = r["status"]

    # 6. Flaky count per entity (test is flaky if it has both passes AND failures in the window)
    entity_flaky: dict[str, int] = {e: 0 for e in entities}
    for cname in canonical_names:
        entity = entity_map[cname]
        hist_statuses = list(history_map.get(cname, {}).values())
        has_pass = any(s == "passed" for s in hist_statuses)
        has_fail = any(s in ("failed", "broken") for s in hist_statuses)
        if has_pass and has_fail:
            entity_flaky[entity] = entity_flaky.get(entity, 0) + 1

    # 7. Accumulate per-entity metrics (counts from the latest run only) + build rows
    counters: dict[str, dict[str, int]] = {
        e: {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "new_failures": 0, "fixed": 0}
        for e in entities
    }

    rows_out: list[dict] = []
    for cname in canonical_names:
        entity      = entity_map[cname]
        st_latest   = latest_status_map.get(cname, "absent")
        st_baseline = baseline_map.get(cname, "absent")

        m = counters.get(entity)
        if m is not None:
            m["total"] += 1
            if st_latest == "passed":
                m["passed"] += 1
            elif st_latest in ("failed", "broken"):
                m["failed"] += 1
            elif st_latest == "skipped":
                m["skipped"] += 1
            if st_latest in ("failed", "broken") and st_baseline not in ("failed", "broken"):
                m["new_failures"] += 1
            if st_latest == "passed" and st_baseline in ("failed", "broken"):
                m["fixed"] += 1

        run_history = [
            {"run_sequence": seq, "status": history_map.get(cname, {}).get(seq, "absent")}
            for seq in run_seqs_asc
        ]

        rows_out.append({
            "canonical_name": cname,
            "display_name":   display_map.get(cname, cname),
            "suite":          suite_map.get(cname),
            "owner":          entity if column == "owner" else None,
            "suite_name":     entity if column == "suite" else suite_map.get(cname),
            "status_a":       st_latest,
            "status_b":       st_baseline,
            "error_message":  latest_error_map.get(cname),
            "run_history":    run_history,
        })

    # 8. Assemble response
    def _metrics(entity: str, m: dict) -> dict:
        total  = m["total"]
        passed = m["passed"]
        failed = m["failed"]
        return {
            "label":        entity,
            "total_tests":  total,
            "passed":       passed,
            "failed":       failed,
            "skipped":      m["skipped"],
            "pass_rate":    round(passed / total, 4) if total else 0.0,
            "failure_rate": round(failed / total, 4) if total else 0.0,
            "flaky_count":  entity_flaky.get(entity, 0),
            "new_failures": m["new_failures"],
            "fixed_tests":  m["fixed"],
        }

    time_label = (
        f"Custom range · {run_count} run{'s' if run_count != 1 else ''}"
        if run_ids
        else f"Last {run_count} run{'s' if run_count != 1 else ''}"
    )

    result: dict[str, Any] = {
        "dimension":    column,
        "label_a":      entity_a,
        "label_b":      entity_b,
        "time_label":   time_label,
        "run_count":    run_count,
        "runs_ordered": runs_ordered,
        "metrics_a":    _metrics(entity_a, counters[entity_a]),
        "metrics_b":    _metrics(entity_b, counters[entity_b]),
        "rows":         rows_out,
    }
    if entity_c:
        result["label_c"]   = entity_c
        result["metrics_c"] = _metrics(entity_c, counters[entity_c])
    return result


def _empty_entity_result(
    column: str, entity_a: str, entity_b: str, entity_c: str | None = None
) -> dict[str, Any]:
    empty_metrics = {
        "label": "", "total_tests": 0, "passed": 0, "failed": 0,
        "skipped": 0, "pass_rate": 0.0, "failure_rate": 0.0,
        "flaky_count": 0, "new_failures": 0, "fixed_tests": 0,
    }
    result: dict[str, Any] = {
        "dimension": column, "label_a": entity_a, "label_b": entity_b,
        "time_label": "No runs found", "run_count": 0,
        "runs_ordered": [],
        "metrics_a": {**empty_metrics, "label": entity_a},
        "metrics_b": {**empty_metrics, "label": entity_b},
        "rows": [],
    }
    if entity_c:
        result["label_c"]   = entity_c
        result["metrics_c"] = {**empty_metrics, "label": entity_c}
    return result


# ---------------------------------------------------------------------------
# Breakdown helpers (kept outside the router factory to stay testable)
# ---------------------------------------------------------------------------

def _build_breakdown(
    conn: Any,
    *,
    group_by: str,
    project: str | None,
    limit: int,
    run_ids: list[str] | None,
) -> dict[str, Any]:
    """Assemble the owner/suite breakdown comparison response dict."""

    # ------------------------------------------------------------------ #
    # 1. Resolve the run set                                               #
    # ------------------------------------------------------------------ #
    if run_ids:
        placeholders = ",".join("?" * len(run_ids))
        run_rows = conn.execute(
            f"SELECT run_id, run_sequence, started_at FROM runs"
            f" WHERE run_id IN ({placeholders})"
            f" ORDER BY run_sequence ASC",
            run_ids,
        ).fetchall()
    else:
        params: list = []
        project_clause = ""
        if project:
            project_clause = "WHERE project = ?"
            params.append(project)
        # Fetch the N most recent, then reverse to get oldest-first order
        recent = conn.execute(
            f"SELECT run_id, run_sequence, started_at FROM runs"
            f" {project_clause}"
            f" ORDER BY run_sequence DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        run_rows = list(reversed(recent))

    if not run_rows:
        return {
            "group_by": group_by,
            "runs": [],
            "groups": [],
            "summary": {"total_runs": 0, "total_groups": 0},
        }

    resolved_run_ids = [r["run_id"] for r in run_rows]
    run_meta = {
        r["run_id"]: {
            "run_id": r["run_id"],
            "run_sequence": r["run_sequence"],
            "display_name": f"Run #{r['run_sequence']}",
            "started_at": r["started_at"],
        }
        for r in run_rows
    }

    # ------------------------------------------------------------------ #
    # 2. Aggregate counts per (group_value, run_id)                       #
    # group_by is already validated against a whitelist above.            #
    # ------------------------------------------------------------------ #
    placeholders = ",".join("?" * len(resolved_run_ids))
    params2: list = []
    project_filter = ""
    if project and not run_ids:
        project_filter = "AND r.project = ?"
        params2.append(project)
    params2.extend(resolved_run_ids)

    rows = conn.execute(
        f"""
        SELECT
            COALESCE(tc.{group_by}, '__unassigned__') AS group_name,
            r.run_id,
            COUNT(*)                                                            AS total,
            SUM(CASE WHEN tc.status = 'passed'              THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN tc.status = 'skipped'             THEN 1 ELSE 0 END) AS skipped
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        WHERE tc.is_retry = 0
          {project_filter}
          AND r.run_id IN ({placeholders})
        GROUP BY group_name, r.run_id
        ORDER BY group_name ASC, r.run_sequence ASC
        """,
        params2,
    ).fetchall()

    # ------------------------------------------------------------------ #
    # 3. Pivot into {group_name: {run_id: cell}}                          #
    # ------------------------------------------------------------------ #
    pivot: dict[str, dict[str, dict]] = {}
    for row in rows:
        g = row["group_name"]
        if g not in pivot:
            pivot[g] = {}
        total = row["total"] or 0
        passed = row["passed"] or 0
        failed = row["failed"] or 0
        skipped = row["skipped"] or 0
        pivot[g][row["run_id"]] = {
            "run_id": row["run_id"],
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": round(passed / total, 4) if total else None,
        }

    # ------------------------------------------------------------------ #
    # 4. Build response groups with per-run cells and summary stats       #
    # ------------------------------------------------------------------ #
    groups = []
    for group_name, cells_by_run in sorted(pivot.items()):
        cells = [
            cells_by_run.get(rid, {
                "run_id": rid,
                "total": None,
                "passed": None,
                "failed": None,
                "skipped": None,
                "pass_rate": None,
            })
            for rid in resolved_run_ids
        ]

        # Pass rates for runs where the group was present
        present_rates = [c["pass_rate"] for c in cells if c["pass_rate"] is not None]
        avg_pass_rate = round(sum(present_rates) / len(present_rates), 4) if present_rates else None

        # Simple trend: compare first-half avg vs second-half avg
        trend = _compute_trend(present_rates)

        groups.append({
            "name": group_name,
            "avg_pass_rate": avg_pass_rate,
            "trend": trend,
            "cells": cells,
        })

    # ------------------------------------------------------------------ #
    # 5. Summary                                                           #
    # ------------------------------------------------------------------ #
    present_groups = [g for g in groups if g["avg_pass_rate"] is not None]
    worst = min(present_groups, key=lambda g: g["avg_pass_rate"])["name"] if present_groups else None
    best = max(present_groups, key=lambda g: g["avg_pass_rate"])["name"] if present_groups else None

    return {
        "group_by": group_by,
        "runs": [run_meta[rid] for rid in resolved_run_ids],
        "groups": groups,
        "summary": {
            "total_runs": len(resolved_run_ids),
            "total_groups": len(groups),
            "worst_group": worst,
            "best_group": best,
        },
    }


def _compute_trend(rates: list[float]) -> str:
    """Return 'improving', 'degrading', or 'stable' based on pass-rate trajectory.

    Compares the average of the first half of runs to the average of the second
    half.  Returns 'stable' when fewer than two data points are available or the
    delta is within a ±5 % noise band.
    """
    if len(rates) < 2:
        return "stable"
    mid = len(rates) // 2
    first_avg = sum(rates[:mid]) / mid
    second_avg = sum(rates[mid:]) / len(rates[mid:])
    delta = second_avg - first_avg
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "degrading"
    return "stable"
