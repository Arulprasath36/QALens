"""Tests for the :class:`~qalens.parsers.detector.Detector` class.

These tests use the real file-system fixtures under
``tests/fixtures/`` to exercise detection end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.parsers.allure import AllureHtmlParser
from qalens.parsers.base import ParserNotFoundError
from qalens.parsers.cypress import CypressJsonParser
from qalens.parsers.detector import Detector
from qalens.parsers.extent import ExtentHtmlParser
from qalens.parsers.junit import JUnitXmlParser
from qalens.parsers.playwright import PlaywrightReportParser
from qalens.parsers.testng import TestNGXmlParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
EXTENT_DIR = FIXTURES / "extent_sample"
ALLURE_DIR = FIXTURES / "allure_sample"
JUNIT_DIR = FIXTURES / "junit_sample"
TESTNG_DIR = FIXTURES / "testng_sample"
PLAYWRIGHT_DIR = FIXTURES / "playwright_json_sample"
PLAYWRIGHT_HTML_DIR = FIXTURES / "playwright_html_sample"
CYPRESS_DIR = FIXTURES / "cypress_mochawesome_sample"


# ---------------------------------------------------------------------------
# Construction and registration
# ---------------------------------------------------------------------------


class TestDetectorConstruction:
    def test_default_parsers_registered(self) -> None:
        d = Detector()
        assert "allure" in d.registered_keys
        assert "extent" in d.registered_keys
        assert "junit" in d.registered_keys
        assert "testng" in d.registered_keys
        assert "playwright" in d.registered_keys
        assert "cypress" in d.registered_keys

    def test_empty_registry_when_explicit_empty_list(self) -> None:
        d = Detector(parsers=[])
        assert d.registered_keys == []

    def test_explicit_parsers_respected(self) -> None:
        d = Detector(parsers=[AllureHtmlParser()])
        assert d.registered_keys == ["allure"]
        assert "extent" not in d.registered_keys

    def test_register_adds_parser(self) -> None:
        d = Detector(parsers=[])
        d.register(AllureHtmlParser())
        assert "allure" in d.registered_keys

    def test_register_replaces_existing_key(self) -> None:
        d = Detector()
        initial_len = len(d.registered_keys)
        d.register(ExtentHtmlParser())  # replace existing "extent"
        assert len(d.registered_keys) == initial_len
        assert d.registered_keys.count("extent") == 1

    def test_unregister_removes_parser(self) -> None:
        d = Detector()
        removed = d.unregister("allure")
        assert removed is True
        assert "allure" not in d.registered_keys

    def test_unregister_returns_false_for_unknown_key(self) -> None:
        d = Detector()
        assert d.unregister("nonexistent") is False


# ---------------------------------------------------------------------------
# Detection — Allure
# ---------------------------------------------------------------------------


class TestDetectorAllureDetection:
    def test_detects_allure_directory(self) -> None:
        d = Detector()
        result = d.detect(ALLURE_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "allure"

    def test_allure_confidence_high(self) -> None:
        d = Detector()
        result = d.detect(ALLURE_DIR)
        assert result.confidence >= 0.80

    def test_allure_reasons_non_empty(self) -> None:
        d = Detector()
        result = d.detect(ALLURE_DIR)
        assert len(result.reasons) >= 1

    def test_allure_matched_files_includes_json(self) -> None:
        d = Detector()
        result = d.detect(ALLURE_DIR)
        names = [f.name for f in result.matched_files]
        assert "summary.json" in names or "suites.json" in names

    def test_detects_allure_from_index_html(self) -> None:
        d = Detector()
        result = d.detect(ALLURE_DIR / "index.html")
        assert result.matched
        assert result.parser_key == "allure"


# ---------------------------------------------------------------------------
# Detection — Extent
# ---------------------------------------------------------------------------


class TestDetectorExtentDetection:
    def test_detects_extent_directory(self) -> None:
        d = Detector()
        result = d.detect(EXTENT_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "extent"


# ---------------------------------------------------------------------------
# Detection — JUnit XML
# ---------------------------------------------------------------------------


class TestDetectorJUnitDetection:
    def test_detects_junit_directory(self) -> None:
        d = Detector()
        result = d.detect(JUNIT_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "junit"


# ---------------------------------------------------------------------------
# Detection — TestNG XML
# ---------------------------------------------------------------------------


class TestDetectorTestNGDetection:
    def test_detects_testng_directory(self) -> None:
        d = Detector()
        result = d.detect(TESTNG_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "testng"

    def test_detects_testng_xml_file(self) -> None:
        d = Detector()
        result = d.detect(TESTNG_DIR / "testng-results.xml")
        assert result.matched
        assert result.parser_key == "testng"


# ---------------------------------------------------------------------------
# Detection — Playwright
# ---------------------------------------------------------------------------


class TestDetectorPlaywrightDetection:
    def test_detects_playwright_json_directory(self) -> None:
        d = Detector()
        result = d.detect(PLAYWRIGHT_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "playwright"


# ---------------------------------------------------------------------------
# Detection — Cypress/Mocha
# ---------------------------------------------------------------------------


class TestDetectorCypressDetection:
    def test_detects_cypress_mochawesome_directory(self) -> None:
        d = Detector()
        result = d.detect(CYPRESS_DIR)
        assert result.matched, f"expected matched=True, reasons={result.reasons}"
        assert result.parser_key == "cypress"

    def test_detects_playwright_html_directory(self) -> None:
        d = Detector()
        result = d.detect(PLAYWRIGHT_HTML_DIR)
        assert result.matched
        assert result.parser_key == "playwright"

    def test_detects_junit_xml_file(self) -> None:
        d = Detector()
        result = d.detect(JUNIT_DIR / "TEST-shopnow.xml")
        assert result.matched
        assert result.parser_key == "junit"

    def test_extent_confidence_high(self) -> None:
        d = Detector()
        result = d.detect(EXTENT_DIR)
        assert result.confidence >= 0.80

    def test_extent_reasons_non_empty(self) -> None:
        d = Detector()
        result = d.detect(EXTENT_DIR)
        assert len(result.reasons) >= 1

    def test_detects_extent_from_html_file(self) -> None:
        d = Detector()
        result = d.detect(EXTENT_DIR / "ExtentReport.html")
        assert result.matched
        assert result.parser_key == "extent"


# ---------------------------------------------------------------------------
# Detection — no match / ambiguous
# ---------------------------------------------------------------------------


class TestDetectorNoMatch:
    def test_unknown_returned_for_empty_directory(self, tmp_path: Path) -> None:
        d = Detector()
        result = d.detect(tmp_path)
        assert not result.matched
        assert result.parser_key == "unknown"

    def test_unknown_returned_below_threshold(self, tmp_path: Path) -> None:
        # Create a directory with no recognizable signals
        html = tmp_path / "index.html"
        html.write_text("<html><body>Hello world</body></html>")
        d = Detector()
        result = d.detect(tmp_path)
        assert not result.matched

    def test_returns_highest_confidence_format(self) -> None:
        # Allure dir should beat extent when both registered
        d = Detector()
        result = d.detect(ALLURE_DIR)
        assert result.parser_key == "allure"


# ---------------------------------------------------------------------------
# get_parser / get_parser_for_path
# ---------------------------------------------------------------------------


class TestDetectorGetParser:
    def test_get_parser_returns_correct_instance(self) -> None:
        d = Detector()
        parser = d.get_parser("allure")
        assert isinstance(parser, AllureHtmlParser)

    def test_get_parser_raises_for_unknown_key(self) -> None:
        d = Detector()
        with pytest.raises(ParserNotFoundError):
            d.get_parser("nonexistent")

    def test_get_parser_for_path_returns_allure(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(ALLURE_DIR)
        assert isinstance(parser, AllureHtmlParser)

    def test_get_parser_for_path_returns_extent(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(EXTENT_DIR)
        assert isinstance(parser, ExtentHtmlParser)

    def test_get_parser_for_path_returns_junit(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(JUNIT_DIR)
        assert isinstance(parser, JUnitXmlParser)

    def test_get_parser_for_path_returns_testng(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(TESTNG_DIR)
        assert isinstance(parser, TestNGXmlParser)

    def test_get_parser_for_path_returns_playwright(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(PLAYWRIGHT_DIR)
        assert isinstance(parser, PlaywrightReportParser)

    def test_get_parser_for_path_returns_cypress(self) -> None:
        d = Detector()
        parser = d.get_parser_for_path(CYPRESS_DIR)
        assert isinstance(parser, CypressJsonParser)

    def test_get_parser_for_path_raises_on_no_match(
        self, tmp_path: Path
    ) -> None:
        d = Detector()
        with pytest.raises(ParserNotFoundError):
            d.get_parser_for_path(tmp_path)
