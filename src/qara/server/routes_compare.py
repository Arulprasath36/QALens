"""Run-comparison route handlers for the QARA FastAPI server.

Factory function :func:`make_compare_router` registers all
``/api/compare/*`` endpoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from qara.server.models import CompareRequest


def _parse_compare_filters(params: dict[str, Any]):
    """Convert a flat filter dict into a :class:`~ari.analyzers.comparison.ComparisonFilters`."""
    from qara.analyzers.comparison import ComparisonFilters
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
        project: str | None = Query(None),
        limit: int = Query(5, ge=1, le=50, description="Window size (1-50 runs)."),
        before_run_id: str | None = Query(None, description="Paginate: runs older than this run_id."),
    ) -> dict[str, Any]:
        """Return a sliding-window comparison for the N most recent runs.

        Use ``before_run_id`` to append older runs (Add-more-runs workflow).
        """
        from qara.analyzers.comparison import ComparisonService, comparison_to_dict
        from qara.db.schema import get_connection

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
        from qara.analyzers.comparison import ComparisonService, comparison_to_dict
        from qara.db.schema import get_connection

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
        project: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        before_run_id: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        """Return a lightweight run list for the run-picker dropdown."""
        from qara.analyzers.comparison import ComparisonService
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return ComparisonService(conn).available_runs(
                project=project, limit=limit, before_run_id=before_run_id
            )
        finally:
            conn.close()

    return router
