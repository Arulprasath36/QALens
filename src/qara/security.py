"""Security helpers shared by ingestion and artifact handling.

Report files and artifact references are untrusted input.  Keep these helpers
small and dependency-free so parsers and policies can enforce the same basic
rules without duplicating ad-hoc checks.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_LLM_PROMPT_CHARS = 80_000
SUPPORTED_REPORT_FILE_EXTENSIONS = frozenset({".html", ".htm", ".json"})
SUPPORTED_SQLITE_EXTENSIONS = frozenset({".db", ".sqlite", ".sqlite3"})
SUPPORTED_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
})

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bsk-(?:live|test|proj|ant|or|)[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
        "[REDACTED_JWT]",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
    (
        re.compile(
            r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|pwd|secret)\b"
            r"(\s*[:=]\s*)"
            r"([^\s,;'\"]{6,})"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
            r"[^:\s/@]+:[^@\s]+@[^\s]+"
        ),
        "[REDACTED_CONNECTION_STRING]",
    ),
)


def validate_report_input_path(path: Path) -> None:
    """Reject unsupported single-file report inputs before parser detection.

    Directories are allowed because Allure and Extent commonly emit report
    folders. Single files must use an explicitly supported extension.
    """
    if path.is_dir():
        return
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_REPORT_FILE_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_REPORT_FILE_EXTENSIONS))
        raise ValueError(f"Unsupported report file type {suffix!r}. Allowed: {allowed}.")


def validate_sqlite_db_path(db_path: str | Path) -> str | Path:
    """Validate a user-configured SQLite database path.

    QARA supports an explicit ``:memory:`` database for tests. File-backed
    databases must be normal filesystem paths with SQLite-like extensions; this
    prevents accidental writes to arbitrary special URI-style locations.
    """
    if str(db_path) == ":memory:":
        return ":memory:"

    raw = str(db_path)
    if raw.startswith("file:"):
        raise ValueError("SQLite URI database paths are not supported.")

    path = Path(db_path).expanduser()
    if path.exists() and path.is_dir():
        raise ValueError("SQLite database path must be a file, not a directory.")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SQLITE_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_SQLITE_EXTENSIONS))
        raise ValueError(f"Unsupported SQLite database extension {suffix!r}. Allowed: {allowed}.")

    resolved_parent = path.parent.resolve(strict=False)
    resolved = resolved_parent / path.name
    return resolved


def redact_secrets(text: str) -> str:
    """Redact common secret patterns from untrusted report-derived text."""
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def prepare_llm_prompt_text(text: str, *, max_chars: int = MAX_LLM_PROMPT_CHARS) -> str:
    """Sanitize, redact, and bound text before it is sent to an LLM provider."""
    cleaned = text.encode("utf-8", errors="ignore").decode("utf-8")
    cleaned = redact_secrets(cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    return (
        cleaned[:max_chars]
        + "\n\n[QARA SECURITY NOTE: prompt text was truncated before LLM submission.]"
    )


def sniff_image_mime(data: bytes) -> str | None:
    """Return the image MIME type indicated by file magic bytes.

    SVG is intentionally not accepted as an image artifact because it can carry
    active content when served back to a browser.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


def normalize_reported_image_mime(mime_type: str | None) -> str | None:
    """Normalize a parser- or extension-reported image MIME type."""
    if not mime_type:
        return None
    value = mime_type.lower().split(";", 1)[0].strip()
    if value == "image/jpg":
        return "image/jpeg"
    return value


def validate_image_bytes(data: bytes, reported_mime: str | None = None) -> str:
    """Validate image bytes and return the trusted MIME type.

    Raises:
        ValueError: if bytes are not a supported raster image or if the
            reported MIME conflicts with the detected content.
    """
    detected = sniff_image_mime(data)
    if detected is None:
        raise ValueError("Unsupported or unrecognized image content.")

    reported = normalize_reported_image_mime(reported_mime)
    if reported and reported not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"Unsupported image MIME type: {reported}.")
    if reported and reported != detected:
        raise ValueError(f"Image MIME mismatch: reported {reported}, detected {detected}.")
    return detected
