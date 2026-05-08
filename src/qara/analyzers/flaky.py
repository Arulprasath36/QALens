"""Flaky test detection for QARA.

:class:`FlakyScorer` queries the QARA database to compute a stability
profile for every test across its run history.  No ML is required —
the algorithm is based on pass rate and status flip count.

Usage::

    from qara.db.schema import get_connection
    from qara.analyzers.flaky import FlakyScorer, FlakyClassification

    conn = get_connection()
    scorer = FlakyScorer(conn)

    result = scorer.score("verifyadminusersearch", project="OrangeHRM")
    print(result.classification)      # FlakyClassification.FLAKY
    print(result.flakiness_score)     # e.g. 0.67
    print(result.history)             # ["passed","failed","passed","failed"]

    all_flaky = scorer.get_all_flaky(project="OrangeHRM")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum


class FlakyClassification(str, Enum):
    """Stability classification assigned to a test based on its run history.

    Attributes:
        FLAKY: The test alternates between passing and failing — unreliable.
        CONSISTENTLY_BROKEN: The test has never passed in the observed window.
        STABLE: The test is highly reliable with strong pass rate and low flip activity.
        CONSISTENT: The test has low recent flip activity but is not yet reliable enough
            to be considered truly stable.
        INSUFFICIENT_DATA: Fewer than 2 runs — cannot classify yet.
    """

    FLAKY = "flaky"
    CONSISTENTLY_BROKEN = "consistently_broken"
    STABLE = "stable"
    CONSISTENT = "consistent"
    INSUFFICIENT_DATA = "insufficient_data"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


@dataclass
class FlakyResult:
    """Stability profile for a single test across multiple runs.

    Attributes:
        canonical_name: Normalised test name used as the cross-run key.
        display_name: Most recent raw display name for this test.
        project: Project filter this result was computed for (or ``None``).
        run_count: Number of runs in which this test appeared.
        pass_count: Number of times the test passed.
        fail_count: Number of times the test failed or was broken.
        skip_count: Number of times the test was skipped.
        pass_rate: ``pass_count / run_count`` as a float in [0.0, 1.0].
        flip_score: ``flip_count / (run_count - 1)`` — 0.0 means perfectly
            stable, 1.0 means the status flipped every consecutive run.
        flakiness_score: Alias for ``flip_score`` (kept for clarity in output).
        classification: Stability label.
        history: Ordered list of statuses, oldest first
            (e.g. ``["passed", "failed", "passed"]``).
        last_passed_seq: ``run_sequence`` of the most recent passing run,
            or ``None`` if the test has never passed in the window.
        last_failed_seq: ``run_sequence`` of the most recent failing run,
            or ``None`` if the test has never failed.
        current_streak: Number of consecutive identical statuses at the
            end of history (positive = passes, negative = failures).
        fingerprints: Set of unique failure fingerprints seen for this test.
    """

    canonical_name: str
    display_name: str
    project: str | None
    run_count: int
    pass_count: int
    fail_count: int
    skip_count: int
    pass_rate: float
    flip_score: float
    classification: FlakyClassification
    history: list[str]
    last_passed_seq: int | None
    last_failed_seq: int | None
    current_streak: int
    owner: str | None = None
    fingerprints: set[str] = field(default_factory=set)

    @property
    def flakiness_score(self) -> float:
        """Alias for ``flip_score``."""
        return self.flip_score

    @property
    def sparkline(self) -> str:
        """Single-line visual history using Unicode symbols.

        Each run is rendered as one character:
        ``✓`` passed, ``✗`` failed/broken, ``-`` skipped/other.
        """
        symbols = {
            "passed": "✓",
            "failed": "✗",
            "broken": "✗",
            "skipped": "-",
            "pending": "·",
            "unknown": "?",
        }
        return "".join(symbols.get(s, "?") for s in self.history)


def _classify(
    run_count: int,
    pass_rate: float,
    flip_score: float,
    *,
    flaky_threshold: float = 0.35,
    broken_threshold: float = 0.20,
    stable_pass_threshold: float = 0.90,
    stable_flip_threshold: float = 0.10,
) -> FlakyClassification:
    """Apply classification rules to computed metrics.

    Args:
        run_count: Total runs observed.
        pass_rate: Fraction of runs that passed [0, 1].
        flip_score: Flip fraction [0, 1].
        flaky_threshold: Minimum ``flip_score`` to be classified as flaky.
            Default 0.35 (flips in more than a third of consecutive pairs).
        broken_threshold: Maximum ``pass_rate`` below which a test is
            classified as consistently broken even if it occasionally passes.
            Default 0.20 (fails 80 %+ of the time → broken, not stable).
        stable_pass_threshold: Minimum ``pass_rate`` required to classify a
            low-volatility test as truly stable. Default 0.90.
        stable_flip_threshold: Maximum ``flip_score`` allowed for the stable
            bucket. Default 0.10.

    Returns:
        A :class:`FlakyClassification` value.
    """
    if run_count < 2:
        return FlakyClassification.INSUFFICIENT_DATA
    if flip_score >= flaky_threshold:
        return FlakyClassification.FLAKY
    if pass_rate <= broken_threshold:
        return FlakyClassification.CONSISTENTLY_BROKEN
    if pass_rate >= stable_pass_threshold and flip_score <= stable_flip_threshold:
        return FlakyClassification.STABLE
    return FlakyClassification.CONSISTENT


def _compute_flip_score(history: list[str]) -> float:
    """Count status transitions and normalise to [0, 1].

    Args:
        history: Ordered list of status strings, oldest first.

    Returns:
        ``flip_count / (len(history) - 1)``, or 0.0 for single-entry lists.
    """
    if len(history) < 2:
        return 0.0

    def _is_failing(s: str) -> bool:
        return s in ("failed", "broken")

    def _is_passing(s: str) -> bool:
        return s == "passed"

    flips = 0
    for i in range(1, len(history)):
        prev_fail = _is_failing(history[i - 1])
        curr_fail = _is_failing(history[i])
        prev_pass = _is_passing(history[i - 1])
        curr_pass = _is_passing(history[i])
        # A flip is pass→fail or fail→pass (skipped/unknown don't count)
        if (prev_pass and curr_fail) or (prev_fail and curr_pass):
            flips += 1

    return flips / (len(history) - 1)


def _compute_streak(history: list[str]) -> int:
    """Return the length of the current consecutive run at the tail.

    Positive = consecutive passes; negative = consecutive failures.

    Args:
        history: Ordered status list, oldest first.

    Returns:
        Signed integer streak length.
    """
    if not history:
        return 0
    last = history[-1]
    count = 0
    for s in reversed(history):
        if s == last:
            count += 1
        else:
            break
    if last == "passed":
        return count
    if last in ("failed", "broken"):
        return -count
    return 0


class FlakyScorer:
    """Computes flakiness scores for tests stored in the QARA database.

    Args:
        conn: An open :class:`sqlite3.Connection` to an initialised QARA DB.
        flaky_threshold: Minimum ``flip_score`` to classify a test as flaky.
            Default is 0.35.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        flaky_threshold: float = 0.35,
        broken_threshold: float = 0.20,
        stable_pass_threshold: float = 0.90,
        stable_flip_threshold: float = 0.10,
    ) -> None:
        self._conn = conn
        self._threshold = flaky_threshold
        self._broken_threshold = broken_threshold
        self._stable_pass_threshold = stable_pass_threshold
        self._stable_flip_threshold = stable_flip_threshold

    def score(
        self,
        canonical_name: str,
        *,
        project: str | None = None,
        limit: int = 30,
    ) -> FlakyResult:
        """Compute the stability profile for a single test.

        Args:
            canonical_name: Normalised test name (use
                :func:`~qara.analyzers.canonical.to_canonical_name` first).
            project: Restrict history to this project, or ``None`` for all.
            limit: Maximum run history depth to consider.

        Returns:
            A fully populated :class:`FlakyResult`.
        """
        rows = self._fetch_history(canonical_name, project=project, limit=limit)

        if not rows:
            return FlakyResult(
                canonical_name=canonical_name,
                display_name=canonical_name,
                project=project,
                run_count=0,
                pass_count=0,
                fail_count=0,
                skip_count=0,
                pass_rate=0.0,
                flip_score=0.0,
                classification=FlakyClassification.INSUFFICIENT_DATA,
                history=[],
                last_passed_seq=None,
                last_failed_seq=None,
                current_streak=0,
            )

        history = [r["status"] for r in rows]
        display_name = rows[-1]["name"] or canonical_name
        run_count = len(history)
        pass_count = sum(1 for s in history if s == "passed")
        fail_count = sum(1 for s in history if s in ("failed", "broken"))
        skip_count = sum(1 for s in history if s == "skipped")
        pass_rate = pass_count / run_count if run_count else 0.0
        flip_score = _compute_flip_score(history)
        classification = _classify(
            run_count, pass_rate, flip_score,
            flaky_threshold=self._threshold,
            broken_threshold=self._broken_threshold,
            stable_pass_threshold=self._stable_pass_threshold,
            stable_flip_threshold=self._stable_flip_threshold,
        )
        streak = _compute_streak(history)

        last_passed_seq: int | None = None
        last_failed_seq: int | None = None
        fingerprints: set[str] = set()

        for r in reversed(rows):
            if last_passed_seq is None and r["status"] == "passed":
                last_passed_seq = r["run_sequence"]
            if last_failed_seq is None and r["status"] in ("failed", "broken"):
                last_failed_seq = r["run_sequence"]
            if r["fingerprint"]:
                fingerprints.add(r["fingerprint"])

        owner = self._fetch_owner(canonical_name, project=project)
        return FlakyResult(
            canonical_name=canonical_name,
            display_name=display_name,
            project=project,
            run_count=run_count,
            pass_count=pass_count,
            fail_count=fail_count,
            skip_count=skip_count,
            pass_rate=pass_rate,
            flip_score=flip_score,
            classification=classification,
            history=history,
            last_passed_seq=last_passed_seq,
            last_failed_seq=last_failed_seq,
            current_streak=streak,
            owner=owner,
            fingerprints=fingerprints,
        )

    def get_all(
        self,
        *,
        project: str | None = None,
        min_runs: int = 2,
        limit_per_test: int = 30,
    ) -> list[FlakyResult]:
        """Score every test in the database that has sufficient history.

        Args:
            project: Restrict to this project, or ``None`` for all projects.
            min_runs: Only include tests that appeared in at least this many
                runs.  Default 2 (minimum needed to compute a flip score).
            limit_per_test: History depth passed to :meth:`score`.

        Returns:
            List of :class:`FlakyResult` objects, sorted by ``flip_score``
            descending (most flaky first).
        """
        names = self._fetch_candidate_names(project=project, min_runs=min_runs)
        results = [
            self.score(name, project=project, limit=limit_per_test)
            for name in names
        ]
        results.sort(key=lambda r: r.flip_score, reverse=True)
        return results

    def get_all_flaky(
        self,
        *,
        project: str | None = None,
        min_runs: int = 2,
        limit_per_test: int = 30,
    ) -> list[FlakyResult]:
        """Return only tests classified as :attr:`FlakyClassification.FLAKY`.

        Args:
            project: Project filter (``None`` = all).
            min_runs: Minimum run appearances to be included.
            limit_per_test: History depth.

        Returns:
            Flaky tests sorted by ``flip_score`` descending.
        """
        return [
            r for r in self.get_all(
                project=project,
                min_runs=min_runs,
                limit_per_test=limit_per_test,
            )
            if r.classification == FlakyClassification.FLAKY
        ]

    def get_consistently_broken(
        self,
        *,
        project: str | None = None,
        min_runs: int = 2,
    ) -> list[FlakyResult]:
        """Return only tests classified as consistently broken.

        Args:
            project: Project filter.
            min_runs: Minimum run appearances.

        Returns:
            Consistently broken tests sorted by ``fail_count`` descending.
        """
        results = [
            r for r in self.get_all(project=project, min_runs=min_runs)
            if r.classification == FlakyClassification.CONSISTENTLY_BROKEN
        ]
        results.sort(key=lambda r: r.fail_count, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_history(
        self,
        canonical_name: str,
        *,
        project: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        if project is not None:
            return self._conn.execute(
                """
                SELECT r.run_sequence, tc.status, tc.name, f.fingerprint
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                LEFT JOIN failures f ON f.tc_id = tc.tc_id
                WHERE tc.canonical_name = ?
                  AND r.project = ?
                  AND tc.is_retry = 0
                  AND r.run_sequence IN (
                      SELECT run_sequence FROM runs
                      WHERE project = ?
                      ORDER BY run_sequence DESC LIMIT ?
                  )
                ORDER BY r.run_sequence ASC
                """,
                (canonical_name, project, project, limit),
            ).fetchall()
        else:
            return self._conn.execute(
                """
                SELECT r.run_sequence, tc.status, tc.name, f.fingerprint
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                LEFT JOIN failures f ON f.tc_id = tc.tc_id
                WHERE tc.canonical_name = ?
                  AND tc.is_retry = 0
                  AND r.run_sequence IN (
                      SELECT run_sequence FROM runs
                      ORDER BY run_sequence DESC LIMIT ?
                  )
                ORDER BY r.run_sequence ASC
                """,
                (canonical_name, limit),
            ).fetchall()

    def _fetch_candidate_names(
        self,
        *,
        project: str | None,
        min_runs: int,
    ) -> list[str]:
        if project is not None:
            rows = self._conn.execute(
                """
                SELECT tc.canonical_name
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE r.project = ?
                  AND tc.is_retry = 0
                GROUP BY tc.canonical_name
                HAVING COUNT(DISTINCT r.run_id) >= ?
                ORDER BY tc.canonical_name
                """,
                (project, min_runs),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT tc.canonical_name
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.is_retry = 0
                GROUP BY tc.canonical_name
                HAVING COUNT(DISTINCT r.run_id) >= ?
                ORDER BY tc.canonical_name
                """,
                (min_runs,),
            ).fetchall()
        return [r["canonical_name"] for r in rows]

    def _fetch_owner(
        self,
        canonical_name: str,
        *,
        project: str | None,
    ) -> str | None:
        """Return the most recent non-null owner for the given test."""
        if project is not None:
            row = self._conn.execute(
                """
                SELECT tc.owner
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND r.project = ?
                  AND tc.owner IS NOT NULL
                ORDER BY r.run_sequence DESC
                LIMIT 1
                """,
                (canonical_name, project),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT tc.owner
                FROM test_cases tc
                JOIN runs r ON r.run_id = tc.run_id
                WHERE tc.canonical_name = ?
                  AND tc.owner IS NOT NULL
                ORDER BY r.run_sequence DESC
                LIMIT 1
                """,
                (canonical_name,),
            ).fetchone()
        return row["owner"] if row else None
