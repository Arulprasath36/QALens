"""Shareable report export command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def report(
    db: Annotated[
        Path | None,
        typer.Option("--db", help="Path to QALens SQLite database. Defaults to ~/.qalens/qalens.db."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Project name to report on. Defaults to the latest run's project.",
        ),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Run id, run sequence number, or 'latest'."),
    ] = "latest",
    format: Annotated[  # noqa: A002
        str,
        typer.Option("--format", "-f", help="Output format: html, markdown, md, or json."),
    ] = "html",
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output path. Defaults to qalens-report.html/md/json."),
    ] = None,
    window: Annotated[
        int,
        typer.Option(
            "--window",
            min=1,
            max=100,
            help="Recent run count used for recurring failure groups.",
        ),
    ] = 10,
    min_runs: Annotated[
        int,
        typer.Option(
            "--min-runs",
            min=1,
            max=100,
            help="Minimum history depth for stability and flaky sections.",
        ),
    ] = 2,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=50, help="Maximum rows per report section."),
    ] = 10,
    open_browser: Annotated[
        bool,
        typer.Option("--open", help="Open HTML output in the default browser after writing it."),
    ] = False,
) -> None:
    """Export a deterministic shareable QALens report.

    The report is generated from QALens's SQLite data, not by an LLM. It is safe
    to use in CI artifacts, release notes, and team triage handoffs.
    """
    from qalens.reports import build_report, render_html, render_json, render_markdown

    fmt = format.lower().strip()
    if fmt not in {"html", "markdown", "md", "json"}:
        err_console.print(f"[red]Unknown format:[/red] {format!r}. Use html, markdown, or json.")
        raise typer.Exit(code=1)

    try:
        data = build_report(
            db_path=db,
            project=project,
            run_id=run_id,
            window=window,
            min_runs=min_runs,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Report export failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if fmt == "html":
        content = render_html(data)
        default_name = "qalens-report.html"
    elif fmt in {"markdown", "md"}:
        content = render_markdown(data)
        default_name = "qalens-report.md"
    else:
        content = render_json(data)
        default_name = "qalens-report.json"

    output_path = out or Path(default_name)
    output_path.write_text(content, encoding="utf-8")
    console.print(f"[green]Written:[/green] {output_path}")
    console.print(
        f"  Scope: {data.scope_label}\n"
        f"  Latest run: #{data.latest_run.run_sequence}\n"
        f"  Failed: {data.latest_run.failed}\n"
        f"  Failure groups: {len(data.failure_groups)}"
    )

    if open_browser and fmt == "html":
        import webbrowser

        webbrowser.open(output_path.resolve().as_uri())
