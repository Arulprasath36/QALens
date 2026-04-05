"""Tests for :class:`~ari.parsers.extent.ExtentHtmlParser`.

Uses synthetic HTML fixtures under ``tests/fixtures/extent_sample/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qara.models.run import TestRun
from qara.models.test_case import TestStatus
from qara.models.warnings import WarningSeverity
from qara.parsers.base import DetectionResult, ReportMalformedError
from qara.parsers.extent import ExtentHtmlParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
EXTENT_DIR = FIXTURES / "extent_sample"
ALLURE_DIR = FIXTURES / "allure_sample"


@pytest.fixture()
def parser() -> ExtentHtmlParser:
    return ExtentHtmlParser()


# ---------------------------------------------------------------------------
# can_parse — positive signals
# ---------------------------------------------------------------------------


class TestExtentCanParsePositive:
    def test_matches_extent_directory(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert result.matched, f"reasons={result.reasons}"

    def test_confidence_high_for_meta_generator(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert result.confidence >= 0.80

    def test_reasons_mention_generator_or_script_vars(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR)
        combined = " ".join(result.reasons).lower()
        assert "extentreports" in combined or "reportconfig" in combined or "testdata" in combined

    def test_matched_files_contains_html(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert any(f.suffix == ".html" for f in result.matched_files)

    def test_matches_from_html_file_directly(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR / "index.html")
        assert result.matched

    def test_parser_key_is_extent(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert result.parser_key == "extent"

    def test_parser_name_is_set(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert result.parser_name == "Extent HTML Report Parser"

    def test_detects_script_vars(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        reasons_text = " ".join(result.reasons)
        assert "reportconfig" in reasons_text.lower() or "testdata" in reasons_text.lower()

    def test_detects_meta_generator_signal(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR)
        reasons_text = " ".join(result.reasons).lower()
        assert "extentreports" in reasons_text or "reportconfig" in reasons_text


# ---------------------------------------------------------------------------
# can_parse — negative signals
# ---------------------------------------------------------------------------


class TestExtentCanParseNegative:
    def test_low_confidence_for_allure_directory(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert not result.matched, (
            f"Should not match Allure directory; confidence={result.confidence}, "
            f"reasons={result.reasons}"
        )

    def test_no_match_for_missing_path(
        self, parser: ExtentHtmlParser, tmp_path: Path
    ) -> None:
        result = parser.can_parse(tmp_path / "does_not_exist")
        assert not result.matched

    def test_low_confidence_for_empty_directory(
        self, parser: ExtentHtmlParser, tmp_path: Path
    ) -> None:
        result = parser.can_parse(tmp_path)
        assert not result.matched

    def test_low_confidence_for_generic_html(
        self, parser: ExtentHtmlParser, tmp_path: Path
    ) -> None:
        html = tmp_path / "index.html"
        html.write_text("<html><title>My App</title><body>Hello</body></html>")
        result = parser.can_parse(tmp_path)
        assert not result.matched


# ---------------------------------------------------------------------------
# parse — Phase 3 full extraction
# ---------------------------------------------------------------------------


class TestExtentParse:
    def test_parse_returns_test_run(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert isinstance(run, TestRun)

    def test_extracts_four_test_cases(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert len(run.test_cases) == 4

    def test_test_case_names_present(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        names = [tc.name for tc in run.test_cases]
        assert "Login with valid credentials" in names
        assert "Login with invalid password" in names

    def test_statuses_two_passed_one_failed_one_skipped(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        statuses = [tc.status for tc in run.test_cases]
        assert statuses.count(TestStatus.PASSED) == 2
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1

    def test_failed_test_has_failure_object(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None

    def test_failed_test_error_type(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert failed.failure.error_type == "org.openqa.selenium.NoSuchElementException"

    def test_failed_test_stack_trace_present(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert failed.failure.stack_trace is not None
        assert "LoginTest.java" in failed.failure.stack_trace

    def test_failed_test_has_steps(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert len(failed.steps) > 0

    def test_failed_test_has_attachments(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert len(failed.attachments) > 0

    def test_passed_test_has_no_failure(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        passed = [tc for tc in run.test_cases if tc.status == TestStatus.PASSED]
        for tc in passed:
            assert tc.failure is None

    def test_test_case_has_steps(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        # First test has 3 steps in the fixture
        first = next(
            tc for tc in run.test_cases if tc.name == "Login with valid credentials"
        )
        assert len(first.steps) == 3

    def test_test_case_tags_extracted(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        first = next(
            tc for tc in run.test_cases if tc.name == "Login with valid credentials"
        )
        assert len(first.tags) > 0

    def test_metadata_report_format_is_extent(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.report_format == "extent"

    def test_metadata_report_path_set(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.report_path  # non-empty string

    def test_metadata_project_extracted(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.project is not None
        assert "My CI Project" in run.metadata.project

    def test_metadata_report_version_extracted(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        # Our fixture has ExtentReports 5.0.9 in the meta tag
        assert run.metadata.report_version == "5.0.9"

    def test_metadata_started_at_set(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.started_at is not None

    def test_metadata_finished_at_set(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.finished_at is not None

    def test_parse_from_html_file_path(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR / "index.html")
        assert isinstance(run, TestRun)

    def test_parse_raises_on_missing_html(
        self, parser: ExtentHtmlParser, tmp_path: Path
    ) -> None:
        with pytest.raises((FileNotFoundError, ReportMalformedError)):
            parser.parse(tmp_path)


# ---------------------------------------------------------------------------
# Detection result model
# ---------------------------------------------------------------------------


class TestDetectionResultModel:
    def test_no_match_factory(self) -> None:
        r = DetectionResult.no_match("extent", "Extent HTML Report Parser", "testing")
        assert not r.matched
        assert r.confidence == 0.0
        assert r.parser_key == "extent"

    def test_unknown_factory(self) -> None:
        r = DetectionResult.unknown()
        assert r.parser_key == "unknown"
        assert r.confidence == 0.0
        assert not r.matched

    def test_matched_property_true_at_threshold(self) -> None:
        r = DetectionResult(
            parser_key="extent",
            parser_name="Extent HTML Report Parser",
            confidence=0.50,
            reasons=["test"],
        )
        assert r.matched is True

    def test_matched_property_false_below_threshold(self) -> None:
        r = DetectionResult(
            parser_key="extent",
            parser_name="Extent HTML Report Parser",
            confidence=0.49,
            reasons=["test"],
        )
        assert r.matched is False
