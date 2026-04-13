"""Owner-aware analytics layer for QARA.

This package provides deterministic analytics so QARA can answer owner-related
questions without relying on the LLM to infer joins or aggregates.

Typical usage
-------------
::

    import pandas as pd
    from qara.analytics.owner_metrics import build_owner_analytics_view
    from qara.analytics.owner_queries import (
        answer_failing_tests_by_owner,
        answer_failure_rate_per_engineer,
        answer_owner_with_most_flaky_tests,
        answer_engineer_with_highest_failure_count,
    )

    view = build_owner_analytics_view(executions_df, owners_df, flakiness_df)
    result = answer_failing_tests_by_owner(view, "Fatima")
    # Pass `result` to the LLM only for wording — all numbers are already computed.

Pipeline integration
--------------------
User question
  → classify intent              (qara.llm.intent_detection)
  → call owner_queries function  (this package — deterministic)
  → pass structured result to LLM (wording only)
"""
from __future__ import annotations

from qara.analytics.owner_metrics import (
    build_owner_analytics_view,
    compute_failure_count_per_owner,
    compute_failure_rate_per_owner,
    compute_failing_tests_for_owner,
    compute_flaky_test_count_per_owner,
)
from qara.analytics.owner_queries import (
    answer_engineer_with_highest_failure_count,
    answer_failing_tests_by_owner,
    answer_failure_rate_per_engineer,
    answer_owner_with_most_flaky_tests,
)
from qara.analytics.owner_resolution import normalize_owner_name, resolve_owner_name
from qara.analytics.schemas import OwnerResolutionResult

__all__ = [
    # View builder
    "build_owner_analytics_view",
    # Metrics
    "compute_failure_rate_per_owner",
    "compute_failure_count_per_owner",
    "compute_flaky_test_count_per_owner",
    "compute_failing_tests_for_owner",
    # Resolution
    "normalize_owner_name",
    "resolve_owner_name",
    "OwnerResolutionResult",
    # High-level Q&A
    "answer_failing_tests_by_owner",
    "answer_failure_rate_per_engineer",
    "answer_owner_with_most_flaky_tests",
    "answer_engineer_with_highest_failure_count",
]
