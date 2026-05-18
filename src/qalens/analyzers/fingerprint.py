"""Stack-trace fingerprinting for QALens.

A *fingerprint* is a short, stable hex string that identifies the
*shape* of a failure independently of run-specific noise (line numbers,
memory addresses, absolute file paths, timestamps, session IDs).

Two failures that share a fingerprint are considered the same root cause
for grouping and flaky-detection purposes.

Usage::

    from qalens.analyzers.fingerprint import compute_fingerprint

    fp = compute_fingerprint(error_type="NullPointerException",
                             stack_trace=raw_trace)
"""

from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------------------
# Regex patterns used for normalisation
# ---------------------------------------------------------------------------

# Java-style frame:  at com.example.Foo.bar(Foo.java:123)
_JAVA_FRAME_RE = re.compile(
    r"^\s*at\s+"
    r"([\w$.]+)"          # fully-qualified class + method
    r"\("
    r"[^)]*"              # filename:line or "Native Method" or "Unknown Source"
    r"\)\s*$"
)

# Python-style frame:  File "/abs/path/foo.py", line 42, in bar
_PYTHON_FRAME_RE = re.compile(
    r'^\s*File\s+"[^"]+",\s*line\s+\d+,\s*in\s+(\w+)\s*$'
)

# Generic "at" frame that does not match the strict Java pattern
_GENERIC_AT_RE = re.compile(r"^\s*at\s+")

# Noise patterns applied to each frame before hashing
_LINE_NUMBER_RE = re.compile(r":\d+")        # :87  →  :LINE
_MEMORY_ADDR_RE = re.compile(r"@[0-9a-fA-F]+")  # @1f3e4a  →  @ADDR
_ABS_PATH_RE = re.compile(r'(?:/[^/\s"]+)+')    # /home/user/project/... strip


def normalize_stack_trace(stack_trace: str) -> str:
    """Return a noise-free version of *stack_trace* suitable for hashing.

    The following transformations are applied line-by-line:

    * Line numbers stripped (``Foo.java:87`` → ``Foo.java:LINE``)
    * Memory addresses stripped (``@1f3e4a`` → ``@ADDR``)
    * Absolute file paths replaced with the final path component
    * Lines that are purely dynamic noise (timestamps, UUIDs, session IDs)
      are dropped

    Only the first **10 frame lines** are kept so that deeply nested
    call stacks from different code paths do not produce false negatives.

    Args:
        stack_trace: Raw stack trace string as extracted from the report.

    Returns:
        Normalised multi-line string; empty string if input was blank.
    """
    if not stack_trace or not stack_trace.strip():
        return ""

    normalised_frames: list[str] = []

    for raw_line in stack_trace.splitlines():
        if len(raw_line) > 500:
            continue
        line = raw_line.strip()
        if not line:
            continue

        # Keep only lines that look like stack frames
        is_java = bool(_JAVA_FRAME_RE.match(raw_line))
        is_python = bool(_PYTHON_FRAME_RE.match(raw_line))
        is_generic_at = bool(_GENERIC_AT_RE.match(raw_line))

        if not (is_java or is_python or is_generic_at):
            # First non-frame line is typically the exception message —
            # include it once then stop collecting non-frame lines.
            if not normalised_frames:
                # Exception/error headline — keep but normalise paths
                line = _ABS_PATH_RE.sub(lambda m: m.group(0).split("/")[-1], line)
                normalised_frames.append(line)
            continue

        # Normalise the frame
        line = _LINE_NUMBER_RE.sub(":LINE", line)
        line = _MEMORY_ADDR_RE.sub("@ADDR", line)
        line = _ABS_PATH_RE.sub(lambda m: m.group(0).split("/")[-1], line)

        normalised_frames.append(line)

        if len(normalised_frames) >= 10:
            break

    return "\n".join(normalised_frames)


def compute_fingerprint(
    *,
    error_type: str | None,
    stack_trace: str | None,
    message: str | None = None,
) -> str:
    """Compute a 16-character hex fingerprint for a failure.

    The fingerprint is derived from:

    1. The normalised stack trace (first 10 frames), **or**
    2. ``error_type + ":" + first 80 chars of message`` as a fallback when
       no stack trace is available.

    This means the same bug on different machines, runs, or test data will
    produce the same fingerprint as long as the code path is identical.

    Args:
        error_type: Exception class or error category (may be ``None``).
        stack_trace: Raw stack trace string (may be ``None`` or empty).
        message: Error message, used only as fallback when *stack_trace*
            is absent.

    Returns:
        A 16-character lowercase hex string (first 16 chars of SHA-256).
    """
    normalised = normalize_stack_trace(stack_trace or "")

    if normalised:
        payload = normalised
    else:
        # Fallback: use error type + truncated message
        parts: list[str] = []
        if error_type:
            parts.append(error_type.strip())
        if message:
            parts.append(message.strip()[:80])
        payload = ":".join(parts) if parts else "unknown"

    digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]
