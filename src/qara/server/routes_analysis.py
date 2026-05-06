"""Analysis route handlers for the QARA FastAPI server.

Factory function :func:`make_analysis_router` registers endpoints for
stability, flaky-test detection, failure groups, and risk prediction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from qara.server.models import _dc_to_dict

_ALLOWED_RISK_TIERS = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
_MAX_FAILURE_GROUP_RUN_IDS = 50


def make_analysis_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with all analysis endpoints."""
    router = APIRouter()

    @router.get("/api/stability", tags=["analysis"])
    async def stability(
        project: str | None = Query(None, description="Filter by project name."),
        min_runs: int = Query(2, ge=1, description="Minimum run appearances."),
        limit: int = Query(30, ge=5, le=100, description="History window size per test."),
    ) -> list[dict[str, Any]]:
        """Return flakiness profiles for all tests with sufficient history."""
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            results = FlakyScorer(conn).get_all(project=project, min_runs=min_runs, limit_per_test=limit)
            suite_map = RunRepository(conn).get_latest_suite_per_canonical_name(project=project)
            return [_dc_to_dict(r) | {"suite": suite_map.get(r.canonical_name, "")} for r in results]
        finally:
            conn.close()

    @router.get("/api/stability/flaky", tags=["analysis"])
    async def flaky_tests(
        project: str | None = Query(None),
        min_runs: int = Query(2, ge=1),
    ) -> list[dict[str, Any]]:
        """Return only tests classified as FLAKY."""
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            results = FlakyScorer(conn).get_all_flaky(project=project, min_runs=min_runs)
            return [_dc_to_dict(r) for r in results]
        finally:
            conn.close()

    @router.get("/api/failure-groups", tags=["analysis"])
    async def failure_groups(
        project: str | None = Query(None),
        limit: int = Query(20, ge=1, le=200),
        run_ids: str | None = Query(None, description="Comma-separated run IDs to scope counts to a window."),
    ) -> list[dict[str, Any]]:
        """Return recurring failure groups ranked by occurrence count.

        When ``run_ids`` is supplied all counts are scoped to those runs and
        each group carries ``scope="window"``.  Without ``run_ids`` the
        response is all-time and groups carry ``scope="all_time"``.
        """
        from qara.analyzers.categorizer import categorize_failure
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        parsed_run_ids = [r.strip() for r in run_ids.split(",") if r.strip()] if run_ids else None
        if parsed_run_ids is not None and len(parsed_run_ids) > _MAX_FAILURE_GROUP_RUN_IDS:
            raise HTTPException(status_code=422, detail="At most 50 run IDs allowed.")

        conn = get_connection(db_path)
        try:
            groups = RunRepository(conn).get_failure_groups(
                project=project,
                limit=limit,
                run_ids=parsed_run_ids,
            )
            for g in groups:
                cat = categorize_failure(
                    error_type=g.get("error_type"),
                    message=g.get("message"),
                )
                g["category"] = cat.label
            return groups
        finally:
            conn.close()

    @router.get("/api/risk", tags=["analysis"])
    async def risk_predictions(
        project: str | None = Query(None, description="Filter by project name."),
        min_runs: int = Query(2, ge=1, description="Minimum run appearances."),
        tier: str | None = Query(None, description="Filter by tier: CRITICAL, HIGH, MEDIUM, LOW."),
    ) -> list[dict[str, Any]]:
        """Return flakiness risk predictions for all tests with sufficient history."""
        from qara.analyzers.predictor import RiskPredictor
        from qara.db.schema import get_connection, init_db

        conn = get_connection(db_path)
        try:
            init_db(conn)
            predictor = RiskPredictor(conn)
            predictions = predictor.predict_all(project=project, min_runs=min_runs)
            if tier:
                tier_upper = tier.upper()
                if tier_upper not in _ALLOWED_RISK_TIERS:
                    allowed = ", ".join(sorted(_ALLOWED_RISK_TIERS))
                    raise HTTPException(status_code=422, detail=f"Invalid risk tier. Allowed: {allowed}.")
                predictions = [p for p in predictions if p.tier.name == tier_upper]
            return [_dc_to_dict(p) for p in predictions]
        finally:
            conn.close()

    @router.get("/api/stability/trends", tags=["analysis"])
    async def stability_trends(
        project: str | None = Query(None),
        min_runs: int = Query(2, ge=1),
        limit: int = Query(30, ge=5, le=100, description="History window size per test."),
    ) -> list[dict[str, Any]]:
        """Return per-test pass-rate trend direction for the Flaky Tests table."""
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection, init_db
        from qara.llm.trend import RunRate, compute_trend

        conn = get_connection(db_path)
        try:
            init_db(conn)
            scorer = FlakyScorer(conn)
            repo = RunRepository(conn)
            results = scorer.get_all(project=project, min_runs=min_runs, limit_per_test=limit)
            out = []
            for r in results:
                history = repo.get_test_history(
                    r.canonical_name, project=project, limit=limit
                )
                if len(history) < 2:
                    continue
                run_rates = [
                    RunRate(
                        label=f"Run #{e.run_sequence}",
                        pass_rate=1.0 if e.status == "passed" else 0.0,
                    )
                    for e in history
                ]
                trend = compute_trend(run_rates)
                out.append({
                    "canonical_name": r.canonical_name,
                    "direction": trend.direction,
                    "delta_pct": trend.delta_pct,
                    "confidence": trend.confidence,
                })
            return out
        finally:
            conn.close()

    @router.get("/api/owner-stats", tags=["analysis"])
    async def owner_stats(
        project: str | None = Query(None, description="Filter by project name."),
    ) -> dict:
        """Return all-time failure rate and execution counts per owner.

        Uses each test's most recent non-NULL owner so figures reflect
        current ownership.  Covers the full run history (no window limit).
        """
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            cur = conn.cursor()
            current_owner_project_clause = "AND r.project = ?" if project else ""
            main_project_clause = "AND r.project = ?" if project else ""
            params: list = []
            if project:
                params.append(project)
                params.append(project)

            cur.execute(
                f"""
                WITH latest_owner AS (
                    SELECT tc.canonical_name, MAX(r.run_sequence) AS run_sequence
                    FROM test_cases tc
                    JOIN runs r ON tc.run_id = r.run_id
                    WHERE tc.owner IS NOT NULL
                      {current_owner_project_clause}
                    GROUP BY tc.canonical_name
                ),
                current_owner AS (
                    SELECT tc.canonical_name, MAX(tc.owner) AS owner
                    FROM test_cases tc
                    JOIN runs r ON tc.run_id = r.run_id
                    JOIN latest_owner lo
                      ON lo.canonical_name = tc.canonical_name
                     AND lo.run_sequence = r.run_sequence
                    WHERE tc.owner IS NOT NULL
                    GROUP BY tc.canonical_name
                )
                SELECT
                    co.owner,
                    COUNT(*)                                                            AS total_executions,
                    SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END)  AS failed_executions,
                    COUNT(DISTINCT tc.canonical_name)                                   AS total_tests,
                    COUNT(DISTINCT CASE WHEN tc.status IN ('failed','broken')
                                        THEN tc.canonical_name END)                     AS failing_tests,
                    COUNT(DISTINCT r.run_id)                                            AS run_count
                FROM test_cases tc
                JOIN runs r ON tc.run_id = r.run_id
                JOIN current_owner co ON co.canonical_name = tc.canonical_name
                WHERE 1=1 {main_project_clause}
                GROUP BY co.owner
                ORDER BY failed_executions DESC, co.owner
                """,
                params,
            )
            rows = cur.fetchall()

            if project:
                total_runs = cur.execute(
                    "SELECT COUNT(*) FROM runs WHERE project = ?", (project,)
                ).fetchone()[0]
            else:
                total_runs = cur.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            conn.close()

        owners = [
            {
                "owner": row[0],
                "total_executions": row[1],
                "failed_executions": row[2],
                "failure_rate": round(row[2] / row[1], 4) if row[1] else 0.0,
                "total_tests": row[3],
                "failing_tests": row[4],
                "run_count": row[5],
            }
            for row in rows
        ]
        return {"total_runs": total_runs, "owners": owners}

    @router.post("/api/failure-groups/{fingerprint}/bug-links", tags=["analysis"])
    async def add_bug_link(fingerprint: str, body: dict) -> dict:
        """Link a bug URL to a failure fingerprint."""
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        url = (body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        if len(url) > 2048:
            raise HTTPException(status_code=400, detail="url must be 2048 characters or fewer")
        from urllib.parse import urlparse
        _scheme = urlparse(url).scheme.lower()
        if _scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="url must use http or https")
        label = (body.get("label") or _extract_label(url) or None)
        conn = get_connection(db_path)
        try:
            repo = RunRepository(conn)
            new_id = repo.add_bug_link(fingerprint, url, label)
            return {"id": new_id, "bug_url": url, "label": label}
        finally:
            conn.close()

    @router.delete("/api/failure-groups/{fingerprint}/bug-links/{link_id}", tags=["analysis"])
    async def remove_bug_link(fingerprint: str, link_id: int) -> dict:
        """Remove a bug link by ID."""
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            repo = RunRepository(conn)
            repo.remove_bug_link(link_id)
            return {"ok": True}
        finally:
            conn.close()

    return router


def _extract_label(url: str) -> str | None:
    """Auto-extract a short label from a bug tracker URL."""
    # JIRA: /browse/PROJ-123
    m = re.search(r"/browse/([A-Z]+-\d+)", url)
    if m:
        return m.group(1)
    # GitHub issues/PRs: /issues/456 or /pull/456
    m = re.search(r"/(?:issues|pull)/(\d+)", url)
    if m:
        return f"#{m.group(1)}"
    # Linear: /issue/TEAM-789
    m = re.search(r"/issue/([A-Z]+-\d+)", url)
    if m:
        return m.group(1)
    return None
