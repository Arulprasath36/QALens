"""Typed models for deterministic QALens report exports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunSummary:
    """Summary of one ingested run."""

    run_id: str
    run_sequence: int
    project: str | None
    report_format: str
    environment: str | None
    branch: str | None
    build_number: str | None
    started_at: float | None
    total_ms: int | None
    total_tests: int
    passed: int
    failed: int
    skipped: int
    pass_rate: float | None


@dataclass(frozen=True)
class TestSummary:
    """Compact test row used in report sections."""

    name: str
    canonical_name: str
    status: str
    suite: str | None
    owner: str | None
    duration_ms: int | None
    message: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class RunComparisonSummary:
    """Latest-vs-previous run comparison."""

    baseline: RunSummary
    target: RunSummary
    new_failures: list[TestSummary] = field(default_factory=list)
    recovered: list[TestSummary] = field(default_factory=list)
    persistent_failures: list[TestSummary] = field(default_factory=list)
    newly_skipped: list[TestSummary] = field(default_factory=list)


@dataclass(frozen=True)
class FailureGroupSummary:
    """Recurring failure group summarized for a shareable report."""

    fingerprint: str
    category: str
    error_type: str | None
    message: str | None
    occurrence_count: int
    affected_tests: int
    affected_runs: int
    first_seen_seq: int | None
    last_seen_seq: int | None
    affected_canonical_names: list[str] = field(default_factory=list)
    bug_links: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class StabilitySummary:
    """Test stability summary row."""

    name: str
    canonical_name: str
    owner: str | None
    run_count: int
    pass_rate: float
    flip_score: float
    classification: str
    sparkline: str
    current_streak: int


@dataclass(frozen=True)
class ImpactSummary:
    """Suite or owner impact summary."""

    name: str
    total: int
    failed: int
    skipped: int
    pass_rate: float | None


@dataclass(frozen=True)
class ShareableReport:
    """Complete deterministic QALens report payload."""

    generated_at: str
    scope_label: str
    project: str | None
    latest_run: RunSummary
    comparison: RunComparisonSummary | None
    failure_groups: list[FailureGroupSummary]
    flaky_tests: list[StabilitySummary]
    risk_tests: list[StabilitySummary]
    suite_impacts: list[ImpactSummary]
    owner_impacts: list[ImpactSummary]
    recommendations: list[str]
    executive_summary: list[str] = field(default_factory=list)
    trend_intelligence: list[dict[str, object]] = field(default_factory=list)
    fix_first: list[dict[str, object]] = field(default_factory=list)
