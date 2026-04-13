"""Shared fixtures for the owner analytics test suite.

Sample dataset
--------------
Owners:
  - Fatima Al-Rashid  (Frontend team)  — 3 tests
  - John Doe          (Payments team)  — 2 tests
  - John Smith        (Backend team)   — 1 test  ← exists for "John" ambiguity tests
  - testOrphan        has no owner     → becomes "Unassigned"

Flakiness:
  - testLogin                   is_flaky=True   (Fatima)
  - testAutocompleteSuggestions is_flaky=True   (Fatima)
  - testEmailValidation         is_flaky=True   (John Smith)
  - all others                  is_flaky=False
"""
from __future__ import annotations

import pandas as pd
import pytest

from qara.analytics.owner_metrics import build_owner_analytics_view


# ---------------------------------------------------------------------------
# Raw tables
# ---------------------------------------------------------------------------


@pytest.fixture()
def executions_df() -> pd.DataFrame:
    """One row per test execution."""
    return pd.DataFrame(
        [
            # Fatima Al-Rashid — 3 tests, 2 unique failures
            {
                "test_name": "testLogin",
                "run_id": "run_01",
                "status": "PASSED",
                "error_type": None,
                "timestamp": "2024-01-10T10:00:00",
            },
            {
                "test_name": "testLogin",
                "run_id": "run_02",
                "status": "FAILED",
                "error_type": "AssertionError",
                "timestamp": "2024-01-11T10:00:00",
            },
            {
                "test_name": "testAutocompleteSuggestions",
                "run_id": "run_25",
                "status": "FAILED",
                "error_type": "TimeoutError",
                "timestamp": "2024-01-12T10:00:00",
            },
            {
                "test_name": "testSearchFilters",
                "run_id": "run_03",
                "status": "PASSED",
                "error_type": None,
                "timestamp": "2024-01-10T11:00:00",
            },
            # John Doe — 2 tests, 2 failures on testCheckout
            {
                "test_name": "testCheckout",
                "run_id": "run_04",
                "status": "FAILED",
                "error_type": "NullPointerException",
                "timestamp": "2024-01-10T12:00:00",
            },
            {
                "test_name": "testCheckout",
                "run_id": "run_05",
                "status": "FAILED",
                "error_type": "NullPointerException",
                "timestamp": "2024-01-11T12:00:00",
            },
            {
                "test_name": "testPayment",
                "run_id": "run_06",
                "status": "PASSED",
                "error_type": None,
                "timestamp": "2024-01-10T13:00:00",
            },
            # John Smith — 1 test, 1 failure (used for "John" ambiguity tests)
            {
                "test_name": "testEmailValidation",
                "run_id": "run_07",
                "status": "FAILED",
                "error_type": "ValidationError",
                "timestamp": "2024-01-10T14:00:00",
            },
            # No owner — will become Unassigned
            {
                "test_name": "testOrphan",
                "run_id": "run_08",
                "status": "FAILED",
                "error_type": "UnknownError",
                "timestamp": "2024-01-10T15:00:00",
            },
        ]
    )


@pytest.fixture()
def owners_df() -> pd.DataFrame:
    """Ownership mapping. testOrphan is intentionally absent."""
    return pd.DataFrame(
        [
            {"test_name": "testLogin", "owner": "Fatima Al-Rashid", "team": "Frontend"},
            {
                "test_name": "testAutocompleteSuggestions",
                "owner": "Fatima Al-Rashid",
                "team": "Frontend",
            },
            {
                "test_name": "testSearchFilters",
                "owner": "Fatima Al-Rashid",
                "team": "Frontend",
            },
            {"test_name": "testCheckout", "owner": "John Doe", "team": "Payments"},
            {"test_name": "testPayment", "owner": "John Doe", "team": "Payments"},
            {"test_name": "testEmailValidation", "owner": "John Smith", "team": "Backend"},
        ]
    )


@pytest.fixture()
def flakiness_df() -> pd.DataFrame:
    """Flakiness metadata table."""
    return pd.DataFrame(
        [
            {"test_name": "testLogin", "is_flaky": True, "flaky_score": 0.72},
            {
                "test_name": "testAutocompleteSuggestions",
                "is_flaky": True,
                "flaky_score": 0.68,
            },
            {"test_name": "testSearchFilters", "is_flaky": False, "flaky_score": 0.10},
            {"test_name": "testCheckout", "is_flaky": False, "flaky_score": 0.05},
            {"test_name": "testPayment", "is_flaky": False, "flaky_score": 0.02},
            {"test_name": "testEmailValidation", "is_flaky": True, "flaky_score": 0.85},
        ]
    )


# ---------------------------------------------------------------------------
# Pre-built views
# ---------------------------------------------------------------------------


@pytest.fixture()
def analytics_view(
    executions_df: pd.DataFrame,
    owners_df: pd.DataFrame,
    flakiness_df: pd.DataFrame,
) -> pd.DataFrame:
    """Full analytics view: executions + owners + flakiness."""
    return build_owner_analytics_view(executions_df, owners_df, flakiness_df)


@pytest.fixture()
def analytics_view_no_flaky(
    executions_df: pd.DataFrame,
    owners_df: pd.DataFrame,
) -> pd.DataFrame:
    """Analytics view built without flakiness data."""
    return build_owner_analytics_view(executions_df, owners_df)
