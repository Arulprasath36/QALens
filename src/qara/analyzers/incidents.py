"""Incident assembly from run failure data.

Transforms raw :class:`~qara.db.models.TestCaseRow` failures for a given run
into :class:`~qara.models.incident.IncidentSummary` objects by:

1. Grouping failures that share the same ``fingerprint`` — identical root-cause
   signal produced by :mod:`qara.analyzers.fingerprint`.
2. Sub-grouping fingerprint-less failures by ``error_type``.
3. Collecting any remaining ungrouped failures into a single catch-all incident.
4. Annotating each group with category, evidence bullets, and a concrete
   recommended action sourced from rule-based heuristics.

No ML or external services are required — everything is derived from data
already persisted to SQLite during ingestion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from qara.analyzers.categorizer import FailureCategory, categorize_failure
from qara.models.incident import IncidentSummary

if TYPE_CHECKING:
    from qara.db.models import TestCaseRow

# ---------------------------------------------------------------------------
# Severity thresholds (impacted test count → label)
# ---------------------------------------------------------------------------

_SEVERITY: list[tuple[int, str]] = [
    (5, "critical"),
    (3, "high"),
    (2, "medium"),
    (1, "low"),
]

# ---------------------------------------------------------------------------
# Category → probable root cause phrase
# ---------------------------------------------------------------------------

_ROOT_CAUSE: dict[str, str] = {
    FailureCategory.ELEMENT_NOT_FOUND.value: (
        "UI locator failure — expected DOM element not found"
    ),
    FailureCategory.STALE_ELEMENT.value: (
        "Stale UI element — DOM changed or reloaded after element was located"
    ),
    FailureCategory.TIMEOUT.value: (
        "Synchronization / wait timeout — element or response too slow"
    ),
    FailureCategory.ASSERTION.value: (
        "Assertion failure — application returned an unexpected state or value"
    ),
    FailureCategory.NULL_POINTER.value: (
        "Null reference error — unexpected nil/null value in test or application code"
    ),
    FailureCategory.NETWORK.value: (
        "Network or service connectivity failure — backend unreachable or returning errors"
    ),
    FailureCategory.AUTHENTICATION.value: (
        "Authentication or session failure — credentials, tokens, or session config problem"
    ),
    FailureCategory.INFRASTRUCTURE.value: (
        "Infrastructure or test environment problem — driver, container, or config failure"
    ),
    FailureCategory.TEST_DATA.value: (
        "Test data setup problem — fixture, seed data, or pre-condition not satisfied"
    ),
    FailureCategory.PERMISSION.value: (
        "Permission or access control failure — insufficient grants or role misconfiguration"
    ),
    FailureCategory.CONFIGURATION.value: (
        "Environment configuration drift — mismatch between expected and actual config"
    ),
    FailureCategory.UNKNOWN.value: (
        "Unclassified failure — no known pattern matched; manual inspection needed"
    ),
}

# ---------------------------------------------------------------------------
# Category → concrete recommended action
# ---------------------------------------------------------------------------

_ACTION: dict[str, str] = {
    FailureCategory.ELEMENT_NOT_FOUND.value: (
        "Inspect selector drift and DOM changes; verify element visibility and rendering timing"
    ),
    FailureCategory.STALE_ELEMENT.value: (
        "Add explicit waits before re-interacting with the element; "
        "inspect page navigation or dynamic DOM reload events"
    ),
    FailureCategory.TIMEOUT.value: (
        "Inspect synchronization waits and retry strategy; "
        "check for race conditions, slow service responses, or flaky async behavior"
    ),
    FailureCategory.ASSERTION.value: (
        "Compare expected vs actual values in failure messages; "
        "verify test data setup, teardown, and application state preconditions"
    ),
    FailureCategory.NULL_POINTER.value: (
        "Inspect object initialization and dependency injection; "
        "ensure clean test isolation and no shared mutable state between tests"
    ),
    FailureCategory.NETWORK.value: (
        "Inspect service health and network connectivity; "
        "rerun tests after verifying the dependent service is stable"
    ),
    FailureCategory.AUTHENTICATION.value: (
        "Inspect credentials, session configuration, and token expiry; "
        "verify auth service health and test environment secrets"
    ),
    FailureCategory.INFRASTRUCTURE.value: (
        "Inspect environment health and configuration drift; "
        "compare running config against last known-good baseline"
    ),
    FailureCategory.TEST_DATA.value: (
        "Inspect test data fixtures and setup scripts; "
        "ensure database or external state is reset between runs"
    ),
    FailureCategory.PERMISSION.value: (
        "Inspect access control configuration and service-to-service permission grants; "
        "check role bindings in CI/CD environment"
    ),
    FailureCategory.CONFIGURATION.value: (
        "Inspect environment variable and config file drift; "
        "diff configuration against the last passing run"
    ),
    FailureCategory.UNKNOWN.value: (
        "Inspect error logs and stack traces in the test detail; "
        "attempt to reproduce in isolation to narrow the cause"
    ),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _severity(count: int) -> str:
    for threshold, label in _SEVERITY:
        if count >= threshold:
            return label
    return "low"


def _confidence(count: int, *, has_signature: bool) -> str:
    """Qualitative confidence based on grouping strength."""
    if has_signature and count >= 3:
        return "high"
    if has_signature:
        return "medium"
    if count >= 3:
        return "medium"
    return "low"


def _incident_id(run_id: str, group_key: str) -> str:
    """Return a stable 16-char hex ID for the (run, group) pair."""
    return hashlib.sha256(f"{run_id}:{group_key}".encode()).hexdigest()[:16]


def _short_error_type(error_type: str | None) -> str | None:
    """Return just the simple class name from a fully-qualified exception string."""
    if not error_type:
        return None
    return error_type.split(".")[-1].split("$")[-1]


def _incident_title(
    category: FailureCategory,
    error_type: str | None,
    components: list[str],
) -> str:
    short = _short_error_type(error_type)
    location = components[0] if components else None
    if short and location:
        return f"{short} in {location}"
    if short:
        return short
    if location:
        return f"{category.label} failures in {location}"
    return f"{category.label} failures"


def _build_evidence(
    tests: list[TestCaseRow],
    category: FailureCategory,
    *,
    has_signature: bool,
) -> list[str]:
    """Build a concise list of evidence bullet points for the incident."""
    bullets: list[str] = []
    count = len(tests)

    if has_signature and count > 1:
        sig = tests[0].fingerprint or ""
        bullets.append(
            f"{count} tests share the identical failure signature `{sig[:8]}…`"
        )
    elif count > 1:
        bullets.append(f"{count} tests failed with the same error type")

    error_types = {t.error_type for t in tests if t.error_type}
    if len(error_types) == 1:
        bullets.append(f"All failures raise `{next(iter(error_types))}`")

    suites = sorted({t.suite for t in tests if t.suite})
    if len(suites) == 1:
        bullets.append(f"All failures are isolated to suite: {suites[0]}")
    elif 1 < len(suites) <= 3:
        bullets.append(f"Failures span suites: {', '.join(suites)}")
    elif len(suites) > 3:
        bullets.append(f"Failures span {len(suites)} different suites")

    retried = [t for t in tests if t.retry_count > 0]
    if retried:
        bullets.append(
            f"{len(retried)} of {count} test(s) were retried — "
            "suggests transient or environment-sensitive failure"
        )

    if category in (FailureCategory.NETWORK, FailureCategory.INFRASTRUCTURE):
        bullets.append(
            "Multiple unrelated tests affected — likely a shared service "
            "or environment dependency rather than individual test logic"
        )

    if not bullets:
        bullets.append(f"Test failed with a {category.label} pattern")

    return bullets


def _build_incident(
    group_key: str,
    tests: list[TestCaseRow],
    run_id: str,
    *,
    has_signature: bool,
) -> IncidentSummary:
    rep = tests[0]
    category = categorize_failure(error_type=rep.error_type, message=rep.message)
    components = sorted(
        {t.suite for t in tests if t.suite}
        | {t.feature for t in tests if t.feature}
    )
    rep_message = (
        (rep.message or "").splitlines()[0][:200]
        if rep.message
        else None
    )
    return IncidentSummary(
        incident_id=_incident_id(run_id, group_key),
        run_id=run_id,
        title=_incident_title(category, rep.error_type, components),
        severity=_severity(len(tests)),
        impacted_test_count=len(tests),
        impacted_tests=[t.name for t in tests],
        probable_root_cause=_ROOT_CAUSE[category.value],
        root_cause_category=category.value,
        confidence=_confidence(len(tests), has_signature=has_signature),
        evidence=_build_evidence(tests, category, has_signature=has_signature),
        recommended_action=_ACTION[category.value],
        signature=rep.fingerprint if has_signature else group_key,
        error_type=rep.error_type,
        representative_message=rep_message,
        representative_stack_trace=rep.stack_trace or None,
        components=components,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_incidents(
    run_id: str,
    db_path: str | Path | None,
    *,
    project: str | None = None,  # reserved for future cross-run enrichment
) -> list[IncidentSummary]:
    """Build :class:`~qara.models.incident.IncidentSummary` objects for *run_id*.

    Reads persisted failure data from the SQLite database; no live parsing or
    LLM calls are performed.

    Args:
        run_id:   Run to analyse.
        db_path:  Path to the SQLite database (``None`` → default location).
        project:  Reserved for future cross-run context enrichment.

    Returns:
        List of incidents sorted by *impacted_test_count* descending, so the
        most impactful incident appears first.
    """
    from qara.db.repository import RunRepository
    from qara.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        failed = repo.get_test_cases_for_run(run_id, status="failed")
        broken = repo.get_test_cases_for_run(run_id, status="broken")
        tests: list[TestCaseRow] = failed + broken
    finally:
        conn.close()

    if not tests:
        return []

    # ── Group 1: by fingerprint (strongest signal) ──────────────────────────
    by_fp: dict[str, list[TestCaseRow]] = {}
    no_fp: list[TestCaseRow] = []
    for t in tests:
        if t.fingerprint:
            by_fp.setdefault(t.fingerprint, []).append(t)
        else:
            no_fp.append(t)

    # ── Group 2: fingerprint-less → by error_type ───────────────────────────
    by_et: dict[str, list[TestCaseRow]] = {}
    ungrouped: list[TestCaseRow] = []
    for t in no_fp:
        if t.error_type:
            by_et.setdefault(t.error_type, []).append(t)
        else:
            ungrouped.append(t)

    # ── Assemble ────────────────────────────────────────────────────────────
    incidents: list[IncidentSummary] = []

    for fp, group in by_fp.items():
        incidents.append(_build_incident(fp, group, run_id, has_signature=True))

    for et, group in by_et.items():
        incidents.append(
            _build_incident(f"et:{et}", group, run_id, has_signature=False)
        )

    if ungrouped:
        incidents.append(
            _build_incident("ungrouped", ungrouped, run_id, has_signature=False)
        )

    # Sort: most impactful first
    incidents.sort(key=lambda i: i.impacted_test_count, reverse=True)
    return incidents
