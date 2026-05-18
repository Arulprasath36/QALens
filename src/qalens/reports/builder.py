"""Build deterministic QaLens shareable report payloads from SQLite data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from qalens.analyzers.categorizer import categorize_failure
from qalens.analyzers.decision import build_decision_summary
from qalens.analyzers.flaky import FlakyClassification, FlakyScorer
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.reports.model import (
    FailureGroupSummary,
    ImpactSummary,
    RunComparisonSummary,
    RunSummary,
    ShareableReport,
    StabilitySummary,
    TestSummary,
)

if TYPE_CHECKING:
    from pathlib import Path

    from qalens.analyzers.flaky import FlakyResult
    from qalens.db.models import RunRow, TestCaseRow


def build_report(
    *,
    db_path: str | Path | None = None,
    project: str | None = None,
    run_id: str | None = None,
    window: int = 10,
    min_runs: int = 2,
    limit: int = 10,
) -> ShareableReport:
    """Build a deterministic shareable report from stored QaLens data.

    Args:
        db_path: SQLite database path. ``None`` uses QaLens's default DB.
        project: Optional project filter. If omitted, the report scopes itself
            to the latest run's project.
        run_id: Optional run id, ``latest``, or run sequence number.
        window: Recent run count used for scoped failure groups.
        min_runs: Minimum history depth for stability/flaky sections.
        limit: Maximum rows per report section.

    Returns:
        A complete :class:`ShareableReport`.

    Raises:
        ValueError: If no matching runs exist.

    """
    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        latest = _resolve_run(repo, run_id=run_id, project=project)
        effective_project = project or latest.project
        latest_tests = repo.get_test_cases_for_run(latest.run_id, include_details=False)
        previous = _previous_comparable_run(repo, latest, project=effective_project)
        previous_tests = (
            repo.get_test_cases_for_run(previous.run_id, include_details=False)
            if previous
            else []
        )
        recent_runs = repo.list_runs(project=effective_project, limit=max(1, window))
        recent_run_ids = [run.run_id for run in recent_runs]

        scorer = FlakyScorer(conn)
        stability = scorer.get_all(project=effective_project, min_runs=min_runs)
        flaky = [
            _stability_summary(item)
            for item in stability
            if item.classification == FlakyClassification.FLAKY
        ][:limit]
        risk_tests = [_stability_summary(item) for item in _risk_candidates(stability)][:limit]

        comparison = (
            _build_comparison(previous, latest, previous_tests, latest_tests)
            if previous
            else None
        )
        failure_groups = [
            _failure_group_summary(group)
            for group in repo.get_failure_groups(
                project=effective_project,
                run_ids=recent_run_ids,
                limit=limit,
            )
        ]
        suite_impacts = _impact_summaries(latest_tests, attr="suite")[:limit]
        owner_impacts = _impact_summaries(latest_tests, attr="owner")[:limit]

        latest_summary = _run_summary(latest)
        decision = build_decision_summary(
            db_path=str(db_path) if db_path is not None else None,
            project=effective_project,
            run_id=latest.run_id,
            window=window,
        )
        recommendations = list(decision.get("executive_summary") or []) or _recommendations(
            latest_summary=latest_summary,
            comparison=comparison,
            failure_groups=failure_groups,
            flaky_tests=flaky,
            suite_impacts=suite_impacts,
        )
        return ShareableReport(
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            scope_label=_scope_label(effective_project, latest),
            project=effective_project,
            latest_run=latest_summary,
            comparison=comparison,
            failure_groups=failure_groups,
            flaky_tests=flaky,
            risk_tests=risk_tests,
            suite_impacts=suite_impacts,
            owner_impacts=owner_impacts,
            recommendations=recommendations,
            executive_summary=list(decision.get("executive_summary") or []),
            trend_intelligence=list(decision.get("trend_intelligence") or []),
            fix_first=list(decision.get("fix_first") or []),
        )
    finally:
        conn.close()


def _resolve_run(
    repo: RunRepository,
    *,
    run_id: str | None,
    project: str | None,
) -> RunRow:
    if run_id and run_id.lower() != "latest":
        run = repo.get_run(run_id)
        if run is None and run_id.isdigit():
            run = repo.get_run_by_sequence(int(run_id), project=project)
        if run is None:
            raise ValueError(f"No run found for {run_id!r}.")
        if project is not None and run.project != project:
            raise ValueError(f"Run {run_id!r} does not belong to project {project!r}.")
        return run

    runs = repo.list_runs(project=project, limit=1)
    if not runs:
        suffix = f" for project {project!r}" if project else ""
        raise ValueError(f"No QaLens runs found{suffix}.")
    return runs[0]


def _previous_comparable_run(
    repo: RunRepository,
    latest: RunRow,
    *,
    project: str | None,
) -> RunRow | None:
    candidates = repo.list_runs(project=project, limit=500)
    ordered = sorted(
        candidates,
        key=lambda run: (run.run_sequence or 0, run.started_at or 0),
        reverse=True,
    )
    for candidate in ordered:
        if candidate.run_id == latest.run_id:
            continue
        if latest.project and candidate.project and candidate.project != latest.project:
            continue
        if candidate.run_sequence < latest.run_sequence:
            return candidate
        if (
            candidate.run_sequence == latest.run_sequence
            and latest.started_at is not None
            and candidate.started_at is not None
            and candidate.started_at < latest.started_at
        ):
            return candidate
    return None


def _run_summary(run: RunRow) -> RunSummary:
    total = int(run.total_tests or 0)
    passed = int(run.passed_count or 0)
    failed = int(run.failed_count or 0)
    skipped = int(run.skipped_count or 0)
    return RunSummary(
        run_id=run.run_id,
        run_sequence=run.run_sequence,
        project=run.project,
        report_format=run.report_format,
        environment=run.environment,
        branch=run.branch,
        build_number=run.build_number,
        started_at=run.started_at,
        total_ms=run.total_ms,
        total_tests=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate=(passed / total) if total else None,
    )


def _test_summary(test: TestCaseRow) -> TestSummary:
    return TestSummary(
        name=test.name,
        canonical_name=test.canonical_name,
        status=test.status,
        suite=test.suite,
        owner=test.owner,
        duration_ms=test.duration_ms,
        message=test.message,
        fingerprint=test.fingerprint,
    )


def _is_failure(status: str) -> bool:
    return status in {"failed", "broken"}


def _build_comparison(
    baseline: RunRow,
    target: RunRow,
    baseline_tests: list[TestCaseRow],
    target_tests: list[TestCaseRow],
) -> RunComparisonSummary:
    baseline_by_name = {test.canonical_name: test for test in baseline_tests}
    new_failures: list[TestSummary] = []
    recovered: list[TestSummary] = []
    persistent: list[TestSummary] = []
    newly_skipped: list[TestSummary] = []

    for test in target_tests:
        previous = baseline_by_name.get(test.canonical_name)
        previous_status = previous.status if previous else None
        if _is_failure(test.status):
            if previous_status is None or previous_status in {"passed", "skipped"}:
                new_failures.append(_test_summary(test))
            elif _is_failure(previous_status):
                persistent.append(_test_summary(test))
        elif test.status == "passed" and previous_status and _is_failure(previous_status):
            recovered.append(_test_summary(test))
        elif test.status == "skipped" and previous_status != "skipped":
            newly_skipped.append(_test_summary(test))

    return RunComparisonSummary(
        baseline=_run_summary(baseline),
        target=_run_summary(target),
        new_failures=new_failures,
        recovered=recovered,
        persistent_failures=persistent,
        newly_skipped=newly_skipped,
    )


def _failure_group_summary(group: dict[str, Any]) -> FailureGroupSummary:
    category = categorize_failure(
        error_type=group.get("error_type"),
        message=group.get("message"),
    )
    return FailureGroupSummary(
        fingerprint=str(group["fingerprint"]),
        category=category.label,
        error_type=group.get("error_type"),
        message=group.get("message"),
        occurrence_count=int(group.get("occurrence_count") or 0),
        affected_tests=int(group.get("affected_tests") or 0),
        affected_runs=int(group.get("affected_runs") or 0),
        first_seen_seq=group.get("first_seen_seq"),
        last_seen_seq=group.get("last_seen_seq"),
        affected_canonical_names=list(group.get("affected_canonical_names") or []),
        bug_links=[dict(link) for link in group.get("bug_links") or []],
    )


def _stability_summary(item: FlakyResult) -> StabilitySummary:
    return StabilitySummary(
        name=item.display_name,
        canonical_name=item.canonical_name,
        owner=item.owner,
        run_count=item.run_count,
        pass_rate=item.pass_rate,
        flip_score=item.flip_score,
        classification=item.classification.label,
        sparkline=item.sparkline,
        current_streak=item.current_streak,
    )


def _risk_candidates(stability: list[FlakyResult]) -> list[FlakyResult]:
    def score(item: FlakyResult) -> tuple[float, int, int]:
        failing_now = 1 if item.current_streak < 0 else 0
        failure_rate = item.fail_count / item.run_count if item.run_count else 0.0
        return (
            (failure_rate * 0.5) + (item.flip_score * 0.35) + (failing_now * 0.15),
            item.fail_count,
            item.run_count,
        )

    candidates = [
        item for item in stability
        if item.current_streak < 0 or item.flip_score >= 0.25 or item.pass_rate < 0.75
    ]
    return sorted(candidates, key=score, reverse=True)


def _impact_summaries(tests: list[TestCaseRow], *, attr: str) -> list[ImpactSummary]:
    rows: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "failed": 0, "skipped": 0})
    fallback = "Unassigned" if attr == "owner" else "Unknown suite"
    for test in tests:
        name = getattr(test, attr) or fallback
        rows[name]["total"] += 1
        if _is_failure(test.status):
            rows[name]["failed"] += 1
        if test.status == "skipped":
            rows[name]["skipped"] += 1

    impacts = [
        ImpactSummary(
            name=name,
            total=values["total"],
            failed=values["failed"],
            skipped=values["skipped"],
            pass_rate=(
                (values["total"] - values["failed"] - values["skipped"]) / values["total"]
                if values["total"]
                else None
            ),
        )
        for name, values in rows.items()
    ]
    return sorted(
        impacts,
        key=lambda item: (item.failed, item.total, item.name.lower()),
        reverse=True,
    )


def _recommendations(
    *,
    latest_summary: RunSummary,
    comparison: RunComparisonSummary | None,
    failure_groups: list[FailureGroupSummary],
    flaky_tests: list[StabilitySummary],
    suite_impacts: list[ImpactSummary],
) -> list[str]:
    recommendations: list[str] = []
    if comparison and comparison.new_failures:
        recommendations.append(
            f"Triage {len(comparison.new_failures)} new failure(s) before recurring failures."
        )
    if failure_groups:
        top = failure_groups[0]
        recommendations.append(
            f"Start with fingerprint {top.fingerprint[:12]} because it affects "
            f"{top.affected_tests} test(s) across {top.affected_runs} run(s)."
        )
    if suite_impacts and suite_impacts[0].failed:
        recommendations.append(
            f"Focus first on {suite_impacts[0].name}; it has "
            f"{suite_impacts[0].failed} failing test(s) in the latest run."
        )
    if flaky_tests:
        recommendations.append(
            f"Review or quarantine the top {min(5, len(flaky_tests))} flaky test(s)."
        )
    if latest_summary.failed == 0:
        recommendations.append("No failed tests were found in the latest run.")
    if not recommendations:
        recommendations.append("No high-priority triage actions were detected.")
    return recommendations


def _scope_label(project: str | None, latest: RunRow) -> str:
    project_label = project or "All projects"
    return f"{project_label} - latest run #{latest.run_sequence}"
