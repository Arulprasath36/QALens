"""Trend computation helpers for QALens pass-rate trend analysis.

These are pure, side-effect-free functions that take a list of
``(label, pass_rate)`` tuples (oldest first) and return a
:class:`TrendResult` describing direction, magnitude, and confidence.

Usage::

    from qalens.llm.trend import compute_trend, render_trend_facts

    rates = [("Run #51", 0.76), ("Run #52", 0.80), ("Run #53", 0.72)]
    result = compute_trend(rates)
    facts = render_trend_facts(result, newly_failing=8, recovered=3, consistent=3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


class RunRate(NamedTuple):
    """A single run's pass-rate data point."""

    label: str      # e.g. "Run #53"
    pass_rate: float  # 0.0–1.0
    passed: int | None = None
    failed: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class TrendResult:
    """Summary of a pass-rate trend across multiple runs."""

    direction: str          # "improving" | "declining" | "stable" | "insufficient_data"
    confidence: str         # "high" | "medium" | "low"
    delta_pct: float | None  # latest minus previous, e.g. -8.0 means dropped 8 pp
    runs: list[RunRate] = field(default_factory=list)  # oldest → newest

    @property
    def has_data(self) -> bool:
        return self.direction != "insufficient_data"

    @property
    def magnitude(self) -> str:
        """Human label for the size of the change."""
        if self.delta_pct is None:
            return ""
        abs_delta = abs(self.delta_pct)
        if abs_delta >= 15:
            return "sharply"
        if abs_delta >= 5:
            return "slightly"
        return "marginally"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_trend(runs: list[RunRate]) -> TrendResult:
    """Compute trend direction and confidence from ``runs`` (oldest first).

    Direction rules
    ---------------
    - **improving**: last rate > first rate by > 2 pp AND slope is positive
    - **declining**: last rate < first rate by > 2 pp AND slope is negative
    - **stable**: variance < 5 pp across all runs

    Confidence rules
    ----------------
    - **high**: 4+ runs AND direction is consistent (no reversals)
    - **medium**: 2–3 runs OR direction mostly consistent with one reversal
    - **low**: only 2 data points OR high variance with no clear direction

    Args:
        runs: List of :class:`RunRate` objects ordered oldest → newest.
              Must have at least 2 items for a meaningful result.

    Returns:
        A :class:`TrendResult`.  If fewer than 2 runs are provided,
        ``direction`` is ``"insufficient_data"`` and ``confidence`` is ``"low"``.
    """
    if len(runs) < 2:
        return TrendResult(
            direction="insufficient_data",
            confidence="low",
            delta_pct=None,
            runs=list(runs),
        )

    rates = [r.pass_rate for r in runs]
    first_rate = rates[0]
    last_rate = rates[-1]
    delta = (last_rate - first_rate) * 100  # percentage points

    # Simple linear slope: positive = improving, negative = declining
    n = len(rates)
    mean_x = (n - 1) / 2
    mean_y = sum(rates) / n
    numerator = sum((i - mean_x) * (rates[i] - mean_y) for i in range(n))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    slope = numerator / denominator if denominator else 0.0

    # Variance across all runs (max - min spread)
    spread = (max(rates) - min(rates)) * 100

    # Determine direction
    STABLE_THRESHOLD = 5.0  # pp
    CHANGE_THRESHOLD = 2.0  # pp

    if spread < STABLE_THRESHOLD:
        direction = "stable"
    elif slope > 0 and delta > CHANGE_THRESHOLD:
        direction = "improving"
    elif slope < 0 and delta < -CHANGE_THRESHOLD:
        direction = "declining"
    else:
        direction = "stable"

    # Count direction reversals in adjacent pairs
    reversals = 0
    for i in range(1, n - 1):
        prev_dir = rates[i] - rates[i - 1]
        next_dir = rates[i + 1] - rates[i]
        if prev_dir * next_dir < 0:  # sign change
            reversals += 1

    # Confidence
    if n >= 4 and reversals == 0:
        confidence = "high"
    elif n >= 3 and reversals <= 1:
        confidence = "medium"
    elif n == 2:
        confidence = "low"
    else:
        confidence = "medium" if reversals <= 1 else "low"

    return TrendResult(
        direction=direction,
        confidence=confidence,
        delta_pct=round(delta, 1),
        runs=list(runs),
    )


# ---------------------------------------------------------------------------
# Context rendering
# ---------------------------------------------------------------------------


def render_trend_facts(
    trend: TrendResult,
    *,
    newly_failing: int = 0,
    recovered: int = 0,
    consistently_failing: int = 0,
) -> str:
    """Render a ``[TREND ANALYSIS]`` block to inject as structured facts.

    The block contains *only real values* — no placeholders.  The LLM is
    instructed to copy values from this section verbatim.

    Args:
        trend:                Pre-computed :class:`TrendResult`.
        newly_failing:        Count of newly failing tests (from comparison).
        recovered:            Count of recovered tests.
        consistently_failing: Count of consistently failing tests.

    Returns:
        A multi-line string starting with ``[TREND ANALYSIS]``.
    """
    if not trend.has_data:
        return (
            "[TREND ANALYSIS]\n"
            "Not enough data to determine a trend (fewer than 2 runs available).\n"
        )

    lines: list[str] = ["[TREND ANALYSIS]"]

    # Direction + confidence
    lines.append(
        f"Direction     : {trend.direction}  (confidence: {trend.confidence})"
    )

    if trend.delta_pct is not None:
        sign = "+" if trend.delta_pct > 0 else ""
        lines.append(f"Overall change : {sign}{trend.delta_pct:.1f} percentage points")

    # Per-run breakdown (real values, oldest → newest)
    lines.append("Per-run rates (oldest → newest):")
    for r in trend.runs:
        pct_str = f"{r.pass_rate:.0%}"
        if r.passed is not None and r.total:
            detail = f" ({r.passed} passed, {r.failed} failed of {r.total} total)"
        else:
            detail = ""
        lines.append(f"  {r.label}: {pct_str}{detail}")

    # Evidence from comparison (omit zeros)
    evidence: list[str] = []
    if newly_failing:
        evidence.append(f"Newly failing tests increased: {newly_failing} test(s)")
    if consistently_failing:
        evidence.append(
            f"Consistently failing tests: {consistently_failing} test(s)"
        )
    if recovered:
        evidence.append(f"Recovered tests: {recovered} test(s)")

    if evidence:
        lines.append("Supporting evidence (from last 2-run comparison):")
        for item in evidence:
            lines.append(f"  • {item}")

    return "\n".join(lines)
