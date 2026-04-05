"""Evidence drawer API routes for the QARA web UI.

Provides lightweight, lazily-fetched evidence payloads used by the in-chat
Evidence Drawer.  Click a source card → fetch from here → display context
without navigating away from the chat.

Public endpoints
----------------
GET /api/evidence/test/{canonical_name}
    Returns concise evidence for a specific test: risk tier, recent run
    pattern, most frequent failure, and signal-derived "why_relevant" bullets.

GET /api/evidence/run/{run_id}
    Returns a summary snapshot of a single run: counts, top failures, and
    any recurring failure pattern already catalogued.
"""

from __future__ import annotations

from pathlib import Path

from datetime import datetime, timezone
from urllib.parse import quote as _quote

from fastapi import APIRouter, HTTPException, Query


def make_evidence_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with the evidence endpoints."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # Test-level evidence
    # ------------------------------------------------------------------

    @router.get("/api/evidence/test/{canonical_name}", tags=["evidence"])
    async def test_evidence(
        canonical_name: str,
        project: str | None = None,
    ) -> dict:
        """Return concise evidence for a single test.

        The payload is designed for the Evidence Drawer and includes:

        * ``title`` — display name
        * ``classification`` / ``risk_tier`` / ``risk_pct`` — stability labels
        * ``why_relevant`` — signal-derived human-readable bullets
        * ``recent_runs`` — last 5 run statuses with IDs and timestamps
        * ``most_frequent_error`` — dominant error type and first-line message
        * ``owner`` — attribution when available
        * ``sparkline`` — compact history string (``✓✗…``)
        * ``actions`` — URLs for navigation to full history / latest run

        Args:
            canonical_name: URL-safe canonical test name.
            project: Optional project filter.

        Raises:
            HTTP 404 when no history is found for the test.
        """
        from qara.analyzers.canonical import to_canonical_name
        from qara.analyzers.flaky import FlakyScorer
        from qara.analyzers.predictor import RiskPredictor, RiskTier
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        conn = get_connection(db_path)

        try:
            repo = RunRepository(conn)
            canonical = to_canonical_name(canonical_name)

            # --- Flaky score (always available) ---
            scorer = FlakyScorer(conn)
            flaky = scorer.score(canonical, project=project)

            if flaky.run_count == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"No history found for test '{canonical_name}'.",
                )

            # --- Risk prediction (adds tier / signals) ---
            predictor = RiskPredictor(conn)
            try:
                prediction = predictor.predict(canonical, project=project)
                risk_tier = prediction.tier.value
                risk_pct = prediction.risk_pct
                signals = prediction.signals
            except Exception:
                prediction = None
                risk_tier = None
                risk_pct = None
                signals = None

            # --- Why relevant (signal bullets) ---
            why_relevant: list[str] = []
            if flaky.flip_score >= 0.5:
                why_relevant.append(
                    f"High volatility — switches pass↔fail {flaky.flip_score:.0%} of the time"
                )
            elif flaky.flip_score >= 0.25:
                why_relevant.append(
                    f"Moderate volatility (flip score {flaky.flip_score:.2f})"
                )
            if flaky.pass_rate < 0.5:
                why_relevant.append(
                    f"Low pass rate ({flaky.pass_rate:.0%} across {flaky.run_count} runs)"
                )
            if signals is not None:
                if signals.recent_decline > 0.15:
                    why_relevant.append(
                        "Recent decline — failure rate higher than historical average"
                    )
                if signals.fail_streak > 0.33:
                    streak = abs(flaky.current_streak)
                    why_relevant.append(
                        f"Active failure streak ({streak} consecutive {'failure' if streak == 1 else 'failures'})"
                    )
                if signals.duration_spike > 0.15:
                    why_relevant.append("Duration spike — test is getting slower over time")
            if not why_relevant:
                why_relevant.append(
                    f"Included in context ({flaky.classification.label}, "
                    f"{flaky.pass_rate:.0%} pass rate)"
                )

            # --- Recent runs (last 5) ---
            # Fetch full history (ASC = oldest first); slice the tail for the
            # 5 most recent runs, then reverse to display newest-first.
            history = repo.get_test_history(canonical, project=project, limit=500)
            recent_runs = [
                {
                    "run_id": h.run_id,
                    "run_label": f"Run #{h.run_sequence}" if h.run_sequence else h.run_id[:8],
                    "status": h.status,
                    "timestamp": datetime.fromtimestamp(h.started_at, tz=timezone.utc).isoformat() if h.started_at else None,
                }
                for h in reversed(history[-5:])  # 5 most recent, newest first
            ]

            # --- Most frequent error ---
            most_frequent_error: dict | None = None
            error_counts: dict[str, dict] = {}
            for h in history:
                if h.error_type:
                    key = h.error_type
                    if key not in error_counts:
                        error_counts[key] = {
                            "category": h.error_type,
                            "message": (h.message or "").split("\n")[0][:200],
                            "count": 0,
                        }
                    error_counts[key]["count"] += 1
            if error_counts:
                top = max(error_counts.values(), key=lambda e: e["count"])
                total_failures = sum(e["count"] for e in error_counts.values())
                most_frequent_error = {
                    "category": top["category"],
                    "message": top["message"],
                    "count": top["count"],
                    "total_failures": total_failures,
                }

            # --- Owner ---
            owner: str | None = getattr(prediction, "owner", None) or flaky.owner

            # --- Action URLs (relative paths) ---
            actions = {
                "history_url": f"/?tab=analysis",
                "latest_run_url": (
                    f"/?run={recent_runs[0]['run_id']}&label={_quote(recent_runs[0]['run_label'])}"
                    if recent_runs
                    else None
                ),
                "risk_url": f"/?tab=risk&highlight={_quote(canonical)}",
            }

            return {
                "type": "test",
                "canonical_name": canonical,
                "title": flaky.display_name,
                "classification": flaky.classification.label,
                "risk_tier": risk_tier,
                "risk_pct": risk_pct,
                "pass_rate": round(flaky.pass_rate, 4),
                "flip_score": round(flaky.flip_score, 4),
                "run_count": flaky.run_count,
                "sparkline": flaky.sparkline,
                "why_relevant": why_relevant,
                "recent_runs": recent_runs,
                "most_frequent_error": most_frequent_error,
                "owner": owner,
                "actions": actions,
            }

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Run-level evidence
    # ------------------------------------------------------------------

    @router.get("/api/evidence/run/{run_id}", tags=["evidence"])
    async def run_evidence(
        run_id: str,
        category: str | None = Query(None, description="Filter by comparison category: newly_failing | recovered | consistently_failing"),
        vs_run_id: str | None = Query(None, description="Older run ID for comparison categories"),
    ) -> dict:
        """Return a summary snapshot for a single run.

        When *category* and *vs_run_id* are provided the response focuses on
        the specific comparison group (newly_failing, recovered, or
        consistently_failing) by diffing *run_id* against *vs_run_id*.

        Args:
            run_id:     UUID of the (newer) run.
            category:   Comparison group to filter by.
            vs_run_id:  UUID of the older run to compare against.

        Raises:
            HTTP 404 when the run is not found.
        """
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        conn = get_connection(db_path)

        _CATEGORY_LABELS = {
            "newly_failing":        "Newly Failing Tests",
            "recovered":            "Recovered Tests",
            "consistently_failing": "Consistently Failing Tests",
        }

        try:
            repo = RunRepository(conn)
            run = repo.get_run(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

            run_label = (
                f"Run #{run.run_sequence}"
                if run.run_sequence
                else run_id[:8]
            )

            # ── Category-filtered view (comparison card) ──────────────────
            if category in _CATEGORY_LABELS and vs_run_id:
                newer_tcs = repo.get_test_cases_for_run(run_id)
                older_tcs = repo.get_test_cases_for_run(vs_run_id)

                older_run = repo.get_run(vs_run_id)
                older_label = (
                    f"Run #{older_run.run_sequence}" if older_run and older_run.run_sequence
                    else (vs_run_id[:8] if vs_run_id else "older run")
                )

                def _failed(status: str) -> bool:
                    return status in ("failed", "broken")

                newer_map = {tc.name: tc for tc in newer_tcs}
                older_map = {tc.name: tc for tc in older_tcs}
                all_names = sorted(set(newer_map) | set(older_map))

                category_tests = []
                for name in all_names:
                    newer_tc = newer_map.get(name)
                    older_tc = older_map.get(name)
                    newer_failed = _failed(newer_tc.status) if newer_tc else False
                    older_failed = _failed(older_tc.status) if older_tc else False

                    if category == "newly_failing" and newer_failed and not older_failed:
                        tc = newer_tc
                        category_tests.append({
                            "name": tc.name,
                            "status": tc.status,
                            "error_type": tc.error_type,
                            "message": (tc.message or "").split("\n")[0][:200],
                        })
                    elif category == "recovered" and not newer_failed and older_failed:
                        tc = newer_tc or older_tc
                        category_tests.append({
                            "name": name,
                            "status": "passed",
                            "error_type": older_tc.error_type if older_tc else None,
                            "message": None,
                        })
                    elif category == "consistently_failing" and newer_failed and older_failed:
                        tc = newer_tc
                        category_tests.append({
                            "name": tc.name,
                            "status": tc.status,
                            "error_type": tc.error_type,
                            "message": (tc.message or "").split("\n")[0][:200],
                        })

                return {
                    "type": "run",
                    "run_id": run_id,
                    "title": _CATEGORY_LABELS[category],
                    "tests_label": _CATEGORY_LABELS[category],
                    "meta": f"{run_label} vs {older_label}",
                    "project": run.project,
                    "top_failed": category_tests[:20],
                    "recurring_pattern": None,
                    "actions": {
                        "run_url": f"/?run={run_id}&label={_quote(run_label)}",
                        "run_label": f"Go to {run_label}",
                        "history_url": "/?tab=analysis",
                        "risk_url": "/?tab=risk",
                    },
                }

            # ── Generic run snapshot (no category) ───────────────────────
            test_cases = repo.get_test_cases_for_run(run_id)
            failed = [tc for tc in test_cases if tc.status in ("failed", "broken")]

            # Top failed tests (up to 5)
            top_failed = [
                {
                    "name": tc.name,
                    "status": tc.status,
                    "error_type": tc.error_type,
                    "message": (tc.message or "").split("\n")[0][:200],
                }
                for tc in failed[:5]
            ]

            # Most common failure fingerprint among failures in this run
            fp_counts: dict[str, int] = {}
            fp_samples: dict[str, dict] = {}
            for tc in failed:
                if tc.fingerprint:
                    fp_counts[tc.fingerprint] = fp_counts.get(tc.fingerprint, 0) + 1
                    if tc.fingerprint not in fp_samples:
                        fp_samples[tc.fingerprint] = {
                            "error_type": tc.error_type,
                            "message": (tc.message or "").split("\n")[0][:200],
                        }
            recurring_pattern: dict | None = None
            if fp_counts:
                top_fp = max(fp_counts, key=lambda k: fp_counts[k])
                if fp_counts[top_fp] > 1:
                    recurring_pattern = {
                        "count": fp_counts[top_fp],
                        **fp_samples[top_fp],
                    }

            return {
                "type": "run",
                "run_id": run_id,
                "title": run_label,
                "project": run.project,
                "started_at": datetime.fromtimestamp(run.started_at, tz=timezone.utc).isoformat() if run.started_at else None,
                "total_tests": run.total_tests,
                "passed_count": run.passed_count,
                "failed_count": run.failed_count,
                "skipped_count": run.skipped_count,
                "top_failed": top_failed,
                "recurring_pattern": recurring_pattern,
                "actions": {
                    "run_url": f"/?run={run_id}&label={_quote(run_label)}",
                    "run_label": f"Go to {run_label}",
                },
            }

        finally:
            conn.close()

    return router
