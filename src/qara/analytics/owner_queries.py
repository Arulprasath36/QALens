"""High-level deterministic owner analytics Q&A functions.

Each function in this module:

1. Accepts a pre-built analytics view DataFrame (and optionally a raw owner
   query string).
2. Performs **all** joins, aggregations, and ranking using deterministic
   Python — the LLM is never asked to compute anything.
3. Returns a structured ``dict`` that can be forwarded directly to the LLM
   **for wording only**.

Pipeline integration
--------------------
::

    User question
      → classify intent              (qara.llm.intent_detection)
      → call owner_queries function  (this module — deterministic)
      → pass structured result to LLM (wording only, no math)

Routing guide
-------------
=================================================================  ============================================
User question pattern                                              Function to call
=================================================================  ============================================
"Which tests owned by Fatima are failing?"                         :func:`answer_failing_tests_by_owner`
"Show failure rate per engineer"                                    :func:`answer_failure_rate_per_engineer`
"Who owns the most flaky tests?"                                    :func:`answer_owner_with_most_flaky_tests`
"Which engineer has the highest failure count?"                     :func:`answer_engineer_with_highest_failure_count`
=================================================================  ============================================

Output format
-------------
Every function returns a ``dict`` with these keys:

``question_type``
    Machine-readable identifier string.

``success``
    ``True`` when the question was answered; ``False`` on ambiguous/no-match.

``assumptions``
    List of transparent reasoning statements (e.g. "Interpreted 'Fatima'
    as 'Fatima Al-Rashid'").

``data``
    The computed result payload (structure varies per question type).

``summary``
    One human-readable sentence summarising the answer.

``warnings``
    Non-fatal issues (e.g. tie notifications, missing flakiness data).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from qara.analytics.owner_metrics import (
    UNASSIGNED_LABEL,
    compute_failure_count_per_owner,
    compute_failure_rate_per_owner,
    compute_failing_tests_for_owner,
    compute_flaky_test_count_per_owner,
)
from qara.analytics.owner_resolution import resolve_owner_name
from qara.analytics.schemas import OwnerResolutionResult

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _known_owners(view_df: pd.DataFrame, *, exclude_unassigned: bool = True) -> list[str]:
    """Return the unique canonical owner names present in *view_df*."""
    owners: list[str] = view_df["owner"].unique().tolist()
    if exclude_unassigned:
        owners = [o for o in owners if o != UNASSIGNED_LABEL]
    return owners


def _ambiguous_response(question_type: str, resolution: OwnerResolutionResult) -> dict[str, Any]:
    """Build a standard structured response for an ambiguous owner query."""
    return {
        "question_type": question_type,
        "success": False,
        "assumptions": [],
        "data": {"candidates": resolution.candidates},
        "summary": f"Multiple owner matches found for '{resolution.query}'.",
        "warnings": [
            "Owner name is ambiguous. Please specify one of: "
            + ", ".join(f"'{c}'" for c in resolution.candidates)
            + "."
        ],
    }


def _no_match_response(question_type: str, resolution: OwnerResolutionResult) -> dict[str, Any]:
    """Build a standard structured response when no owner could be resolved."""
    return {
        "question_type": question_type,
        "success": False,
        "assumptions": [],
        "data": {},
        "summary": f"No owner matched '{resolution.query}'.",
        "warnings": [resolution.explanation],
    }


# ---------------------------------------------------------------------------
# Public Q&A functions
# ---------------------------------------------------------------------------


def answer_failing_tests_by_owner(
    view_df: pd.DataFrame,
    owner_query: str,
    *,
    fuzzy_threshold: int = 85,
) -> dict[str, Any]:
    """Return all failing tests for the owner whose name matches *owner_query*.

    Owner name resolution uses the three-step strategy (exact → partial →
    fuzzy).  When the query is ambiguous or unmatched, a structured error
    response is returned — callers do not need to catch an exception.

    The ``assumptions`` list records any name interpretation so the LLM can
    phrase it naturally (e.g. "Interpreted 'Fatima' as 'Fatima Al-Rashid'").

    Args:
        view_df: Analytics view from
            :func:`~qara.analytics.owner_metrics.build_owner_analytics_view`.
        owner_query: Raw owner string from the user (e.g. ``"Fatima"``).
        fuzzy_threshold: Passed to the resolver (default 85).

    Returns:
        Structured dict — see module docstring for schema.

    Example output (success)::

        {
          "question_type": "failing_tests_by_owner",
          "success": true,
          "assumptions": [
            "Interpreted 'Fatima' as 'Fatima Al-Rashid' using partial name resolution"
          ],
          "data": {
            "owner": "Fatima Al-Rashid",
            "failing_tests": [
              {"owner": "Fatima Al-Rashid", "test_name": "testAutocompleteSuggestions",
               "run_id": "run_25", "status": "FAILED", "error_type": "TimeoutError"}
            ]
          },
          "summary": "Found 1 failing test owned by Fatima Al-Rashid.",
          "warnings": []
        }

    Example output (ambiguous)::

        {
          "question_type": "failing_tests_by_owner",
          "success": false,
          "assumptions": [],
          "data": {"candidates": ["Fatima Al-Rashid", "Fatima Khan"]},
          "summary": "Multiple owner matches found for 'Fatima'.",
          "warnings": ["Owner name is ambiguous. Please specify one of: ..."]
        }
    """
    qt = "failing_tests_by_owner"
    known = _known_owners(view_df)
    resolution = resolve_owner_name(owner_query, known, fuzzy_threshold=fuzzy_threshold)

    if resolution.match_type == "ambiguous":
        return _ambiguous_response(qt, resolution)
    if resolution.match_type == "none":
        return _no_match_response(qt, resolution)

    # match_type is one of "exact", "partial", "fuzzy" → matched_owner is set
    canonical = resolution.matched_owner  # type: ignore[assignment]  # guaranteed non-None

    assumptions: list[str] = []
    if canonical != owner_query:
        assumptions.append(
            f"Interpreted '{owner_query}' as '{canonical}' "
            f"using {resolution.match_type} name resolution."
        )

    failing_df = compute_failing_tests_for_owner(view_df, canonical)
    failing_tests = failing_df.to_dict(orient="records")
    count = len(failing_tests)

    return {
        "question_type": qt,
        "success": True,
        "assumptions": assumptions,
        "data": {
            "owner": canonical,
            "failing_tests": failing_tests,
        },
        "summary": (
            f"Found {count} failing test{'s' if count != 1 else ''} "
            f"owned by {canonical}."
        ),
        "warnings": [],
    }


def answer_failure_rate_per_engineer(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> dict[str, Any]:
    """Return failure rate for every engineer, ranked descending.

    ``failure_rate = failed_executions / total_executions``

    Ranking is by ``failed_executions DESC``, then ``failure_rate DESC``.
    This surfaces engineers whose tests are failing most in absolute terms;
    the rate acts as a tie-breaker for engineers with few but consistently
    failing tests.

    Args:
        view_df: Analytics view from
            :func:`~qara.analytics.owner_metrics.build_owner_analytics_view`.
        exclude_unassigned: Skip rows with no recorded owner (default ``True``).

    Returns:
        Structured dict — see module docstring for schema.
    """
    qt = "failure_rate_per_engineer"
    assumptions: list[str] = []
    if exclude_unassigned:
        assumptions.append(
            f"Rows with owner='{UNASSIGNED_LABEL}' are excluded from rankings."
        )

    rate_df = compute_failure_rate_per_owner(view_df, exclude_unassigned=exclude_unassigned)

    if rate_df.empty:
        return {
            "question_type": qt,
            "success": True,
            "assumptions": assumptions,
            "data": {"engineers": []},
            "summary": "No owner data available to compute failure rates.",
            "warnings": ["The analytics view contains no owned test executions."],
        }

    engineers = rate_df.to_dict(orient="records")
    top = engineers[0]

    return {
        "question_type": qt,
        "success": True,
        "assumptions": assumptions,
        "data": {"engineers": engineers},
        "summary": (
            f"{top['owner']} has the highest failure count "
            f"({top['failed_executions']} failures out of "
            f"{top['total_executions']} executions, "
            f"{top['failure_rate'] * 100:.1f}% failure rate)."
        ),
        "warnings": [],
    }


def answer_owner_with_most_flaky_tests(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> dict[str, Any]:
    """Return the owner with the highest count of distinct flaky tests.

    Flaky test count = number of **unique test names** where ``is_flaky`` is
    ``True``, per owner.  Counting unique tests (not executions) prevents
    high-frequency tests from dominating the ranking.

    Tie handling: when multiple owners share the top count, all are returned
    in ``data.tied_owners`` and the response sets ``data.tied = true``.

    Args:
        view_df: Analytics view.  Must contain an ``is_flaky`` column for a
            non-empty result.
        exclude_unassigned: Skip unassigned rows (default ``True``).

    Returns:
        Structured dict — see module docstring for schema.
    """
    qt = "owner_with_most_flaky_tests"

    if "is_flaky" not in view_df.columns:
        return {
            "question_type": qt,
            "success": False,
            "assumptions": [],
            "data": {},
            "summary": "Flakiness data is not available in the current analytics view.",
            "warnings": [
                "No 'is_flaky' column found. "
                "Provide flakiness_df when building the analytics view."
            ],
        }

    flaky_df = compute_flaky_test_count_per_owner(
        view_df, exclude_unassigned=exclude_unassigned
    )

    if flaky_df.empty:
        return {
            "question_type": qt,
            "success": True,
            "assumptions": [],
            "data": {"owner": None, "flaky_test_count": 0, "ranking": [], "tied": False},
            "summary": "No flaky tests found in the current dataset.",
            "warnings": [],
        }

    ranking = flaky_df.to_dict(orient="records")
    top_count = ranking[0]["flaky_test_count"]
    top_owners = [r for r in ranking if r["flaky_test_count"] == top_count]
    is_tied = len(top_owners) > 1

    warnings: list[str] = []
    if is_tied:
        tie_names = [r["owner"] for r in top_owners]
        warnings.append(
            f"Tie: {len(top_owners)} owners share the top flaky count "
            f"({top_count}): {tie_names}."
        )
        summary = (
            f"{len(top_owners)} owners are tied with {top_count} "
            f"flaky test{'s' if top_count != 1 else ''} each: "
            f"{', '.join(tie_names)}."
        )
        top_owner = None
    else:
        top_owner = top_owners[0]["owner"]
        summary = (
            f"{top_owner} owns the most flaky tests "
            f"({top_count} unique flaky test{'s' if top_count != 1 else ''})."
        )

    return {
        "question_type": qt,
        "success": True,
        "assumptions": [
            "Flaky test count = distinct test names with is_flaky=True, per owner.",
            (
                f"Rows with owner='{UNASSIGNED_LABEL}' are "
                f"{'excluded' if exclude_unassigned else 'included'}."
            ),
        ],
        "data": {
            "owner": top_owner,
            "flaky_test_count": top_count,
            "ranking": ranking,
            "tied": is_tied,
        },
        "summary": summary,
        "warnings": warnings,
    }


def answer_engineer_with_highest_failure_count(
    view_df: pd.DataFrame,
    *,
    exclude_unassigned: bool = True,
) -> dict[str, Any]:
    """Return the engineer whose tests have the most failing executions.

    Failure count = rows where status is in ``{FAIL, FAILED, BROKEN}``,
    grouped by owner.  Counts executions, not distinct failing tests.

    Tie handling: when multiple engineers share the top count, all are
    returned and the response sets ``data.tied = true``.

    Args:
        view_df: Analytics view.
        exclude_unassigned: Skip unassigned rows (default ``True``).

    Returns:
        Structured dict — see module docstring for schema.
    """
    qt = "engineer_with_highest_failure_count"

    count_df = compute_failure_count_per_owner(
        view_df, exclude_unassigned=exclude_unassigned
    )

    if count_df.empty:
        return {
            "question_type": qt,
            "success": True,
            "assumptions": [],
            "data": {"owner": None, "failure_count": 0, "ranking": [], "tied": False},
            "summary": "No failing executions found in the current dataset.",
            "warnings": [],
        }

    ranking = count_df.to_dict(orient="records")
    top_count = ranking[0]["failure_count"]
    top_owners = [r for r in ranking if r["failure_count"] == top_count]
    is_tied = len(top_owners) > 1

    warnings: list[str] = []
    if is_tied:
        tie_names = [r["owner"] for r in top_owners]
        warnings.append(
            f"Tie: {len(top_owners)} engineers share the top failure count "
            f"({top_count}): {tie_names}."
        )
        summary = (
            f"{len(top_owners)} engineers are tied with {top_count} "
            f"failing execution{'s' if top_count != 1 else ''} each: "
            f"{', '.join(tie_names)}."
        )
        top_owner = None
    else:
        top_owner = top_owners[0]["owner"]
        summary = (
            f"{top_owner} has the highest failure count "
            f"({top_count} failing execution{'s' if top_count != 1 else ''})."
        )

    return {
        "question_type": qt,
        "success": True,
        "assumptions": [
            "Failure count = failing executions (rows), not distinct failing tests.",
            (
                f"Rows with owner='{UNASSIGNED_LABEL}' are "
                f"{'excluded' if exclude_unassigned else 'included'}."
            ),
        ],
        "data": {
            "owner": top_owner,
            "failure_count": top_count,
            "ranking": ranking,
            "tied": is_tied,
        },
        "summary": summary,
        "warnings": warnings,
    }
