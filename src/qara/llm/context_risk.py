"""Risk-prediction context builder for QARA LLM queries.

Extracted from :mod:`ari.llm.context` for cohesion.
All public names are re-exported from :mod:`ari.llm.context` for backward
compatibility.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Risk-question detection
# ---------------------------------------------------------------------------

_RISK_PHRASES: frozenset[str] = frozenset({
    "almost certain", "certain to fail", "likely to fail", "will fail",
    "going to fail", "fail next", "fail in the next", "next run",
    "at risk", "high risk", "risk score", "risk tier", "risk prediction",
    "predict", "prediction", "forecast",
    # duration / slowing questions
    "taking longer", "slower", "slowing", "duration spike", "getting slow",
    "execution time", "slow test", "slow down", "stable but", "duration trend",
})


def is_risk_question(question: str) -> bool:
    """Return ``True`` when the question is asking about future failure likelihood."""
    lower = question.lower()
    return any(phrase in lower for phrase in _RISK_PHRASES)


# ---------------------------------------------------------------------------
# Signal ranking helper
# ---------------------------------------------------------------------------


def _has_slowing_chip(signals: "RiskSignals") -> bool:  # type: ignore[name-defined]
    """Return ``True`` when ``duration_spike`` is one of the top-2 signals.

    Mirrors the JavaScript ``_topSignals`` function in the Risks page:
    rank all five signals by descending value, take the top 2 (where value
    > 0), and check whether ``duration_spike`` appears in that set.  This
    determines whether the "Slowing" chip is shown for a test row.
    """
    from qara.analyzers.predictor import RiskSignals  # noqa: F821 – type guard
    sig_values = [
        ("volatility",     signals.volatility),
        ("failure_burden", signals.failure_burden),
        ("recent_decline", signals.recent_decline),
        ("fail_streak",    signals.fail_streak),
        ("duration_spike", signals.duration_spike),
    ]
    positive = sorted(
        ((k, v) for k, v in sig_values if round(v * 100) > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    top2 = {k for k, _ in positive[:2]}
    return "duration_spike" in top2


# ---------------------------------------------------------------------------
# Risk-prediction context
# ---------------------------------------------------------------------------


def gather_risk_context(
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
    min_runs: int = 2,
) -> tuple[str, list[dict]]:
    """Build a context block driven by :class:`~ari.analyzers.predictor.RiskPredictor`.

    Used for questions asking which tests are likely to fail on the next run.
    Returns risk-tier source cards that link to the Risk page instead of run
    history cards.

    Returns:
        A tuple of ``(context_text, sources)``.
    """
    from qara.analyzers.predictor import RiskPredictor, RiskTier
    from qara.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        predictor = RiskPredictor(conn)
        predictions = predictor.predict_all(project=project, min_runs=min_runs)
    finally:
        conn.close()

    if not predictions:
        ctx = (
            "=== Risk Predictions: Insufficient history ===\n"
            "Not enough run history to compute risk predictions. "
            "Ingest at least 2 runs for any test to enable risk scoring."
        )
        return ctx, []

    critical = [p for p in predictions if p.tier == RiskTier.CRITICAL]
    high     = [p for p in predictions if p.tier == RiskTier.HIGH]
    medium   = [p for p in predictions if p.tier == RiskTier.MEDIUM]
    low      = [p for p in predictions if p.tier == RiskTier.LOW]

    proj_label = project or "(all projects)"
    parts: list[str] = []
    sources: list[dict] = []

    parts.append(f"=== Risk Predictions: Next-Run Failure Risk ({proj_label}) ===")
    parts.append(
        f"Tests scored: {len(predictions)}  "
        f"Critical: {len(critical)}  High: {len(high)}  "
        f"Medium: {len(medium)}  Low: {len(low)}"
    )
    parts.append("")

    if critical:
        parts.append("--- CRITICAL risk (\u226562% — almost certain to fail) ---")
        for p in critical:
            streak_label = (
                f"streak={p.current_streak}" if p.current_streak != 0 else "no streak"
            )
            parts.append(
                f"  {p.display_name}"
                f"  [risk={p.risk_pct}% \u00b7 pass={p.pass_rate:.0%}"
                f" \u00b7 {streak_label} \u00b7 history={p.sparkline}]"
            )
            parts.append(
                f"    signals: volatility={p.signals.volatility:.2f}"
                f" failure_burden={p.signals.failure_burden:.2f}"
                f" recent_decline={p.signals.recent_decline:.2f}"
                f" fail_streak={p.signals.fail_streak:.2f}"
            )
            sources.append({
                "type": "risk",
                "icon": "\U0001f534",
                "label": p.display_name,
                "meta": f"CRITICAL \u00b7 {p.risk_pct}% risk \u00b7 {p.pass_rate:.0%} pass rate",
                "tier": p.tier.value,
                "canonical_name": p.canonical_name,
            })
        parts.append("")

    if high:
        parts.append("--- HIGH risk (41\u201361% — likely to fail soon) ---")
        for p in high:
            streak_label = (
                f"streak={p.current_streak}" if p.current_streak != 0 else "no streak"
            )
            parts.append(
                f"  {p.display_name}"
                f"  [risk={p.risk_pct}% \u00b7 pass={p.pass_rate:.0%}"
                f" \u00b7 {streak_label} \u00b7 history={p.sparkline}]"
            )
            sources.append({
                "type": "risk",
                "icon": "\U0001f7e0",
                "label": p.display_name,
                "meta": f"HIGH \u00b7 {p.risk_pct}% risk \u00b7 {p.pass_rate:.0%} pass rate",
                "tier": p.tier.value,
                "canonical_name": p.canonical_name,
            })
        parts.append("")

    if medium:
        parts.append("--- MEDIUM risk (24\u201340% — worth watching) ---")
        for p in medium:
            parts.append(
                f"  {p.display_name}"
                f"  [risk={p.risk_pct}% \u00b7 pass={p.pass_rate:.0%}"
                f" \u00b7 history={p.sparkline}]"
            )
        parts.append("")

    if low:
        # Mirror the Risks-screen "Slowing" chip: only flag a test when
        # duration_spike ranks in the top-2 signals by value (same logic as
        # the JavaScript _topSignals function).  Tests with duration_spike > 0
        # but outscored by volatility/failure_burden are NOT "Slowing" in the UI.
        slowing_low = [p for p in low if _has_slowing_chip(p.signals)]
        stable_only = [p for p in low if not _has_slowing_chip(p.signals)]
        if slowing_low:
            parts.append(
                f"--- LOW risk (<24%) — stable tests with Slowing signal"
                f" (duration_spike is top-ranked, {len(slowing_low)} test(s)) ---"
            )
            for p in slowing_low:
                parts.append(
                    f"  {p.display_name}"
                    f"  [suite={p.suite or '-'} \u00b7 pass={p.pass_rate:.0%}"
                    f" \u00b7 duration_spike={p.signals.duration_spike:.2f}"
                    f" \u00b7 history={p.sparkline}]"
                )
            parts.append("")
        if stable_only:
            parts.append(
                f"--- LOW risk (<24%) — {len(stable_only)} fully stable test(s)"
                f" (no dominant Slowing signal) ---"
            )
        parts.append("")

    return "\n".join(parts).strip(), sources
