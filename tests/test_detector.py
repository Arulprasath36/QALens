"""Tests for the :class:`~ari.parsers.detector.Detector` class.

These tests use the real file-system fixtures under
``tests/fixtures/`` to exercise detection end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qara.parsers.allure import AllureHtmlParser
from qara.parsers.base import DetectionResult, ParserNotFoundError
from qara.parsers.detector import Detector
from qara.parsers.extent import ExtentHtmlParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
EXTENT_DIR = FIXTURES / "extent_sample"
ALLURE_DIR = FIXTURES / "allure_sample"


# ---------------------------------------------------------------------------
# Construction and registration
# ---------------------------------------------------------------------------


class TestDetectorConstruction:
    def test_default_parsers_registered(self) -> None:
        d = Detector()
        assert "allure" in d.registered_keys
        assert "extent" in d.registered_keys

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
        result = d.detect(EXTENT_DIR / "index.html")
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

    def test_get_parser_for_path_raises_on_no_match(
        self, tmp_path: Path
    ) -> None:
        d = Detector()
        with pytest.raises(ParserNotFoundError):
            d.get_parser_for_path(tmp_path)
