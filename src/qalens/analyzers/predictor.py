"""Flakiness risk predictor for QaLens.

Computes a risk score (0–100 %) for every test using historical pass/fail
patterns from the QaLens database.  No ML model is needed — the score is a
weighted combination of four deterministic signals derived from a test's
:class:`~qalens.analyzers.flaky.FlakyResult`:

``volatility``
    Normalised flip score (how often the test switches between pass and fail).

``failure_burden``
    Overall fraction of runs that ended in failure.

``recent_decline``
    How much *worse* the test has been in the last three runs compared to its
    all-time average.  Zero if the test is trending stable or better.

``fail_streak``
    Penalty applied when the test is currently on a consecutive fail streak
    (0.0 for 0 fails, 0.33 for 1, 0.67 for 2, 1.0 for 3+).

``duration_spike``
    Positive slope of test duration over recent runs, normalised by the mean
    duration.  A test that is steadily slowing down scores higher here.

Score formula::

    risk = 0.30 * volatility
         + 0.25 * failure_burden
         + 0.25 * recent_decline
         + 0.15 * fail_streak
         + 0.05 * duration_spike

The result is clamped to [0.0, 1.0] and expressed as a percentage (0–100).

Usage::

    from qalens.db.schema import get_connection
    from qalens.analyzers.predictor import RiskPredictor, RiskTier

    conn = get_connection()
    predictor = RiskPredictor(conn)

    predictions = predictor.predict_all(project="OrangeHRM")
    for p in predictions[:5]:
        print(f"{p.display_name:40s}  {p.risk_pct:3d}%  {p.tier.value}")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from qalens.analyzers.flaky import FlakyResult, FlakyScorer


class RiskTier(str, Enum):
    """Qualitative risk level derived from the numeric risk score.

    Attributes:
        CRITICAL: Risk ≥ 62 % — extremely high volatility plus a recent failure streak.
        HIGH: Risk 41–61 % — clearly concerning, likely to fail soon.
        MEDIUM: Risk 24–40 % — worth watching.
        LOW: Risk < 24 % — probably stable.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> "RiskTier":
        """Map a numeric risk score to a tier.

        The formula's mathematical ceiling is ~0.75 (when volatility = 1.0,
        failure_burden + recent_decline = 1.0, and fail_streak = 1.0),
        so thresholds are calibrated to that reachable range.

        Args:
            score: Risk score in [0.0, 1.0].

        Returns:
            Corresponding :class:`RiskTier`.
        """
        if score >= 0.62:
            return cls.CRITICAL
        if score >= 0.41:
            return cls.HIGH
        if score >= 0.24:
            return cls.MEDIUM
        return cls.LOW

    @property
    def label(self) -> str:
        """Human-readable label."""
        return self.value.title()


@dataclass
class RiskSignals:
    """Individual signal contributions to the overall risk score.

    All values are in [0.0, 1.0].

    Attributes:
        volatility: Flip-score signal — how often the test switches outcomes.
        failure_burden: All-time failure rate (1 - pass_rate).
        recent_decline: Excess failure rate in the last 3 runs vs all-time.
        fail_streak: Penalty for an active consecutive-fail streak.
        duration_spike: Normalised test-duration growth slope.
    """

    volatility: float
    failure_burden: float
    recent_decline: float
    fail_streak: float
    duration_spike: float


@dataclass
class RiskPrediction:
    """Full prediction result for a single test.

    Attributes:
        canonical_name: Normalised test name (cross-run key).
        display_name: Most recent raw display name.
        project: Project this prediction was scoped to (or ``None``).
        suite: Suite name from the database (or ``None``).
        module: Best-effort module/suite label for UI grouping.
        risk_score: Numeric risk value in [0.0, 1.0].
        risk_pct: ``round(risk_score * 100)`` — used for the UI progress bar.
        tier: Qualitative risk tier.
        signals: Breakdown of the contributing signals.
        run_count: Number of historical runs observed for this test.
        pass_rate: All-time pass rate in [0.0, 1.0].
        flip_score: Raw flip score in [0.0, 1.0].
        sparkline: Unicode history string (e.g. ``"✓✗✓✗✓"``), oldest first.
        current_streak: Signed streak length (positive = passes, negative = fails).
    """

    canonical_name: str
    display_name: str
    project: str | None
    suite: str | None
    module: str
    risk_score: float
    risk_pct: int
    tier: RiskTier
    signals: RiskSignals
    run_count: int
    pass_rate: float
    flip_score: float
    sparkline: str
    current_streak: int
    owner: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _duration_trend(durations: list[float]) -> float:
    """Compute a normalised duration-growth slope in [0.0, 1.0].

    Uses ordinary least-squares on the provided ordered duration samples
    (oldest first).  Only positive slopes (test getting slower) contribute;
    a test that is getting faster returns 0.0.

    Args:
        durations: Ordered list of ``duration_ms`` values, oldest first.
            ``None`` entries should be excluded before calling.

    Returns:
        Normalised slope clamped to [0.0, 1.0], or 0.0 if the list has
        fewer than three samples or the mean duration is zero.
    """
    if len(durations) < 3:
        return 0.0
    n = len(durations)
    mean_x = (n - 1) / 2.0
    mean_y = sum(durations) / n
    if mean_y == 0.0:
        return 0.0
    num = sum((i - mean_x) * (d - mean_y) for i, d in enumerate(durations))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0
    slope = num / den
    normalized = slope / mean_y
    return min(1.0, max(0.0, normalized))


def _module_label(suite: str | None, display_name: str) -> str:
    """Derive a short module label for UI grouping.

    Priority:
    1. ``suite`` if not ``None`` / blank.
    2. First camelCase word of ``display_name`` after stripping a leading
       ``test`` / ``Test`` prefix (e.g. ``testLoginUser`` → ``Login``).
    3. Fallback: ``"(unclassified)"``.

    Args:
        suite: Suite field from the database, may be ``None``.
        display_name: Human-readable test name.

    Returns:
        Short module string suitable for display.
    """
    if suite:
        return suite
    name = display_name
    if name.lower().startswith("test"):
        name = name[4:]
    first_word: list[str] = []
    for ch in name:
        if first_word and ch.isupper():
            break
        first_word.append(ch)
    label = "".join(first_word).strip("_- ")
    return label or "(unclassified)"


def _compute_risk(
    result: FlakyResult,
    duration_trend: float,
) -> tuple[float, RiskSignals]:
    """Compute risk score and signals from a :class:`~qalens.analyzers.flaky.FlakyResult`.

    Args:
        result: Scored flakiness profile for the test.
        duration_trend: Normalised duration growth, from :func:`_duration_trend`.

    Returns:
        ``(risk_score, signals)`` where ``risk_score`` is in [0.0, 1.0].
    """
    history = result.history
    flip_score = result.flip_score
    all_fail_rate = 1.0 - result.pass_rate

    # Recent decline: compare tail-3 fail rate vs all-time fail rate
    tail = history[-3:] if len(history) >= 3 else history
    recent_fail_rate = (
        sum(1 for s in tail if s in ("failed", "broken")) / len(tail)
        if tail
        else 0.0
    )
    recent_decline = max(0.0, recent_fail_rate - all_fail_rate)

    # Active fail-streak penalty: 1 fail→0.33, 2→0.67, 3+→1.0
    streak_factor = (
        min(1.0, abs(result.current_streak) / 3.0)
        if result.current_streak < 0
        else 0.0
    )

    signals = RiskSignals(
        volatility=round(flip_score, 4),
        failure_burden=round(all_fail_rate, 4),
        recent_decline=round(recent_decline, 4),
        fail_streak=round(streak_factor, 4),
        duration_spike=round(duration_trend, 4),
    )

    score = (
        0.30 * flip_score
        + 0.25 * all_fail_rate
        + 0.25 * recent_decline
        + 0.15 * streak_factor
        + 0.05 * duration_trend
    )
    return min(1.0, max(0.0, score)), signals


# ---------------------------------------------------------------------------
# Public predictor class
# ---------------------------------------------------------------------------


class RiskPredictor:
    """Predicts which tests are most likely to fail on the next run.

    Args:
        conn: An open :class:`sqlite3.Connection` to an initialised QaLens DB.
        flaky_threshold: Flip-score threshold passed to :class:`FlakyScorer`.
            Default 0.35.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        flaky_threshold: float = 0.35,
    ) -> None:
        self._conn = conn
        self._scorer = FlakyScorer(conn, flaky_threshold=flaky_threshold)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(
        self,
        canonical_name: str,
        *,
        project: str | None = None,
        history_limit: int = 30,
    ) -> RiskPrediction:
        """Compute the risk prediction for a single test.

        Args:
            canonical_name: Normalised test name.
            project: Project scope (``None`` = all projects).
            history_limit: Maximum run history depth.

        Returns:
            A fully populated :class:`RiskPrediction`.
        """
        result = self._scorer.score(canonical_name, project=project, limit=history_limit)
        dt = self._fetch_duration_trend(canonical_name, project=project, limit=history_limit)
        suite = self._fetch_suite(canonical_name, project=project)
        risk, signals = _compute_risk(result, dt)
        return RiskPrediction(
            canonical_name=canonical_name,
            display_name=result.display_name,
            project=project,
            suite=suite,
            module=_module_label(suite, result.display_name),
            risk_score=round(risk, 4),
            risk_pct=round(risk * 100),
            tier=RiskTier.from_score(risk),
            signals=signals,
            run_count=result.run_count,
            pass_rate=round(result.pass_rate, 4),
            flip_score=round(result.flip_score, 4),
            sparkline=result.sparkline,
            current_streak=result.current_streak,
            owner=result.owner,
        )

    def predict_all(
        self,
        *,
        project: str | None = None,
        min_runs: int = 2,
        history_limit: int = 30,
    ) -> list[RiskPrediction]:
        """Return risk predictions for all tests with sufficient history.

        Args:
            project: Project scope (``None`` = all projects).
            min_runs: Minimum run appearances required.
            history_limit: History depth per test.

        Returns:
            List of :class:`RiskPrediction` objects sorted by
            ``risk_score`` descending (highest risk first).
        """
        flaky_results = self._scorer.get_all(
            project=project,
            min_runs=min_runs,
            limit_per_test=history_limit,
        )
        predictions: list[RiskPrediction] = []
        for result in flaky_results:
            dt = self._fetch_duration_trend(
                result.canonical_name, project=project, limit=history_limit
            )
            suite = self._fetch_suite(result.canonical_name, project=project)
            risk, signals = _compute_risk(result, dt)
            predictions.append(
                RiskPrediction(
                    canonical_name=result.canonical_name,
                    display_name=result.display_name,
                    project=project,
                    suite=suite,
                    module=_module_label(suite, result.display_name),
                    risk_score=round(risk, 4),
                    risk_pct=round(risk * 100),
                    tier=RiskTier.from_score(risk),
                    signals=signals,
                    run_count=result.run_count,
                    pass_rate=round(result.pass_rate, 4),
                    flip_score=round(result.flip_score, 4),
                    sparkline=result.sparkline,
                    current_streak=result.current_streak,
                    owner=result.owner,
                )
            )
        predictions.sort(key=lambda p: p.risk_score, reverse=True)
        return predictions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_duration_trend(
        self,
        canonical_name: str,
        *,
        project: str | None,
        limit: int,
    ) -> float:
        """Query duration history and compute the growth trend score."""
        if project is not None:
            rows = self._conn.execute(
                """
                SELECT tc.duration_ms
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND r.project = ?
                  AND tc.duration_ms IS NOT NULL
                ORDER BY r.run_sequence ASC
                LIMIT ?
                """,
                (canonical_name, project, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT tc.duration_ms
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND tc.duration_ms IS NOT NULL
                ORDER BY r.run_sequence ASC
                LIMIT ?
                """,
                (canonical_name, limit),
            ).fetchall()
        return _duration_trend([float(r["duration_ms"]) for r in rows])

    def _fetch_suite(
        self,
        canonical_name: str,
        *,
        project: str | None,
    ) -> str | None:
        """Return the most recent non-null suite name for the given test."""
        if project is not None:
            row = self._conn.execute(
                """
                SELECT tc.suite
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND r.project = ?
                  AND tc.suite IS NOT NULL
                ORDER BY r.run_sequence DESC
                LIMIT 1
                """,
                (canonical_name, project),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT tc.suite
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND tc.suite IS NOT NULL
                ORDER BY r.run_sequence DESC
                LIMIT 1
                """,
                (canonical_name,),
            ).fetchone()
        return row["suite"] if row else None
