"""Base parser abstractions, detection results, and QARA exceptions.

This module defines the contracts every QARA parser must satisfy.
It also defines the :class:`DetectionResult` model that carries
explainable evidence from detection, and the exception hierarchy
used throughout the parser layer.

Design notes:
- :class:`BaseParser` is an ABC. Concrete parsers subclass it and
  implement :meth:`can_parse` and :meth:`parse`.
- :class:`DetectionResult` is a Pydantic model so it serializes cleanly
  to JSON alongside the rest of ARI's output.
- Exceptions are kept in this module to avoid a proliferation of tiny
  files; they are re-exported from :mod:`ari.parsers`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from qara.models.run import TestRun
from qara.models.warnings import ExtractionWarning, WarningSeverity


# ---------------------------------------------------------------------------
# QARA exception hierarchy
# ---------------------------------------------------------------------------


class QARAError(Exception):
    """Base class for all QARA errors."""


class ReportNotSupportedError(QARAError):
    """Raised when no registered parser can handle a given report path.

    Args:
        path: The report path that could not be matched.
        tried: Names of parsers that were attempted.
    """

    def __init__(self, path: Path, tried: list[str] | None = None) -> None:
        self.path = path
        self.tried = tried or []
        tried_str = ", ".join(self.tried) if self.tried else "none"
        super().__init__(
            f"No parser could handle report at '{path}'. "
            f"Parsers tried: {tried_str}."
        )


class ReportMalformedError(QARAError):
    """Raised when a parser detects a structurally invalid report.

    This is distinct from :class:`ReportNotSupportedError`: a parser
    identified the format but found the content to be corrupt or
    missing required structure.

    Args:
        path: The report path being parsed.
        detail: Human-readable description of the structural problem.
    """

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Malformed report at '{path}': {detail}")


class ParserNotFoundError(QARAError):
    """Raised when a specific parser key is requested but not registered.

    Args:
        parser_key: The requested parser key.
    """

    def __init__(self, parser_key: str) -> None:
        self.parser_key = parser_key
        super().__init__(f"No parser registered with key '{parser_key}'.")


# ---------------------------------------------------------------------------
# Detection result model
# ---------------------------------------------------------------------------


class DetectionResult(BaseModel):
    """Explainable result of attempting to detect the report format at a path.

    Each parser's :meth:`BaseParser.can_parse` method returns a
    :class:`DetectionResult`. The :class:`~ari.parsers.detector.Detector`
    collects results from all registered parsers and selects the best match.

    Attributes:
        parser_key: Short identifier for the matched parser
            (e.g. ``"allure"``, ``"extent"``), or ``"unknown"`` if no
            parser matched confidently.
        parser_name: Human-readable parser name.
        confidence: Detection confidence in [0.0, 1.0].
            - ≥ 0.8 : high confidence — multiple strong signals matched.
            - 0.5 – 0.79 : medium confidence — partial structural match.
            - 0.3 – 0.49 : low confidence — weak DOM or filename match.
            - < 0.3 : no match.
        reasons: Ordered list of human-readable strings explaining which
            signals were found and how they influenced confidence.
        matched_files: Files that were found and contributed to detection.
        warnings: Non-fatal issues encountered during detection
            (e.g. a file could not be read).
    """

    parser_key: str = Field(..., description="Short parser identifier or 'unknown'.")
    parser_name: str = Field(..., description="Human-readable parser name.")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Detection confidence [0, 1].",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Evidence strings explaining the confidence score.",
    )
    matched_files: list[Path] = Field(
        default_factory=list,
        description="Files found during detection that contributed to the match.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues encountered during detection.",
    )

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    @property
    def matched(self) -> bool:
        """Return ``True`` if confidence meets the match threshold (≥ 0.5)."""
        return self.confidence >= 0.5

    @property
    def confidence_label(self) -> str:
        """Return a human-readable confidence tier label."""
        if self.confidence >= 0.8:
            return "high"
        if self.confidence >= 0.5:
            return "medium"
        if self.confidence >= 0.3:
            return "low"
        return "none"

    @classmethod
    def no_match(cls, parser_key: str, parser_name: str, reason: str) -> "DetectionResult":
        """Convenience constructor for a negative detection result.

        Args:
            parser_key: Parser identifier.
            parser_name: Parser display name.
            reason: Why the parser did not match.

        Returns:
            A :class:`DetectionResult` with confidence ``0.0``.
        """
        return cls(
            parser_key=parser_key,
            parser_name=parser_name,
            confidence=0.0,
            reasons=[reason],
        )

    @classmethod
    def unknown(cls) -> "DetectionResult":
        """Return an 'unknown format' result used when no parser matched.

        Returns:
            A :class:`DetectionResult` with ``parser_key="unknown"`` and
            confidence ``0.0``.
        """
        return cls(
            parser_key="unknown",
            parser_name="Unknown",
            confidence=0.0,
            reasons=["No registered parser produced a confident match."],
        )


# ---------------------------------------------------------------------------
# Base parser ABC
# ---------------------------------------------------------------------------


class BaseParser(ABC):
    """Abstract base class for all QARA report parsers.

    Concrete parsers must:

    1. Set :attr:`parser_key` and :attr:`parser_name` as class attributes.
    2. Implement :meth:`can_parse` to return a :class:`DetectionResult`
       based on file/content signals — **without** heavy I/O or full parsing.
    3. Implement :meth:`parse` to return a normalized :class:`~ari.models.run.TestRun`.

    Parsers must never perform analysis, categorization, or scoring.
    That responsibility belongs exclusively to the analyzer layer.

    Warning collection:
        During parsing, call :meth:`_warn` to record
        :class:`~ari.models.warnings.ExtractionWarning` objects. These are
        attached to the returned :class:`~ari.models.run.TestRun`.
    """

    #: Short unique identifier for this parser format.
    #: Must be lowercase, no spaces (e.g. ``"allure"``, ``"extent"``).
    parser_key: str

    #: Human-readable display name for this parser.
    parser_name: str

    def __init__(self) -> None:
        self._extraction_warnings: list[ExtractionWarning] = []

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def can_parse(self, report_path: Path) -> DetectionResult:
        """Determine whether this parser can handle the given report path.

        Implementations should use cheap signals (file existence, metadata,
        lightweight DOM inspections) and return a :class:`DetectionResult`
        with a confidence score and evidence reasons.

        This method must be fast. It should **not** perform full parsing.

        Args:
            report_path: A directory or HTML file path to inspect.

        Returns:
            A :class:`DetectionResult` with confidence in [0, 1] and
            an evidence list. Return ``confidence=0.0`` if no match.
        """

    @abstractmethod
    def parse(self, report_path: Path) -> TestRun:
        """Parse the report at ``report_path`` and return a normalized run.

        Implementations must:
        - Return a :class:`~ari.models.run.TestRun` even for partial results.
        - Call :meth:`_warn` for every field that could not be populated.
        - Raise :class:`ReportMalformedError` if the report is structurally
          invalid to the point where no useful data can be extracted.
        - Never raise for missing optional fields — use warnings instead.

        Args:
            report_path: A directory or HTML file path to parse.

        Returns:
            A normalized :class:`~ari.models.run.TestRun`.

        Raises:
            ReportMalformedError: If the report cannot yield any useful data.
        """

    # ------------------------------------------------------------------
    # Warning helpers
    # ------------------------------------------------------------------

    def _warn(
        self,
        field: str,
        reason: str,
        *,
        test_name: str | None = None,
        severity: WarningSeverity = WarningSeverity.LOW,
        raw_value: str | None = None,
    ) -> None:
        """Record an extraction warning without interrupting parsing.

        Args:
            field: Dotted field path that could not be populated.
            reason: Human-readable explanation of why extraction degraded.
            test_name: Name of the affected test, if applicable.
            severity: Impact level of this warning.
            raw_value: Raw value fragment encountered, for debugging.
        """
        self._extraction_warnings.append(
            ExtractionWarning(
                field=field,
                reason=reason,
                test_name=test_name,
                severity=severity,
                raw_value=raw_value,
            )
        )

    def _collect_warnings(self) -> list[ExtractionWarning]:
        """Return accumulated warnings and reset the internal list.

        This is called by :meth:`parse` implementations at the end of
        extraction to attach warnings to the returned :class:`~ari.models.run.TestRun`.

        Returns:
            All warnings accumulated since the last call or since
            instantiation.
        """
        warnings = list(self._extraction_warnings)
        self._extraction_warnings.clear()
        return warnings

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key={self.parser_key!r})"
