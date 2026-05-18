"""Artifact storage abstraction and local filesystem backend.

``ArtifactStore`` is the abstract interface.  Additional backends (S3,
MinIO, GCS, etc.) can be added by implementing the three abstract methods.

``LocalFilesystemStore``
    Stores artifacts as ``<sha256[:16]><ext>`` files under a single base
    directory.  An accompanying ``sha256_index.txt`` enables O(1) duplicate
    detection without directory scans.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

# MIME → file extension mapping used by both storage and policy modules
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def mime_to_ext(mime_type: str) -> str:
    """Return the file extension (including dot) for *mime_type*, or ``".bin"``."""
    return _MIME_TO_EXT.get(mime_type.lower() if mime_type else "", ".bin")


class ArtifactStore(ABC):
    """Abstract artifact storage backend.

    Implementations must be idempotent: calling :meth:`store` twice with the
    same *sha256* must not create two copies of the data and must return the
    same URI both times.

    Public interface
    ----------------
    :meth:`store`
        Persist bytes and return a storage URI.
    :meth:`exists`
        Check for an existing artifact by SHA-256.
    :meth:`resolve_uri`
        Convert a storage URI back to a local :class:`~pathlib.Path`.
    """

    @abstractmethod
    def store(
        self,
        data: bytes,
        sha256: str,
        mime_type: str,
        preferred_name: str,
    ) -> str:
        """Persist artifact bytes and return a storage URI.

        Args:
            data: Raw image or artifact bytes.
            sha256: Hex SHA-256 digest of *data*.
            mime_type: MIME type of the artifact.
            preferred_name: Human-friendly filename suggestion (may be ignored).

        Returns:
            A string URI, e.g. ``"file:///home/user/.qalens/artifacts/abc123.png"``.
        """

    @abstractmethod
    def exists(self, sha256: str) -> str | None:
        """Return the storage URI if an artifact with *sha256* is already stored.

        Args:
            sha256: Hex SHA-256 to look up.

        Returns:
            URI string if found, ``None`` otherwise.
        """

    @abstractmethod
    def resolve_uri(self, uri: str) -> Path | None:
        """Resolve a storage URI to an absolute local filesystem path.

        Args:
            uri: A URI returned by :meth:`store`.

        Returns:
            :class:`~pathlib.Path` if the URI scheme is supported and the file
            exists, ``None`` otherwise.
        """


class LocalFilesystemStore(ArtifactStore):
    """Stores artifacts as files under a local base directory.

    **File naming**: ``<sha256_hex[:16]><ext>``.  The first 16 hex chars of the
    SHA-256 form a 64-bit collision-resistant prefix — sufficient for any
    realistic artifact set.

    **Deduplication index**: ``sha256_index.txt`` inside the base directory maps
    full SHA-256 → filename, one entry per line, tab-separated.  The index is
    loaded lazily and flushed after every successful write.

    Args:
        base_dir: Root directory for artifact storage.  Created on first write.
    """

    _INDEX_FILE = "sha256_index.txt"

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._index: dict[str, str] = {}   # sha256 → filename
        self._index_loaded: bool = False

    # ------------------------------------------------------------------
    # ArtifactStore interface
    # ------------------------------------------------------------------

    def store(
        self,
        data: bytes,
        sha256: str,
        mime_type: str,
        preferred_name: str,
    ) -> str:
        """Write *data* to disk and return a ``file://`` URI."""
        self._ensure_index_loaded()

        # Idempotent: don't overwrite if the same hash is already stored
        existing = self._index.get(sha256)
        if existing and (self._base_dir / existing).is_file():
            return self._to_uri(existing)

        ext = mime_to_ext(mime_type) or Path(preferred_name).suffix or ".bin"
        filename = f"{sha256[:16]}{ext}"
        dest = self._base_dir / filename

        self._base_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.debug("Stored artifact: %s (%d bytes)", dest, len(data))

        self._index[sha256] = filename
        self._flush_index()

        return self._to_uri(filename)

    def exists(self, sha256: str) -> str | None:
        """Return URI if an artifact with this SHA-256 is stored, else ``None``."""
        self._ensure_index_loaded()
        filename = self._index.get(sha256)
        if not filename:
            return None
        if (self._base_dir / filename).is_file():
            return self._to_uri(filename)
        # Stale index entry — remove it
        del self._index[sha256]
        self._flush_index()
        return None

    def resolve_uri(self, uri: str) -> Path | None:
        """Resolve a ``file://`` URI to a :class:`~pathlib.Path`."""
        if not uri.startswith("file://"):
            return None
        path = Path(uri[len("file://"):])
        try:
            resolved = path.resolve(strict=True)
            base = self._base_dir.resolve()
        except OSError:
            return None
        if resolved == base or not resolved.is_relative_to(base):
            return None
        return resolved if resolved.is_file() else None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _to_uri(self, filename: str) -> str:
        return f"file://{self._base_dir / filename}"

    def _ensure_index_loaded(self) -> None:
        if self._index_loaded:
            return
        index_file = self._base_dir / self._INDEX_FILE
        if index_file.is_file():
            try:
                for line in index_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if "\t" in line:
                        sha, fname = line.split("\t", 1)
                        clean_name = Path(fname.strip()).name
                        if clean_name == fname.strip():
                            self._index[sha.strip()] = clean_name
            except OSError as exc:
                logger.warning("Could not load artifact index: %s", exc)
        self._index_loaded = True

    def _flush_index(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        index_file = self._base_dir / self._INDEX_FILE
        lines = sorted(f"{sha}\t{fname}" for sha, fname in self._index.items())
        content = "\n".join(lines) + ("\n" if lines else "")
        try:
            index_file.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not flush artifact index: %s", exc)
