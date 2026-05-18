"""Data-intake CLI commands: detect, extract, ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from qalens.api.library import QaLensClient

console = Console()
err_console = Console(stderr=True)


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
    client = QaLensClient()
    result = client.detect_report(report_path)
    if result.matched:
        console.print(
            f"[green]Detected:[/green] [bold]{result.parser_name}[/bold] "
            f"(confidence {result.confidence:.0%})"
        )
        if verbose:
            for reason in result.reasons:
                console.print(f"  • {reason}")
    else:
        err_console.print(f"[red]Could not detect report format for:[/red] {report_path}")
        if verbose:
            err_console.print(f"Best confidence: {result.confidence:.0%}")
        raise typer.Exit(code=1)


def extract(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write normalized JSON to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
) -> None:
    """Extract and normalize a report to canonical JSON.

    Reads the report at REPORT_PATH, runs the appropriate parser, and
    writes the normalized ``TestRun`` as JSON. Prints to stdout if
    --out is not provided.
    """
    import json

    client = QaLensClient()
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


def ingest(
    report_path: Path = typer.Argument(
        ...,
        help="Path to a report directory or HTML file.",
        exists=True,
        readable=True,
    ),
    db: Optional[Path] = typer.Option(
        None,
        "--db",
        help="Path to QaLens SQLite database. Defaults to ~/.qalens/qalens.db.",
    ),
    attachments_dir: Optional[Path] = typer.Option(
        None,
        "--attachments-dir",
        help=(
            "[Legacy] Write base64 screenshots to this directory during parsing. "
            "Prefer --artifact-mode=full for new ingestions."
        ),
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-ingest even if this run already exists in the database.",
    ),
    owner_map: Optional[Path] = typer.Option(
        None,
        "--owner-map",
        help="JSON/TOML file mapping tests, suites, features, or tags to owners.",
        exists=True,
        readable=True,
    ),
    override_owners: bool = typer.Option(
        False,
        "--override-owners/--no-override-owners",
        help="Let --owner-map replace owner labels already present in the report.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    # ---- Artifact policy options ----
    artifact_mode: str = typer.Option(
        "metadata-only",
        "--artifact-mode",
        help=(
            "Artifact ingestion mode:\n\n"
            "  text-only     — no artifact records created\n\n"
            "  metadata-only — metadata (hash, size, dimensions) stored; no image bytes written\n\n"
            "  full          — metadata + image bytes stored to artifact storage"
        ),
    ),
    max_screenshots_per_failure: int = typer.Option(
        2,
        "--max-screenshots-per-failure",
        min=0,
        help="Maximum screenshots retained per failed test (0 = unlimited).",
    ),
    max_screenshot_bytes: int = typer.Option(
        5 * 1024 * 1024,
        "--max-screenshot-bytes",
        min=1024,
        help="Maximum bytes allowed for one screenshot artifact.",
    ),
    max_total_screenshot_bytes: int = typer.Option(
        50 * 1024 * 1024,
        "--max-total-screenshot-bytes",
        min=1024,
        help="Maximum screenshot bytes decoded for one run.",
    ),
    compress_images: bool = typer.Option(
        True,
        "--compress-images/--no-compress-images",
        help="Apply resize/quality reduction before storing (requires Pillow).",
    ),
    max_image_width: int = typer.Option(
        1600,
        "--max-image-width",
        min=64,
        help="Maximum image width in pixels (full mode only).",
    ),
    jpeg_quality: int = typer.Option(
        80,
        "--jpeg-quality",
        min=1,
        max=95,
        help="JPEG/WebP compression quality (1-95, full mode only).",
    ),
    generate_thumbnails: bool = typer.Option(
        False,
        "--generate-thumbnails/--no-generate-thumbnails",
        help="[Reserved] Generate thumbnail images alongside full-size (not yet active).",
    ),
    dedupe_images: bool = typer.Option(
        True,
        "--dedupe-images/--no-dedupe-images",
        help="Skip storing image bytes when the same content hash already exists.",
    ),
    artifact_storage_dir: Optional[Path] = typer.Option(
        None,
        "--artifact-storage-dir",
        help=(
            "Root directory for image storage (full mode only). "
            "Defaults to a sibling 'artifacts/' folder next to the database."
        ),
    ),
) -> None:
    """Parse a report and store it in the local QaLens database.

    On subsequent calls with the same report the run is skipped (idempotent).
    Use --force to overwrite an existing run.

    \\b
    Artifact ingestion modes
    ------------------------
    text-only     Store only textual failure data; no images or artifact metadata.
    metadata-only Store textual data + artifact metadata (hash, size, dimensions).
                  Default. Safe and lightweight; no image bytes written.
    full          Store textual data + metadata + image bytes.
                  Requires writable artifact storage directory.
    """
    from qalens.artifacts.config import ArtifactConfig, ArtifactMode
    from qalens.models.test_case import TestStatus

    # Validate artifact mode
    try:
        mode = ArtifactMode(artifact_mode)
    except ValueError:
        err_console.print(
            f"[red]Invalid --artifact-mode:[/red] {artifact_mode!r}. "
            "Choose from: text-only, metadata-only, full."
        )
        raise typer.Exit(code=1)

    artifact_config = ArtifactConfig(
        mode=mode,
        max_screenshots_per_failure=max_screenshots_per_failure,
        max_screenshot_bytes=max_screenshot_bytes,
        max_total_screenshot_bytes_per_run=max_total_screenshot_bytes,
        compress_images=compress_images,
        max_image_width=max_image_width,
        jpeg_quality=jpeg_quality,
        generate_thumbnails=generate_thumbnails,
        dedupe_images=dedupe_images,
        storage_dir=artifact_storage_dir,
    )

    # Legacy attachments_dir: only pass through when explicitly provided AND
    # artifact_mode is not full (to avoid double-writing screenshots).
    _legacy_attachments_dir: Path | None = None
    if attachments_dir is not None and mode != ArtifactMode.FULL:
        _legacy_attachments_dir = attachments_dir

    client = QaLensClient()
    try:
        run, inserted, artifact_stats = client.ingest_report(
            report_path,
            db_path=db,
            attachments_dir=_legacy_attachments_dir,
            skip_if_exists=not force,
            artifact_config=artifact_config,
            owner_map_path=owner_map,
            override_owners=override_owners,
        )
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not inserted:
        console.print(
            f"[yellow]Skipped:[/yellow] run [bold]{run.metadata.run_id}[/bold] "
            "already in database. Use --force to re-ingest."
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
    skipped_count = by_status.get(TestStatus.SKIPPED, 0)

    console.print(
        f"Tests  : {total} total  "
        f"[green]{passed} passed[/green]  "
        f"[red]{failed} failed[/red]  "
        f"[yellow]{skipped_count} skipped[/yellow]"
    )

    db_display = db or (Path.home() / ".qalens" / "qalens.db")
    console.print(f"Stored → [dim]{db_display}[/dim]")

    # Artifact ingestion summary
    _print_artifact_summary(artifact_stats, mode.value)

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


def _print_artifact_summary(
    stats: object,
    mode_label: str,
) -> None:
    """Print the artifact ingestion summary block."""
    console.print(f"\n[bold]Artifact ingestion[/bold] (mode: [cyan]{mode_label}[/cyan])")
    if stats is None:
        console.print("  No artifact policy applied.")
        return

    from qalens.artifacts.models import ArtifactIngestStats
    if not isinstance(stats, ArtifactIngestStats):
        return

    console.print(f"  Screenshot refs found    : {stats.refs_found}")
    if mode_label == "text-only":
        console.print("  [dim]All artifact refs discarded (text-only mode)[/dim]")
        return

    console.print(f"  Selected after cap       : {stats.refs_selected}")
    console.print(f"  Artifact records created : {stats.records_created}")
    if mode_label == "full":
        console.print(f"  Images stored            : {stats.images_stored}")
        if stats.duplicates_skipped:
            console.print(f"  Duplicates skipped       : [dim]{stats.duplicates_skipped}[/dim]")
    if stats.errors_skipped:
        console.print(
            f"  [yellow]Skipped (bad/missing)  : {stats.errors_skipped}[/yellow]"
        )
