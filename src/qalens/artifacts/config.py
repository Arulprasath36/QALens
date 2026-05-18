"""Configuration models for the artifact ingestion pipeline.

``ArtifactMode`` defines the three ingestion tiers.
``ArtifactConfig`` collects every knob the pipeline exposes so callers can
pass a single object rather than a proliferating keyword-argument list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ArtifactMode(str, Enum):
    """Controls how screenshot artifacts are handled during ingestion.

    Attributes:
        TEXT_ONLY: Ingest text (name, status, failure message, stack trace,
            logs, step names).  All artifact references are discarded after
            parsing.  The ``artifacts`` DB table is left empty for the run.
        METADATA_ONLY: Everything from ``TEXT_ONLY`` plus lightweight artifact
            metadata persisted to the DB (content hash, MIME type, dimensions,
            sequence number, etc.).  No image bytes are written.
        FULL: Everything from ``METADATA_ONLY`` plus image bytes written to the
            configured :class:`~qalens.artifacts.storage.ArtifactStore`.
            Optional compression/resizing is applied before storage.
    """

    TEXT_ONLY = "text-only"
    METADATA_ONLY = "metadata-only"
    FULL = "full"


@dataclass
class ArtifactConfig:
    """Complete configuration for the artifact ingestion pipeline.

    Attributes:
        mode: Ingestion tier — text-only / metadata-only / full.
        max_screenshots_per_failure: Hard cap on screenshots retained per
            failed test.  The :func:`~qalens.artifacts.selector.select_screenshots`
            function applies a priority ranking before truncation.
        compress_images: Apply resize/quality reduction before storage in
            ``full`` mode.  Requires Pillow; silently skipped if unavailable.
        max_image_width: Maximum pixel width after resizing.  Aspect ratio is
            preserved; images narrower than this value are not upscaled.
        jpeg_quality: JPEG/WebP quality (1–95) used during compression.
        generate_thumbnails: Generate a small thumbnail alongside the
            full-size image in ``full`` mode.  Not yet implemented; reserved
            for future use.
        dedupe_images: Skip writing bytes when an artifact with the same
            SHA-256 already exists in the store.  A DB record still points to
            the existing stored file.
        max_screenshot_bytes: Maximum bytes allowed for one screenshot.
        max_total_screenshot_bytes_per_run: Maximum screenshot bytes decoded
            for a single run.
        storage_dir: Root directory for the
            :class:`~qalens.artifacts.storage.LocalFilesystemStore`.  Required
            when ``mode == FULL``.  Defaults to ``~/.qalens/artifacts/`` in
            :meth:`~qalens.api.library.QaLensClient.ingest_report`.
    """

    mode: ArtifactMode = ArtifactMode.METADATA_ONLY
    max_screenshots_per_failure: int = 2
    compress_images: bool = True
    max_image_width: int = 1600
    jpeg_quality: int = 80
    generate_thumbnails: bool = False
    dedupe_images: bool = True
    max_screenshot_bytes: int = 5 * 1024 * 1024
    max_total_screenshot_bytes_per_run: int = 50 * 1024 * 1024
    storage_dir: Path | None = field(default=None)
