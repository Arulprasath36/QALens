"""QARA command-line interface.

Built with Typer. Entry point registered in ``pyproject.toml`` as ``qara``.

Usage examples::

    qara detect ./reports/allure-report
    qara extract ./reports/allure-report --out extracted.json
    qara analyze ./reports/allure-report --history ./history --out analysis.json
    qara summarize ./reports/extent-report --format markdown --out summary.md
    qara clusters ./reports/allure-report
"""

from __future__ import annotations

import typer
from rich.console import Console

from qara.version import __version__

app = typer.Typer(
    name="qara",
    help=(
        "QARA — Automated Root-cause Insights.\n\n"
        "Transforms static test HTML reports into triage-ready intelligence.\n\n"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"qara version [bold]{__version__}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Print QARA version and exit.",
        callback=_version_callback,
        is_eager=True,
        show_default=False,
    ),
) -> None:
    """QARA — Automated Root-cause Insights."""


# ---------------------------------------------------------------------------
# Register commands from sub-modules
# ---------------------------------------------------------------------------

from qara.cli.commands.ingest import detect, extract, ingest  # noqa: E402
from qara.cli.commands.analyze import analyze, digest, summarize, clusters  # noqa: E402
from qara.cli.commands.ask import ask  # noqa: E402
from qara.cli.commands.config import llm_config  # noqa: E402
from qara.cli.commands.serve import serve  # noqa: E402

app.command()(detect)
app.command()(extract)
app.command()(ingest)
app.command()(analyze)
app.command()(digest)
app.command()(ask)
app.command(name="llm-config")(llm_config)
app.command()(serve)
app.command()(summarize)
app.command()(clusters)
