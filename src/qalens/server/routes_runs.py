"""Run-data route handlers for the QALens FastAPI server.

Factory function :func:`make_runs_router` registers all ``/api/runs`` and
``/api/tests`` endpoints onto an :class:`~fastapi.APIRouter`, which is then
mounted by :func:`~qalens.server.app.create_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from qalens.security import ALLOWED_TEST_STATUSES
from qalens.server.models import _dc_to_dict


def make_runs_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with all run-data endpoints."""
    router = APIRouter()

    @router.get("/api/runs", tags=["data"])
    async def list_runs(
        project: str | None = Query(None, max_length=200, description="Filter by project name."),
        limit: int = Query(50, ge=1, le=500, description="Maximum rows."),
    ) -> list[dict[str, Any]]:
        """Return the most-recent run rows, newest first."""
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            repo = RunRepository(conn)
            rows = repo.list_runs(project=project, limit=limit)
            return [_dc_to_dict(r) for r in rows]
        finally:
            conn.close()

    @router.get("/api/runs/{run_id}", tags=["data"])
    async def get_run(run_id: str) -> dict[str, Any]:
        """Return metadata for a single run."""
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            row = RunRepository(conn).get_run(run_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
            return _dc_to_dict(row)
        finally:
            conn.close()

    @router.get("/api/runs/{run_id}/tests", tags=["data"])
    async def get_run_tests(
        run_id: str,
        status: str | None = Query(None, description="Filter by status (passed/failed/skipped)."),
        include_details: bool = Query(
            True,
            description="Include stack traces and attachment metadata.",
        ),
    ) -> list[dict[str, Any]]:
        """Return all test cases for a run."""
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            if status is not None and status.lower() not in ALLOWED_TEST_STATUSES:
                allowed = ", ".join(sorted(ALLOWED_TEST_STATUSES))
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid status filter. Allowed: {allowed}.",
                )
            status_filter = status.lower() if status else None
            repo = RunRepository(conn)
            if repo.get_run(run_id) is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
            tests = repo.get_test_cases_for_run(
                run_id,
                status=status_filter,
                include_details=include_details,
            )
            return [_dc_to_dict(t) for t in tests]
        finally:
            conn.close()

    @router.get("/api/tests/{tc_id}/attachment/{idx}", tags=["data"], include_in_schema=False)
    async def get_attachment(tc_id: str, idx: int) -> Response:
        """Serve a test-case attachment file by 0-based index (path resolved from DB)."""
        import mimetypes

        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT kind, name, resolved_path FROM attachments WHERE tc_id = ? ORDER BY id",
                (tc_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows or idx < 0 or idx >= len(rows):
            raise HTTPException(status_code=404, detail="Attachment not found.")
        row = rows[idx]
        file_path = row["resolved_path"]
        if not file_path:
            raise HTTPException(status_code=404, detail="Attachment has no resolved path.")
        stored = Path(file_path)
        try:
            # strict=True raises OSError if the path does not exist,
            # and follows all symlinks to the real target.
            resolved = stored.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail="Attachment file not found on disk.",
            ) from exc
        # The stored path was produced by safe_join().resolve() at ingest time,
        # so it is already canonical.  If resolve() now returns a different path,
        # a symlink was placed at the stored location after ingestion — reject it.
        if resolved != stored:
            raise HTTPException(status_code=403, detail="Attachment path is invalid.")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="Attachment file not found on disk.")
        mime, _ = mimetypes.guess_type(str(resolved))
        return Response(
            content=resolved.read_bytes(),
            media_type=mime or "application/octet-stream",
        )

    @router.get("/api/tests/{tc_id}/artifact/{artifact_id}", tags=["data"], include_in_schema=False)
    async def get_artifact(tc_id: str, artifact_id: int) -> Response:
        """Serve a policy-ingested artifact file by its DB id."""
        import mimetypes

        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT storage_uri, mime_type FROM artifacts WHERE id = ? AND tc_id = ?",
                (artifact_id, tc_id),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        storage_uri = row["storage_uri"] or ""
        if not storage_uri.startswith("file://"):
            raise HTTPException(status_code=404, detail="Artifact has no stored file.")
        file_path = storage_uri[len("file://"):]
        stored = Path(file_path)
        try:
            resolved = stored.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail="Artifact file not found on disk.",
            ) from exc
        if resolved != stored:
            raise HTTPException(status_code=403, detail="Artifact path is invalid.")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="Artifact file not found on disk.")
        mime = (
            row["mime_type"]
            or mimetypes.guess_type(str(resolved))[0]
            or "application/octet-stream"
        )
        return Response(content=resolved.read_bytes(), media_type=mime)

    @router.get("/api/runs/{run_id}/incidents", tags=["incidents"])
    async def get_run_incidents(run_id: str) -> list[dict[str, Any]]:
        """Return incident summaries for *run_id*.

        Incidents are assembled on-demand by grouping failed/broken test cases
        from the run by failure fingerprint and error type, then annotating each
        group with a probable root cause, evidence bullets, and a recommended
        action.  Returns an empty list when no failures exist.
        """
        from qalens.analyzers.incidents import assemble_incidents
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            if RunRepository(conn).get_run(run_id) is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        finally:
            conn.close()

        incidents = assemble_incidents(run_id, db_path)
        return [i.to_dict() for i in incidents]

    return router
