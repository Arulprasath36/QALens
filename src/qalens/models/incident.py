"""Incident-centric presentation model for QaLens.

An *incident* is a group of related test failures that share a probable root
cause.  It is the primary triage unit surfaced to the user rather than
individual raw test cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IncidentSummary:
    """Presentation-layer view model for a single detected incident.

    Instances are assembled by :func:`~qalens.analyzers.incidents.assemble_incidents`
    from persisted :class:`~qalens.db.models.TestCaseRow` failure data and are
    never stored in the database — they are computed on-demand per request.
    """

    incident_id: str
    """16-char deterministic hex ID derived from run_id + failure group key."""

    run_id: str
    """The run this incident belongs to."""

    title: str
    """Short human-readable title, e.g. ``"NullPointerException in CheckoutSuite"``."""

    severity: str
    """Qualitative severity: ``"critical"`` | ``"high"`` | ``"medium"`` | ``"low"``."""

    impacted_test_count: int
    """Number of test cases grouped into this incident."""

    impacted_tests: list[str]
    """Display names of the grouped test cases."""

    probable_root_cause: str
    """Short phrase describing the probable root cause."""

    root_cause_category: str
    """:class:`~qalens.analyzers.categorizer.FailureCategory` value string."""

    confidence: str
    """Qualitative confidence: ``"high"`` | ``"medium"`` | ``"low"``."""

    evidence: list[str]
    """Bullet-point evidence bullets that ground the root cause hypothesis."""

    recommended_action: str
    """Concrete, specific recommended action for the on-call SDET."""

    signature: str | None
    """16-char failure fingerprint from :mod:`qalens.analyzers.fingerprint`,
    present when the group is fingerprint-based."""

    error_type: str | None
    """Representative exception/error type for the incident group."""

    representative_message: str | None
    """First line of the representative failure message (≤ 200 chars)."""

    representative_stack_trace: str | None = None
    """Raw stack trace from the representative test case in this incident group."""

    components: list[str] = field(default_factory=list)
    """Distinct suite / feature names for the tests in this incident."""

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain :class:`dict` suitable for JSON serialisation."""
        return {
            "incident_id": self.incident_id,
            "run_id": self.run_id,
            "title": self.title,
            "severity": self.severity,
            "impacted_test_count": self.impacted_test_count,
            "impacted_tests": self.impacted_tests,
            "probable_root_cause": self.probable_root_cause,
            "root_cause_category": self.root_cause_category,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "recommended_action": self.recommended_action,
            "signature": self.signature,
            "error_type": self.error_type,
            "representative_message": self.representative_message,
            "representative_stack_trace": self.representative_stack_trace,
            "components": self.components,
        }
