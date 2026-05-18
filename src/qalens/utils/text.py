"""Text processing utilities for QALens parsers.

Small, pure helpers for cleaning and transforming strings extracted from
HTML reports.  No I/O, no parsing — just string operations.
"""

from __future__ import annotations

import re


def clean_html_text(text: str) -> str:
    """Strip HTML tags and normalize whitespace in *text*.

    Converts ``<br>``, ``<p>``, and ``<li>`` tags to newlines before
    stripping, so that multi-paragraph descriptions preserve line breaks.

    Args:
        text: Raw text that may contain HTML markup.

    Returns:
        A clean plain-text string with normalized whitespace.
    """
    # Block-level tags → newlines
    text = re.sub(r"<(?:br\s*/?|/p|/li)>", "\n", text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse runs of whitespace, preserve intentional newlines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Remove empty leading/trailing lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def truncate(text: str, max_chars: int = 2000, ellipsis: str = "…") -> str:
    """Truncate *text* to at most *max_chars* characters.

    If truncation is needed the *ellipsis* string is appended.

    Args:
        text: The input string.
        max_chars: Maximum number of characters to keep.
        ellipsis: String appended when truncation occurs.

    Returns:
        The (possibly truncated) string.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + ellipsis


def first_nonempty(*values: str | None) -> str | None:
    """Return the first non-empty, non-None string in *values*.

    Args:
        *values: Candidate strings, in priority order.

    Returns:
        The first candidate that is truthy after stripping, or ``None``
        if all are empty/None.
    """
    for v in values:
        if v and v.strip():
            return v.strip()
    return None


def parse_epoch_ms(value: int | float | str | None) -> int | None:
    """Parse a millisecond epoch timestamp from various source formats.

    Accepts integer, float, or numeric string values.  Returns ``None``
    for ``None``, empty strings, or non-numeric values.

    Args:
        value: The raw timestamp value from a report.

    Returns:
        The timestamp as a Python ``int`` (milliseconds since epoch),
        or ``None`` if the input is null or unparseable.
    """
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_duration_ms(value: str | int | float | None) -> int | None:
    """Parse a duration into milliseconds.

    Handles:
    - Plain integers / floats (already in ms).
    - Strings like ``"843ms"``, ``"1.2s"``, ``"2m 3s"``.

    Args:
        value: Raw duration value from the report.

    Returns:
        Duration in milliseconds as ``int``, or ``None`` if unparseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().lower()

    # Pure numeric string
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return int(float(text))

    # "Xms"  or  "X ms"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*ms", text)
    if m:
        return int(float(m.group(1)))

    # "Xs"  or  "X s"  or  "X sec"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s(?:ec)?", text)
    if m:
        return int(float(m.group(1)) * 1000)

    # "Xm Ys" or "Xmin Ys"
    m = re.fullmatch(r"(\d+)\s*m(?:in)?\s*(\d+(?:\.\d+)?)\s*s(?:ec)?", text)
    if m:
        return int(m.group(1)) * 60_000 + int(float(m.group(2)) * 1000)

    # "Xm" alone
    m = re.fullmatch(r"(\d+)\s*m(?:in)?", text)
    if m:
        return int(m.group(1)) * 60_000

    return None


def sanitize_test_id(raw: str) -> str:
    """Return a filesystem-safe, stable test identifier.

    Replaces whitespace and special characters with underscores, collapses
    runs of underscores, and lowercases the result.

    Args:
        raw: The raw name or identifier string.

    Returns:
        A stable lowercase identifier string.
    """
    sanitized = re.sub(r"[^\w]+", "_", raw.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_").lower()
    return sanitized or "unknown"


def extract_error_type(stack_trace: str) -> str | None:
    """Extract the exception class name from the first line of a stack trace.

    Handles common patterns:
    - ``org.openqa.selenium.NoSuchElementException: ...``
    - ``java.lang.AssertionError: ...``
    - ``AssertionError: ...``
    - ``TypeError: ...``

    Args:
        stack_trace: The raw stack trace text.

    Returns:
        The exception type string (everything before the first ``:``)
        or ``None`` if no recognizable pattern is found.
    """
    if not stack_trace:
        return None
    first_line = stack_trace.splitlines()[0].strip()
    m = re.match(r"^([\w.]+(?:\$[\w.]+)?)\s*:", first_line)
    if m:
        return m.group(1)
    return None


def split_error_message(stack_trace: str) -> tuple[str | None, str | None]:
    """Split a stack trace into (error_type, message) from its first line.

    Args:
        stack_trace: The raw stack trace text.

    Returns:
        A ``(error_type, message)`` tuple.  Either may be ``None``.
    """
    if not stack_trace:
        return None, None
    first_line = stack_trace.splitlines()[0].strip()
    m = re.match(r"^([\w.]+(?:\$[\w.]+)?)\s*:\s*(.*)", first_line)
    if m:
        return m.group(1), m.group(2).strip() or None
    return None, first_line or None
