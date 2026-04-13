"""Tests for qara.analytics.owner_metrics."""
from __future__ import annotations

import pandas as pd
import pytest

from qara.analytics.owner_metrics import (
    FAIL_STATUSES,
    UNASSIGNED_LABEL,
    build_owner_analytics_view,
    compute_failure_count_per_owner,
    compute_failure_rate_per_owner,
    compute_failing_tests_for_owner,
    compute_flaky_test_count_per_owner,
)


# ---------------------------------------------------------------------------
# build_owner_analytics_view — basic join
# ---------------------------------------------------------------------------


class TestBuildOwnerAnalyticsView:
    def test_all_execution_rows_preserved(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        """LEFT JOIN must keep every execution, even orphan rows."""
        view = build_owner_analytics_view(executions_df, owners_df)
        assert len(view) == len(executions_df)

    def test_owner_column_populated(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df)
        assert "owner" in view.columns
        assert view["owner"].notna().all()

    def test_unowned_rows_labelled_unassigned(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df)
        # testOrphan has no owner entry.
        orphan_rows = view[view["test_name"] == "testOrphan"]
        assert (orphan_rows["owner"] == UNASSIGNED_LABEL).all()

    def test_team_column_present_when_in_owners(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df)
        assert "team" in view.columns

    def test_status_uppercased(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        lower_exec = executions_df.copy()
        lower_exec["status"] = lower_exec["status"].str.lower()
        view = build_owner_analytics_view(lower_exec, owners_df)
        assert (view["status"] == view["status"].str.upper()).all()

    def test_flakiness_joined_when_provided(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df, flakiness_df)
        assert "is_flaky" in view.columns

    def test_is_flaky_missing_rows_filled_false(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df, flakiness_df)
        # testOrphan has no flakiness entry → should default to False.
        orphan = view[view["test_name"] == "testOrphan"]
        assert (orphan["is_flaky"] == False).all()  # noqa: E712

    def test_no_flakiness_df_no_is_flaky_column(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        view = build_owner_analytics_view(executions_df, owners_df)
        assert "is_flaky" not in view.columns

    def test_duplicate_owner_rows_do_not_inflate_executions(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        dup_owners = pd.concat([owners_df, owners_df], ignore_index=True)
        view = build_owner_analytics_view(executions_df, dup_owners)
        assert len(view) == len(executions_df)

    def test_raises_on_missing_required_exec_columns(
        self, owners_df: pd.DataFrame
    ) -> None:
        bad_exec = pd.DataFrame({"test_name": ["t1"], "status": ["PASSED"]})
        # Missing "run_id"
        with pytest.raises(ValueError, match="run_id"):
            build_owner_analytics_view(bad_exec, owners_df)

    def test_raises_on_missing_required_owner_columns(
        self, executions_df: pd.DataFrame
    ) -> None:
        bad_owners = pd.DataFrame({"test_name": ["t1"]})
        with pytest.raises(ValueError, match="owner"):
            build_owner_analytics_view(executions_df, bad_owners)

    def test_raises_on_missing_required_flaky_columns(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        bad_flaky = pd.DataFrame({"test_name": ["t1"]})
        with pytest.raises(ValueError, match="is_flaky"):
            build_owner_analytics_view(executions_df, owners_df, bad_flaky)

    def test_raises_type_error_for_non_dataframe_executions(
        self, owners_df: pd.DataFrame
    ) -> None:
        with pytest.raises(TypeError):
            build_owner_analytics_view([{"test_name": "t"}], owners_df)  # type: ignore[arg-type]

    def test_raises_type_error_for_non_dataframe_flakiness(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        with pytest.raises(TypeError):
            build_owner_analytics_view(executions_df, owners_df, [])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_failure_rate_per_owner
# ---------------------------------------------------------------------------


class TestComputeFailureRatePerOwner:
    def test_returns_expected_owners(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view)
        owners = set(rate_df["owner"].tolist())
        assert "Fatima Al-Rashid" in owners
        assert "John Doe" in owners

    def test_unassigned_excluded_by_default(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view)
        assert UNASSIGNED_LABEL not in rate_df["owner"].values

    def test_unassigned_included_when_requested(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view, exclude_unassigned=False)
        assert UNASSIGNED_LABEL in rate_df["owner"].values

    def test_failure_rate_between_zero_and_one(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view)
        assert (rate_df["failure_rate"] >= 0.0).all()
        assert (rate_df["failure_rate"] <= 1.0).all()

    def test_john_doe_failure_rate(self, analytics_view: pd.DataFrame) -> None:
        # John Doe: 3 executions, 2 FAILED (testCheckout x2), 1 PASSED.
        rate_df = compute_failure_rate_per_owner(analytics_view)
        row = rate_df[rate_df["owner"] == "John Doe"].iloc[0]
        assert row["total_executions"] == 3
        assert row["failed_executions"] == 2
        assert row["failure_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_fatima_failure_rate(self, analytics_view: pd.DataFrame) -> None:
        # Fatima: 4 executions, 2 FAILED.
        rate_df = compute_failure_rate_per_owner(analytics_view)
        row = rate_df[rate_df["owner"] == "Fatima Al-Rashid"].iloc[0]
        assert row["total_executions"] == 4
        assert row["failed_executions"] == 2

    def test_sorted_by_failed_executions_desc(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view)
        counts = rate_df["failed_executions"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_output_columns_present(self, analytics_view: pd.DataFrame) -> None:
        rate_df = compute_failure_rate_per_owner(analytics_view)
        assert set(rate_df.columns) >= {"owner", "total_executions", "failed_executions", "failure_rate"}


# ---------------------------------------------------------------------------
# compute_failure_count_per_owner
# ---------------------------------------------------------------------------


class TestComputeFailureCountPerOwner:
    def test_john_doe_failure_count(self, analytics_view: pd.DataFrame) -> None:
        count_df = compute_failure_count_per_owner(analytics_view)
        row = count_df[count_df["owner"] == "John Doe"].iloc[0]
        assert row["failure_count"] == 2

    def test_unassigned_excluded_by_default(self, analytics_view: pd.DataFrame) -> None:
        count_df = compute_failure_count_per_owner(analytics_view)
        assert UNASSIGNED_LABEL not in count_df["owner"].values

    def test_sorted_desc(self, analytics_view: pd.DataFrame) -> None:
        count_df = compute_failure_count_per_owner(analytics_view)
        counts = count_df["failure_count"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_empty_dataframe_when_no_failures(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        passing_exec = executions_df.copy()
        passing_exec["status"] = "PASSED"
        view = build_owner_analytics_view(passing_exec, owners_df)
        count_df = compute_failure_count_per_owner(view)
        assert count_df.empty
        assert "owner" in count_df.columns
        assert "failure_count" in count_df.columns

    def test_broken_status_counted_as_failure(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        broken_exec = executions_df.copy()
        broken_exec.loc[0, "status"] = "BROKEN"  # first row is Fatima's testLogin
        view = build_owner_analytics_view(broken_exec, owners_df)
        count_df = compute_failure_count_per_owner(view)
        fatima_row = count_df[count_df["owner"] == "Fatima Al-Rashid"]
        assert not fatima_row.empty
        # BROKEN row + original FAILED rows
        assert fatima_row.iloc[0]["failure_count"] >= 1


# ---------------------------------------------------------------------------
# compute_flaky_test_count_per_owner
# ---------------------------------------------------------------------------


class TestComputeFlakyTestCountPerOwner:
    def test_fatima_has_two_flaky_tests(self, analytics_view: pd.DataFrame) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view)
        row = flaky_df[flaky_df["owner"] == "Fatima Al-Rashid"].iloc[0]
        assert row["flaky_test_count"] == 2

    def test_john_smith_has_one_flaky_test(self, analytics_view: pd.DataFrame) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view)
        row = flaky_df[flaky_df["owner"] == "John Smith"].iloc[0]
        assert row["flaky_test_count"] == 1

    def test_john_doe_not_in_flaky_output(self, analytics_view: pd.DataFrame) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view)
        assert "John Doe" not in flaky_df["owner"].values

    def test_sorted_desc(self, analytics_view: pd.DataFrame) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view)
        counts = flaky_df["flaky_test_count"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_returns_empty_when_no_is_flaky_column(
        self, analytics_view_no_flaky: pd.DataFrame
    ) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view_no_flaky)
        assert flaky_df.empty
        assert "owner" in flaky_df.columns
        assert "flaky_test_count" in flaky_df.columns

    def test_counts_distinct_tests_not_executions(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        # Add a second run of a flaky test for Fatima.
        extra = pd.DataFrame(
            [{"test_name": "testLogin", "run_id": "run_99", "status": "PASSED",
              "error_type": None, "timestamp": "2024-01-13T10:00:00"}]
        )
        multi_exec = pd.concat([executions_df, extra], ignore_index=True)
        view = build_owner_analytics_view(multi_exec, owners_df, flakiness_df)
        flaky_df = compute_flaky_test_count_per_owner(view)
        fatima_row = flaky_df[flaky_df["owner"] == "Fatima Al-Rashid"].iloc[0]
        # Still 2 distinct flaky tests, not 3 executions.
        assert fatima_row["flaky_test_count"] == 2

    def test_unassigned_excluded_by_default(self, analytics_view: pd.DataFrame) -> None:
        flaky_df = compute_flaky_test_count_per_owner(analytics_view)
        assert UNASSIGNED_LABEL not in flaky_df["owner"].values


# ---------------------------------------------------------------------------
# compute_failing_tests_for_owner
# ---------------------------------------------------------------------------


class TestComputeFailingTestsForOwner:
    def test_returns_failing_rows_for_fatima(self, analytics_view: pd.DataFrame) -> None:
        result = compute_failing_tests_for_owner(analytics_view, "Fatima Al-Rashid")
        assert len(result) == 2
        assert set(result["test_name"].tolist()) == {
            "testLogin",
            "testAutocompleteSuggestions",
        }

    def test_all_rows_are_failing_status(self, analytics_view: pd.DataFrame) -> None:
        result = compute_failing_tests_for_owner(analytics_view, "Fatima Al-Rashid")
        assert result["status"].isin(FAIL_STATUSES).all()

    def test_owner_column_correct(self, analytics_view: pd.DataFrame) -> None:
        result = compute_failing_tests_for_owner(analytics_view, "John Doe")
        assert (result["owner"] == "John Doe").all()

    def test_returns_empty_for_unknown_owner(self, analytics_view: pd.DataFrame) -> None:
        result = compute_failing_tests_for_owner(analytics_view, "Nobody")
        assert result.empty

    def test_optional_columns_included_when_present(
        self, analytics_view: pd.DataFrame
    ) -> None:
        result = compute_failing_tests_for_owner(analytics_view, "Fatima Al-Rashid")
        # executions_df has error_type and timestamp.
        assert "error_type" in result.columns
        assert "timestamp" in result.columns

    def test_optional_columns_absent_when_not_in_view(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        # Build a minimal view without optional columns.
        minimal = executions_df[["test_name", "run_id", "status"]]
        view = build_owner_analytics_view(minimal, owners_df)
        result = compute_failing_tests_for_owner(view, "Fatima Al-Rashid")
        assert "error_type" not in result.columns
        assert "timestamp" not in result.columns

    def test_tied_failure_count_scenario(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        """Both John Doe and Fatima have 2 failing executions in the base dataset."""
        view = build_owner_analytics_view(executions_df, owners_df)
        fatima_fails = compute_failing_tests_for_owner(view, "Fatima Al-Rashid")
        john_doe_fails = compute_failing_tests_for_owner(view, "John Doe")
        assert len(fatima_fails) == len(john_doe_fails) == 2
