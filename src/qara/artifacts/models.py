"""Data-transfer objects internal to the artifact pipeline.

``ArtifactRecord``
    Produced by :class:`~qara.artifacts.policy.ArtifactIngestionPolicy`.
    Ready for insertion into the ``artifacts`` DB table.

``ArtifactIngestStats``
    Collects per-run counters and is returned by
    :meth:`~qara.api.library.QARAClient.ingest_report` alongside the
    ``(TestRun, inserted)`` tuple.

Note: ``ArtifactRef`` lives in ``qara.models.artifact_ref`` (not here) so
that parsers can import it without pulling in the full artifacts sub-package.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ArtifactRecord:
    """A processed artifact ready for insertion into the ``artifacts`` DB table.

    Produced by :meth:`~qara.artifacts.policy.ArtifactIngestionPolicy.process`
    after applying the configured :class:`~qara.artifacts.config.ArtifactMode`.

    Attributes:
        tc_id: DB-stored ``tc_id`` key in the ``test_cases`` table.
        artifact_type: Artifact category, e.g. ``"screenshot"`` or ``"log"``.
        failure_id: Optional FK to ``failures(id)`` for tight linkage.
        storage_uri: URI to stored bytes (``file:///…``).  ``None`` when the
            mode is ``metadata-only`` or storage failed non-fatally.
        source_reference: Truncated source URI/path (first 512 chars).  For
            base64 data URIs the payload is stripped and replaced with the
            mime/encoding prefix only.
        file_name: Original or derived filename (max 256 chars).
        mime_type: MIME type of the image.
        size_bytes: Byte count of the *original* artifact (before compression).
        sha256: Hex SHA-256 of the *original* bytes.
        width: Image width in pixels, if determinable without Pillow.
        height: Image height in pixels, if determinable without Pillow.
        sequence_no: Zero-based position index within the test case.
        step_name: Step name this artifact was attached to.
        is_primary: ``True`` for the first / highest-priority artifact
            selected for the test.
        metadata_json: Free-form JSON string for extra key-value metadata.
        created_at: Unix timestamp of record creation.
    """

    tc_id: str
    artifact_type: str = "screenshot"
    failure_id: int | None = None
    storage_uri: str | None = None
    source_reference: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    sequence_no: int = 0
    step_name: str | None = None
    is_primary: bool = False
    metadata_json: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class ArtifactIngestStats:
    """Per-run artifact processing counters.

    Returned by :meth:`~qara.api.library.QARAClient.ingest_report` alongside
    the ``(TestRun, inserted)`` pair.  Used by the CLI to print the
    end-of-run ingestion summary.

    Attributes:
        refs_found: Total artifact references found by the parser.
        refs_selected: References remaining after the screenshot cap.
        records_created: DB records successfully created.
        images_stored: Image files written to the artifact store (full mode).
        duplicates_skipped: Refs whose SHA-256 already existed in the store.
        errors_skipped: Refs that failed processing non-fatally (bad base64,
            missing file, corrupt image, etc.).
        artifact_mode: The ``ArtifactMode`` value used for the run.
    """

    refs_found: int = 0
    refs_selected: int = 0
    records_created: int = 0
    images_stored: int = 0
    duplicates_skipped: int = 0
    errors_skipped: int = 0
    artifact_mode: str = "text-only"

    def merge(self, other: "ArtifactIngestStats") -> None:
        """Add *other*'s counters into this instance in-place."""
        self.refs_found += other.refs_found
        self.refs_selected += other.refs_selected
        self.records_created += other.records_created
        self.images_stored += other.images_stored
        self.duplicates_skipped += other.duplicates_skipped
        self.errors_skipped += other.errors_skipped
