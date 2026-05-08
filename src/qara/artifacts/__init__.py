"""Artifact ingestion policy, storage, and image processing for QARA.

Three ingestion modes
---------------------
``text-only``
    Only textual failure information is ingested.  No artifact records are
    created and no bytes are written.

``metadata-only`` *(default)*
    Textual information plus artifact metadata (content hash, dimensions,
    MIME type, sequence number, etc.) is persisted.  No image bytes are
    written to external storage.

``full``
    Everything from ``metadata-only`` plus compressed image bytes stored in
    the configured :class:`~qara.artifacts.storage.ArtifactStore`.

Public re-exports
-----------------
``ArtifactMode``, ``ArtifactConfig``
    Configuration objects — pass to :meth:`~qara.api.library.QARAClient.ingest_report`.

``ArtifactIngestStats``
    Per-run statistics returned by :meth:`~qara.api.library.QARAClient.ingest_report`.
"""

from qara.artifacts.config import ArtifactConfig, ArtifactMode
from qara.artifacts.models import ArtifactIngestStats, ArtifactRecord
from qara.artifacts.policy import ArtifactIngestionPolicy
from qara.artifacts.storage import ArtifactStore, LocalFilesystemStore

__all__ = [
    "ArtifactConfig",
    "ArtifactIngestStats",
    "ArtifactIngestionPolicy",
    "ArtifactMode",
    "ArtifactRecord",
    "ArtifactStore",
    "LocalFilesystemStore",
]
