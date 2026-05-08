"""QARA parsers package.

Contains the report detector and format-specific parsers for Extent and Allure.
All parsers implement :class:`BaseParser` and return a canonical
:class:`~qara.models.run.TestRun`.

Public API
----------
- :class:`~qara.parsers.base.BaseParser` — abstract base for all parsers.
- :class:`~qara.parsers.base.DetectionResult` — result of format detection.
- :class:`~qara.parsers.base.QARAError` — base exception.
- :class:`~qara.parsers.base.ReportNotSupportedError` — raised when no parser matched.
- :class:`~qara.parsers.base.ReportMalformedError` — raised on corrupt/incomplete reports.
- :class:`~qara.parsers.base.ParserNotFoundError` — raised for unknown parser keys.
- :class:`~qara.parsers.detector.Detector` — multi-parser registry & dispatcher.
- :class:`~qara.parsers.extent.ExtentHtmlParser` — Extent Reports v4/v5.
- :class:`~qara.parsers.allure.AllureHtmlParser` — Allure Report v2.
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
