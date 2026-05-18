"""Failure information model for QaLens.

``FailureInfo`` captures everything known about why a test failed —
the raw error type, message, and stack trace as extracted from the report,
plus normalized/enriched versions added by the signature engine.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FailureInfo(BaseModel):
    """All information pertaining to a single test failure.

    The ``error_type``, ``message``, and ``stack_trace`` fields are populated
    directly from the source report (Extent or Allure) and are never altered.

    The ``normalized_*`` fields and ``failure_signature`` are populated by
    ``qalens.analyzers.signatures.SignatureEngine`` during the analysis phase.
    They are ``None`` until the signature engine has processed this failure.

    Attributes:
        error_type: The exception class or error category as extracted from
            the report (e.g. ``"org.openqa.selenium.NoSuchElementException"``).
        message: The full error message string, unmodified.
        stack_trace: The full stack trace text as extracted, or ``None`` if
            not available.
        normalized_message: The message after removing dynamic noise such as
            timestamps, UUIDs, and session IDs. Set by the signature engine.
        normalized_stack_trace: The stack trace after normalizing line numbers,
            addresses, and dynamic identifiers. Set by the signature engine.
        failure_signature: A stable short hash uniquely identifying the
            "shape" of this failure for grouping purposes. Set by the
            signature engine.
        failed_step: The name or description of the test step that was
            executing when the failure occurred, if available.
    """

    error_type: str | None = Field(
        default=None,
        description="Exception class or error category from the report.",
    )
    message: str | None = Field(
        default=None,
        description="Full error message string, unmodified.",
    )
    stack_trace: str | None = Field(
        default=None,
        description="Full stack trace text as extracted from the report.",
    )
    normalized_message: str | None = Field(
        default=None,
        description="Message with dynamic noise removed. Set by SignatureEngine.",
    )
    normalized_stack_trace: str | None = Field(
        default=None,
        description="Stack trace with dynamic identifiers removed. Set by SignatureEngine.",
    )
    failure_signature: str | None = Field(
        default=None,
        description=(
            "Stable 16-character hex hash identifying the failure shape. "
            "Two failures with the same signature are considered the same "
            "root cause. Set by SignatureEngine."
        ),
    )
    failed_step: str | None = Field(
        default=None,
        description="Name of the step that was executing when the failure occurred.",
    )

    model_config = {"frozen": False}  # Mutable: signature engine writes normalized fields.

    def has_stack_trace(self) -> bool:
        """Return ``True`` if a non-empty stack trace is present."""
        return bool(self.stack_trace and self.stack_trace.strip())

    def has_signature(self) -> bool:
        """Return ``True`` if the failure signature has been computed."""
        return self.failure_signature is not None

    def summary_line(self, max_length: int = 120) -> str:
        """Return a short one-line summary of the failure for display.

        Combines error type and the first line of the message.

        Args:
            max_length: Maximum length of the returned string.

        Returns:
            A truncated summary string.
        """
        parts: list[str] = []
        if self.error_type:
            parts.append(self.error_type)
        if self.message:
            first_line = self.message.splitlines()[0].strip()
            parts.append(first_line)
        result = ": ".join(parts) if parts else "(no failure detail)"
        return result[:max_length] + ("…" if len(result) > max_length else "")
