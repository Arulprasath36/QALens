"""Ask command: natural-language Q&A via the configured LLM."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


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
    from qalens.llm.deterministic_answers import answer_question

    deterministic_answer = answer_question(question, project=project, db_path=db)
    if deterministic_answer is not None:
        console.print()
        console.rule("[bold]Answer[/bold]")
        console.print(deterministic_answer)
        console.rule()
        return

    from qalens.llm.answer_plan import build_answer_plan, detect_answer_intent
    from qalens.llm.client import LLMError
    from qalens.llm.config import load_config, provider_display_name
    from qalens.llm.context import gather_project_context, gather_test_context
    from qalens.llm.context_history import extract_prior_context_from_history
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
    _answer_plan = build_answer_plan(detect_answer_intent(question), question=question)
    with console.status("[dim]Building context from database…[/dim]"):
        # LLM-powered intent + entity extraction (falls back to keywords if LLM unavailable)
        _intent = parse_query_intent(question, config=cfg)
        # Signal-based routing (owner, risk, duration, stability, trend, ranking, comparison)
        _signals = detect_signals(normalize_query(question))
        _routed_ctx, _routed_facts, _routed_src, _routed_mode = gather_context_for_signals(
            _signals, question, project=project, db_path=db, intent=_intent,
            answer_plan=_answer_plan,
        )
        _structured_facts: str | None = _routed_facts if _routed_facts else None
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
    prompt = build_prompt(question, context, mode=mode, answer_plan=_answer_plan, structured_facts=_structured_facts)

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
