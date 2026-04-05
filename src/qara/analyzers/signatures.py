"""Failure signature engine for QARA — Phase 4.

The ``SignatureEngine`` is the first analysis step in the QARA pipeline.
It walks every ``TestCaseResult`` in a ``TestRun``, normalises the
``FailureInfo`` attached to each failing test (and its failed steps), and
stamps three fields that all downstream phases depend on:

* ``failure.normalized_message``    — message with dynamic noise removed
* ``failure.normalized_stack_trace`` — normalised via :func:`normalize_stack_trace`
* ``failure.failure_signature``      — stable 16-char hash via :func:`compute_fingerprint`

The engine is **idempotent**: calling :meth:`~SignatureEngine.enrich` on a
``TestRun`` that has already been processed is a no-op for any
``FailureInfo`` where ``failure_signature`` is already set.

Usage::

    from qara.analyzers.signatures import SignatureEngine
    from qara.models.run import TestRun

    engine = SignatureEngine()
    engine.enrich(run)          # mutates in-place; returns run for chaining
    # All failing tests now have normalized_message, normalized_stack_trace,
    # and failure_signature populated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from qara.analyzers.fingerprint import compute_fingerprint, normalize_stack_trace

if TYPE_CHECKING:
    from qara.models.failure import FailureInfo
    from qara.models.run import TestRun

# ---------------------------------------------------------------------------
# Message normalisation regex patterns
# ---------------------------------------------------------------------------

# ISO 8601 datetime with optional fractional seconds and timezone
_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    re.IGNORECASE,
)

# Time-only: HH:MM:SS or HH:MM:SS.mmm
_TIME_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b")

# RFC 4122 UUID
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

# Explicit hex memory address: 0x1a2b3c4d
_HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")

# Long hex strings that look like session IDs / tokens (≥ 16 hex chars,
# not part of a Java/Python qualified name containing dots or underscores)
_HEX_ID_RE = re.compile(r"(?<![.\w])[0-9a-f]{16,}(?![.\w])", re.IGNORECASE)

# IPv4 addresses, optionally with port
_IP_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"
)

# localhost / hostname with port
_LOCALHOST_PORT_RE = re.compile(r"\blocalhost:\d+\b", re.IGNORECASE)

# Absolute Unix paths — keep only the final component
_ABS_PATH_RE = re.compile(r"(?:/[^/\s\"']+){2,}")


def normalize_message(message: str | None) -> str | None:
    """Return a noise-free version of *message* suitable for deduplication.

    The following substitutions are applied, in order:

    1. ISO 8601 timestamps → ``<TIMESTAMP>``
    2. Time-only strings (``HH:MM:SS``) → ``<TIME>``
    3. UUIDs → ``<UUID>``
    4. Hex memory addresses (``0x…``) → ``<ADDR>``
    5. Long hex strings / session IDs (≥ 16 hex chars) → ``<HEX_ID>``
    6. IPv4 addresses (with optional port) → ``<IP>``
    7. ``localhost:<port>`` → ``localhost:<PORT>``
    8. Absolute file paths → basename only

    Only the **first line** of the message is returned — subsequent lines
    are boilerplate stack-trace continuations that belong in
    ``normalized_stack_trace``.

    Args:
        message: Raw failure message from the report.

    Returns:
        Normalised first line, or ``None`` if *message* was ``None``.

    """
    if message is None:
        return None
    if not message.strip():
        return message

    # Work on just the first line
    first_line = message.splitlines()[0].strip()

    first_line = _TIMESTAMP_RE.sub("<TIMESTAMP>", first_line)
    first_line = _TIME_RE.sub("<TIME>", first_line)
    first_line = _UUID_RE.sub("<UUID>", first_line)
    first_line = _HEX_ADDR_RE.sub("<ADDR>", first_line)
    first_line = _HEX_ID_RE.sub("<HEX_ID>", first_line)
    first_line = _IP_RE.sub("<IP>", first_line)
    first_line = _LOCALHOST_PORT_RE.sub("localhost:<PORT>", first_line)
    first_line = _ABS_PATH_RE.sub(
        lambda m: m.group(0).split("/")[-1], first_line
    )

    return first_line


# ---------------------------------------------------------------------------
# SignatureEngine
# ---------------------------------------------------------------------------


class SignatureEngine:
    """Enrich failing ``FailureInfo`` objects with normalised fields and a signature.

    The engine is stateless — instantiate once and reuse across multiple runs.

    Example::

        engine = SignatureEngine()
        run = client.extract_report("./reports/allure-report")
        engine.enrich(run)
        # run.test_cases[*].failure.failure_signature is now populated
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enrich(self, run: TestRun) -> TestRun:
        """Enrich all failing tests in *run* with normalised failure fields.

        The operation is **in-place**: ``run`` is mutated directly.  The same
        object is returned so calls can be chained::

            summary = engine.enrich(run).test_cases

        Only tests with a failing status (``FAILED`` or ``BROKEN``) are
        processed.  Passing, skipped, and pending tests are untouched.
        Step-level ``FailureInfo`` objects are also enriched.

        Idempotency: if ``failure.failure_signature`` is already set, that
        ``FailureInfo`` is skipped — it will not be re-processed.

        Args:
            run: A ``TestRun`` produced by any QARA parser.

        Returns:
            The same *run* object (mutated in-place).

        """
        for tc in run.test_cases:
            if tc.status.is_failing and tc.failure is not None:
                self._enrich_failure_info(tc.failure)
            for step in tc.steps:
                if step.failure is not None:
                    self._enrich_failure_info(step.failure)
        return run

    def enrich_failure_info(self, failure: FailureInfo) -> FailureInfo:
        """Enrich a single :class:`~ari.models.failure.FailureInfo` in-place.

        Useful for one-off enrichment outside of a full ``TestRun``.
        Idempotent: a ``FailureInfo`` that already has ``failure_signature``
        set is returned unchanged.

        Args:
            failure: The ``FailureInfo`` to enrich.

        Returns:
            The same *failure* object (mutated in-place).

        """
        self._enrich_failure_info(failure)
        return failure

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enrich_failure_info(self, failure: FailureInfo) -> None:
        """Write normalised fields into *failure* unless already present."""
        if failure.failure_signature is not None:
            return  # idempotent — already enriched

        failure.normalized_message = normalize_message(failure.message)
        failure.normalized_stack_trace = normalize_stack_trace(
            failure.stack_trace or ""
        ) or None  # store None rather than empty string when trace absent
        failure.failure_signature = compute_fingerprint(
            error_type=failure.error_type,
            stack_trace=failure.stack_trace,
            message=failure.message,
        )
