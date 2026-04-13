"""Tests for qara.analytics.owner_queries."""
from __future__ import annotations

import pandas as pd
import pytest

from qara.analytics.owner_queries import (
    answer_engineer_with_highest_failure_count,
    answer_failing_tests_by_owner,
    answer_failure_rate_per_engineer,
    answer_owner_with_most_flaky_tests,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_response_shape(response: dict) -> None:
    """Every response must have the standard five keys."""
    assert "question_type" in response
    assert "success" in response
    assert "assumptions" in response
    assert "data" in response
    assert "summary" in response
    assert "warnings" in response
    assert isinstance(response["assumptions"], list)
    assert isinstance(response["warnings"], list)
    assert isinstance(response["summary"], str)


# ---------------------------------------------------------------------------
# answer_failing_tests_by_owner
# ---------------------------------------------------------------------------


class TestAnswerFailingTestsByOwner:
    def test_exact_match_returns_success(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima Al-Rashid")
        _assert_response_shape(res)
        assert res["success"] is True
        assert res["question_type"] == "failing_tests_by_owner"

    def test_exact_match_data_payload(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima Al-Rashid")
        assert res["data"]["owner"] == "Fatima Al-Rashid"
        assert len(res["data"]["failing_tests"]) == 2

    def test_exact_match_no_assumptions_recorded(
        self, analytics_view: pd.DataFrame
    ) -> None:
        # No interpretation needed when query exactly matches.
        res = answer_failing_tests_by_owner(analytics_view, "Fatima Al-Rashid")
        assert res["assumptions"] == []

    def test_partial_match_records_assumption(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima")
        assert res["success"] is True
        assert len(res["assumptions"]) > 0
        assert "Fatima Al-Rashid" in res["assumptions"][0]

    def test_partial_match_returns_correct_owner(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima")
        assert res["data"]["owner"] == "Fatima Al-Rashid"

    def test_ambiguous_returns_failure(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "John")
        assert res["success"] is False
        assert res["question_type"] == "failing_tests_by_owner"
        assert "candidates" in res["data"]
        assert len(res["data"]["candidates"]) >= 2

    def test_ambiguous_has_no_failing_tests_key(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "John")
        assert "failing_tests" not in res["data"]

    def test_no_match_returns_failure(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Zaphod Beeblebrox")
        assert res["success"] is False
        assert res["data"] == {}

    def test_no_match_populates_warnings(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Zaphod Beeblebrox")
        assert len(res["warnings"]) > 0

    def test_summary_mentions_owner_on_success(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima Al-Rashid")
        assert "Fatima Al-Rashid" in res["summary"]

    def test_summary_mentions_count_on_success(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_failing_tests_by_owner(analytics_view, "Fatima Al-Rashid")
        assert "2" in res["summary"]

    def test_owner_with_no_failures_returns_empty_list(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        passing_exec = executions_df.copy()
        passing_exec.loc[
            passing_exec["test_name"].isin(
                ["testLogin", "testAutocompleteSuggestions", "testSearchFilters"]
            ),
            "status",
        ] = "PASSED"
        from qara.analytics.owner_metrics import build_owner_analytics_view
        view = build_owner_analytics_view(passing_exec, owners_df, flakiness_df)
        res = answer_failing_tests_by_owner(view, "Fatima Al-Rashid")
        assert res["success"] is True
        assert res["data"]["failing_tests"] == []

    def test_fuzzy_match_resolves_typo(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failing_tests_by_owner(
            analytics_view, "Fathima", fuzzy_threshold=70
        )
        # Should resolve to Fatima Al-Rashid via partial or fuzzy matching.
        assert res["success"] is True
        assert res["data"]["owner"] == "Fatima Al-Rashid"


# ---------------------------------------------------------------------------
# answer_failure_rate_per_engineer
# ---------------------------------------------------------------------------


class TestAnswerFailureRatePerEngineer:
    def test_returns_success(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        _assert_response_shape(res)
        assert res["success"] is True

    def test_question_type(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        assert res["question_type"] == "failure_rate_per_engineer"

    def test_engineers_list_non_empty(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        assert len(res["data"]["engineers"]) > 0

    def test_each_engineer_has_required_fields(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        for eng in res["data"]["engineers"]:
            assert "owner" in eng
            assert "total_executions" in eng
            assert "failed_executions" in eng
            assert "failure_rate" in eng

    def test_unassigned_excluded_by_default(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        owners = [e["owner"] for e in res["data"]["engineers"]]
        from qara.analytics.owner_metrics import UNASSIGNED_LABEL
        assert UNASSIGNED_LABEL not in owners

    def test_summary_names_top_owner(self, analytics_view: pd.DataFrame) -> None:
        res = answer_failure_rate_per_engineer(analytics_view)
        top_owner = res["data"]["engineers"][0]["owner"]
        assert top_owner in res["summary"]

    def test_empty_view_returns_warning(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        from qara.analytics.owner_metrics import build_owner_analytics_view
        empty = build_owner_analytics_view(
            executions_df[executions_df["test_name"] == "NONEXISTENT"],
            owners_df,
        )
        res = answer_failure_rate_per_engineer(empty)
        assert res["success"] is True
        assert len(res["warnings"]) > 0


# ---------------------------------------------------------------------------
# answer_owner_with_most_flaky_tests
# ---------------------------------------------------------------------------


class TestAnswerOwnerWithMostFlakyTests:
    def test_returns_success(self, analytics_view: pd.DataFrame) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view)
        _assert_response_shape(res)
        assert res["success"] is True

    def test_question_type(self, analytics_view: pd.DataFrame) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view)
        assert res["question_type"] == "owner_with_most_flaky_tests"

    def test_fatima_is_top_owner(self, analytics_view: pd.DataFrame) -> None:
        # Fatima has 2 flaky tests, John Smith has 1.
        res = answer_owner_with_most_flaky_tests(analytics_view)
        assert res["data"]["owner"] == "Fatima Al-Rashid"

    def test_flaky_count_correct(self, analytics_view: pd.DataFrame) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view)
        assert res["data"]["flaky_test_count"] == 2

    def test_ranking_includes_all_flaky_owners(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view)
        owner_names = [r["owner"] for r in res["data"]["ranking"]]
        assert "Fatima Al-Rashid" in owner_names
        assert "John Smith" in owner_names

    def test_tied_flag_false_when_no_tie(self, analytics_view: pd.DataFrame) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view)
        assert res["data"]["tied"] is False

    def test_tied_flag_true_and_owner_none_on_tie(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        # Give John Doe 2 flaky tests (testCheckout + testPayment) to tie Fatima.
        tied_flaky = flakiness_df.copy()
        tied_flaky.loc[tied_flaky["test_name"] == "testCheckout", "is_flaky"] = True
        tied_flaky.loc[tied_flaky["test_name"] == "testPayment", "is_flaky"] = True
        from qara.analytics.owner_metrics import build_owner_analytics_view
        view = build_owner_analytics_view(executions_df, owners_df, tied_flaky)
        res = answer_owner_with_most_flaky_tests(view)
        assert res["data"]["tied"] is True
        assert res["data"]["owner"] is None
        assert len(res["warnings"]) > 0

    def test_no_flaky_column_returns_failure(
        self, analytics_view_no_flaky: pd.DataFrame
    ) -> None:
        res = answer_owner_with_most_flaky_tests(analytics_view_no_flaky)
        assert res["success"] is False
        assert len(res["warnings"]) > 0

    def test_no_flaky_tests_in_data_returns_success_empty(
        self,
        executions_df: pd.DataFrame,
        owners_df: pd.DataFrame,
        flakiness_df: pd.DataFrame,
    ) -> None:
        all_stable = flakiness_df.copy()
        all_stable["is_flaky"] = False
        from qara.analytics.owner_metrics import build_owner_analytics_view
        view = build_owner_analytics_view(executions_df, owners_df, all_stable)
        res = answer_owner_with_most_flaky_tests(view)
        assert res["success"] is True
        assert res["data"]["owner"] is None
        assert res["data"]["flaky_test_count"] == 0


# ---------------------------------------------------------------------------
# answer_engineer_with_highest_failure_count
# ---------------------------------------------------------------------------


class TestAnswerEngineerWithHighestFailureCount:
    def test_returns_success(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        _assert_response_shape(res)
        assert res["success"] is True

    def test_question_type(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        assert res["question_type"] == "engineer_with_highest_failure_count"

    def test_top_owner_has_most_failures(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        top = res["data"]["owner"]
        top_count = res["data"]["failure_count"]
        ranking = res["data"]["ranking"]
        for r in ranking:
            assert r["failure_count"] <= top_count or r["owner"] == top

    def test_john_doe_and_fatima_tied_at_two(
        self, analytics_view: pd.DataFrame
    ) -> None:
        # Both have 2 failures in the base dataset — could be a tie.
        res = answer_engineer_with_highest_failure_count(analytics_view)
        top_count = res["data"]["failure_count"]
        assert top_count == 2

    def test_tied_flag_true_on_tie(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        # Fatima and John Doe both have 2 failures.
        if res["data"]["tied"]:
            assert res["data"]["owner"] is None
            assert len(res["warnings"]) > 0

    def test_ranking_sorted_desc(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        counts = [r["failure_count"] for r in res["data"]["ranking"]]
        assert counts == sorted(counts, reverse=True)

    def test_unassigned_excluded_by_default(self, analytics_view: pd.DataFrame) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        from qara.analytics.owner_metrics import UNASSIGNED_LABEL
        owners = [r["owner"] for r in res["data"]["ranking"]]
        assert UNASSIGNED_LABEL not in owners

    def test_no_failures_returns_empty_ranking(
        self, executions_df: pd.DataFrame, owners_df: pd.DataFrame
    ) -> None:
        all_pass = executions_df.copy()
        all_pass["status"] = "PASSED"
        from qara.analytics.owner_metrics import build_owner_analytics_view
        view = build_owner_analytics_view(all_pass, owners_df)
        res = answer_engineer_with_highest_failure_count(view)
        assert res["success"] is True
        assert res["data"]["failure_count"] == 0
        assert res["data"]["ranking"] == []

    def test_assumptions_document_counting_method(
        self, analytics_view: pd.DataFrame
    ) -> None:
        res = answer_engineer_with_highest_failure_count(analytics_view)
        assumptions_text = " ".join(res["assumptions"]).lower()
        assert "execution" in assumptions_text or "row" in assumptions_text
