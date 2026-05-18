"""Report export route handlers for the QaLens FastAPI server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

if TYPE_CHECKING:
    from pathlib import Path

    from qalens.reports.model import ShareableReport


def make_report_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with report export endpoints."""
    router = APIRouter()

    @router.get("/api/report/export", tags=["report"])
    async def export_report(
        project: str | None = Query(None, description="Project name to report on."),
        format: str = Query("html", description="Export format: html, markdown, md, or json."),  # noqa: A002
        run_id: str = Query("latest", description="Run id, run sequence number, or 'latest'."),
        window: int = Query(10, ge=1, le=100, description="Recent run count."),
        min_runs: int = Query(2, ge=1, le=100, description="Minimum stability history depth."),
        limit: int = Query(10, ge=1, le=50, description="Maximum rows per section."),
    ) -> Response:
        """Export a deterministic shareable report as a downloadable file."""
        from qalens.reports import build_report

        fmt = format.lower().strip()
        if fmt not in {"html", "markdown", "md", "json"}:
            raise HTTPException(
                status_code=422,
                detail="Format must be html, markdown, md, or json.",
            )

        try:
            data = build_report(
                db_path=db_path,
                project=project or None,
                run_id=run_id,
                window=window,
                min_runs=min_runs,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Report export failed: {exc}") from exc

        content, media_type, filename = _render_report_payload(data, fmt)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router


def _render_report_payload(data: ShareableReport, fmt: str) -> tuple[str, str, str]:
    from qalens.reports import render_html, render_json, render_markdown

    stem = _filename_stem(data.scope_label)
    if fmt == "html":
        return render_html(data), "text/html; charset=utf-8", f"{stem}.html"
    if fmt in {"markdown", "md"}:
        return render_markdown(data), "text/markdown; charset=utf-8", f"{stem}.md"
    return render_json(data), "application/json; charset=utf-8", f"{stem}.json"


def _filename_stem(scope_label: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in scope_label)
    safe = "-".join(part for part in safe.split("-") if part)
    return f"qalens-report-{safe or 'latest'}"
