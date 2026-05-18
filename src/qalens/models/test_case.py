"""Test case and step models for QaLens.

``TestCaseResult`` is the central unit of analysis in QaLens — one instance per
test that appeared in the report, regardless of status. ``StepResult``
represents a single execution step within a test case.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from qalens.models.artifact_ref import ArtifactRef
from qalens.models.attachment import Attachment
from qalens.models.failure import FailureInfo


class TestStatus(str, Enum):
    """Normalised test execution status.

    QaLens maps every source-specific status string (Extent's ``pass``/``fail``,
    Allure's ``passed``/``failed``/``broken``, etc.) onto this set.

    Attributes:
        PASSED: The test completed without assertion failures.
        FAILED: The test failed with an assertion or unexpected exception.
        BROKEN: The test encountered an unexpected error unrelated to an
            assertion (used for distinction where the source supports it;
            maps to ``FAILED`` in output summaries by default).
        SKIPPED: The test was explicitly skipped.
        PENDING: The test is defined but has not yet been executed.
        UNKNOWN: Status could not be determined from the report.
    """

    PASSED = "passed"
    FAILED = "failed"
    BROKEN = "broken"
    SKIPPED = "skipped"
    PENDING = "pending"
    UNKNOWN = "unknown"

    @property
    def is_failing(self) -> bool:
        """Return ``True`` if this status represents a failure or breakage."""
        return self in (TestStatus.FAILED, TestStatus.BROKEN)

    @classmethod
    def from_string(cls, value: str) -> "TestStatus":
        """Map a raw status string from any supported report format.

        Args:
            value: Raw status string from Extent, Allure, or similar tool.

        Returns:
            The corresponding ``TestStatus`` member, or ``UNKNOWN`` if the
            value is not recognised.
        """
        normalised = value.strip().lower()
        mapping: dict[str, "TestStatus"] = {
            # Allure
            "passed": cls.PASSED,
            "failed": cls.FAILED,
            "broken": cls.BROKEN,
            "skipped": cls.SKIPPED,
            "pending": cls.PENDING,
            # Extent
            "pass": cls.PASSED,
            "fail": cls.FAILED,
            "skip": cls.SKIPPED,
            "warning": cls.BROKEN,
            "info": cls.PASSED,
        }
        return mapping.get(normalised, cls.UNKNOWN)


class StepResult(BaseModel):
    """A single step within a test case execution.

    Steps correspond to ``nodes`` in Extent reports and ``steps`` in Allure
    reports. They may be nested; this model represents a flattened view.

    Attributes:
        step_id: Unique identifier within the test run. Auto-generated if
            not present in the source report.
        name: Step description or name.
        status: Execution status of this step.
        started_at: Step start time, if recorded.
        finished_at: Step end time, if recorded.
        duration_ms: Duration in milliseconds derived from start/end or
            directly from the report.
        log_output: Any textual log lines captured during this step.
        attachments: Files attached during this step.
        failure: Failure details if this step failed.
        depth: Nesting depth (0 = top-level step, 1 = child step, etc.).
    """

    step_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique step identifier within the run.",
    )
    name: str = Field(..., description="Step description or action name.")
    status: TestStatus = Field(
        default=TestStatus.UNKNOWN,
        description="Execution status of this step.",
    )
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None, ge=0)
    log_output: str | None = Field(
        default=None,
        description="Text log captured during this step.",
    )
    attachments: list[Attachment] = Field(default_factory=list)
    failure: FailureInfo | None = Field(
        default=None,
        description="Failure detail if this step did not pass.",
    )
    depth: int = Field(
        default=0,
        ge=0,
        description="Nesting depth within the step hierarchy.",
    )

    model_config = {"frozen": False}


class TestCaseResult(BaseModel):
    """A single test case result extracted from a report.

    This is the canonical unit of analysis in QaLens. One ``TestCaseResult``
    is created per test that appeared in the source report, regardless of
    whether it passed or failed.

    Attributes:
        test_id: A stable identifier for deduplication and history tracking.
            Parsers should derive this from the test class + method name
            when available, falling back to a UUID.
        name: The display name of the test case.
        full_name: Fully qualified name including class/package if available
            (e.g. ``com.example.LoginTest#testValidLogin``).
        status: Final execution status.
        suite: The suite or class name this test belongs to.
        feature: Feature or epic label, if present in the report.
        story: Story or sub-feature label, if present.
        owner: Author or assigned owner, if available.
        tags: List of category, label, or tag strings attached to this test.
        parameters: Key-value test parameters (for parameterised tests).
        links: Issue tracker or documentation links associated with this test.
        started_at: Test start timestamp.
        finished_at: Test end timestamp.
        duration_ms: Total test duration in milliseconds.
        steps: Ordered list of execution steps.
        failure: Failure details if the test did not pass. ``None`` for
            passed/skipped tests.
        attachments: Files attached at the test level.
        retry_count: Number of times this test was retried before the
            recorded result. 0 = first attempt.
        is_retry: ``True`` if this record itself is a retry attempt (i.e.
            not the last/final attempt).
        flaky_score: Float in [0, 1] set by ``FlakyScorer`` during analysis.
            ``None`` until computed.
        source_format: The report format this was parsed from
            (e.g. ``"allure"``, ``"extent"``).
        raw_id: The original ID string from the source report, for tracing.
    """

    test_id: str = Field(
        ...,
        description="Stable identifier for deduplication and history linkage.",
    )
    name: str = Field(..., description="Display name of the test case.")
    full_name: str | None = Field(
        default=None,
        description="Fully qualified name with class/package if available.",
    )
    status: TestStatus = Field(..., description="Final execution status.")
    suite: str | None = Field(
        default=None,
        description="Suite or class name this test belongs to.",
    )
    feature: str | None = Field(default=None, description="Feature or epic label.")
    story: str | None = Field(default=None, description="Story or sub-feature label.")
    owner: str | None = Field(default=None, description="Assigned author or owner.")
    tags: list[str] = Field(
        default_factory=list,
        description="Category, label, or tag strings.",
    )
    parameters: dict[str, str] = Field(
        default_factory=dict,
        description="Test parameter key-value pairs for parameterised tests.",
    )
    links: list[str] = Field(
        default_factory=list,
        description="Issue tracker or documentation URLs.",
    )
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None, ge=0)
    steps: list[StepResult] = Field(
        default_factory=list,
        description="Ordered execution steps.",
    )
    failure: FailureInfo | None = Field(
        default=None,
        description="Failure details; None for passing/skipped tests.",
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        description="Files attached at the test level.",
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of retries before this result.",
    )
    is_retry: bool = Field(
        default=False,
        description="True if this record is itself a non-final retry attempt.",
    )
    flaky_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Flaky probability [0,1]; set by FlakyScorer.",
    )
    source_format: str | None = Field(
        default=None,
        description="Report format this result was parsed from.",
    )
    raw_id: str | None = Field(
        default=None,
        description="Original ID from the source report, for tracing.",
    )
    raw_artifact_refs: list[ArtifactRef] = Field(
        default_factory=list,
        exclude=True,
        description=(
            "Raw artifact references produced by the parser. "
            "Consumed by ArtifactIngestionPolicy during ingest; never serialized."
        ),
    )

    model_config = {"frozen": False}

    @property
    def is_failed(self) -> bool:
        """Return ``True`` if the test has a failing status."""
        return self.status.is_failing

    @property
    def was_retried(self) -> bool:
        """Return ``True`` if the test was attempted more than once."""
        return self.retry_count > 0

    @property
    def passed_on_retry(self) -> bool:
        """Return ``True`` if the final status is ``PASSED`` after retries.

        This is a strong signal for flakiness.
        """
        return self.status == TestStatus.PASSED and self.retry_count > 0


# Resolve forward references after both models are defined.
StepResult.model_rebuild()
TestCaseResult.model_rebuild()
