"""Deterministic failure clustering engine for QARA.

Groups failing tests from a single ``TestRun`` by their normalised failure
signature.  Two failures are considered the *same root cause* when they
share an identical signature — a short SHA-256 hash computed from the
normalised stack trace (or error-type + message when no trace is available).

The algorithm is fully deterministic and requires no external dependencies.
An optional second pass merges singleton clusters that share the same
``FailureCategory`` when their signatures differ only because one test lacked
a stack trace (i.e. ``message``-only hash vs. ``stack_trace`` hash).

Usage::

    from qara.analyzers.clustering import cluster_failures
    from qara.models.run import TestRun

    clusters = cluster_failures(run)
    for c in clusters:
        print(c.label, c.size, c.failure_signature)
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from qara.analyzers.categorizer import FailureCategory, categorize_failure
from qara.analyzers.fingerprint import compute_fingerprint
from qara.models.insight import FailureCluster, InsightCategory

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qara.models.test_case import TestCaseResult

# ---------------------------------------------------------------------------
# Mapping from FailureCategory → InsightCategory
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[FailureCategory, InsightCategory] = {
    FailureCategory.ELEMENT_NOT_FOUND: InsightCategory.LIKELY_TEST_SCRIPT_ISSUE,
    FailureCategory.STALE_ELEMENT: InsightCategory.LIKELY_TEST_SCRIPT_ISSUE,
    FailureCategory.TIMEOUT: InsightCategory.LIKELY_FLAKY,
    FailureCategory.ASSERTION: InsightCategory.LIKELY_PRODUCT_DEFECT,
    FailureCategory.NULL_POINTER: InsightCategory.LIKELY_PRODUCT_DEFECT,
    FailureCategory.NETWORK: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
    FailureCategory.AUTHENTICATION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
    FailureCategory.INFRASTRUCTURE: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
    FailureCategory.TEST_DATA: InsightCategory.LIKELY_TEST_DATA_ISSUE,
    FailureCategory.PERMISSION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
    FailureCategory.CONFIGURATION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
    FailureCategory.UNKNOWN: InsightCategory.UNKNOWN,
}

# Confidence assigned to a cluster based on how many members it has.
# Single-member clusters get lower confidence; larger clusters are more reliable.
def _cluster_confidence(size: int, category: InsightCategory) -> float:
    """Return a confidence score for a cluster of *size* members."""
    if category is InsightCategory.UNKNOWN:
        return 0.3
    if size >= 5:
        return 0.85
    if size >= 3:
        return 0.75
    if size == 2:
        return 0.65
    return 0.5  # singleton — moderate confidence


def _dominant_category(member_categories: list[InsightCategory]) -> InsightCategory:
    """Return the most common category in *member_categories*."""
    if not member_categories:
        return InsightCategory.UNKNOWN
    counts: dict[InsightCategory, int] = defaultdict(int)
    for cat in member_categories:
        counts[cat] += 1
    return max(counts, key=lambda k: counts[k])


def _resolve_signature(tc: TestCaseResult) -> str:
    """Return the failure signature for *tc*, computing it if not already set."""
    if tc.failure and tc.failure.failure_signature:
        return tc.failure.failure_signature
    if tc.failure:
        return compute_fingerprint(
            error_type=tc.failure.error_type,
            stack_trace=tc.failure.stack_trace,
            message=tc.failure.message,
        )
    # Passed / skipped tests without a failure should not reach here,
    # but guard defensively.
    return compute_fingerprint(error_type=None, stack_trace=None, message=tc.name)


def _build_label(
    error_type: str | None,
    message: str | None,
    category: FailureCategory,
) -> str:
    """Derive a short human-readable cluster label.

    Uses the error type when available, falling back to the first 60
    characters of the message, and finally the category label.
    """
    if error_type:
        # Strip fully-qualified Java package: keep only the simple class name
        simple_type = error_type.rstrip(":").split(".")[-1].split("$")[-1].strip()
        if simple_type:
            return simple_type
    if message:
        snippet = message.strip().splitlines()[0][:60].strip()
        if snippet:
            return snippet
    return category.label


def cluster_failures(
    test_cases: Sequence[TestCaseResult],
) -> list[FailureCluster]:
    """Group failing test cases by normalised failure signature.

    Only tests with a failing status (``FAILED`` or ``BROKEN``) are
    processed; passed, skipped, and pending tests are ignored.

    The algorithm is deterministic and runs in O(n) time:

    1. For each failing test, resolve (or compute) a 16-char hex signature.
    2. Group tests by signature.
    3. For each group, determine the dominant ``InsightCategory`` by
       categorizing the representative failure with the rule-based
       categorizer.
    4. Sort clusters by size descending, then by label ascending (stable
       ordering for deterministic output).

    Args:
        test_cases: All test case results from a single run (including
            passing tests — non-failing tests are skipped automatically).

    Returns:
        A list of :class:`~qara.models.insight.FailureCluster` objects,
        ordered by cluster size descending.  An empty list is returned
        when there are no failing tests.

    """
    # --- Step 1: collect failing tests, resolve signatures -----------------
    # signature → list of TestCaseResult
    groups: dict[str, list[TestCaseResult]] = defaultdict(list)

    for tc in test_cases:
        if not tc.status.is_failing:
            continue
        sig = _resolve_signature(tc)
        groups[sig].append(tc)

    if not groups:
        return []

    # --- Step 2: build FailureCluster for each signature group -------------
    clusters: list[FailureCluster] = []

    for signature, members in groups.items():
        # Use the first member as the representative for label / category
        rep = members[0]
        rep_failure = rep.failure

        error_type = rep_failure.error_type if rep_failure else None
        message = rep_failure.message if rep_failure else None
        stack_trace = rep_failure.normalized_stack_trace or (
            rep_failure.stack_trace if rep_failure else None
        )

        # Categorize using the rule-based engine
        failure_cat = categorize_failure(
            error_type=error_type,
            message=message,
        )

        # Build per-member insight categories for dominant-category voting
        member_cats: list[InsightCategory] = []
        for tc in members:
            f = tc.failure
            cat = categorize_failure(
                error_type=f.error_type if f else None,
                message=f.message if f else None,
            )
            member_cats.append(_CATEGORY_MAP.get(cat, InsightCategory.UNKNOWN))

        dominant = _dominant_category(member_cats)

        label = _build_label(error_type, message, failure_cat)
        confidence = _cluster_confidence(len(members), dominant)

        cluster = FailureCluster(
            cluster_id=signature,
            label=label,
            failure_signature=signature,
            member_test_ids=[tc.test_id for tc in members],
            category=dominant,
            confidence=confidence,
            rationale=(
                f"{len(members)} test(s) share the same failure signature. "
                f"Dominant category: {dominant.display_name}."
            ),
            representative_message=message,
            representative_stack_trace=stack_trace,
        )
        clusters.append(cluster)

    # --- Step 3: sort by size desc, then label asc for deterministic order -
    clusters.sort(key=lambda c: (-c.size, c.label))
    return clusters
