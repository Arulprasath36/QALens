"""Deterministic owner-level metrics over pandas DataFrames.

Terminology
-----------
- **Execution**      – one row in the analytics view (one test case run once).
- **Failure count**  – count of *executions* where status is a failing status.
  A test that fails 5 times contributes 5 to the count.  Use this to answer
  "whose tests are causing the most noise right now?".
- **Failure rate**   – ``failed_executions / total_executions`` per owner.
  Normalises for the difference between large and small test suites.
- **Flaky test count** – count of *distinct* ``test_name`` values where
  ``is_flaky`` is ``True``, grouped by owner.  Counts unique tests (not
  executions) to avoid inflating counts for high-frequency tests.

Assumptions
-----------
- Rows without a recorded owner are labelled ``"Unassigned"`` and excluded
  from ranking outputs by default (configurable via ``exclude_unassigned``).
- "Failing" statuses: ``FAIL``, ``FAILED``, ``BROKEN`` (case-insensitive).
- When ``flakiness_df`` is not provided, ``is_flaky`` is absent from the
  view and :func:`compute_flaky_test_count_per_owner` returns an empty
  DataFrame with the correct schema rather than raising an error.
- Duplicate ``test_name`` rows in ``owners_df`` or ``flakiness_df`` are
  de-duplicated (first occurrence kept) before joining, so the execution
  count is never inflated by ownership duplicates.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Status values (uppercased) that are treated as failures.
FAIL_STATUSES: frozenset[str] = frozenset({"FAIL", "FAILED", "BROKEN"})

#: Label used for test executions that have no matching owner.
UNASSIGNED_LABEL: str = "Unassigned"

_REQUIRED_EXEC_COLS: frozenset[str] = frozenset({"test_name", "run_id", "status"})
_REQUIRED_OWNER_COLS: frozenset[str] = frozenset({"test_name", "owner"})
_REQUIRED_FLAKY_COLS: frozenset[str] = frozenset({"test_name", "is_flaky"})


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def _validate_columns(df: pd.DataFrame, required: frozenset[str], label: str) -> None:
    """Raise ``ValueError`` if *df* is missing any column in *required*."""
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{label} is missing required columns: {sorted(missing)}. "
            f"Found: {sorted(df.columns)}."
        )


# ---------------------------------------------------------------------------
# Analytics view builder
# ---------------------------------------------------------------------------


def build_owner_analytics_view(
    executions_df: pd.DataFrame,
    owners_df: pd.DataFrame,
    flakiness_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Join execution data with ownership and optionally flakiness metadata.

    The returned DataFrame is the single source of truth for all downstream
    owner-level metric functions in this module.

    Join strategy
    -------------
    - LEFT JOIN ``executions_df`` → ``owners_df`` on ``test_name`` so every
      execution row is preserved even when no owner is recorded.
    - LEFT JOIN the result → ``flakiness_df`` on ``test_name`` (optional).

    Missing-value handling
    ----------------------
    - ``owner`` is filled with :data:`UNASSIGNED_LABEL` when absent.
    - ``team`` is left as ``NaN`` when absent.
    - ``is_flaky`` is filled with ``False`` when the column exists but a
      specific row has no flakiness entry.
    - ``status`` is uppercased and stripped so comparisons against
      :data:`FAIL_STATUSES` are case-insensitive.

    Args:
        executions_df: One row per test execution.  Required columns:
            ``test_name``, ``run_id``, ``status``.
        owners_df: Ownership mapping.  Required columns:
            ``test_name``, ``owner``.  Optional: ``team``.
        flakiness_df: Flakiness metadata.  Required columns when provided:
            ``test_name``, ``is_flaky``.  Optional: ``flaky_score``.

    Returns:
        Wide DataFrame ready for all metric functions.

    Raises:
        TypeError:  If any argument is not a ``pd.DataFrame`` (when provided).
        ValueError: If required columns are missing from any input.
    """
    if not isinstance(executions_df, pd.DataFrame):
        raise TypeError(
            f"executions_df must be a pd.DataFrame, got {type(executions_df).__name__}."
        )
    if not isinstance(owners_df, pd.DataFrame):
        raise TypeError(
            f"owners_df must be a pd.DataFrame, got {type(owners_df).__name__}."
        )
    if flakiness_df is not None and not isinstance(flakiness_df, pd.DataFrame):
        raise TypeError(
            f"flakiness_df must be a pd.DataFrame or None, "
            f"got {type(flakiness_df).__name__}."
        )

    _validate_columns(executions_df, _REQUIRED_EXEC_COLS, "executions_df")
    _validate_columns(owners_df, _REQUIRED_OWNER_COLS, "owners_df")
    if flakiness_df is not None:
        _validate_columns(flakiness_df, _REQUIRED_FLAKY_COLS, "flakiness_df")

    # De-duplicate ownership rows (keep first per test_name) to avoid
    # multiplying execution rows during the join.
    owner_cols = ["test_name", "owner"]
    if "team" in owners_df.columns:
        owner_cols.append("team")
    owners_clean = owners_df[owner_cols].drop_duplicates(subset=["test_name"])

    # LEFT JOIN: executions → owners
    view = executions_df.merge(owners_clean, on="test_name", how="left")
    view["owner"] = view["owner"].fillna(UNASSIGNED_LABEL)

    # Normalise status to uppercase for consistent comparisons.
    view["status"] = view["status"].astype(str).str.upper().str.strip()

    # LEFT JOIN: view → flakiness (optional)
    if flakiness_df is not None:
        flaky_cols = ["test_name", "is_flaky"]
        if "flaky_score" in flakiness_df.columns:
            flaky_cols.append("flaky_score")
        flaky_clean = flakiness_df[flaky_cols].drop_duplicates(subset=["test_name"])
        view = view.merge(flaky_clean, on="test_name", how="left")
        view["is_flaky"] = view["is_flaky"].fillna(False).astype(bool)

    return view.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_failing(status_series: pd.Series) -> pd.Series:
    """Return a boolean Series: ``True`` where status is a failing status."""
    return status_series.isin(FAIL_STATUSES)


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def compute_failure_rate_per_owner(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> pd.DataFrame:
    """Compute per-owner failure rate.

    ``failure_rate = failed_executions / total_executions``

    "Execution" means one row — one test run once.  The rate is based on all
    execution attempts for the owner, not just distinct tests.

    Ranking: sorted descending by ``failed_executions``, then ``failure_rate``.
    This surfaces owners causing the most absolute noise; the rate acts as a
    tie-breaker to penalise owners with small suites that fail consistently.

    Args:
        view_df: Analytics view from :func:`build_owner_analytics_view`.
        exclude_unassigned: When ``True`` (default), rows owned by
            :data:`UNASSIGNED_LABEL` are excluded.

    Returns:
        DataFrame with columns: ``owner``, ``total_executions``,
        ``failed_executions``, ``failure_rate``.
    """
    df = view_df.copy()
    if exclude_unassigned:
        df = df[df["owner"] != UNASSIGNED_LABEL]

    df = df.copy()
    df["_is_fail"] = _is_failing(df["status"])

    agg = df.groupby("owner", as_index=False).agg(
        total_executions=("status", "count"),
        failed_executions=("_is_fail", "sum"),
    )
    agg["failed_executions"] = agg["failed_executions"].astype(int)
    agg["failure_rate"] = (
        agg["failed_executions"] / agg["total_executions"].replace(0, float("nan"))
    ).fillna(0.0).round(4)

    return (
        agg[["owner", "total_executions", "failed_executions", "failure_rate"]]
        .sort_values(["failed_executions", "failure_rate"], ascending=False)
        .reset_index(drop=True)
    )


def compute_failure_count_per_owner(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> pd.DataFrame:
    """Count failing executions per owner.

    Counts *executions* (rows with a failing status), not distinct failing
    tests.  Use this to answer "whose tests are failing the most right now?".

    Args:
        view_df: Analytics view from :func:`build_owner_analytics_view`.
        exclude_unassigned: When ``True`` (default), skip unassigned rows.

    Returns:
        DataFrame with columns: ``owner``, ``failure_count``.
        Sorted descending by ``failure_count``.
    """
    df = view_df.copy()
    if exclude_unassigned:
        df = df[df["owner"] != UNASSIGNED_LABEL]

    failures = df[_is_failing(df["status"])]

    if failures.empty:
        return pd.DataFrame(columns=["owner", "failure_count"])

    agg = (
        failures.groupby("owner", as_index=False)
        .size()
        .rename(columns={"size": "failure_count"})
    )
    return agg.sort_values("failure_count", ascending=False).reset_index(drop=True)


def compute_flaky_test_count_per_owner(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> pd.DataFrame:
    """Count distinct flaky tests per owner.

    Counts *unique ``test_name``* values where ``is_flaky`` is ``True``,
    grouped by owner.  This avoids inflating counts for high-frequency tests.

    When the ``is_flaky`` column is absent (i.e. flakiness data was not
    provided to :func:`build_owner_analytics_view`), an empty DataFrame with
    the correct schema is returned rather than raising an error.

    Args:
        view_df: Analytics view from :func:`build_owner_analytics_view`.
        exclude_unassigned: When ``True`` (default), skip unassigned rows.

    Returns:
        DataFrame with columns: ``owner``, ``flaky_test_count``.
        Sorted descending by ``flaky_test_count``.
    """
    if "is_flaky" not in view_df.columns:
        return pd.DataFrame(columns=["owner", "flaky_test_count"])

    df = view_df.copy()
    if exclude_unassigned:
        df = df[df["owner"] != UNASSIGNED_LABEL]

    flaky_rows = df[df["is_flaky"].astype(bool)]

    if flaky_rows.empty:
        return pd.DataFrame(columns=["owner", "flaky_test_count"])

    agg = (
        flaky_rows.groupby("owner")["test_name"]
        .nunique()
        .reset_index()
        .rename(columns={"test_name": "flaky_test_count"})
    )
    return agg.sort_values("flaky_test_count", ascending=False).reset_index(drop=True)


def compute_failing_tests_for_owner(
    view_df: pd.DataFrame,
    owner: str,
) -> pd.DataFrame:
    """Return all failing test executions for a specific owner.

    Pass the **canonical** owner name here (use the resolver to obtain it
    before calling this function).  Matching is an exact string comparison.

    Args:
        view_df: Analytics view from :func:`build_owner_analytics_view`.
        owner: Canonical owner name (exact match).

    Returns:
        DataFrame with columns: ``owner``, ``test_name``, ``run_id``,
        ``status``, plus ``error_type`` and ``timestamp`` when present in
        *view_df*.  Empty DataFrame with the same schema when no failures
        are found.
    """
    base_cols = ["owner", "test_name", "run_id", "status"]
    optional_cols = ["error_type", "timestamp"]

    mask = (view_df["owner"] == owner) & _is_failing(view_df["status"])
    result = view_df[mask].copy()

    keep = base_cols + [c for c in optional_cols if c in result.columns]
    return result[keep].reset_index(drop=True)
