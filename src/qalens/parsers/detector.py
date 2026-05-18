"""Format detector for QALens.

Provides :class:`Detector` — the registry that runs all registered
:class:`~qalens.parsers.base.BaseParser` implementations against a given
report path and returns the best-matching :class:`~qalens.parsers.base.DetectionResult`.

Typical usage
-------------
::

    from pathlib import Path
    from qalens.parsers.detector import Detector

    detector = Detector()                          # uses default parsers
    result = detector.detect(Path("/reports/my-run"))
    if result.matched:
        print(result.parser_key, result.confidence)

Custom parsers can be registered before or after construction::

    detector.register(MyCustomParser())
    result = detector.detect(path)

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qalens.parsers.allure import AllureHtmlParser
from qalens.parsers.base import BaseParser, DetectionResult, ParserNotFoundError
from qalens.parsers.cypress import CypressJsonParser
from qalens.parsers.extent import ExtentHtmlParser
from qalens.parsers.junit import JUnitXmlParser
from qalens.parsers.playwright import PlaywrightReportParser
from qalens.parsers.testng import TestNGXmlParser

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Minimum confidence for a detector result to be considered a match.
_MATCH_THRESHOLD: float = 0.30


class Detector:
    """Registry and dispatcher for all QALens report parsers.

    On construction, a default set of built-in parsers is registered
    (currently :class:`~qalens.parsers.allure.AllureHtmlParser` and
    :class:`~qalens.parsers.extent.ExtentHtmlParser`).

    Parsers are tried in registration order; the result with the highest
    confidence is returned. Ties are broken by registration order (first wins).

    Args:
        parsers: An optional list of :class:`~qalens.parsers.base.BaseParser`
            instances.  When ``None`` (the default), the built-in parsers
            are registered automatically.  Pass an empty list to start
            with a clean registry.

    """

    def __init__(
        self,
        parsers: list[BaseParser] | None = None,
        attachments_dir: Path | None = None,
    ) -> None:
        """Initialize the detector registry."""
        if parsers is None:
            self._parsers: list[BaseParser] = [
                AllureHtmlParser(),
                ExtentHtmlParser(attachments_dir=attachments_dir),
                JUnitXmlParser(),
                TestNGXmlParser(),
                PlaywrightReportParser(),
                CypressJsonParser(),
            ]
        else:
            self._parsers = list(parsers)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, parser: BaseParser) -> None:
        """Add a parser to the registry.

        If a parser with the same :attr:`~qalens.parsers.base.BaseParser.parser_key`
        is already registered, it is **replaced** to avoid
        ambiguous detection results.

        Args:
            parser: The :class:`~qalens.parsers.base.BaseParser` instance to add.

        """
        existing_keys = {p.parser_key for p in self._parsers}
        if parser.parser_key in existing_keys:
            self._parsers = [
                p for p in self._parsers if p.parser_key != parser.parser_key
            ]
            logger.debug(
                "Replaced existing parser with key '%s'.", parser.parser_key
            )
        self._parsers.append(parser)

    def unregister(self, parser_key: str) -> bool:
        """Remove a parser from the registry by key.

        Args:
            parser_key: The :attr:`~qalens.parsers.base.BaseParser.parser_key`
                of the parser to remove.

        Returns:
            ``True`` if a parser was removed, ``False`` if no such key
            was registered.

        """
        before = len(self._parsers)
        self._parsers = [p for p in self._parsers if p.parser_key != parser_key]
        return len(self._parsers) < before

    @property
    def registered_keys(self) -> list[str]:
        """Return the parser keys of all registered parsers, in order."""
        return [p.parser_key for p in self._parsers]

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self, report_path: Path) -> DetectionResult:
        """Run all registered parsers against *report_path* and return the best result.

        Each parser's :meth:`~qalens.parsers.base.BaseParser.can_parse` is
        called.  The result with the highest
        :attr:`~qalens.parsers.base.DetectionResult.confidence` is returned.
        If no parser reaches the match threshold (``0.30``) an
        :meth:`~qalens.parsers.base.DetectionResult.unknown` sentinel is
        returned.

        Args:
            report_path: Path to the report directory or HTML file.

        Returns:
            The :class:`~qalens.parsers.base.DetectionResult` with the
            highest confidence, or
            :meth:`~qalens.parsers.base.DetectionResult.unknown` if no
            parser matched.

        """
        if not self._parsers:
            logger.warning("Detector has no registered parsers.")
            return DetectionResult.unknown()

        results: list[DetectionResult] = []
        for parser in self._parsers:
            try:
                result = parser.can_parse(report_path)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Parser '%s' raised an unexpected error during detection: %s",
                    parser.parser_key,
                    exc,
                )
                continue
            results.append(result)
            logger.debug(
                "Parser '%s' → confidence=%.2f  reasons=%s",
                result.parser_key,
                result.confidence,
                result.reasons,
            )

        if not results:
            return DetectionResult.unknown()

        best = max(results, key=lambda r: r.confidence)

        if best.confidence < _MATCH_THRESHOLD:
            logger.debug(
                "Best match was '%s' at %.2f, below threshold %.2f — returning unknown.",
                best.parser_key,
                best.confidence,
                _MATCH_THRESHOLD,
            )
            return DetectionResult.unknown()

        return best

    # ------------------------------------------------------------------
    # Parser lookup
    # ------------------------------------------------------------------

    def get_parser(self, parser_key: str) -> BaseParser:
        """Retrieve a registered parser by its key.

        Args:
            parser_key: The :attr:`~qalens.parsers.base.BaseParser.parser_key`
                to look up.

        Returns:
            The matching :class:`~qalens.parsers.base.BaseParser`.

        Raises:
            ParserNotFoundError: If no parser with that key is registered.

        """
        for parser in self._parsers:
            if parser.parser_key == parser_key:
                return parser
        raise ParserNotFoundError(parser_key)

    def get_parser_for_path(self, report_path: Path) -> BaseParser:
        """Detect the report format and return the corresponding parser.

        Convenience wrapper combining :meth:`detect` and
        :meth:`get_parser`.

        Args:
            report_path: Path to the report directory or HTML file.

        Returns:
            The :class:`~qalens.parsers.base.BaseParser` that matched with
            the highest confidence.

        Raises:
            ParserNotFoundError: If no registered parser matched the report
                (i.e. detection returned an unknown result).

        """
        result = self.detect(report_path)
        if not result.matched:
            raise ParserNotFoundError(
                f"<unknown: no parser matched '{report_path}'>"
            )
        return self.get_parser(result.parser_key)
