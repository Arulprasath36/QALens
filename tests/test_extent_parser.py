"""Tests for :class:`~qalens.parsers.extent.ExtentHtmlParser`.

Uses synthetic HTML fixtures under ``tests/fixtures/extent_sample/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.models.run import TestRun
from qalens.models.test_case import TestStatus
from qalens.models.warnings import WarningSeverity
from qalens.parsers.base import DetectionResult, ReportMalformedError
from qalens.parsers.extent import ExtentHtmlParser

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
        assert "extent" in combined

    def test_matched_files_contains_html(self, parser: ExtentHtmlParser) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert any(f.suffix == ".html" for f in result.matched_files)

    def test_matches_from_html_file_directly(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR / "ExtentReport.html")
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
        assert "extent" in reasons_text.lower()

    def test_detects_meta_generator_signal(
        self, parser: ExtentHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR)
        reasons_text = " ".join(result.reasons).lower()
        assert "extent" in reasons_text


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

    def test_extracts_test_cases(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert len(run.test_cases) == 3

    def test_test_case_names_present(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        names = [tc.name for tc in run.test_cases]
        assert "verifySuccessfulLogin" in names
        assert "verifyPendingLeaveRequests" in names

    def test_statuses_two_passed_one_failed_no_skipped(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        statuses = [tc.status for tc in run.test_cases]
        assert statuses.count(TestStatus.PASSED) == 2
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 0

    def test_failed_test_has_failure_object(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None

    def test_failed_test_error_type(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert failed.failure.error_type is None
        assert failed.failure.message == "Test Failed"

    def test_failed_test_stack_trace_absent_when_report_omits_it(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert failed.failure.stack_trace is None

    def test_failed_test_allows_empty_steps(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.steps == []

    def test_failed_test_has_screenshot_artifact_ref(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert len(failed.raw_artifact_refs) > 0

    def test_passed_test_has_no_failure(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        passed = [tc for tc in run.test_cases if tc.status == TestStatus.PASSED]
        for tc in passed:
            assert tc.failure is None

    def test_test_case_allows_empty_steps(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        first = next(tc for tc in run.test_cases if tc.name == "verifySuccessfulLogin")
        assert first.steps == []

    def test_test_case_allows_empty_tags(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        first = next(tc for tc in run.test_cases if tc.name == "verifySuccessfulLogin")
        assert first.tags == []

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
        assert "OrangeHRM Automation Report" in run.metadata.project

    def test_metadata_report_version_extracted(
        self, parser: ExtentHtmlParser
    ) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.report_version is None

    def test_metadata_started_at_set(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.started_at is None

    def test_metadata_finished_at_set(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR)
        assert run.metadata.finished_at is None

    def test_parse_from_html_file_path(self, parser: ExtentHtmlParser) -> None:
        run = parser.parse(EXTENT_DIR / "ExtentReport.html")
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
