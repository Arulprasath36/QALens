"""QaLens parsers package.

Contains the report detector and format-specific parsers for Extent, Allure,
JUnit XML, TestNG XML, Playwright JSON/HTML, and Cypress/Mocha JSON reports.
All parsers implement :class:`BaseParser` and return a canonical
:class:`~qalens.models.run.TestRun`.

Public API
----------
- :class:`~qalens.parsers.base.BaseParser` — abstract base for all parsers.
- :class:`~qalens.parsers.base.DetectionResult` — result of format detection.
- :class:`~qalens.parsers.base.QaLensError` — base exception.
- :class:`~qalens.parsers.base.ReportNotSupportedError` — raised when no parser matched.
- :class:`~qalens.parsers.base.ReportMalformedError` — raised on corrupt/incomplete reports.
- :class:`~qalens.parsers.base.ParserNotFoundError` — raised for unknown parser keys.
- :class:`~qalens.parsers.detector.Detector` — multi-parser registry & dispatcher.
- :class:`~qalens.parsers.extent.ExtentHtmlParser` — Extent Reports v4/v5.
- :class:`~qalens.parsers.allure.AllureHtmlParser` — Allure Report v2.
- :class:`~qalens.parsers.junit.JUnitXmlParser` — JUnit-compatible XML.
- :class:`~qalens.parsers.testng.TestNGXmlParser` — TestNG XML.
- :class:`~qalens.parsers.playwright.PlaywrightReportParser` — Playwright JSON/HTML.
- :class:`~qalens.parsers.cypress.CypressJsonParser` — Cypress/Mocha JSON.
"""

from qalens.parsers.allure import AllureHtmlParser
from qalens.parsers.base import (
    BaseParser,
    DetectionResult,
    ParserNotFoundError,
    QaLensError,
    ReportMalformedError,
    ReportNotSupportedError,
)
from qalens.parsers.cypress import CypressJsonParser
from qalens.parsers.detector import Detector
from qalens.parsers.extent import ExtentHtmlParser
from qalens.parsers.junit import JUnitXmlParser
from qalens.parsers.playwright import PlaywrightReportParser
from qalens.parsers.testng import TestNGXmlParser

__all__ = [
    "QaLensError",
    "AllureHtmlParser",
    "BaseParser",
    "CypressJsonParser",
    "DetectionResult",
    "Detector",
    "ExtentHtmlParser",
    "JUnitXmlParser",
    "ParserNotFoundError",
    "PlaywrightReportParser",
    "ReportMalformedError",
    "ReportNotSupportedError",
    "TestNGXmlParser",
]
