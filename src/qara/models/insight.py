"""Insight, cluster, and analysis summary models for ARI.

These models carry the output of the QARA analysis pipeline.
Every insight is fully explainable — it includes the category,
confidence, a human-readable explanation, and concrete evidence
items that drove the classification.
"""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class InsightCategory(str, Enum):
    """The set of root-cause categories QARA can assign to a failure.

    These are the canonical output categories for v1. Every failed test
    receives exactly one category assignment.

    Attributes:
        LIKELY_FLAKY: The test fails intermittently. Signals include
            retry recovery, timeout errors, or historical alternation.
        LIKELY_ENVIRONMENT_ISSUE: The failure originates in infrastructure
            (browser grid, DNS, auth service) rather than the application
            under test or the test script itself.
        LIKELY_TEST_SCRIPT_ISSUE: The failure is caused by the test code
            itself — stale locators, bad selectors, or test utility errors.
        LIKELY_PRODUCT_DEFECT: A stable, reproducible failure tied to a
            business-logic assertion in the application under test.
        LIKELY_TEST_DATA_ISSUE: The failure is caused by missing, stale, or
            incorrect test data (entities, accounts, seed data).
        UNKNOWN: Insufficient signals to assign a confident category.
    """

    LIKELY_FLAKY = "likely_flaky"
    LIKELY_ENVIRONMENT_ISSUE = "likely_environment_issue"
    LIKELY_TEST_SCRIPT_ISSUE = "likely_test_script_issue"
    LIKELY_PRODUCT_DEFECT = "likely_product_defect"
    LIKELY_TEST_DATA_ISSUE = "likely_test_data_issue"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        """Return a formatted display name for console and report output."""
        return self.value.replace("_", " ").title()


class Insight(BaseModel):
    """A single root-cause insight for one test case failure.

    Every ``Insight`` is fully explainable. The ``category``, ``confidence``,
    ``explanation``, and ``evidence`` fields must all be populated by the
    categorizer. QARA never produces silent black-box verdicts.

    Attributes:
        insight_id: Auto-generated unique ID.
        test_id: The ``test_id`` of the ``TestCaseResult`` this insight
            belongs to.
        test_name: Display name of the test, for convenience.
        category: The assigned root-cause category.
        confidence: A float in [0.0, 1.0] representing how confident QARA is
            in this categorization. 0.8+ = high, 0.5–0.79 = medium,
            0.35–0.49 = low, < 0.35 = unknown.
        explanation: A human-readable sentence or short paragraph explaining
            why this category was chosen.
        evidence: A list of concrete signal strings that drove the
            categorization (e.g. ``"passed on retry #2"``,
            ``"stack trace contains WebDriverException: session not created"``).
        related_tests: IDs of other tests that share the same failure
            signature or cluster.
        failure_signature: The signature hash from ``FailureInfo``, if
            available, for cross-referencing clusters.
        rule_name: The name of the categorization rule that produced this
            insight, for traceability.
    """

    insight_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Auto-generated unique identifier for this insight.",
    )
    test_id: str = Field(
        ...,
        description="ID of the TestCaseResult this insight belongs to.",
    )
    test_name: str = Field(
        ...,
        description="Display name of the test case.",
    )
    category: InsightCategory = Field(
        ...,
        description="Root-cause category assigned to this failure.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score in [0, 1]. 0.8+ = high confidence.",
    )
    explanation: str = Field(
        ...,
        description="Human-readable rationale for the category assignment.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete signal strings that drove this classification.",
    )
    related_tests: list[str] = Field(
        default_factory=list,
        description="test_ids of other tests sharing the same signature or cluster.",
    )
    failure_signature: str | None = Field(
        default=None,
        description="Failure signature hash for cross-referencing with clusters.",
    )
    rule_name: str | None = Field(
        default=None,
        description="Name of the categorization rule that produced this insight.",
    )

    model_config = {"frozen": True}

    @field_validator("evidence")
    @classmethod
    def evidence_must_not_be_empty_for_high_confidence(
        cls, v: list[str], info: object
    ) -> list[str]:
        """Warn (via a convention) that high-confidence insights need evidence.

        We don't raise here because the validator context does not easily
        access ``confidence``. Enforcement is done in the categorizer itself.
        """
        return v

    @property
    def confidence_label(self) -> str:
        """Return a human-readable confidence tier label."""
        if self.confidence >= 0.8:
            return "high"
        if self.confidence >= 0.5:
            return "medium"
        if self.confidence >= 0.35:
            return "low"
        return "very low"


class FailureCluster(BaseModel):
    """A group of test failures sharing the same root cause signature.

    Clusters are the primary output of the clustering engine. Each cluster
    has a label and summary describing what all member tests have in common.

    Attributes:
        cluster_id: Unique identifier for this cluster, typically derived
            from the shared failure signature.
        label: A short title for display (e.g.,
            ``"NullPointerException in CheckoutService"``).
        failure_signature: The shared failure signature of all members, or
            ``None`` for fuzzy clusters which don't have a single signature.
        member_test_ids: IDs of all ``TestCaseResult`` objects in this cluster.
        category: The insight category shared by most members of this cluster.
        confidence: Confidence in the cluster's category label.
        rationale: Short explanation of what all members have in common.
        representative_message: The failure message from the most
            representative member, for display.
        representative_stack_trace: The normalised stack trace snippet from
            the representative member.
        size: Number of member tests (derived from ``member_test_ids``).
    """

    cluster_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique cluster identifier.",
    )
    label: str = Field(
        ...,
        description="Short display title for this cluster.",
    )
    failure_signature: str | None = Field(
        default=None,
        description="Shared failure signature hash, or None for fuzzy clusters.",
    )
    member_test_ids: list[str] = Field(
        default_factory=list,
        description="IDs of all TestCaseResult objects in this cluster.",
    )
    category: InsightCategory = Field(
        default=InsightCategory.UNKNOWN,
        description="Dominant insight category across cluster members.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the cluster's category label.",
    )
    rationale: str = Field(
        default="",
        description="Explanation of what cluster members have in common.",
    )
    representative_message: str | None = Field(
        default=None,
        description="Failure message from the most representative member.",
    )
    representative_stack_trace: str | None = Field(
        default=None,
        description="Normalised stack trace snippet from the representative member.",
    )

    model_config = {"frozen": False}

    @property
    def size(self) -> int:
        """Number of test cases in this cluster."""
        return len(self.member_test_ids)


class StatusCounts(BaseModel):
    """Aggregate counts of test statuses in a run.

    Attributes:
        total: Total number of test cases.
        passed: Number of passed tests.
        failed: Number of failed tests (includes broken).
        skipped: Number of skipped tests.
        pending: Number of pending tests.
        pass_rate: Pass rate as a percentage (0–100).
    """

    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)

    model_config = {"frozen": True}

    @property
    def pass_rate(self) -> float:
        """Pass rate as a float in [0, 1]."""
        return self.passed / self.total if self.total > 0 else 0.0

    @property
    def pass_rate_pct(self) -> float:
        """Pass rate as a percentage (0–100)."""
        return round(self.pass_rate * 100, 1)


class CategoryCounts(BaseModel):
    """Counts of failure insights per root-cause category.

    Attributes:
        likely_flaky: Number of tests classified as likely flaky.
        likely_environment_issue: Number classified as environment issues.
        likely_test_script_issue: Number classified as test script issues.
        likely_product_defect: Number classified as product defects.
        likely_test_data_issue: Number classified as test data issues.
        unknown: Number with no confident classification.
    """

    likely_flaky: int = Field(default=0, ge=0)
    likely_environment_issue: int = Field(default=0, ge=0)
    likely_test_script_issue: int = Field(default=0, ge=0)
    likely_product_defect: int = Field(default=0, ge=0)
    likely_test_data_issue: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)

    model_config = {"frozen": True}

    def for_category(self, category: InsightCategory) -> int:
        """Return the count for a given ``InsightCategory``."""
        field_map: dict[InsightCategory, str] = {
            InsightCategory.LIKELY_FLAKY: "likely_flaky",
            InsightCategory.LIKELY_ENVIRONMENT_ISSUE: "likely_environment_issue",
            InsightCategory.LIKELY_TEST_SCRIPT_ISSUE: "likely_test_script_issue",
            InsightCategory.LIKELY_PRODUCT_DEFECT: "likely_product_defect",
            InsightCategory.LIKELY_TEST_DATA_ISSUE: "likely_test_data_issue",
            InsightCategory.UNKNOWN: "unknown",
        }
        return getattr(self, field_map[category], 0)


class AnalysisSummary(BaseModel):
    """The complete output of the QARA analysis pipeline for one test run.

    This is the object consumed by all output writers (JSON, Markdown,
    console). It aggregates the ``TestRun`` statistics, all per-test
    insights, clusters, and recommended actions.

    Attributes:
        run_id: The run ID from ``TestRun.metadata.run_id``.
        report_format: Source report format.
        report_path: Path to the source report.
        status_counts: Aggregate pass/fail/skip counts.
        category_counts: Count of failures per insight category.
        insights: All per-test insights, one per failed test.
        clusters: Failure clusters grouped by signature.
        flaky_test_ids: IDs of tests with a high flaky score.
        recommended_actions: Ordered list of actionable recommendation strings.
        extraction_warning_count: Number of parser warnings in the source run.
        analysis_engine_version: The QARA version that produced this summary.
    """

    run_id: str = Field(..., description="Run ID from the source TestRun.")
    report_format: str = Field(..., description="Source report format identifier.")
    report_path: str = Field(..., description="Path to the source report.")
    status_counts: StatusCounts = Field(
        ...,
        description="Aggregate test status counts.",
    )
    category_counts: CategoryCounts = Field(
        ...,
        description="Failure count broken down by root-cause category.",
    )
    insights: list[Insight] = Field(
        default_factory=list,
        description="All per-test insights, one per failed test case.",
    )
    clusters: list[FailureCluster] = Field(
        default_factory=list,
        description="Failure clusters ordered by size descending.",
    )
    flaky_test_ids: list[str] = Field(
        default_factory=list,
        description="IDs of tests with flaky_score ≥ 0.6.",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Ordered actionable recommendation strings for triage.",
    )
    extraction_warning_count: int = Field(
        default=0,
        ge=0,
        description="Number of extraction warnings from the parser.",
    )
    analysis_engine_version: str = Field(
        default="",
        description="QARA version that produced this summary.",
    )

    model_config = {"frozen": False}

    def top_clusters(self, n: int = 5) -> list[FailureCluster]:
        """Return the top N clusters by member count.

        Args:
            n: Number of clusters to return.

        Returns:
            Up to ``n`` clusters, ordered by size descending.
        """
        return sorted(self.clusters, key=lambda c: c.size, reverse=True)[:n]

    def insights_by_category(
        self, category: InsightCategory
    ) -> list[Insight]:
        """Return all insights for a specific category.

        Args:
            category: The ``InsightCategory`` to filter by.

        Returns:
            A list of matching ``Insight`` objects.
        """
        return [i for i in self.insights if i.category == category]
