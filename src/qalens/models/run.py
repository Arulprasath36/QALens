"""Test run models for QA Lens.

``TestRun`` is the top-level canonical object produced by every parser.
It contains run-level metadata and the full list of test case results.
Analyzers consume ``TestRun`` objects exclusively.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field

from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.models.warnings import ExtractionWarning


class RunMetadata(BaseModel):
    """Metadata about a test execution run.

    Attributes:
        run_id: Auto-generated stable identifier for this run.
        report_format: The source report format (``"allure"`` or ``"extent"``).
        report_version: Version string of the report generator, if detectable.
        report_path: Absolute path to the report root on disk.
        project: Project or application name, if present in the report.
        environment: Environment label (``"staging"``, ``"prod"``, etc.)
            extracted from the report or configuration.
        branch: VCS branch name, if recorded.
        build_number: CI build number, if recorded.
        execution_host: Hostname or CI node, if available.
        started_at: Earliest test start time across all tests.
        finished_at: Latest test finish time across all tests.
        total_duration_ms: Total wall-clock duration of the entire run.
        custom_fields: Additional key-value metadata extracted from the
            report that does not map to a standard field.
    """

    run_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable unique identifier for this run.",
    )
    report_format: str = Field(
        ...,
        description="Source report format identifier, e.g. 'allure' or 'extent'.",
    )
    report_version: str | None = Field(
        default=None,
        description="Version string of the report generator.",
    )
    report_path: str = Field(
        ...,
        description="Absolute path to the report root directory or file.",
    )
    project: str | None = Field(
        default=None,
        description="Project or application name from the report.",
    )
    environment: str | None = Field(
        default=None,
        description="Target environment label (e.g. 'staging', 'prod').",
    )
    branch: str | None = Field(
        default=None,
        description="VCS branch name if recorded in the report.",
    )
    build_number: str | None = Field(
        default=None,
        description="CI build number if recorded.",
    )
    execution_host: str | None = Field(
        default=None,
        description="Hostname or CI node identifier.",
    )
    started_at: datetime | None = Field(
        default=None,
        description="Earliest test start time across all tests in this run.",
    )
    finished_at: datetime | None = Field(
        default=None,
        description="Latest test finish time across all tests in this run.",
    )
    total_duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Total wall-clock duration in milliseconds.",
    )
    custom_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Additional metadata that does not map to standard fields.",
    )

    model_config = {"frozen": False}


class TestRun(BaseModel):
    """The canonical top-level object produced by every QA Lens parser.

    Every parser MUST return a ``TestRun``. It contains the run metadata
    and the complete list of test case results. Analyzers receive a
    ``TestRun`` and produce an ``AnalysisSummary``.

    Attributes:
        metadata: Run-level metadata extracted from the report.
        test_cases: All test case results, including passed, failed,
            skipped, and broken tests.
        warnings: Extraction warnings emitted by the parser for fields
            that could not be fully populated.
    """

    metadata: RunMetadata = Field(
        ...,
        description="Run-level metadata describing the execution context.",
    )
    test_cases: list[TestCaseResult] = Field(
        default_factory=list,
        description="All test case results from this run.",
    )
    warnings: list[ExtractionWarning] = Field(
        default_factory=list,
        description="Warnings from the parser for missing or malformed fields.",
    )

    model_config = {"frozen": False}

    # ------------------------------------------------------------------
    # Computed convenience properties
    # ------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def total_count(self) -> int:
        """Total number of test cases in this run."""
        return len(self.test_cases)

    @computed_field  # type: ignore[misc]
    @property
    def passed_count(self) -> int:
        """Number of tests with ``PASSED`` status."""
        return sum(1 for t in self.test_cases if t.status == TestStatus.PASSED)

    @computed_field  # type: ignore[misc]
    @property
    def failed_count(self) -> int:
        """Number of tests with ``FAILED`` or ``BROKEN`` status."""
        return sum(1 for t in self.test_cases if t.status.is_failing)

    @computed_field  # type: ignore[misc]
    @property
    def skipped_count(self) -> int:
        """Number of tests with ``SKIPPED`` status."""
        return sum(1 for t in self.test_cases if t.status == TestStatus.SKIPPED)

    @computed_field  # type: ignore[misc]
    @property
    def pass_rate(self) -> float:
        """Pass rate as a fraction in [0, 1], or 0.0 for empty runs."""
        if self.total_count == 0:
            return 0.0
        return self.passed_count / self.total_count

    def failed_tests(self) -> list[TestCaseResult]:
        """Return only the tests that have a failing status.

        Returns:
            A list of ``TestCaseResult`` objects with ``FAILED`` or
            ``BROKEN`` status.
        """
        return [t for t in self.test_cases if t.status.is_failing]

    def tests_by_status(self, status: TestStatus) -> list[TestCaseResult]:
        """Return tests filtered by a specific status.

        Args:
            status: The ``TestStatus`` to filter by.

        Returns:
            A list of matching ``TestCaseResult`` objects.
        """
        return [t for t in self.test_cases if t.status == status]

    def has_warnings(self) -> bool:
        """Return ``True`` if any extraction warnings were recorded."""
        return len(self.warnings) > 0
