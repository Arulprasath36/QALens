"""Extraction warning model for QARA.

When a parser encounters a missing, malformed, or unexpected field during
report extraction, it records an ``ExtractionWarning`` instead of raising
an exception. This ensures that partial data is always preferred over a
complete failure, and that callers can inspect what was degraded.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WarningSeverity(str, Enum):
    """Severity level for an extraction warning.

    Attributes:
        LOW: The missing field is optional and unlikely to affect analysis.
        MEDIUM: The missing field may reduce insight quality for the
            affected test, but analysis can proceed.
        HIGH: The missing field is significant and may cause the affected
            test to be analysed with substantially reduced accuracy.
        CRITICAL: A required structural field is missing; the test or run
            record may be unusable.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExtractionWarning(BaseModel):
    """A warning raised by a parser when a field cannot be fully extracted.

    Warnings are collected in ``TestRun.warnings`` so that consumers can
    inspect extraction quality without interrupting analysis.

    Attributes:
        field: Dotted path to the field that could not be populated
            (e.g. ``"FailureInfo.stack_trace"``).
        test_name: The name of the test case the warning relates to,
            or ``None`` for run-level warnings.
        reason: A human-readable description of why the field is missing
            or malformed.
        severity: How significantly this warning affects insight quality.
        raw_value: The raw string fragment that was encountered, if any,
            for debugging purposes.
    """

    field: str = Field(
        ...,
        description="Dotted field path that could not be populated, e.g. 'FailureInfo.stack_trace'.",
    )
    test_name: str | None = Field(
        default=None,
        description="Name of the affected test case, or None for run-level warnings.",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation of why extraction degraded.",
    )
    severity: WarningSeverity = Field(
        default=WarningSeverity.LOW,
        description="Impact level of this warning on insight quality.",
    )
    raw_value: str | None = Field(
        default=None,
        description="The raw value fragment encountered, for debugging.",
    )

    model_config = {"frozen": True}

    def __str__(self) -> str:
        """Return a concise one-line string representation."""
        test_part = f" [{self.test_name}]" if self.test_name else ""
        return f"[{self.severity.value.upper()}]{test_part} {self.field}: {self.reason}"
