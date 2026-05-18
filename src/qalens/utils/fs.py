"""Filesystem helper utilities for QA Lens parsers.

All parsers use these helpers for consistent, safe file operations.
No parser should contain raw ``open()`` calls or ``Path.glob()`` calls
unless the operation is so specific that a helper would not generalize.

Functions here are intentionally small and single-purpose.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Names considered candidates for a report's entry HTML file, in priority order.
_ENTRY_HTML_CANDIDATES: tuple[str, ...] = (
    "index.html",
    "index.htm",
    "report.html",
    "report.htm",
    "extent.html",
    "allure-report.html",
)


def resolve_report_root(path: Path) -> Path:
    """Return the report root directory for a given path.

    If ``path`` is a file, its parent directory is returned.
    If ``path`` is a directory, it is returned unchanged.

    Args:
        path: A path to a report directory or HTML file.

    Returns:
        The directory containing (or equal to) the report root.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Report path does not exist: {path}")
    return path.parent if path.is_file() else path


def find_entry_html(root: Path) -> Path | None:
    """Locate the main HTML entry file within a report directory.

    Searches for known entry file names in priority order, then falls back
    to the first ``*.html`` file found directly under ``root``.

    Args:
        root: The report root directory to search.

    Returns:
        The resolved :class:`~pathlib.Path` to the entry HTML file, or
        ``None`` if no HTML file is found.
    """
    for name in _ENTRY_HTML_CANDIDATES:
        candidate = root / name
        if candidate.is_file():
            return candidate

    # Fallback: any .html at the top level
    html_files = sorted(root.glob("*.html"))
    if html_files:
        return html_files[0]

    return None


def safe_read_text(
    path: Path,
    encoding: str = "utf-8",
    max_bytes: int | None = None,
) -> str | None:
    """Read a file's text content without raising exceptions.

    Handles encoding errors, permission errors, and missing files
    gracefully by returning ``None`` and logging a warning.

    Args:
        path: The file to read.
        encoding: Text encoding to use. Defaults to UTF-8.
        max_bytes: If set, refuse to read files larger than this many bytes.
            Returns ``None`` and logs a warning when exceeded.

    Returns:
        The file's text content, or ``None`` on any read error.
    """
    try:
        if max_bytes is not None:
            size = path.stat().st_size
            if size > max_bytes:
                logger.warning(
                    "Skipping oversized file (%d bytes > %d-byte limit): %s",
                    size, max_bytes, path,
                )
                return None
        return path.read_text(encoding=encoding, errors="replace")
    except (OSError, PermissionError, UnicodeError) as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


def file_contains(path: Path, needle: str, *, case_sensitive: bool = True) -> bool:
    """Return ``True`` if a file's text content contains ``needle``.

    Returns ``False`` if the file cannot be read.

    Args:
        path: The file to inspect.
        needle: The substring to search for.
        case_sensitive: Whether the search is case-sensitive.
            Defaults to ``True``.

    Returns:
        ``True`` if ``needle`` is found in the file's text content.
    """
    content = safe_read_text(path)
    if content is None:
        return False
    if not case_sensitive:
        return needle.lower() in content.lower()
    return needle in content


def list_files(root: Path, glob_pattern: str) -> list[Path]:
    """List files matching a glob pattern under ``root``.

    Args:
        root: The directory to search from.
        glob_pattern: A glob pattern relative to ``root``
            (e.g. ``"**/*.json"`` or ``"data/*.json"``).

    Returns:
        A sorted list of matching :class:`~pathlib.Path` objects.
        Returns an empty list if ``root`` does not exist or the
        glob produces no matches.
    """
    if not root.is_dir():
        return []
    return sorted(root.glob(glob_pattern))


def directory_contains(root: Path, *relative_paths: str) -> list[Path]:
    """Check which of the given relative paths exist under ``root``.

    Useful for quickly scoring how many expected structural files are
    present in a report directory.

    Args:
        root: The directory to check under.
        *relative_paths: Relative path strings to test for existence.

    Returns:
        A list of the :class:`~pathlib.Path` objects that exist.

    Example::

        found = directory_contains(
            report_root,
            "widgets/summary.json",
            "data/suites.json",
            "data/test-cases",
        )
        confidence = len(found) / 3
    """
    return [root / rp for rp in relative_paths if (root / rp).exists()]


def safe_join(root: Path, untrusted_relative: str) -> Path | None:
    """Resolve *untrusted_relative* under *root* and return it only if it
    stays within *root* (path-traversal guard).

    Args:
        root: The trusted base directory.
        untrusted_relative: A relative path string from untrusted input.

    Returns:
        The resolved :class:`~pathlib.Path` if it is within *root*, or
        ``None`` if the path escapes the root or cannot be resolved.
    """
    try:
        resolved = (root / untrusted_relative).resolve()
        root_resolved = root.resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return resolved
        logger.warning(
            "Path traversal attempt blocked: %r escapes root %s",
            untrusted_relative, root,
        )
        return None
    except (ValueError, OSError):
        return None


def count_files_by_extension(root: Path, ext: str) -> int:
    """Count files with a given extension (recursive) under ``root``.

    Args:
        root: Directory to search.
        ext: File extension including the leading dot (e.g. ``".json"``).

    Returns:
        Number of matching files, or 0 if ``root`` is not a directory.
    """
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob(f"*{ext}"))
