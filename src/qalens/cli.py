"""QALens command-line interface.

Built with Typer. Entry point registered in ``pyproject.toml`` as ``qalens``.

Usage examples::

    qalens detect ./reports/allure-report
    qalens extract ./reports/allure-report --out extracted.json
    qalens analyze ./reports/allure-report --history ./history --out analysis.json
    qalens summarize ./reports/extent-report --format markdown --out summary.md
    qalens clusters ./reports/allure-report
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from qalens.api.library import QALensClient
from qalens.version import __version__

app = typer.Typer(
    name="qalens",
    help=(
        "QALens — Quality Assurance + Lens.\n\n"
        "Transforms static test HTML reports into triage-ready intelligence.\n\n"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True)


def _is_public_bind_host(host: str) -> bool:
    """Return True when *host* binds beyond loopback interfaces."""
    normalized = host.strip().lower()
    return normalized in {"0.0.0.0", "::", "[::]"}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"qalens version [bold]{__version__}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Print QALens version and exit.",
        callback=_version_callback,
        is_eager=True,
        show_default=False,
    ),
) -> None:
    """QALens — Quality Assurance + Lens."""


@app.command()
def detect(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Detect the report type at REPORT_PATH.

    Prints the detected format name (e.g. 'allure' or 'extent') and exits.
    Exits with code 1 if the format cannot be determined.
    """
    client = QALensClient()
    result = client.detect_report(report_path)
    if result.matched:
        console.print(f"[green]Detected:[/green] [bold]{result.parser_name}[/bold] (confidence {result.confidence:.0%})")
        if verbose:
            for reason in result.reasons:
                console.print(f"  • {reason}")
    else:
        err_console.print(f"[red]Could not detect report format for:[/red] {report_path}")
        if verbose:
            err_console.print(f"Best confidence: {result.confidence:.0%}")
        raise typer.Exit(code=1)


@app.command()
def extract(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write normalized JSON to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Extract and normalize a report to canonical JSON.

    Reads the report at REPORT_PATH, runs the appropriate parser, and
    writes the normalized ``TestRun`` as JSON. Prints to stdout if
    --out is not provided.
    """
    import json

    client = QALensClient()
    try:
        run = client.extract_report(report_path)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Extraction failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    payload = json.dumps(run.model_dump(mode="json"), indent=2, default=str)

    if out:
        out.write_text(payload, encoding="utf-8")
        console.print(f"[green]Written:[/green] {out}")
    else:
        console.print(payload)

    if verbose or not out:
        console.print(f"\n[bold]Summary:[/bold] {run.metadata.project or '(unknown project)'}")
        console.print(f"  Format  : {run.metadata.report_format}")
        console.print(f"  Tests   : {len(run.test_cases)}")
        from qalens.models.test_case import TestStatus
        by_status = {s: sum(1 for tc in run.test_cases if tc.status == s) for s in TestStatus}
        for status, count in by_status.items():
            if count:
                console.print(f"  {status.value:<10}: {count}")
        if run.warnings:
            console.print(f"  Warnings: {len(run.warnings)}")


@app.command()
def ingest(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QALens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Parse a report and store it in the local QALens database.

    On subsequent calls with the same report the run is skipped
    (idempotent). Use --db to target a project-specific database.
    """
    from qalens.models.test_case import TestStatus

    client = QALensClient()
    try:
        run, inserted = client.ingest_report(report_path, db_path=db)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not inserted:
        console.print(
            f"[yellow]Skipped:[/yellow] run [bold]{run.metadata.run_id}[/bold] "
            "already in database."
        )
        return

    project = run.metadata.project or "(unknown project)"
    fmt = run.metadata.report_format
    version = run.metadata.report_version or ""
    version_str = f" {version}" if version else ""

    console.print(
        f"[green]Ingested:[/green] [bold]{project}[/bold] "
        f"| {fmt}{version_str}"
    )

    total = len(run.test_cases)
    by_status = {s: sum(1 for tc in run.test_cases if tc.status == s) for s in TestStatus}
    passed = by_status.get(TestStatus.PASSED, 0)
    failed = by_status.get(TestStatus.FAILED, 0) + by_status.get(TestStatus.BROKEN, 0)
    skipped = by_status.get(TestStatus.SKIPPED, 0)

    console.print(
        f"Tests  : {total} total  "
        f"[green]{passed} passed[/green]  "
        f"[red]{failed} failed[/red]  "
        f"[yellow]{skipped} skipped[/yellow]"
    )

    db_display = db or (Path.home() / ".qalens" / "qalens.db")
    console.print(f"Stored → [dim]{db_display}[/dim]")

    if verbose and run.failed_tests():
        console.print("\n[bold]Failed tests:[/bold]")
        for tc in run.failed_tests():
            fp_hint = ""
            if tc.failure and tc.failure.stack_trace:
                from qalens.analyzers.fingerprint import compute_fingerprint
                fp = compute_fingerprint(
                    error_type=tc.failure.error_type,
                    stack_trace=tc.failure.stack_trace,
                    message=tc.failure.message,
                )
                fp_hint = f" [dim](fp:{fp})[/dim]"
            console.print(f"  [red]✗[/red] {tc.name}{fp_hint}")


@app.command()
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


@app.command()
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
    elif fmt in ("markdown", "md"):
        content = render_markdown(data)
    else:
        content = render_json(data)

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


@app.command()
def ask(
    question: str = typer.Argument(
        ...,
        help="Natural-language question about your test failures.",
    ),
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
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to LLM config TOML. Defaults to ~/.qalens/config.toml.",
    ),
    show_context: bool = typer.Option(
        False,
        "--show-context",
        help="Print the context block sent to the LLM (for debugging).",
    ),
) -> None:
    """Ask a natural-language question about your test failures.

    QALens builds a structured context from your test database and sends it
    to the configured local or cloud LLM.

    Examples::

        qalens ask "why does testCreateOrder keep failing?" --project "Allure Report"
        qalens ask "summarize all failures" --project "Allure Report"
        qalens ask "which tests are most likely flaky infrastructure issues?"
    """
    from qalens.llm.answer_plan import build_answer_plan, detect_answer_intent
    from qalens.llm.client import LLMError
    from qalens.llm.config import load_config, provider_display_name
    from qalens.llm.context import gather_project_context, gather_test_context
    from qalens.llm.routing import (
        detect_signals,
        gather_context_for_signals,
        normalize_query,
        parse_query_intent,
    )
    from qalens.llm.prompts import build_prompt, build_system_prompt, infer_mode

    try:
        cfg = load_config(config)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Config error:[/red] {exc}")
        err_console.print(
            "Run [bold]qalens llm-config[/bold] to set up your LLM provider."
        )
        raise typer.Exit(code=1) from exc

    provider_name = provider_display_name(cfg.provider)
    console.print(
        f"[dim]Provider: {provider_name}  model: {cfg.model}[/dim]"
    )

    # Build context
    mode = infer_mode(question)
    _answer_plan = build_answer_plan(detect_answer_intent(question))
    with console.status("[dim]Building context from database…[/dim]"):
        # LLM-powered intent + entity extraction (falls back to keywords if LLM unavailable)
        _intent = parse_query_intent(question, config=cfg)
        # Signal-based routing (owner, risk, duration, stability, trend, ranking, comparison)
        _signals = detect_signals(normalize_query(question))
        _routed_ctx, _routed_src, _routed_mode = gather_context_for_signals(
            _signals, question, project=project, db_path=db, intent=_intent,
            answer_plan=_answer_plan,
        )
        if _routed_ctx:
            context, mode = _routed_ctx, _routed_mode
        elif mode == "project":
            context, _ = gather_project_context(project=project, db_path=db)
        else:
            context, _ = gather_test_context(question, project=project, db_path=db)

    if show_context:
        console.print("\n[bold dim]--- Context sent to LLM ---[/bold dim]")
        console.print(context)
        console.print("[bold dim]--- End context ---[/bold dim]\n")

    # Fallback: if test lookup found nothing, retry as a project-level question
    if mode == "test" and "No test matching" in context:
        console.print("[dim]No specific test matched — switching to project context…[/dim]")
        context, _ = gather_project_context(project=project, db_path=db)
        mode = "project"

    if "No test matching" in context and mode == "test":
        console.print(f"[yellow]{context}[/yellow]")
        console.print(
            "\nTip: ingest reports first with [bold]qalens ingest <report>[/bold]"
        )
        raise typer.Exit(code=1)

    # Call LLM
    from qalens.llm.client import LLMClient
    prompt = build_prompt(question, context, mode=mode, answer_plan=_answer_plan)

    try:
        with console.status(f"[dim]Asking {provider_name}…[/dim]"):
            answer = LLMClient(cfg).chat(
                prompt, system_prompt=build_system_prompt(_answer_plan)
            )
    except LLMError as exc:
        err_console.print(f"[red]LLM error:[/red] {exc}")
        err_console.print(
            f"Make sure {provider_name} is running. "
            "Run [bold]qalens llm-config[/bold] to change provider settings."
        )
        raise typer.Exit(code=1) from exc
    except ImportError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print()
    console.rule("[bold]Answer[/bold]")
    console.print(answer)
    console.rule()


@app.command(name="llm-config")
def llm_config(
    show: bool = typer.Option(
        False,
        "--show",
        help="Print the current configuration.",
    ),
    init: bool = typer.Option(
        False,
        "--init",
        help="Write the default config.toml template (if not already present).",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Set provider: ollama | openai | anthropic | gemini | lmstudio | custom",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Set the model name.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Set the API base URL.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="Set the API key.",
    ),
    test: bool = typer.Option(
        False,
        "--test",
        help="Send a connectivity test to the configured endpoint.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config TOML. Defaults to ~/.qalens/config.toml.",
    ),
) -> None:
    """View or update the LLM provider configuration.

    Configuration is stored in [bold]~/.qalens/config.toml[/bold].

    Examples::

        qalens llm-config --show
        qalens llm-config --init
        qalens llm-config --provider openai --model gpt-4o-mini --api-key sk-...
        qalens llm-config --provider ollama --model llama3.2
        qalens llm-config --test
    """
    from qalens.llm.config import (
        _PROVIDER_DEFAULTS,
        default_config_path,
        load_config,
        provider_display_name,
        save_default_config,
    )

    config_path = config or default_config_path()

    if init:
        path = save_default_config(config_path)
        if path.read_text().startswith("# QALens"):
            console.print(f"[green]Config template written:[/green] {path}")
        else:
            console.print(f"[yellow]Config already exists:[/yellow] {path}")
        return

    # Apply field updates by rewriting config.toml
    if any(v is not None for v in (provider, model, base_url, api_key)):
        cfg = load_config(config_path)
        if provider:
            cfg.provider = provider.lower()
            # Apply default URL/model for the new provider if not explicitly set
            if model is None and base_url is None:
                defaults = _PROVIDER_DEFAULTS.get(cfg.provider, {})
                cfg.model = defaults.get("model", cfg.model)
                cfg.base_url = defaults.get("base_url", cfg.base_url)
        if model:
            cfg.model = model
        if base_url:
            cfg.base_url = base_url
        if api_key is not None:
            cfg.api_key = api_key

        _write_config(config_path, cfg)
        console.print(f"[green]Config updated:[/green] {config_path}")
        show = True  # Always show after an update

    if show or not any((init, provider, model, base_url, api_key, test)):
        try:
            cfg = load_config(config_path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Cannot load config:[/red] {exc}")
            console.print(f"Run [bold]qalens llm-config --init[/bold] to create {config_path}")
            raise typer.Exit(code=1) from exc

        from rich.table import Table
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="bold dim")
        t.add_column()
        t.add_row("Config file", str(config_path))
        t.add_row("Provider", provider_display_name(cfg.provider))
        t.add_row("Base URL", cfg.effective_base_url)
        t.add_row("Model", cfg.model)
        t.add_row("API key", ("***" + cfg.effective_api_key[-4:]) if cfg.effective_api_key else "(none)")
        t.add_row("Timeout", f"{cfg.timeout}s")
        t.add_row("Max tokens", str(cfg.max_tokens))
        t.add_row("Temperature", str(cfg.temperature))
        console.print(t)

    if test:
        try:
            cfg = load_config(config_path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]Cannot load config:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        from qalens.llm.client import LLMClient
        console.print(f"Testing connectivity to [bold]{provider_display_name(cfg.provider)}[/bold]…")
        try:
            client = LLMClient(cfg)
            reachable = client.check_connectivity()
        except ImportError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        if reachable:
            console.print("[green]✓ Endpoint is reachable.[/green]")
        else:
            err_console.print(
                f"[red]✗ Cannot reach {cfg.effective_base_url}.[/red] "
                "Is the server running?"
            )
            raise typer.Exit(code=1)


def _write_config(config_path: Path, cfg: object) -> None:
    """Rewrite config.toml from an :class:`~qalens.llm.config.LLMConfig`."""
    from qalens.llm.config import LLMConfig
    assert isinstance(cfg, LLMConfig)
    lines = [
        "# QALens LLM configuration\n",
        "\n",
        "[llm]\n",
        f'provider    = "{cfg.provider}"\n',
        f'base_url    = "{cfg.base_url}"\n',
        f'model       = "{cfg.model}"\n',
        f'api_key     = "{cfg.api_key}"\n',
        f"timeout     = {cfg.timeout}\n",
        f"max_tokens  = {cfg.max_tokens}\n",
        f"temperature = {cfg.temperature}\n",
        f'system_prompt = "{cfg.system_prompt}"\n',
    ]
    config_path.write_text("".join(lines), encoding="utf-8")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host address to bind."),
    port: int = typer.Option(8080, "--port", "-p", help="TCP port to listen on."),
    project: str | None = typer.Option(
        None, "--project", "-P", help="Pre-select this project in the UI."
    ),
    db: Path | None = typer.Option(
        None,
        "--db",
        help="Path to QALens SQLite database (default: ~/.qalens/qalens.db).",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to LLM config.toml (default: ~/.qalens/config.toml).",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the browser automatically after startup.",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Enable uvicorn auto-reload (development mode).",
    ),
    allow_public_bind: bool = typer.Option(
        False,
        "--allow-public-bind",
        help="Allow binding to a public interface. Do not use without authentication or a trusted reverse proxy.",
    ),
    auth_token: str | None = typer.Option(
        None,
        "--auth-token",
        help="Require this bearer token for QALens API access. Can also be set with QALENS_AUTH_TOKEN.",
    ),
) -> None:
    """Start the QALens web UI on [bold]http://host:port[/bold].

    Launches a local FastAPI server with a browser-based dashboard for:
    run history, flakiness analysis, failure groups, digest reports,
    and LLM-powered Q&A.

    Examples::

        qalens serve
        qalens serve --port 9090 --project "Allure Report"
        qalens serve --no-open --host 0.0.0.0 --allow-public-bind
    """
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        err_console.print(
            "[red]uvicorn is not installed.[/red]  "
            "Run: [bold]pip install 'qalens-insights[serve]'[/bold]"
        )
        raise typer.Exit(code=1)

    from qalens.server.app import create_app
    from qalens.server.auth import resolve_auth_token

    if _is_public_bind_host(host) and not allow_public_bind:
        err_console.print(
            "[red]Refusing to bind QALens to a public interface by default.[/red] "
            "Use [bold]--allow-public-bind[/bold] only behind authentication or a trusted reverse proxy."
        )
        raise typer.Exit(code=2)

    db_path = str(db) if db else None
    cfg_path = str(config) if config else None
    effective_auth_token = resolve_auth_token(auth_token)

    application = create_app(
        db_path=db_path,
        config_path=cfg_path,
        default_project=project,
        auth_token=auth_token,
    )

    url = f"http://{host}:{port}"
    if _is_public_bind_host(host):
        auth_hint = (
            "API authentication is enabled for this server session."
            if effective_auth_token
            else "Set QALENS_AUTH_TOKEN or pass --auth-token before exposing QALens."
        )
        err_console.print(
            "\n[bold yellow]⚠  PUBLIC BINDING WARNING[/bold yellow]\n"
            f"   QALens is listening on [bold]{host}:{port}[/bold] — reachable by anyone on the network.\n"
            f"   {auth_hint}\n"
            "   Only expose QALens on trusted networks or behind a reverse proxy.\n"
            "   See SECURITY.md → Production Deployment Checklist.\n"
        )
    console.print(
        f"[bold]QALens[/bold] web UI starting at [link={url}][cyan]{url}[/cyan][/link]"
    )
    console.print("Press [bold]Ctrl+C[/bold] to stop.\n")

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(1.0)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        application,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
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


@app.command()
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

    clusters = client.cluster_report(run)

    if not clusters:
        console.print("[green]No failures found — all tests passed.[/green]")
        raise typer.Exit(code=0)

    console.print(
        f"[bold]Failure clusters[/bold] — {len(clusters)} group(s) "
        f"across {sum(c.size for c in clusters)} failing test(s)"
    )
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Size", justify="right", width=6)
    table.add_column("Signature", style="cyan", width=18)
    table.add_column("Category", width=28)
    table.add_column("Conf", justify="right", width=6)
    table.add_column("Label")

    for idx, cluster in enumerate(clusters, start=1):
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
        for idx, cluster in enumerate(clusters, start=1):
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
            for c in clusters
        ]
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"\n[green]Written:[/green] {out}")
