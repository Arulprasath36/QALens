"""Artifact ingestion policy, storage, and image processing for QALens.

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
    the configured :class:`~qalens.artifacts.storage.ArtifactStore`.

Public re-exports
-----------------
``ArtifactMode``, ``ArtifactConfig``
    Configuration objects — pass to :meth:`~qalens.api.library.QALensClient.ingest_report`.

``ArtifactIngestStats``
    Per-run statistics returned by :meth:`~qalens.api.library.QALensClient.ingest_report`.
"""

from qalens.artifacts.config import ArtifactConfig, ArtifactMode
from qalens.artifacts.models import ArtifactIngestStats, ArtifactRecord
from qalens.artifacts.policy import ArtifactIngestionPolicy
from qalens.artifacts.storage import ArtifactStore, LocalFilesystemStore

__all__ = [
    "ArtifactConfig",
    "ArtifactIngestStats",
    "ArtifactIngestionPolicy",
    "ArtifactMode",
    "ArtifactRecord",
    "ArtifactStore",
    "LocalFilesystemStore",
]
