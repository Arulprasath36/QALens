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

import typer
from rich.console import Console

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


# ---------------------------------------------------------------------------
# Register commands from sub-modules
# ---------------------------------------------------------------------------

from qalens.cli.commands.analyze import analyze, clusters, summarize  # noqa: E402
from qalens.cli.commands.ask import ask  # noqa: E402
from qalens.cli.commands.compare import compare  # noqa: E402
from qalens.cli.commands.config import llm_config  # noqa: E402
from qalens.cli.commands.history import history  # noqa: E402
from qalens.cli.commands.ingest import detect, extract, ingest  # noqa: E402
from qalens.cli.commands.report import report  # noqa: E402
from qalens.cli.commands.serve import serve  # noqa: E402

app.command()(detect)
app.command()(extract)
app.command()(ingest)
app.command()(analyze)
app.command()(report)
app.command()(compare)
app.command()(history)
app.command()(ask)
app.command(name="llm-config")(llm_config)
app.command()(serve)
app.command()(summarize)
app.command()(clusters)
