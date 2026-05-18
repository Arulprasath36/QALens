"""LLM configuration command."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


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
        if path.read_text().startswith("# QaLens"):
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
        "# QaLens LLM configuration\n",
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
