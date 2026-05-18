"""Analysis commands: analyze, digest, summarize, clusters."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from qalens.api.library import QALensClient

console = Console()
err_console = Console(stderr=True)


def analyze(
    project: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project name to filter analysis (use value shown by 'qalens ingest').",
    ),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QALens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    flaky: bool = typer.Option(True, "--flaky/--no-flaky", help="Show flaky test analysis."),
    failures: bool = typer.Option(True, "--failures/--no-failures", help="Show grouped failure analysis."),
    min_runs: int = typer.Option(2, "--min-runs", help="Minimum runs required for flaky scoring."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write analysis JSON to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Analyze test stability and failure patterns from ingested runs.

    Queries the QALens database (populated by 'qalens ingest') to produce:

    \b
    --flaky     Flakiness scores for all tests with sufficient history
    --failures  Recurring failures grouped by root-cause fingerprint

    Use --project to restrict analysis to a single project.
    """
    import json as _json

    from rich.table import Table

    from qalens.analyzers.categorizer import categorize_failure
    from qalens.analyzers.flaky import FlakyClassification

    client = QALensClient()

    output: dict = {"project": project, "flaky": [], "failure_groups": []}

    # ------------------------------------------------------------------ #
    # Flakiness table
    # ------------------------------------------------------------------ #
    if flaky:
        try:
            results = client.get_all_stability(
                project=project, db_path=db, min_runs=min_runs
            )
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Flaky analysis failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if not results:
            console.print(
                f"[yellow]No tests with ≥{min_runs} runs found"
                + (f" for project '{project}'" if project else "")
                + ".[/yellow]"
            )
        else:
            table = Table(
                title=f"Test Stability{f' — {project}' if project else ''}",
                show_lines=False,
            )
            table.add_column("Test", style="bold", max_width=50)
            table.add_column("Runs", justify="right")
            table.add_column("Pass%", justify="right")
            table.add_column("Flip", justify="right")
            table.add_column("History", no_wrap=True)
            table.add_column("Classification")

            _CLASS_STYLE = {
                FlakyClassification.FLAKY: "yellow",
                FlakyClassification.CONSISTENTLY_BROKEN: "red",
                FlakyClassification.STABLE: "green",
                FlakyClassification.CONSISTENT: "cyan",
                FlakyClassification.INSUFFICIENT_DATA: "dim",
            }

            for r in results:
                style = _CLASS_STYLE.get(r.classification, "")
                table.add_row(
                    r.display_name,
                    str(r.run_count),
                    f"{r.pass_rate:.0%}",
                    f"{r.flip_score:.2f}",
                    r.sparkline,
                    f"[{style}]{r.classification.label}[/{style}]",
                )

            console.print(table)
            output["flaky"] = [
                {
                    "canonical_name": r.canonical_name,
                    "display_name": r.display_name,
                    "run_count": r.run_count,
                    "pass_rate": round(r.pass_rate, 4),
                    "flip_score": round(r.flip_score, 4),
                    "classification": r.classification.value,
                    "history": r.history,
                    "sparkline": r.sparkline,
                }
                for r in results
            ]

    # ------------------------------------------------------------------ #
    # Failure groups table
    # ------------------------------------------------------------------ #
    if failures:
        try:
            groups = client.get_failure_groups(project=project, db_path=db)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Failure group analysis failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if groups:
            fg_table = Table(
                title=f"Recurring Failures{f' — {project}' if project else ''}",
                show_lines=False,
            )
            fg_table.add_column("Fingerprint", style="dim", no_wrap=True)
            fg_table.add_column("Category")
            fg_table.add_column("Error Type", max_width=40)
            fg_table.add_column("Occurrences", justify="right")
            fg_table.add_column("Tests", justify="right")
            fg_table.add_column("Runs", justify="right")
            fg_table.add_column("Seen (seq)", justify="right")

            for g in groups:
                cat = categorize_failure(
                    error_type=g.get("error_type"),
                    message=g.get("message"),
                )
                seen = (
                    f"{g['first_seen_seq']}–{g['last_seen_seq']}"
                    if g["first_seen_seq"] != g["last_seen_seq"]
                    else str(g["first_seen_seq"])
                )
                fg_table.add_row(
                    g["fingerprint"],
                    cat.label,
                    (g.get("error_type") or "").split(".")[-1] or "—",
                    str(g["occurrence_count"]),
                    str(g["affected_tests"]),
                    str(g["affected_runs"]),
                    seen,
                )

            console.print(fg_table)
            output["failure_groups"] = groups

    # ------------------------------------------------------------------ #
    # JSON output
    # ------------------------------------------------------------------ #
    if out:
        out.write_text(_json.dumps(output, indent=2, default=str), encoding="utf-8")
        console.print(f"[green]Written:[/green] {out}")


def digest(
    project: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project name to filter (default: all projects).",
    ),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QALens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    format: str = typer.Option(  # noqa: A002
        "html",
        "--format",
        "-f",
        help="Output format: 'html', 'markdown', or 'json'.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write digest to this file (required for html/markdown).",
    ),
    min_runs: int = typer.Option(
        2,
        "--min-runs",
        help="Minimum run count to classify a test.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the generated HTML file in the default browser.",
    ),
) -> None:
    """Generate a shareable failure digest report.

    Reads from the QALens database and produces a triage-ready report showing
    flaky tests, consistently broken tests, and recurring failure groups.

    Examples::

        qalens digest --project "Allure Report" --out digest.html
        qalens digest --project "Allure Report" --format markdown --out digest.md
        qalens digest --project "Allure Report" --format json --out digest.json
    """
    from qalens.outputs.digest import build_digest, render_html, render_json, render_markdown

    fmt = format.lower().strip()
    if fmt not in ("html", "markdown", "md", "json"):
        err_console.print(f"[red]Unknown format:[/red] {format!r}. Use html, markdown, or json.")
        raise typer.Exit(code=1)

    console.print(f"[bold]Building digest[/bold] — project: {project or '(all)'}")

    try:
        data = build_digest(
            project=project,
            db_path=db,
            min_runs=min_runs,
        )
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Digest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if data.run_count == 0:
        console.print("[yellow]No runs found for the given project.[/yellow]")
        raise typer.Exit(code=0)

    console.print(
        f"  Runs analysed : {data.run_count}\n"
        f"  Flaky         : {len(data.flaky)}\n"
        f"  Broken        : {len(data.consistently_broken)}\n"
        f"  Stable        : {len(data.stable)}\n"
        f"  Failure groups: {len(data.failure_groups)}"
    )

    if fmt in ("html",):
        content = render_html(data)
        ext = ".html"
    elif fmt in ("markdown", "md"):
        content = render_markdown(data)
        ext = ".md"
    else:
        content = render_json(data)
        ext = ".json"

    if out:
        out.write_text(content, encoding="utf-8")
        console.print(f"[green]Written:[/green] {out}")
        if open_browser and fmt == "html":
            import webbrowser
            webbrowser.open(out.resolve().as_uri())
    else:
        if fmt == "html":
            # HTML to stdout is rarely useful — warn and print anyway
            err_console.print(
                "[yellow]Tip:[/yellow] use --out digest.html to save the HTML file."
            )
        console.print(content)


def summarize(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    format: str = typer.Option(  # noqa: A002
        "console",
        "--format",
        "-f",
        help="Output format: 'markdown', 'json', or 'console'.",
    ),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write summary to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    # --- CI gate thresholds ---
    fail_on_defects: int = typer.Option(
        -1,
        "--fail-on-defects",
        help=(
            "Exit 2 if product-defect failures ≥ N. "
            "Use 0 to fail on any defect. -1 disables the gate."
        ),
        show_default=False,
    ),
    fail_on_flaky: int = typer.Option(
        -1,
        "--fail-on-flaky",
        help="Exit 2 if flaky failures ≥ N. -1 disables.",
        show_default=False,
    ),
    fail_on_environment: int = typer.Option(
        -1,
        "--fail-on-environment",
        help="Exit 2 if environment failures ≥ N. -1 disables.",
        show_default=False,
    ),
    fail_on_unknown: int = typer.Option(
        -1,
        "--fail-on-unknown",
        help="Exit 2 if unknown-category failures ≥ N. -1 disables.",
        show_default=False,
    ),
    fail_on_script_issues: int = typer.Option(
        -1,
        "--fail-on-script-issues",
        help="Exit 2 if test-script failures ≥ N. -1 disables.",
        show_default=False,
    ),
    fail_on_test_data: int = typer.Option(
        -1,
        "--fail-on-test-data",
        help="Exit 2 if test-data failures ≥ N. -1 disables.",
        show_default=False,
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail (exit 2) on any failure of any category. Shorthand for --fail-on-defects 0 etc.",
    ),
) -> None:
    """Generate a human-readable summary of an analyzed report.

    Formats available: [bold]markdown[/bold], [bold]json[/bold],
    [bold]console[/bold] (default).

    [bold]CI gate[/bold]: use threshold flags to fail the build when failure
    counts exceed a limit.  Exit code [bold]2[/bold] means a gate was breached
    (distinct from exit code 1 which means a QALens error).

    Examples::

        qalens summarize ./reports/allure-report --format json
        qalens summarize ./reports/allure-report --fail-on-defects 0
        qalens summarize ./reports/allure-report --strict
    """
    valid_formats = {"markdown", "json", "console"}
    if format.lower() not in valid_formats:
        err_console.print(
            f"[red]Unknown format '{format}'. Choose: markdown, json, console.[/red]"
        )
        raise typer.Exit(code=1)

    # --strict sets every threshold to 0 (fail on any failure)
    if strict:
        if fail_on_defects == -1:
            fail_on_defects = 0
        if fail_on_flaky == -1:
            fail_on_flaky = 0
        if fail_on_environment == -1:
            fail_on_environment = 0
        if fail_on_unknown == -1:
            fail_on_unknown = 0
        if fail_on_script_issues == -1:
            fail_on_script_issues = 0
        if fail_on_test_data == -1:
            fail_on_test_data = 0

    client = QALensClient()

    with console.status("[dim]Extracting and analysing report…[/dim]"):
        try:
            run = client.extract_report(report_path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Extraction failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if verbose:
            console.print(
                f"[dim]Extracted {len(run.test_cases)} test(s) "
                f"({run.metadata.report_format})[/dim]"
            )

        analysis = client.analyze_report(run)
        content = client.summarize_report(analysis, fmt=format.lower())  # type: ignore[arg-type]

    if out:
        out.write_text(content, encoding="utf-8")
        console.print(f"[green]Written:[/green] {out}")
    else:
        if format.lower() == "console":
            console.print(content)
        else:
            # json / markdown: output as plain text, no Rich markup or ANSI codes
            print(content)  # noqa: T201

    # --- CI gate evaluation ---
    cc = analysis.category_counts
    breaches: list[str] = []

    if fail_on_defects >= 0 and cc.likely_product_defect >= fail_on_defects:
        # threshold 0 means "any defect fails"; only trip when count > 0 at threshold 0,
        # or when count >= N for N > 0
        if fail_on_defects == 0 and cc.likely_product_defect > 0:
            breaches.append(
                f"product defects: {cc.likely_product_defect} (threshold: fail on any)"
            )
        elif fail_on_defects > 0 and cc.likely_product_defect >= fail_on_defects:
            breaches.append(
                f"product defects: {cc.likely_product_defect} ≥ threshold {fail_on_defects}"
            )

    if fail_on_flaky >= 0 and cc.likely_flaky >= fail_on_flaky:
        if fail_on_flaky == 0 and cc.likely_flaky > 0:
            breaches.append(f"flaky tests: {cc.likely_flaky} (threshold: fail on any)")
        elif fail_on_flaky > 0 and cc.likely_flaky >= fail_on_flaky:
            breaches.append(f"flaky tests: {cc.likely_flaky} ≥ threshold {fail_on_flaky}")

    if fail_on_environment >= 0 and cc.likely_environment_issue >= fail_on_environment:
        if fail_on_environment == 0 and cc.likely_environment_issue > 0:
            breaches.append(
                f"environment failures: {cc.likely_environment_issue} (threshold: fail on any)"
            )
        elif fail_on_environment > 0 and cc.likely_environment_issue >= fail_on_environment:
            breaches.append(
                f"environment failures: {cc.likely_environment_issue} "
                f"≥ threshold {fail_on_environment}"
            )

    if fail_on_unknown >= 0 and cc.unknown >= fail_on_unknown:
        if fail_on_unknown == 0 and cc.unknown > 0:
            breaches.append(f"unknown failures: {cc.unknown} (threshold: fail on any)")
        elif fail_on_unknown > 0 and cc.unknown >= fail_on_unknown:
            breaches.append(f"unknown failures: {cc.unknown} ≥ threshold {fail_on_unknown}")

    if fail_on_script_issues >= 0 and cc.likely_test_script_issue >= fail_on_script_issues:
        if fail_on_script_issues == 0 and cc.likely_test_script_issue > 0:
            breaches.append(
                f"test-script failures: {cc.likely_test_script_issue} (threshold: fail on any)"
            )
        elif fail_on_script_issues > 0 and cc.likely_test_script_issue >= fail_on_script_issues:
            breaches.append(
                f"test-script failures: {cc.likely_test_script_issue} "
                f"≥ threshold {fail_on_script_issues}"
            )

    if fail_on_test_data >= 0 and cc.likely_test_data_issue >= fail_on_test_data:
        if fail_on_test_data == 0 and cc.likely_test_data_issue > 0:
            breaches.append(
                f"test-data failures: {cc.likely_test_data_issue} (threshold: fail on any)"
            )
        elif fail_on_test_data > 0 and cc.likely_test_data_issue >= fail_on_test_data:
            breaches.append(
                f"test-data failures: {cc.likely_test_data_issue} "
                f"≥ threshold {fail_on_test_data}"
            )

    if breaches:
        err_console.print("[bold red]CI gate breached:[/bold red]")
        for b in breaches:
            err_console.print(f"  [red]✗[/red] {b}")
        raise typer.Exit(code=2)


def clusters(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write cluster JSON to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Display failure clusters grouped by root-cause signature.

    Each cluster shows the shared failure pattern and all affected tests.

    Examples::

        qalens clusters ./reports/allure-report
        qalens clusters ./reports/allure-report --out clusters.json
    """
    import json

    from rich.table import Table

    client = QALensClient()

    with console.status("[dim]Extracting report…[/dim]"):
        try:
            run = client.extract_report(report_path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Extraction failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    clusters_list = client.cluster_report(run)

    if not clusters_list:
        console.print("[green]No failures found — all tests passed.[/green]")
        raise typer.Exit(code=0)

    console.print(
        f"[bold]Failure clusters[/bold] — {len(clusters_list)} group(s) "
        f"across {sum(c.size for c in clusters_list)} failing test(s)"
    )
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Size", justify="right", width=6)
    table.add_column("Signature", style="cyan", width=18)
    table.add_column("Category", width=28)
    table.add_column("Conf", justify="right", width=6)
    table.add_column("Label")

    for idx, cluster in enumerate(clusters_list, start=1):
        table.add_row(
            str(idx),
            str(cluster.size),
            cluster.failure_signature or "-",
            cluster.category.display_name,
            f"{cluster.confidence:.0%}",
            cluster.label,
        )

    console.print(table)

    if verbose:
        for idx, cluster in enumerate(clusters_list, start=1):
            console.print(f"\n[bold]Cluster {idx}:[/bold] {cluster.label}")
            console.print(f"  Rationale : {cluster.rationale}")
            console.print(f"  Tests     : {', '.join(cluster.member_test_ids[:5])}" +
                          (f" (+ {cluster.size - 5} more)" if cluster.size > 5 else ""))

    if out:
        payload = [
            {
                "cluster_id": c.cluster_id,
                "label": c.label,
                "failure_signature": c.failure_signature,
                "category": c.category.value,
                "confidence": c.confidence,
                "size": c.size,
                "member_test_ids": c.member_test_ids,
                "rationale": c.rationale,
                "representative_message": c.representative_message,
            }
            for c in clusters_list
        ]
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"\n[green]Written:[/green] {out}")
