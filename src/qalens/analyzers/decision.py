"""Decision intelligence synthesis for QaLens.

This module turns existing QaLens facts into a deterministic decision surface:
executive bullets, trend interpretation, and the top actions to fix first.
It intentionally does not call an LLM.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from qalens.analyzers.incidents import assemble_incidents
from qalens.analyzers.predictor import RiskPredictor
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qalens.db.models import RunRow, TestCaseRow

_FAIL_STATUSES = {"failed", "broken"}
_WINDOW_DEFAULT = 5


def build_decision_summary(
    *,
    db_path: str | None = None,
    project: str | None = None,
    run_id: str | None = "latest",
    window: int = _WINDOW_DEFAULT,
) -> dict[str, Any]:
    """Build the decision-intelligence payload for the selected/latest run."""
    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        latest = _resolve_run(repo, project=project, run_id=run_id)
        if latest is None:
            return _empty_payload(project=project, window=window)

        effective_project = project or latest.project
        recent_runs = _recent_runs(repo, latest, project=effective_project, window=window)
        previous = _previous_run(recent_runs, latest)
        latest_tests = repo.get_test_cases_for_run(latest.run_id, include_details=False)
        previous_tests = (
            repo.get_test_cases_for_run(previous.run_id, include_details=False)
            if previous
            else []
        )
        incidents = [i.to_dict() for i in assemble_incidents(latest.run_id, db_path)]
        risk_predictions = RiskPredictor(conn).predict_all(
            project=effective_project,
            min_runs=2,
            history_limit=max(10, window),
        )

        trends = _trend_intelligence(repo, recent_runs, db_path=db_path)
        comparison = _comparison(latest_tests, previous_tests)
        fix_first = _fix_first(
            latest=latest,
            latest_tests=latest_tests,
            comparison=comparison,
            incidents=incidents,
            risk_predictions=risk_predictions,
            trends=trends,
        )
        executive = _executive_summary(
            latest=latest,
            previous=previous,
            latest_tests=latest_tests,
            comparison=comparison,
            incidents=incidents,
            trends=trends,
            fix_first=fix_first,
        )

        return {
            "scope": {
                "project": effective_project,
                "run_id": latest.run_id,
                "run_sequence": latest.run_sequence,
                "window": len(recent_runs),
                "requested_window": window,
                "has_previous_run": previous is not None,
            },
            "executive_summary": executive,
            "trend_intelligence": trends,
            "fix_first": fix_first,
        }
    finally:
        conn.close()


def _empty_payload(*, project: str | None, window: int) -> dict[str, Any]:
    return {
        "scope": {
            "project": project,
            "run_id": None,
            "run_sequence": None,
            "window": 0,
            "requested_window": window,
            "has_previous_run": False,
        },
        "executive_summary": ["No QaLens runs are available for this scope."],
        "trend_intelligence": [
            _trend("Stability", "unknown", 0, "No runs available."),
            _trend("Failures", "unknown", 0, "No runs available."),
            _trend("Flakiness", "unknown", 0, "No runs available."),
            _trend("Incidents", "unknown", 0, "No runs available."),
        ],
        "fix_first": [],
    }


def _resolve_run(
    repo: RunRepository,
    *,
    project: str | None,
    run_id: str | None,
) -> RunRow | None:
    if run_id and run_id != "latest":
        run = repo.get_run(run_id)
        if run is None and run_id.isdigit():
            run = repo.get_run_by_sequence(int(run_id), project=project)
        if run is not None and project is not None and run.project != project:
            return None
        return run
    runs = repo.list_runs(project=project, limit=1)
    return runs[0] if runs else None


def _recent_runs(
    repo: RunRepository,
    latest: RunRow,
    *,
    project: str | None,
    window: int,
) -> list[RunRow]:
    runs = repo.list_runs(project=project, limit=max(window * 3, window, 2))
    comparable = [
        run for run in runs
        if run.run_sequence <= latest.run_sequence and (
            not latest.project or not run.project or run.project == latest.project
        )
    ]
    comparable.sort(key=lambda run: (run.run_sequence, run.started_at or 0), reverse=True)
    return comparable[: max(1, window)]


def _previous_run(runs: list[RunRow], latest: RunRow) -> RunRow | None:
    for run in runs:
        if run.run_id != latest.run_id and run.run_sequence < latest.run_sequence:
            return run
    return None


def _comparison(
    latest_tests: list[TestCaseRow],
    previous_tests: list[TestCaseRow],
) -> dict[str, list[TestCaseRow]]:
    previous_by_name = {t.canonical_name: t for t in previous_tests}
    new_failures: list[TestCaseRow] = []
    recovered: list[TestCaseRow] = []
    persistent: list[TestCaseRow] = []
    newly_skipped: list[TestCaseRow] = []

    for test in latest_tests:
        prev = previous_by_name.get(test.canonical_name)
        prev_status = prev.status if prev else None
        if test.status in _FAIL_STATUSES:
            if prev_status is None or prev_status in {"passed", "skipped"}:
                new_failures.append(test)
            elif prev_status in _FAIL_STATUSES:
                persistent.append(test)
        elif test.status == "passed" and prev_status in _FAIL_STATUSES:
            recovered.append(test)
        elif test.status == "skipped" and prev_status != "skipped":
            newly_skipped.append(test)
    return {
        "new_failures": new_failures,
        "recovered": recovered,
        "persistent": persistent,
        "newly_skipped": newly_skipped,
    }


def _trend_intelligence(
    repo: RunRepository,
    runs_newest_first: list[RunRow],
    *,
    db_path: str | None,
) -> list[dict[str, Any]]:
    if not runs_newest_first:
        return []
    runs_oldest = sorted(runs_newest_first, key=lambda r: (r.run_sequence, r.started_at or 0))
    latest = runs_oldest[-1]
    oldest = runs_oldest[0]
    latest_pass = _pass_rate(latest)
    oldest_pass = _pass_rate(oldest)
    stability_delta = latest_pass - oldest_pass
    stability_direction = _direction(stability_delta, good_when_positive=True, threshold=0.03)

    latest_fail_rate = _failure_rate(latest)
    previous_fail_rates = [_failure_rate(r) for r in runs_oldest[:-1]]
    baseline_fail_rate = (
        sum(previous_fail_rates) / len(previous_fail_rates)
        if previous_fail_rates
        else latest_fail_rate
    )
    failure_delta = latest_fail_rate - baseline_fail_rate
    failure_direction = (
        "spiking" if failure_delta >= 0.08
        else "reducing" if failure_delta <= -0.08
        else "flat"
    )

    flake_recent, flake_older = _flaky_pressure(repo, runs_oldest)
    flake_delta = flake_recent - flake_older
    flake_direction = "increasing" if flake_delta > 0 else "reducing" if flake_delta < 0 else "flat"

    incident_direction, incident_delta = _incident_direction(runs_oldest, db_path=db_path)

    return [
        _trend(
            "Stability",
            stability_direction,
            round(stability_delta * 100, 1),
            (
                f"Pass rate moved from {round(oldest_pass * 100)}% "
                f"to {round(latest_pass * 100)}% over the selected window."
            ),
        ),
        _trend(
            "Failures",
            failure_direction,
            round(failure_delta * 100, 1),
            (
                f"Latest failure rate is {round(latest_fail_rate * 100)}% "
                f"versus a recent baseline of {round(baseline_fail_rate * 100)}%."
            ),
        ),
        _trend(
            "Flakiness",
            flake_direction,
            flake_delta,
            (
                f"{flake_recent} unstable test transition(s) in the recent half "
                f"versus {flake_older} in the older half."
            ),
        ),
        _trend(
            "Incidents",
            incident_direction,
            incident_delta,
            _incident_detail(incident_direction, incident_delta),
        ),
    ]


def _trend(metric: str, direction: str, delta: float | int, detail: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "direction": direction,
        "delta": delta,
        "detail": detail,
    }


def _pass_rate(run: RunRow) -> float:
    total = run.total_tests or 0
    return (run.passed_count or 0) / total if total else 0.0


def _failure_rate(run: RunRow) -> float:
    total = run.total_tests or 0
    return (run.failed_count or 0) / total if total else 0.0


def _direction(delta: float, *, good_when_positive: bool, threshold: float) -> str:
    if abs(delta) < threshold:
        return "stable"
    if good_when_positive:
        return "improving" if delta > 0 else "declining"
    return "declining" if delta > 0 else "improving"


def _flaky_pressure(repo: RunRepository, runs_oldest: list[RunRow]) -> tuple[int, int]:
    if len(runs_oldest) < 2:
        return (0, 0)
    midpoint = max(1, len(runs_oldest) // 2)
    older = runs_oldest[:midpoint]
    recent = runs_oldest[midpoint:]

    def count_flips(runs: list[RunRow]) -> int:
        histories: dict[str, list[str]] = defaultdict(list)
        for run in runs:
            for test in repo.get_test_cases_for_run(run.run_id, include_details=False):
                histories[test.canonical_name].append(test.status)
        flips = 0
        for statuses in histories.values():
            flips += sum(1 for a, b in zip(statuses, statuses[1:], strict=False) if a != b)
        return flips

    return count_flips(recent), count_flips(older)


def _incident_direction(runs_oldest: list[RunRow], *, db_path: str | None) -> tuple[str, int]:
    if not runs_oldest:
        return "unknown", 0
    latest = runs_oldest[-1]
    latest_incidents = assemble_incidents(latest.run_id, db_path)
    previous_incidents = [
        incident
        for run in runs_oldest[:-1]
        for incident in assemble_incidents(run.run_id, db_path)
    ]
    latest_by_key = {
        incident.signature or incident.title: incident.impacted_test_count
        for incident in latest_incidents
    }
    previous_max: dict[str, int] = {}
    for incident in previous_incidents:
        key = incident.signature or incident.title
        previous_max[key] = max(previous_max.get(key, 0), incident.impacted_test_count)

    new_count = sum(1 for key in latest_by_key if key not in previous_max)
    worsening_count = sum(
        1 for key, count in latest_by_key.items()
        if key in previous_max and count > previous_max[key]
    )
    recovering_count = sum(1 for key in previous_max if key not in latest_by_key)

    if worsening_count:
        return "worsening", worsening_count
    if new_count:
        return "new", new_count
    if recovering_count and not latest_by_key:
        return "recovering", recovering_count
    if latest_by_key:
        return "persisting", len(latest_by_key)
    return "stable", 0


def _incident_detail(direction: str, delta: int) -> str:
    if direction == "worsening":
        return f"{delta} incident cluster(s) expanded in the latest run."
    if direction == "new":
        return f"{delta} new incident cluster(s) appeared in the latest run."
    if direction == "recovering":
        return f"{delta} previous incident cluster(s) are no longer active."
    if direction == "persisting":
        return f"{delta} incident cluster(s) remain active."
    return "No active incident movement detected."


def _fix_first(
    *,
    latest: RunRow,
    latest_tests: list[TestCaseRow],
    comparison: dict[str, list[TestCaseRow]],
    incidents: list[dict[str, Any]],
    risk_predictions: list[Any],
    trends: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    new_failures = comparison["new_failures"]
    if new_failures:
        suites = _top_names(t.suite or "Unknown suite" for t in new_failures)
        items.append(_action(
            score=120 + len(new_failures),
            category="regression",
            severity="high" if len(new_failures) < 5 else "critical",
            title=f"Fix {len(new_failures)} new failure(s)",
            reason=(
                "New since the previous comparable run; concentrated in "
                f"{suites or 'unknown areas'}."
            ),
            impact=f"{len(new_failures)} test(s) regressed in Run #{latest.run_sequence}.",
            action="Start with the newly failing tests before recurring failures.",
            evidence=[t.name for t in new_failures[:5]],
            drilldown={
                "type": "regression",
                "payload": {"testNames": [t.name for t in new_failures]},
            },
        ))

    for incident in incidents[:3]:
        count = int(incident.get("impacted_test_count") or 0)
        severity = str(incident.get("severity") or "medium")
        score = 105 + count + {"critical": 12, "high": 8, "medium": 4}.get(severity, 0)
        items.append(_action(
            score=score,
            category="incident",
            severity=severity,
            title=str(incident.get("title") or "Shared failure cluster"),
            reason=f"Affects {count} test(s); likely one fix clears multiple failures.",
            impact=f"{count} impacted test(s).",
            action=str(
                incident.get("recommended_action")
                or "Investigate the shared failure signature."
            ),
            evidence=list(incident.get("evidence") or [])[:4],
            drilldown={
                "type": "incident",
                "payload": {
                    "fingerprint": incident.get("signature"),
                    "testNames": incident.get("impacted_tests") or [],
                },
            },
        ))

    trend_by_metric = {t["metric"]: t for t in trends}
    if trend_by_metric.get("Incidents", {}).get("direction") == "worsening" and incidents:
        top = incidents[0]
        items.append(_action(
            score=112,
            category="worsening_incident",
            severity="high",
            title="Stop the worsening failure cluster",
            reason=str(trend_by_metric["Incidents"]["detail"]),
            impact=f"{top.get('impacted_test_count', 0)} test(s) affected in the latest run.",
            action="Investigate the expanding incident before isolated failures.",
            evidence=list(top.get("evidence") or [])[:4],
            drilldown={
                "type": "incident",
                "payload": {
                    "fingerprint": top.get("signature"),
                    "testNames": top.get("impacted_tests") or [],
                },
            },
        ))

    risky = [p for p in risk_predictions if p.current_streak < 0 or p.risk_score >= 0.41]
    for prediction in risky[:2]:
        items.append(_action(
            score=40 + int(prediction.risk_pct),
            category="risk",
            severity="high" if prediction.risk_score >= 0.41 else "medium",
            title=f"Stabilize {prediction.display_name}",
            reason=(
                f"Risk score {prediction.risk_pct}% with current streak "
                f"{prediction.current_streak}."
            ),
            impact=(
                f"Seen across {prediction.run_count} run(s); "
                f"pass rate {round(prediction.pass_rate * 100)}%."
            ),
            action="Inspect the active fail streak and recent decline signals.",
            evidence=[
                f"flip score {round(prediction.flip_score * 100)}%",
                f"history {prediction.sparkline}",
            ],
            drilldown={
                "type": "risk",
                "payload": {"testNames": [prediction.display_name, prediction.canonical_name]},
            },
        ))

    suite_counts = Counter(
        t.suite or "Unknown suite"
        for t in latest_tests
        if t.status in _FAIL_STATUSES
    )
    if suite_counts:
        suite, count = suite_counts.most_common(1)[0]
        if count >= 2:
            items.append(_action(
                score=70 + count,
                category="suite_hotspot",
                severity="medium",
                title=f"Focus {suite}",
                reason=f"{count} latest-run failure(s) are concentrated in this suite.",
                impact=f"{suite} is the largest current failure area.",
                action="Triage this suite before expanding to lower-impact areas.",
                evidence=[
                    t.name for t in latest_tests
                    if (t.suite or "Unknown suite") == suite
                    and t.status in _FAIL_STATUSES
                ][:5],
                drilldown={"type": "suite", "payload": {"suite": suite}},
            ))

    if not items and (latest.failed_count or 0) == 0:
        items.append(_action(
            score=10,
            category="healthy",
            severity="low",
            title="No failed tests in the latest run",
            reason="Latest run has no active failure to triage.",
            impact="No immediate fix-first action.",
            action="Monitor the next run for regressions or trend changes.",
            evidence=[],
            drilldown={"type": "all", "payload": {}},
        ))

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in sorted(items, key=lambda i: i["_score"], reverse=True):
        key = (item["category"], item["title"])
        deduped.setdefault(key, item)
    ranked = list(deduped.values())[:5]
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
        item.pop("_score", None)
    return ranked


def _action(
    *,
    score: int,
    category: str,
    severity: str,
    title: str,
    reason: str,
    impact: str,
    action: str,
    evidence: list[str],
    drilldown: dict[str, Any],
) -> dict[str, Any]:
    return {
        "_score": score,
        "rank": 0,
        "category": category,
        "severity": severity,
        "title": title,
        "reason": reason,
        "impact": impact,
        "action": action,
        "evidence": [e for e in evidence if e][:5],
        "drilldown": drilldown,
    }


def _top_names(names: Iterable[str]) -> str:
    counts = Counter(name for name in names if name)
    return ", ".join(name for name, _ in counts.most_common(2))


def _executive_summary(
    *,
    latest: RunRow,
    previous: RunRow | None,
    latest_tests: list[TestCaseRow],
    comparison: dict[str, list[TestCaseRow]],
    incidents: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    fix_first: list[dict[str, Any]],
) -> list[str]:
    bullets: list[str] = []
    latest_pass = round(_pass_rate(latest) * 100)
    if previous:
        previous_pass = round(_pass_rate(previous) * 100)
        bullets.append(f"Test stability moved from {previous_pass}% to {latest_pass}% pass rate.")
    else:
        bullets.append(
            f"Latest run is at {latest_pass}% pass rate with no previous comparable run."
        )

    new_failures = len(comparison["new_failures"])
    recovered = len(comparison["recovered"])
    bullets.append(f"{new_failures} new failure(s) introduced; {recovered} test(s) recovered.")

    major_incidents = [
        i for i in incidents
        if str(i.get("severity")) in {"critical", "high"}
    ]
    impacted = sum(int(i.get("impacted_test_count") or 0) for i in major_incidents)
    bullets.append(f"{len(major_incidents)} major incident(s) affect {impacted} test(s).")

    suite = _top_names(
        t.suite or "Unknown suite"
        for t in latest_tests
        if t.status in _FAIL_STATUSES
    )
    if suite:
        bullets.append(f"Risk is concentrated in {suite}.")

    trend_text = ", ".join(f"{t['metric']}: {t['direction']}" for t in trends)
    if trend_text:
        bullets.append(f"Direction signals: {trend_text}.")

    if fix_first:
        bullets.append(f"Fix first: {fix_first[0]['title']} because {fix_first[0]['reason']}")
    return bullets
