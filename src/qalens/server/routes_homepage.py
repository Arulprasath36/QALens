"""Homepage-cards route handler for the QALens FastAPI server.

Provides GET /api/homepage-cards — returns 4 live intelligence cards for the
chat welcome screen, each with a real metric and a suggested question.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from qalens.server.models import HomepageCard, HomepageCardsResponse


def make_homepage_router(db_path: str | Path | None) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with the /api/homepage-cards endpoint."""
    router = APIRouter()

    @router.get("/api/homepage-cards", tags=["ui"])
    async def homepage_cards(
        project: str | None = Query(None, description="Filter by project name."),
    ) -> HomepageCardsResponse:
        """Return 4 live insight cards for the chat home screen.

        Each card carries a real metric drawn from the DB so the user can
        see their current test intelligence at a glance before asking a
        question.  Cards that cannot be computed (insufficient data) have
        ``available=False`` and a placeholder metric.
        """
        from qalens.db.repository import RunRepository
        from qalens.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            repo = RunRepository(conn)
            cards = _build_cards(conn, repo, project)
        finally:
            conn.close()

        return HomepageCardsResponse(cards=cards)

    return router


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _build_cards(conn, repo, project: str | None) -> list[HomepageCard]:
    """Compute all 4 homepage cards, catching any per-card errors."""
    builders = [
        _card_latest_run,
        _card_new_regressions,
        _card_risk,
        _card_root_cause,
    ]
    cards: list[HomepageCard] = []
    for builder in builders:
        try:
            cards.append(builder(conn, repo, project))
        except Exception:
            # Surface a fallback unavailable card rather than failing the whole request
            cards.append(_unavailable_fallback(builder.__name__))
    return cards


def _card_latest_run(conn, repo, project: str | None) -> HomepageCard:
    """Card 1 — latest run failure count."""
    runs = repo.list_runs(project=project, limit=1)
    if not runs:
        return HomepageCard(
            id="latest_run",
            icon="🔥",
            title="Latest Run",
            metric="No runs yet",
            question="What broke in the latest run?",
            available=False,
        )
    latest = runs[0]
    failed = latest.failed_count or 0
    run_label = f" in Run #{latest.run_sequence}" if latest.run_sequence else ""
    if failed == 0:
        metric = f"All tests passed{run_label}"
    else:
        metric = f"{failed} failure{'s' if failed != 1 else ''}{run_label}"
    return HomepageCard(
        id="latest_run",
        icon="🔥",
        title="Latest Run",
        metric=metric,
        question="What broke in the latest run?",
    )


def _card_new_regressions(conn, repo, project: str | None) -> HomepageCard:
    """Card 2 — newly failing tests vs the previous run."""
    runs = repo.list_runs(project=project, limit=2)
    if len(runs) < 2:
        return HomepageCard(
            id="new_regressions",
            icon="🚨",
            title="New Regressions",
            metric="Need ≥ 2 runs",
            question="What new failures were introduced?",
            available=False,
        )
    newer_run, older_run = runs[0], runs[1]
    newer_tests = repo.get_test_cases_for_run(newer_run.run_id)
    older_tests = repo.get_test_cases_for_run(older_run.run_id)

    def _failed(status: str) -> bool:
        return status in ("failed", "broken")

    older_failed = {tc.name for tc in older_tests if _failed(tc.status)}
    newly_failing = sum(
        1 for tc in newer_tests
        if _failed(tc.status) and tc.name not in older_failed
    )
    if newly_failing == 0:
        metric = "No new regressions"
    else:
        metric = f"{newly_failing} new failure{'s' if newly_failing != 1 else ''}"
    return HomepageCard(
        id="new_regressions",
        icon="🚨",
        title="New Regressions",
        metric=metric,
        question="What new failures were introduced?",
    )


def _card_risk(conn, repo, project: str | None) -> HomepageCard:
    """Card 3 — HIGH/CRITICAL risk test count from RiskPredictor."""
    from qalens.analyzers.predictor import RiskPredictor, RiskTier

    predictor = RiskPredictor(conn)
    predictions = predictor.predict_all(project=project)
    high_critical = [
        p for p in predictions
        if p.tier in (RiskTier.HIGH, RiskTier.CRITICAL)
    ]
    count = len(high_critical)
    if count == 0:
        metric = "No high-risk tests"
    else:
        metric = f"{count} high-risk test{'s' if count != 1 else ''}"
    return HomepageCard(
        id="risk",
        icon="⚠️",
        title="At-Risk Tests",
        metric=metric,
        question="What tests are most likely to fail next?",
    )


def _card_root_cause(conn, repo, project: str | None) -> HomepageCard:
    """Card 4 — distinct failure groups in the latest run."""
    runs = repo.list_runs(project=project, limit=1)
    if not runs:
        return HomepageCard(
            id="root_cause",
            icon="🧠",
            title="Root Cause",
            metric="No runs yet",
            question="What is the root cause of these failures?",
            available=False,
        )
    latest_seq = runs[0].run_sequence
    groups = repo.get_failure_groups(project=project, limit=100)
    recent_groups = [g for g in groups if g.get("last_seen_seq") == latest_seq]
    count = len(recent_groups)
    if count == 0:
        metric = "No failure groups found"
    else:
        metric = f"{count} failure group{'s' if count != 1 else ''} detected"
    return HomepageCard(
        id="root_cause",
        icon="🧠",
        title="Root Cause",
        metric=metric,
        question="What is the root cause of these failures?",
    )


def _unavailable_fallback(builder_name: str) -> HomepageCard:
    """Return a generic unavailable card when a builder raises."""
    _defaults = {
        "_card_latest_run": ("latest_run", "🔥", "Latest Run", "What broke in the latest run?"),
        "_card_new_regressions": ("new_regressions", "🚨", "New Regressions", "What new failures were introduced?"),
        "_card_risk": ("risk", "⚠️", "At-Risk Tests", "What tests are most likely to fail next?"),
        "_card_root_cause": ("root_cause", "🧠", "Root Cause", "What is the root cause of these failures?"),
    }
    card_id, icon, title, question = _defaults.get(
        builder_name, ("unknown", "❓", "N/A", "")
    )
    return HomepageCard(
        id=card_id,
        icon=icon,
        title=title,
        metric="Unavailable",
        question=question,
        available=False,
    )
