"""Serve command: launch the QALens web UI."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def _is_public_bind_host(host: str) -> bool:
    """Return True when *host* binds beyond loopback interfaces."""
    normalized = host.strip().lower()
    return normalized in {"0.0.0.0", "::", "[::]"}


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
