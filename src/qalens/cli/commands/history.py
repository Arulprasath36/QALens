"""CLI history views for tests, owners, suites, modules, and failures."""
# ruff: noqa: B008

from __future__ import annotations

import json
import sqlite3  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import Any, Literal

import typer
from rich.console import Console
from rich.table import Table

console = Console()

HistoryKind = Literal["test", "owner", "suite", "module", "failure"]
OutputFormat = Literal["table", "json"]

_FAILING = {"failed", "broken"}
_PASSING = {"passed"}


def history(
    kind: HistoryKind = typer.Argument(
        ...,
        help="History target kind: test, owner, suite, module, or failure.",
    ),
    value: str = typer.Argument(..., help="Target name or failure fingerprint."),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QALens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Restrict history to one project.",
    ),
    window: int = typer.Option(
        30,
        "--window",
        min=1,
        max=200,
        help="Number of most recent matching runs to include.",
    ),
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        help="Output format: table or json.",
    ),
) -> None:
    """Show one test, owner, suite/module, or failure over time.

    Examples:
        qalens history test "testLogin()" --db ./qalens.db
        qalens history owner "Checkout Team" --db ./qalens.db
        qalens history suite "Payments" --db ./qalens.db
        qalens history module "checkout-module" --db ./qalens.db
        qalens history failure abc123 --db ./qalens.db

    """
    from qalens.db.schema import get_connection, init_db

    conn = get_connection(db)
    try:
        init_db(conn)
        if kind == "test":
            payload = _test_history(conn, value=value, project=project, window=window)
        elif kind == "failure":
            payload = _failure_history(conn, fingerprint=value, project=project, window=window)
        else:
            payload = _group_history(conn, kind=kind, value=value, project=project, window=window)
    finally:
        conn.close()

    if output_format == "json":
        console.print(json.dumps(payload, indent=2))
        return

    _print_history(payload)


def _test_history(
    conn: sqlite3.Connection,
    *,
    value: str,
    project: str | None,
    window: int,
) -> dict[str, Any]:
    from qalens.analyzers.canonical import to_canonical_name

    canonical = to_canonical_name(value)
    params: list[Any] = [canonical]
    project_clause = ""
    if project:
        project_clause = "AND r.project = ?"
        params.append(project)
    params.append(window)

    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT
                r.run_id,
                r.run_sequence,
                r.started_at,
                tc.name,
                tc.canonical_name,
                tc.status,
                tc.owner,
                tc.suite,
                tc.feature,
                tc.tags,
                f.fingerprint,
                f.error_type,
                f.message
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            LEFT JOIN failures f ON f.tc_id = tc.tc_id
            WHERE tc.canonical_name = ?
              AND tc.is_retry = 0
              {project_clause}
            ORDER BY r.run_sequence DESC
            LIMIT ?
        ) ORDER BY run_sequence ASC
        """,
        params,
    ).fetchall()

    points = [_row_to_point(row) for row in rows]
    return {
        "kind": "test",
        "value": value,
        "canonical_name": canonical,
        "summary": _summarize_points(points),
        "points": points,
    }


def _failure_history(
    conn: sqlite3.Connection,
    *,
    fingerprint: str,
    project: str | None,
    window: int,
) -> dict[str, Any]:
    params: list[Any] = [fingerprint]
    project_clause = ""
    if project:
        project_clause = "AND r.project = ?"
        params.append(project)
    params.append(window)

    rows = conn.execute(
        f"""
        SELECT
            r.run_id,
            r.run_sequence,
            r.started_at,
            COUNT(*) AS occurrences,
            COUNT(DISTINCT tc.canonical_name) AS affected_tests,
            MIN(f.error_type) AS error_type,
            MIN(f.message) AS message
        FROM failures f
        JOIN test_cases tc ON tc.tc_id = f.tc_id
        JOIN runs r ON r.run_id = tc.run_id
        WHERE f.fingerprint = ?
          {project_clause}
        GROUP BY r.run_id, r.run_sequence, r.started_at
        ORDER BY r.run_sequence DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    points = [
        {
            "run_id": row["run_id"],
            "run_sequence": row["run_sequence"],
            "started_at": row["started_at"],
            "occurrences": row["occurrences"],
            "affected_tests": row["affected_tests"],
            "error_type": row["error_type"],
            "message": row["message"],
        }
        for row in reversed(rows)
    ]
    return {
        "kind": "failure",
        "value": fingerprint,
        "summary": {
            "runs": len(points),
            "occurrences": sum(point["occurrences"] for point in points),
            "affected_tests": max((point["affected_tests"] for point in points), default=0),
        },
        "points": points,
    }


def _group_history(
    conn: sqlite3.Connection,
    *,
    kind: Literal["owner", "suite", "module"],
    value: str,
    project: str | None,
    window: int,
) -> dict[str, Any]:
    if kind == "owner":
        condition = "tc.owner = ?"
        fallback = "Unassigned"
    elif kind == "suite":
        condition = "tc.suite = ?"
        fallback = "Unknown suite"
    else:
        condition = "(tc.suite = ? OR tc.tags LIKE ?)"
        fallback = "Unknown module"

    project_clause = "AND r.project = ?" if project else ""
    params: list[Any] = [value]
    if kind == "module":
        params.append(f"%{value}%")
    if project:
        params.append(project)
    params.append(window)

    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT
                r.run_id,
                r.run_sequence,
                r.started_at,
                COUNT(*) AS total,
                SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passed,
                SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                COUNT(DISTINCT tc.canonical_name) AS unique_tests
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            WHERE {condition}
              AND tc.is_retry = 0
              {project_clause}
            GROUP BY r.run_id, r.run_sequence, r.started_at
            ORDER BY r.run_sequence DESC
            LIMIT ?
        ) ORDER BY run_sequence ASC
        """,
        params,
    ).fetchall()

    points = []
    for row in rows:
        total = row["total"] or 0
        passed = row["passed"] or 0
        points.append(
            {
                "run_id": row["run_id"],
                "run_sequence": row["run_sequence"],
                "started_at": row["started_at"],
                "total": total,
                "unique_tests": row["unique_tests"] or 0,
                "passed": passed,
                "failed": row["failed"] or 0,
                "skipped": row["skipped"] or 0,
                "pass_rate": round(passed / total, 4) if total else None,
            }
        )

    return {
        "kind": kind,
        "value": value or fallback,
        "summary": _summarize_group_points(points),
        "points": points,
    }


def _row_to_point(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "run_sequence": row["run_sequence"],
        "started_at": row["started_at"],
        "name": row["name"],
        "canonical_name": row["canonical_name"],
        "status": row["status"],
        "owner": row["owner"],
        "suite": row["suite"],
        "feature": row["feature"],
        "tags": json.loads(row["tags"] or "[]"),
        "fingerprint": row["fingerprint"],
        "error_type": row["error_type"],
        "message": row["message"],
    }


def _summarize_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [point["status"] for point in points]
    active = [status for status in statuses if status != "absent"]
    passed = sum(1 for status in active if status in _PASSING)
    failed = sum(1 for status in active if status in _FAILING)
    flips = sum(
        1
        for prev, current in zip(active, active[1:], strict=False)
        if (prev in _PASSING and current in _FAILING)
        or (prev in _FAILING and current in _PASSING)
    )
    flip_score = round(flips / (len(active) - 1), 4) if len(active) > 1 else 0.0
    return {
        "runs": len(points),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(active), 4) if active else 0.0,
        "flip_score": flip_score,
        "classification": _classification(active, flip_score),
    }


def _summarize_group_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(point["total"] for point in points)
    passed = sum(point["passed"] for point in points)
    failed = sum(point["failed"] for point in points)
    return {
        "runs": len(points),
        "executions": total,
        "failed_executions": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "trend": _trend([point["pass_rate"] for point in points if point["pass_rate"] is not None]),
    }


def _classification(statuses: list[str], flip_score: float) -> str:
    if len(statuses) < 2:
        return "insufficient_data"
    pass_rate = sum(1 for status in statuses if status in _PASSING) / len(statuses)
    if flip_score >= 0.35:
        return "flaky"
    if pass_rate <= 0.20:
        return "consistently_broken"
    return "stable"


def _trend(values: list[float]) -> str:
    if len(values) < 2:
        return "stable"
    mid = len(values) // 2
    first = values[:mid]
    second = values[mid:]
    delta = (sum(second) / len(second)) - (sum(first) / len(first))
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "degrading"
    return "stable"


def _print_history(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    console.print(
        f"[bold]{payload['kind'].title()} history[/bold] · {payload['value']} · "
        f"{summary.get('runs', 0)} runs"
    )
    if not payload["points"]:
        console.print("[yellow]No matching history found.[/yellow]")
        return

    if payload["kind"] == "test":
        _print_test_table(payload)
    elif payload["kind"] == "failure":
        _print_failure_table(payload)
    else:
        _print_group_table(payload)


def _print_test_table(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    console.print(
        f"Pass rate {summary['pass_rate']:.0%} · flip {summary['flip_score']:.2f} · "
        f"{summary['classification'].replace('_', ' ')}"
    )
    table = Table(show_lines=False)
    table.add_column("Run", justify="right")
    table.add_column("Status")
    table.add_column("Owner")
    table.add_column("Suite")
    table.add_column("Failure", overflow="fold", max_width=40)
    for point in payload["points"]:
        table.add_row(
            f"#{point['run_sequence']}",
            point["status"],
            point["owner"] or "Unassigned",
            point["suite"] or "-",
            point["error_type"] or point["message"] or "-",
        )
    console.print(table)


def _print_group_table(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    console.print(
        f"Pass rate {summary['pass_rate']:.0%} · "
        f"{summary['failed_executions']} failed executions · {summary['trend']}"
    )
    table = Table(show_lines=False)
    table.add_column("Run", justify="right")
    table.add_column("Tests", justify="right")
    table.add_column("Passed", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Pass%", justify="right")
    for point in payload["points"]:
        table.add_row(
            f"#{point['run_sequence']}",
            str(point["total"]),
            str(point["passed"]),
            str(point["failed"]),
            str(point["skipped"]),
            f"{point['pass_rate']:.0%}" if point["pass_rate"] is not None else "-",
        )
    console.print(table)


def _print_failure_table(payload: dict[str, Any]) -> None:
    table = Table(show_lines=False)
    table.add_column("Run", justify="right")
    table.add_column("Occurrences", justify="right")
    table.add_column("Tests", justify="right")
    table.add_column("Error", overflow="fold", max_width=36)
    for point in payload["points"]:
        table.add_row(
            f"#{point['run_sequence']}",
            str(point["occurrences"]),
            str(point["affected_tests"]),
            point["error_type"] or point["message"] or "-",
        )
    console.print(table)
