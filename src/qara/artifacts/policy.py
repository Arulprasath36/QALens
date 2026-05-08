"""Artifact ingestion policy — the single decision-making layer for artifacts.

:class:`ArtifactIngestionPolicy` is the *only* place where
:class:`~qara.artifacts.config.ArtifactMode` controls storage decisions.
Parsers are completely unaware of modes; they just emit
:class:`~qara.models.artifact_ref.ArtifactRef` objects.

Flow
----
1. **Select** — apply the per-failure screenshot cap and priority ranking.
2. **Decode** — base64-decode data URIs or read file paths.
3. **Inspect** — compute SHA-256, size, dimensions (no Pillow needed).
4. **Store** (full mode only) — optionally dedupe, optionally compress, write
   to the configured :class:`~qara.artifacts.storage.ArtifactStore`.
5. **Record** — build :class:`~qara.artifacts.models.ArtifactRecord` objects
   for bulk DB insertion.

Every step is failure-tolerant: exceptions are caught, a warning is logged,
and processing continues with the next ref.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from pathlib import Path

from qara.artifacts.config import ArtifactConfig, ArtifactMode
from qara.artifacts.image import compress_image, get_image_dimensions
from qara.artifacts.models import ArtifactIngestStats, ArtifactRecord
from qara.artifacts.selector import select_screenshots
from qara.artifacts.storage import ArtifactStore, mime_to_ext
from qara.models.artifact_ref import ArtifactRef
from qara.security import (
    MAX_SOURCE_REFERENCE_CHARS,
    SUPPORTED_IMAGE_EXTENSIONS,
    validate_image_bytes,
)

logger = logging.getLogger(__name__)

_DATA_URI_RE = re.compile(r"^data:([^;,\s]+);base64,(.+)$", re.DOTALL)

class ArtifactIngestionPolicy:
    """Applies the configured artifact mode to per-test artifact refs.

    Args:
        config: Ingestion configuration.
        store: Storage backend for ``full`` mode.  When ``None`` and
            ``mode == FULL``, storage is skipped (a warning is logged) but
            metadata records are still created.
    """

    def __init__(
        self,
        config: ArtifactConfig,
        store: ArtifactStore | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._total_screenshot_bytes = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        tc_id: str,
        refs: list[ArtifactRef],
        *,
        failure_id: int | None = None,
    ) -> tuple[list[ArtifactRecord], ArtifactIngestStats]:
        """Process artifact refs for one test case.

        Args:
            tc_id: The DB-stored ``tc_id`` (``"<run_id>::<test_id>"``) for the
                test case.  Used as the FK in the ``artifacts`` table.
            refs: Raw artifact refs produced by the parser.
            failure_id: Optional FK to the ``failures`` table row.

        Returns:
            ``(records, stats)`` where *records* are ready for
            :meth:`~qara.db.repository.RunRepository.save_artifacts`.
        """
        stats = ArtifactIngestStats(
            refs_found=len(refs),
            artifact_mode=self._config.mode.value,
        )

        if self._config.mode == ArtifactMode.TEXT_ONLY or not refs:
            return [], stats

        # Apply selection cap + priority ranking (screenshots only)
        selected = select_screenshots(
            refs,
            max_count=self._config.max_screenshots_per_failure,
        )
        stats.refs_selected = len(selected)

        records: list[ArtifactRecord] = []
        for i, ref in enumerate(selected):
            try:
                record = self._process_ref(
                    tc_id=tc_id,
                    ref=ref,
                    failure_id=failure_id,
                    is_primary=(i == 0),
                    run_stats=stats,
                )
                records.append(record)
                stats.records_created += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Artifact processing skipped for tc_id=%r seq=%d: %s",
                    tc_id,
                    ref.sequence_no,
                    exc,
                )
                stats.errors_skipped += 1

        return records, stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_ref(
        self,
        tc_id: str,
        ref: ArtifactRef,
        failure_id: int | None,
        is_primary: bool,
        run_stats: ArtifactIngestStats,
    ) -> ArtifactRecord:
        """Decode, inspect, optionally store, and build an ArtifactRecord."""
        data, reported_mime = _decode_ref(
            ref,
            max_bytes=self._config.max_screenshot_bytes,
        )
        if ref.kind == "screenshot" or (reported_mime or "").lower().startswith("image/"):
            mime_type = validate_image_bytes(data, reported_mime or ref.mime_type)
            if (
                self._total_screenshot_bytes + len(data)
                > self._config.max_total_screenshot_bytes_per_run
            ):
                raise ValueError(
                    "Run screenshot byte limit exceeded "
                    f"({self._config.max_total_screenshot_bytes_per_run} bytes)."
                )
            self._total_screenshot_bytes += len(data)
        else:
            mime_type = reported_mime

        # Content hash on *original* bytes (before compression)
        sha256 = hashlib.sha256(data).hexdigest()
        original_size = len(data)

        # Dimensions via header parsing — Pillow not required
        dims = get_image_dimensions(data)
        width, height = (dims[0], dims[1]) if dims else (None, None)

        # Source reference: truncated; never expose full base64 payload
        if ref.source_uri.startswith("data:"):
            # Keep the "data:<mime>;base64,..." prefix only (≤ 64 chars)
            prefix_end = ref.source_uri.find(",")
            src_ref = ref.source_uri[: prefix_end + 1] + "…" if prefix_end != -1 else "data:…"
        else:
            src_ref = ref.source_uri[:MAX_SOURCE_REFERENCE_CHARS]

        storage_uri: str | None = None
        if self._config.mode == ArtifactMode.FULL:
            storage_uri = self._store_artifact(
                data, sha256, mime_type, ref, run_stats
            )

        file_name = (ref.name or f"{sha256[:16]}{mime_to_ext(mime_type)}")[:256]

        return ArtifactRecord(
            tc_id=tc_id,
            artifact_type=ref.kind,
            failure_id=failure_id,
            storage_uri=storage_uri,
            source_reference=src_ref,
            file_name=file_name,
            mime_type=mime_type or None,
            size_bytes=original_size,
            sha256=sha256,
            width=width,
            height=height,
            sequence_no=ref.sequence_no,
            step_name=ref.step_name,
            is_primary=is_primary,
        )

    def _store_artifact(
        self,
        data: bytes,
        sha256: str,
        mime_type: str,
        ref: ArtifactRef,
        stats: ArtifactIngestStats,
    ) -> str | None:
        """Store artifact bytes, returning the storage URI (or ``None`` on failure)."""
        if self._store is None:
            logger.warning(
                "full mode requested but no ArtifactStore configured; "
                "metadata will be saved but image bytes will not be stored."
            )
            return None

        # Dedupe check
        if self._config.dedupe_images:
            existing_uri = self._store.exists(sha256)
            if existing_uri:
                stats.duplicates_skipped += 1
                logger.debug("Deduped artifact sha256=%s → %s", sha256[:16], existing_uri)
                return existing_uri

        # Compress if enabled (requires Pillow; falls back silently)
        store_data = data
        store_mime = mime_type
        if self._config.compress_images and mime_type.startswith("image/"):
            store_data, store_mime = compress_image(
                data,
                mime_type,
                max_width=self._config.max_image_width,
                jpeg_quality=self._config.jpeg_quality,
            )

        preferred = ref.name or f"{sha256[:16]}{mime_to_ext(mime_type)}"
        try:
            uri = self._store.store(store_data, sha256, store_mime, preferred)
            stats.images_stored += 1
            return uri
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to store artifact bytes: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


def _decode_ref(ref: ArtifactRef, *, max_bytes: int) -> tuple[bytes, str]:
    """Decode a :class:`~qara.models.artifact_ref.ArtifactRef` to ``(bytes, mime_type)``.

    Raises:
        ValueError: When the source URI cannot be decoded (bad base64,
            missing file, etc.).
    """
    uri = ref.source_uri

    m = _DATA_URI_RE.match(uri)
    if m:
        mime_type = m.group(1)
        b64_payload = m.group(2).strip()
        # Base64 expands data by roughly 4/3. Reject before allocating decoded
        # bytes when the encoded payload is clearly too large.
        if len(b64_payload) > max_bytes * 4 // 3 + 4:
            raise ValueError(f"Artifact exceeds {max_bytes}-byte limit.")
        try:
            data = base64.b64decode(b64_payload, validate=True)
        except Exception as exc:
            raise ValueError(f"Base64 decode failed: {exc}") from exc
        if len(data) > max_bytes:
            raise ValueError(f"Artifact exceeds {max_bytes}-byte limit.")
        return data, mime_type

    # Treat as a file path
    path = Path(uri)
    if not path.is_file():
        raise ValueError(f"Artifact file not found: {uri!r}")
    try:
        if path.stat().st_size > max_bytes:
            raise ValueError(f"Artifact exceeds {max_bytes}-byte limit.")
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read artifact file: {exc}") from exc
    mime_type = ref.mime_type or _ext_to_mime(path.suffix.lower()) or "application/octet-stream"
    return data, mime_type


_EXT_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
assert frozenset(_EXT_TO_MIME) == SUPPORTED_IMAGE_EXTENSIONS


def _ext_to_mime(ext: str) -> str | None:
    return _EXT_TO_MIME.get(ext)
