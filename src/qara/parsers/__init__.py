"""QARA parsers package.

Contains the report detector and format-specific parsers for Extent and Allure.
All parsers implement :class:`BaseParser` and return a canonical
:class:`~ari.models.run.TestRun`.

Public API
----------
- :class:`~ari.parsers.base.BaseParser` — abstract base for all parsers.
- :class:`~ari.parsers.base.DetectionResult` — result of format detection.
- :class:`~ari.parsers.base.QARAError` — base exception.
- :class:`~ari.parsers.base.ReportNotSupportedError` — raised when no parser matched.
- :class:`~ari.parsers.base.ReportMalformedError` — raised on corrupt/incomplete reports.
- :class:`~ari.parsers.base.ParserNotFoundError` — raised for unknown parser keys.
- :class:`~ari.parsers.detector.Detector` — multi-parser registry & dispatcher.
- :class:`~ari.parsers.extent.ExtentHtmlParser` — Extent Reports v4/v5.
- :class:`~ari.parsers.allure.AllureHtmlParser` — Allure Report v2.
"""

from qara.parsers.allure import AllureHtmlParser
from qara.parsers.base import (
    QARAError,
    BaseParser,
    DetectionResult,
    ParserNotFoundError,
    ReportMalformedError,
    ReportNotSupportedError,
)
from qara.parsers.detector import Detector
from qara.parsers.extent import ExtentHtmlParser

__all__ = [
    "QARAError",
    "AllureHtmlParser",
    "BaseParser",
    "DetectionResult",
    "Detector",
    "ExtentHtmlParser",
    "ParserNotFoundError",
    "ReportMalformedError",
    "ReportNotSupportedError",
]
