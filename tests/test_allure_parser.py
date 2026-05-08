"""Tests for :class:`~qara.parsers.allure.AllureHtmlParser`.

Uses synthetic JSON/HTML fixtures under ``tests/fixtures/allure_sample/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qara.models.run import TestRun
from qara.models.test_case import TestStatus
from qara.models.warnings import WarningSeverity
from qara.parsers.allure import AllureHtmlParser
from qara.parsers.base import ReportMalformedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
ALLURE_DIR = FIXTURES / "allure_sample"
EXTENT_DIR = FIXTURES / "extent_sample"


@pytest.fixture()
def parser() -> AllureHtmlParser:
    return AllureHtmlParser()


# ---------------------------------------------------------------------------
# can_parse — positive signals
# ---------------------------------------------------------------------------


class TestAllureCanParsePositive:
    def test_matches_allure_directory(self, parser: AllureHtmlParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert result.matched, f"reasons={result.reasons}"

    def test_confidence_high_with_both_json_files(
        self, parser: AllureHtmlParser
    ) -> None:
        result = parser.can_parse(ALLURE_DIR)
        # Both widgets/summary.json and data/suites.json present → ≥0.95
        assert result.confidence >= 0.90

    def test_parser_key_is_allure(self, parser: AllureHtmlParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert result.parser_key == "allure"

    def test_parser_name_is_set(self, parser: AllureHtmlParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert result.parser_name == "Allure HTML Report Parser"

    def test_reasons_mention_summary_json(self, parser: AllureHtmlParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        reasons_text = " ".join(result.reasons)
        assert "summary.json" in reasons_text

    def test_matched_files_includes_summary_json(
        self, parser: AllureHtmlParser
    ) -> None:
        result = parser.can_parse(ALLURE_DIR)
        names = [f.name for f in result.matched_files]
        assert "summary.json" in names

    def test_matched_files_includes_suites_json(
        self, parser: AllureHtmlParser
    ) -> None:
        result = parser.can_parse(ALLURE_DIR)
        names = [f.name for f in result.matched_files]
        assert "suites.json" in names

    def test_matches_from_index_html_directly(
        self, parser: AllureHtmlParser
    ) -> None:
        result = parser.can_parse(ALLURE_DIR / "index.html")
        assert result.matched

    def test_detects_summary_only_directory(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        (tmp_path / "widgets").mkdir()
        (tmp_path / "widgets" / "summary.json").write_text(
            '{"reportName":"test","statistic":{},"time":{}}'
        )
        result = parser.can_parse(tmp_path)
        assert result.matched
        assert result.confidence >= 0.90

    def test_detects_suites_only_directory(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "suites.json").write_text('{"uid":"x","children":[]}')
        result = parser.can_parse(tmp_path)
        assert result.matched
        assert result.confidence >= 0.80


# ---------------------------------------------------------------------------
# can_parse — negative signals
# ---------------------------------------------------------------------------


class TestAllureCanParseNegative:
    def test_low_confidence_for_extent_directory(
        self, parser: AllureHtmlParser
    ) -> None:
        result = parser.can_parse(EXTENT_DIR)
        assert not result.matched, (
            f"Should not match Extent directory; confidence={result.confidence}, "
            f"reasons={result.reasons}"
        )

    def test_no_match_for_missing_path(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        result = parser.can_parse(tmp_path / "does_not_exist")
        assert not result.matched

    def test_low_confidence_for_empty_directory(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        result = parser.can_parse(tmp_path)
        assert not result.matched

    def test_generic_html_not_matched(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        html = tmp_path / "index.html"
        html.write_text("<html><title>My App</title><body>Hello</body></html>")
        result = parser.can_parse(tmp_path)
        assert not result.matched


# ---------------------------------------------------------------------------
# parse — Phase 3 full extraction
# ---------------------------------------------------------------------------


class TestAllureParse:
    def test_parse_returns_test_run(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        assert isinstance(run, TestRun)

    def test_extracts_four_test_cases(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        assert len(run.test_cases) == 4

    def test_statuses_two_passed_one_failed_one_skipped(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        statuses = [tc.status for tc in run.test_cases]
        assert statuses.count(TestStatus.PASSED) == 2
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1

    def test_failed_test_has_failure_object(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None

    def test_failed_test_failure_message_contains_error_banner(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert "error-banner" in (failed.failure.message or "")

    def test_failed_test_has_stack_trace(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.failure is not None
        assert failed.failure.stack_trace is not None
        assert "NoSuchElementException" in failed.failure.stack_trace

    def test_failed_test_retry_count(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert failed.retry_count == 1

    def test_failed_test_has_steps(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert len(failed.steps) > 0

    def test_failed_test_has_attachments(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        assert len(failed.attachments) > 0

    def test_passed_test_has_steps(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        # tc-001 has 3 steps
        tc001 = next(
            tc
            for tc in run.test_cases
            if tc.full_name == "com.example.tests.LoginTest#testValidLogin"
        )
        assert len(tc001.steps) == 3

    def test_passed_test_has_no_failure(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        passed = [tc for tc in run.test_cases if tc.status == TestStatus.PASSED]
        for tc in passed:
            assert tc.failure is None

    def test_skipped_test_status(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        skipped = next(
            tc for tc in run.test_cases if tc.status == TestStatus.SKIPPED
        )
        assert skipped.full_name == "com.example.tests.ExportTest#testExportPdf"

    def test_labels_feature_story_suite_extracted(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        tc001 = next(
            tc
            for tc in run.test_cases
            if tc.full_name == "com.example.tests.LoginTest#testValidLogin"
        )
        assert tc001.feature == "Authentication"
        assert tc001.story == "Valid Login"
        assert tc001.suite == "Authentication Tests"

    def test_tags_extracted(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        tc001 = next(
            tc
            for tc in run.test_cases
            if tc.full_name == "com.example.tests.LoginTest#testValidLogin"
        )
        assert len(tc001.tags) > 0

    def test_links_extracted(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        tc001 = next(
            tc
            for tc in run.test_cases
            if tc.full_name == "com.example.tests.LoginTest#testValidLogin"
        )
        assert len(tc001.links) > 0

    def test_metadata_report_format_is_allure(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.report_format == "allure"

    def test_metadata_report_path_set(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.report_path  # non-empty string

    def test_metadata_project_from_summary_json(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.project == "My CI Project — Integration Suite"

    def test_metadata_started_at_from_summary_json(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.started_at is not None

    def test_metadata_finished_at_from_summary_json(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.finished_at is not None

    def test_started_at_before_finished_at(
        self, parser: AllureHtmlParser
    ) -> None:
        run = parser.parse(ALLURE_DIR)
        assert run.metadata.started_at < run.metadata.finished_at  # type: ignore[operator]

    def test_parse_from_html_file_path(self, parser: AllureHtmlParser) -> None:
        run = parser.parse(ALLURE_DIR / "index.html")
        assert isinstance(run, TestRun)

    def test_parse_with_no_summary_json_warns(
        self, parser: AllureHtmlParser, tmp_path: Path
    ) -> None:
        # Directory without summary.json but with a valid entry HTML
        html = tmp_path / "index.html"
        html.write_text("<html><title>Allure Report</title></html>")
        run = parser.parse(tmp_path)
        assert isinstance(run, TestRun)
        project_warnings = [
            w for w in run.warnings if "project" in w.field.lower()
        ]
        assert project_warnings  # should warn about missing project name
