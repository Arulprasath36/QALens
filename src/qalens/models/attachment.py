"""Attachment model for QaLens.

Attachments represent files linked to a test execution — screenshots,
log files, videos, HAR traces, or any other artifact captured during
or after the test run.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class AttachmentKind(str, Enum):
    """Enumeration of known attachment types.

    Values are kept lowercase and hyphenated for serialization consistency.
    ``UNKNOWN`` is used when the type cannot be determined from the file
    extension or metadata.
    """

    SCREENSHOT = "screenshot"
    LOG = "log"
    VIDEO = "video"
    HAR = "har"
    XML = "xml"
    JSON = "json"
    HTML = "html"
    TEXT = "text"
    UNKNOWN = "unknown"

    @classmethod
    def from_mime(cls, mime_type: str) -> "AttachmentKind":
        """Infer an ``AttachmentKind`` from a MIME type string.

        Args:
            mime_type: A MIME type string such as ``image/png`` or
                ``text/plain``.

        Returns:
            The best-matching ``AttachmentKind``, or ``UNKNOWN`` if no
            mapping exists.
        """
        mime = mime_type.lower()
        if mime.startswith("image/"):
            return cls.SCREENSHOT
        if mime in {"video/mp4", "video/webm", "video/ogg"}:
            return cls.VIDEO
        if mime == "application/json":
            return cls.JSON
        if mime == "text/html":
            return cls.HTML
        if mime == "text/xml" or mime == "application/xml":
            return cls.XML
        if mime.startswith("text/"):
            return cls.TEXT
        return cls.UNKNOWN

    @classmethod
    def from_path(cls, path: str | Path) -> "AttachmentKind":
        """Infer an ``AttachmentKind`` from a file path's extension.

        Args:
            path: A file path or filename string.

        Returns:
            The best-matching ``AttachmentKind``, or ``UNKNOWN`` if the
            extension is not recognised.
        """
        suffix = Path(path).suffix.lower()
        mapping: dict[str, "AttachmentKind"] = {
            ".png": cls.SCREENSHOT,
            ".jpg": cls.SCREENSHOT,
            ".jpeg": cls.SCREENSHOT,
            ".gif": cls.SCREENSHOT,
            ".webp": cls.SCREENSHOT,
            ".bmp": cls.SCREENSHOT,
            ".mp4": cls.VIDEO,
            ".webm": cls.VIDEO,
            ".log": cls.LOG,
            ".txt": cls.TEXT,
            ".json": cls.JSON,
            ".xml": cls.XML,
            ".html": cls.HTML,
            ".htm": cls.HTML,
            ".har": cls.HAR,
        }
        return mapping.get(suffix, cls.UNKNOWN)


class Attachment(BaseModel):
    """A file artifact captured during or after a test execution.

    Attachments are resolved relative to the report root directory.
    The ``resolved_path`` field is populated by the parser when the
    file is confirmed to exist on disk.

    Attributes:
        name: Human-readable name or label for the attachment.
        kind: The type of attachment (screenshot, log, video, etc.).
        path: The relative or absolute path as recorded in the report.
        resolved_path: Absolute path on disk, set by the parser if the
            file was found. ``None`` if the file could not be located.
        mime_type: The MIME type of the attachment, if known.
        size_bytes: File size in bytes, if known.
        source: The source report format that produced this attachment
            (e.g. ``"allure"``, ``"extent"``).
    """

    name: str = Field(..., description="Human-readable label for this attachment.")
    kind: AttachmentKind = Field(
        default=AttachmentKind.UNKNOWN,
        description="Computed type of the attachment.",
    )
    path: str = Field(..., description="Path as recorded in the source report.")
    resolved_path: Path | None = Field(
        default=None,
        description="Absolute path on disk, populated when the file exists.",
    )
    mime_type: str | None = Field(
        default=None,
        description="MIME type if declared in the report.",
    )
    size_bytes: int | None = Field(
        default=None,
        description="File size in bytes if available.",
        ge=0,
    )
    source: str | None = Field(
        default=None,
        description="Report format that produced this attachment (e.g. 'allure').",
    )

    model_config = {"frozen": True}
