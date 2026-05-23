"""Security helpers shared by ingestion and artifact handling.

Report files and artifact references are untrusted input.  Keep these helpers
small and dependency-free so parsers and policies can enforce the same basic
rules without duplicating ad-hoc checks.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

MAX_LLM_PROMPT_CHARS = 80_000
MAX_ASK_QUESTION_CHARS = 4_000
MAX_ASK_HISTORY_ITEMS = 12
MAX_COMPARE_RUN_IDS = 50
MAX_COMPARE_ENTITY_CHARS = 200
MAX_COMPARE_PROJECT_CHARS = 200
MAX_COMPARE_SEARCH_CHARS = 500
MAX_SOURCE_REFERENCE_CHARS = 512

# Ingestion field-length limits (applied during parsing before DB storage)
MAX_TEST_NAME_CHARS = 1_024
MAX_SUITE_CHARS = 512
MAX_OWNER_CHARS = 256
MAX_ERROR_MESSAGE_CHARS = 50_000
MAX_STACK_TRACE_CHARS = 100_000
MAX_LOG_LINE_CHARS = 10_000
MAX_TESTS_PER_RUN = 100_000
MAX_ATTACHMENTS_PER_TEST = 100

# Query-parameter length limits (applied at API boundary)
MAX_QUERY_PROJECT_CHARS = 200
MAX_QUERY_RUN_ID_CHARS = 128
MAX_QUERY_OWNER_CHARS = 256
MAX_QUERY_SUITE_CHARS = 512
MAX_QUERY_TIER_CHARS = 16

SUPPORTED_REPORT_FILE_EXTENSIONS = frozenset({".html", ".htm", ".json", ".xml"})
SUPPORTED_SQLITE_EXTENSIONS = frozenset({".db", ".sqlite", ".sqlite3"})
SUPPORTED_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
})
SUPPORTED_IMAGE_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
})
ALLOWED_TEST_STATUSES = frozenset({
    "passed",
    "failed",
    "broken",
    "skipped",
    "pending",
    "unknown",
})
ALLOWED_FAILURE_CATEGORIES = frozenset({
    "element_not_found",
    "stale_element",
    "timeout",
    "assertion",
    "null_pointer",
    "network",
    "authentication",
    "infrastructure",
    "test_data",
    "permission",
    "configuration",
    "unknown",
})
LOCAL_LLM_PROVIDERS = frozenset({"ollama", "lmstudio"})
EXTERNAL_LLM_OPT_IN_ENV = "QALENS_ALLOW_EXTERNAL_LLM"
UNTRUSTED_DATA_START = "===== BEGIN UNTRUSTED REPORT DATA ====="
UNTRUSTED_DATA_END = "===== END UNTRUSTED REPORT DATA ====="


def is_local_llm_endpoint(base_url: str | None) -> bool:
    """Return True when an LLM endpoint clearly targets the local machine."""
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ── Private keys ──────────────────────────────────────────────────────────
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # ── AWS ──────────────────────────────────────────────────────────────────
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"\b(?:ASIA|AROA|AIDA|ANPA|ANVA|AIPA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # ── GitHub ───────────────────────────────────────────────────────────────
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # ── Slack ────────────────────────────────────────────────────────────────
    (re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{30,}"), "[REDACTED_SLACK_WEBHOOK]"),
    (re.compile(r"\bxapp-1-[A-Za-z0-9_\-]{60,}\b"), "[REDACTED_SLACK_APP_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    # ── Anthropic ────────────────────────────────────────────────────────────
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{40,}\b"), "[REDACTED_ANTHROPIC_KEY]"),
    # ── OpenAI / generic sk- keys ────────────────────────────────────────────
    (re.compile(r"\bsk-(?:live|test|proj|or|)[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # ── GCP ──────────────────────────────────────────────────────────────────
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"), "[REDACTED_GCP_API_KEY]"),
    (re.compile(r"\bya29\.[A-Za-z0-9_\-]{60,}\b"), "[REDACTED_GCP_OAUTH_TOKEN]"),
    # ── npm ──────────────────────────────────────────────────────────────────
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "[REDACTED_NPM_TOKEN]"),
    # ── Azure ────────────────────────────────────────────────────────────────
    (
        re.compile(
            r"DefaultEndpointProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{30,}"
        ),
        "[REDACTED_AZURE_CONNECTION_STRING]",
    ),
    # ── JWTs ─────────────────────────────────────────────────────────────────
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED_JWT]",
    ),
    # ── Bearer tokens ────────────────────────────────────────────────────────
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"), "Bearer [REDACTED_TOKEN]"),
    # ── Generic key=value secrets ────────────────────────────────────────────
    (
        re.compile(
            r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token"
            r"|password|passwd|pwd|secret|private[_-]?key|client[_-]?secret)\b"
            r"(\s*[:=]\s*)"
            r"([^\s,;'\"]{8,})"
        ),
        r"\1\2[REDACTED]",
    ),
    # ── Database / connection strings ────────────────────────────────────────
    (
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|mssql|sqlserver)://"
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

    QA Lens supports an explicit ``:memory:`` database for tests. File-backed
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
        + "\n\n[QA Lens SECURITY NOTE: prompt text was truncated before LLM submission.]"
    )


def wrap_untrusted_data(text: str) -> str:
    """Wrap report-derived prompt context in explicit untrusted-data markers."""
    return f"{UNTRUSTED_DATA_START}\n{text}\n{UNTRUSTED_DATA_END}"


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
