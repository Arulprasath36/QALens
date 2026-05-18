"""Decision-intelligence route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

if TYPE_CHECKING:
    from pathlib import Path


def make_decision_router(db_path: str | Path | None) -> APIRouter:
    """Return an API router for deterministic decision intelligence."""
    router = APIRouter()

    @router.get("/api/decision-summary", tags=["analysis"])
    async def decision_summary(
        project: str | None = Query(None, max_length=200),
        run_id: str = Query("latest", max_length=128),
        window: int = Query(5, ge=2, le=20),
    ) -> dict[str, Any]:
        """Return executive summary, trend interpretation, and fix-first actions."""
        from qalens.analyzers.decision import build_decision_summary

        return build_decision_summary(
            db_path=db_path,
            project=project or None,
            run_id=run_id,
            window=window,
        )

    return router
