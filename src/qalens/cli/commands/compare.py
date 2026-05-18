"""CLI comparison views for run history, owners, modules, and suites."""
# ruff: noqa: B008

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003
from typing import Any, Literal

import typer
from rich.console import Console
from rich.table import Table

from qalens.analyzers.comparison import ComparisonResult, MatrixRow  # noqa: TC001

console = Console()

CompareDimension = Literal["runs", "owners", "modules", "suites"]
OutputFormat = Literal["table", "json"]

_FAILING = {"failed", "broken"}
_PASSING = {"passed"}


def compare(
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QaLens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Restrict comparison to one project.",
    ),
    by: CompareDimension = typer.Option(
        "runs",
        "--by",
        help="Comparison view: runs, owners, modules, or suites.",
    ),
    window: int = typer.Option(
        10,
        "--window",
        min=1,
        max=50,
        help="Number of most recent runs to compare.",
    ),
    run_id: list[str] | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run id to include. Repeat for multiple runs.",
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        min=1,
        max=200,
        help="Maximum rows to print.",
    ),
    latest_failed: bool = typer.Option(
        False,
        "--latest-failed",
        help="Only include tests failing in the latest selected run.",
    ),
    changed: bool = typer.Option(
        False,
        "--changed",
        help="Only include tests whose latest status changed from the previous run.",
    ),
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        help="Output format: table or json.",
    ),
) -> None:
    """Compare run history by test, owner, module, or suite.

    Examples:
        qalens compare --db ./qalens.db --by runs --window 10
        qalens compare --db ./qalens.db --by owners --window 10
        qalens compare --db ./qalens.db --by modules --window 10
        qalens compare --db ./qalens.db --by runs --run-id RUN_A --run-id RUN_B

    """
    from qalens.analyzers.comparison import (
        ComparisonFilters,
        ComparisonService,
        comparison_to_dict,
    )
    from qalens.db.schema import get_connection, init_db

    filters = ComparisonFilters(
        latest_failed_only=latest_failed,
        changed_only=changed,
    )

    conn = get_connection(db)
    try:
        init_db(conn)
        service = ComparisonService(conn)
        if run_id:
            result = service.compare_custom(
                project=project,
                run_ids=list(dict.fromkeys(run_id)),
                filters=filters,
            )
        else:
            result = service.compare_window(
                project=project,
                limit=window,
                filters=filters,
            )
    finally:
        conn.close()

    if output_format == "json":
        payload: dict[str, Any]
        if by == "runs":
            payload = comparison_to_dict(result)
        else:
            payload = _aggregate_payload(result, by=by, limit=limit)
        console.print(json.dumps(payload, indent=2))
        return

    if by == "runs":
        _print_run_history(result, limit=limit)
    else:
        _print_group_summary(result, by=by, limit=limit)


def _print_run_history(result: ComparisonResult, *, limit: int) -> None:
    summary = result.summary
    console.print(
        f"[bold]Run comparison[/bold] · {summary.window_size} runs · "
        f"{summary.unique_tests} tests · {summary.new_failures_latest} new failures · "
        f"{summary.fixed_latest} fixed"
    )
    if not result.rows:
        console.print("[yellow]No comparison rows found.[/yellow]")
        return

    table = Table(show_lines=False)
    table.add_column("Test", overflow="fold", max_width=36)
    table.add_column("Owner", overflow="fold", max_width=18)
    table.add_column("Module/Suite", overflow="fold", max_width=22)
    table.add_column("Pass%", justify="right")
    table.add_column("Flip", justify="right")
    table.add_column("Class")
    table.add_column("History")

    for row in result.rows[:limit]:
        table.add_row(
            row.display_name,
            row.owner or "Unassigned",
            _module_label(row),
            f"{row.health.pass_rate:.0%}",
            f"{row.health.flip_score:.2f}",
            row.health.classification.replace("_", " "),
            "".join(_state_char(cell.state) for cell in row.cells),
        )

    console.print(table)


def _print_group_summary(result: ComparisonResult, *, by: CompareDimension, limit: int) -> None:
    payload = _aggregate_payload(result, by=by, limit=limit)
    label = payload["group_by"].title()
    summary = payload["summary"]
    console.print(
        f"[bold]{label} comparison[/bold] · {summary['run_count']} runs · "
        f"{summary['group_count']} groups"
    )
    if not payload["groups"]:
        console.print("[yellow]No comparison groups found.[/yellow]")
        return

    table = Table(show_lines=False)
    table.add_column(label, overflow="fold", min_width=16, max_width=34)
    table.add_column("Tests", justify="right")
    table.add_column("Exec", justify="right")
    table.add_column("Failed Exec", justify="right")
    table.add_column("Latest Failed", justify="right")
    table.add_column("New Failures", justify="right")
    table.add_column("Flaky", justify="right")
    table.add_column("Pass%", justify="right")
    table.add_column("Trend")

    for group in payload["groups"]:
        table.add_row(
            group["name"],
            str(group["tests"]),
            str(group["executions"]),
            str(group["failed_executions"]),
            str(group["latest_failed_tests"]),
            str(group["new_failures"]),
            str(group["flaky_tests"]),
            f"{group['pass_rate']:.0%}" if group["pass_rate"] is not None else "-",
            group["trend"],
        )

    console.print(table)


def _aggregate_payload(
    result: ComparisonResult,
    *,
    by: CompareDimension,
    limit: int,
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}

    for row in result.rows:
        labels = _group_labels(row, by=by)
        for label in labels:
            bucket = groups.setdefault(
                label,
                {
                    "name": label,
                    "tests": 0,
                    "executions": 0,
                    "passed_executions": 0,
                    "failed_executions": 0,
                    "latest_failed_tests": 0,
                    "new_failures": 0,
                    "flaky_tests": 0,
                    "pass_rates": [],
                },
            )
            _add_row_to_bucket(bucket, row)

    ranked = []
    for bucket in groups.values():
        executions = bucket["executions"]
        pass_rate = (
            round(bucket["passed_executions"] / executions, 4)
            if executions
            else None
        )
        rates = bucket.pop("pass_rates")
        bucket["pass_rate"] = pass_rate
        bucket["trend"] = _trend(rates)
        ranked.append(bucket)

    ranked.sort(
        key=lambda item: (
            -item["failed_executions"],
            -item["latest_failed_tests"],
            item["name"].lower(),
        )
    )
    ranked = ranked[:limit]

    return {
        "group_by": "modules" if by == "modules" else by,
        "runs": [
            {
                "run_id": run.run_id,
                "run_sequence": run.run_sequence,
                "display_name": run.display_name,
                "started_at": run.started_at,
            }
            for run in result.runs
        ],
        "summary": {
            "run_count": len(result.runs),
            "group_count": len(groups),
        },
        "groups": ranked,
    }


def _add_row_to_bucket(bucket: dict[str, Any], row: MatrixRow) -> None:
    bucket["tests"] += 1
    active = [cell for cell in row.cells if cell.state != "absent"]
    bucket["executions"] += len(active)
    bucket["passed_executions"] += sum(1 for cell in active if cell.state in _PASSING)
    bucket["failed_executions"] += sum(1 for cell in active if cell.state in _FAILING)
    bucket["flaky_tests"] += 1 if row.health.classification == "flaky" else 0

    if row.cells:
        latest = row.cells[-1].state
        previous = row.cells[-2].state if len(row.cells) >= 2 else "absent"
        bucket["latest_failed_tests"] += 1 if latest in _FAILING else 0
        bucket["new_failures"] += 1 if latest in _FAILING and previous not in _FAILING else 0

    for cell in row.cells:
        if cell.state == "absent":
            continue
        bucket["pass_rates"].append(1.0 if cell.state in _PASSING else 0.0)


def _group_labels(row: MatrixRow, *, by: CompareDimension) -> list[str]:
    if by == "owners":
        return [row.owner or "Unassigned"]
    if by == "suites":
        return [row.suite or "Unknown suite"]
    if by == "modules":
        tags = [tag for tag in row.tags if tag]
        return tags or [row.suite or "Unknown module"]
    return ["All tests"]


def _module_label(row: MatrixRow) -> str:
    if row.tags:
        return ", ".join(row.tags[:2])
    return row.suite or "Unknown"


def _state_char(state: str) -> str:
    if state == "passed":
        return "P"
    if state in _FAILING:
        return "F"
    if state == "skipped":
        return "S"
    return "-"


def _trend(values: list[float]) -> str:
    if len(values) < 2:
        return "stable"
    mid = len(values) // 2
    first = values[:mid]
    second = values[mid:]
    if not first or not second:
        return "stable"
    delta = (sum(second) / len(second)) - (sum(first) / len(first))
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "degrading"
    return "stable"
