"""Lightweight data-transfer objects for the QARA database layer.

Extracted from :mod:`ari.db.repository` for cohesion.
All public names are re-exported from :mod:`ari.db.repository` for
backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunRow:
    """Lightweight view of a ``runs`` table row."""

    run_id: str
    project: str | None
    suite: str | None
    report_format: str
    report_version: str | None
    source_path: str
    environment: str | None
    branch: str | None
    build_number: str | None
    started_at: float | None
    finished_at: float | None
    total_ms: int | None
    ingested_at: float
    run_sequence: int
    total_tests: int | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    skipped_count: int | None = None


@dataclass
class TestCaseRow:
    """Lightweight view of a ``test_cases`` joined with its failure."""

    tc_id: str
    run_id: str
    name: str
    canonical_name: str
    status: str
    duration_ms: int | None
    suite: str | None
    feature: str | None
    story: str | None
    owner: str | None
    tags: list[str]
    is_retry: bool
    retry_count: int
    # failure fields (None if no failure row)
    error_type: str | None
    message: str | None
    stack_trace: str | None
    fingerprint: str | None
    failed_step: str | None
    attachments: list[dict] = field(default_factory=list)


@dataclass
class TestHistoryEntry:
    """One entry in a test's cross-run history."""

    run_id: str
    run_sequence: int
    started_at: float | None
    status: str
    fingerprint: str | None
    error_type: str | None = None
    message: str | None = None
    stack_trace: str | None = None
