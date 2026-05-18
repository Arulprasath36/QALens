"""Tests for :class:`~qalens.parsers.playwright.PlaywrightReportParser`."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.models.run import TestRun
from qalens.models.test_case import TestStatus
from qalens.parsers.base import ReportMalformedError
from qalens.parsers.playwright import PlaywrightReportParser

FIXTURES = Path(__file__).parent / "fixtures"
PW_JSON_DIR = FIXTURES / "playwright_json_sample"
PW_JSON = PW_JSON_DIR / "report.json"
PW_HTML_DIR = FIXTURES / "playwright_html_sample"
ALLURE_DIR = FIXTURES / "allure_sample"


@pytest.fixture()
def parser() -> PlaywrightReportParser:
    return PlaywrightReportParser()


class TestPlaywrightCanParse:
    def test_matches_playwright_json_file(self, parser: PlaywrightReportParser) -> None:
        result = parser.can_parse(PW_JSON)
        assert result.matched, result.reasons
        assert result.parser_key == "playwright"

    def test_matches_playwright_json_directory(self, parser: PlaywrightReportParser) -> None:
        result = parser.can_parse(PW_JSON_DIR)
        assert result.matched, result.reasons
        assert result.confidence >= 0.90

    def test_matches_json_backed_html_directory(self, parser: PlaywrightReportParser) -> None:
        result = parser.can_parse(PW_HTML_DIR)
        assert result.matched, result.reasons
        assert result.confidence >= 0.90

    def test_does_not_match_allure_directory(self, parser: PlaywrightReportParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert not result.matched

    def test_generic_json_does_not_match(
        self,
        parser: PlaywrightReportParser,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "report.json"
        path.write_text('{"hello":"world"}', encoding="utf-8")

        result = parser.can_parse(path)

        assert not result.matched


class TestPlaywrightParse:
    def test_parse_returns_test_run(self, parser: PlaywrightReportParser) -> None:
        run = parser.parse(PW_JSON)
        assert isinstance(run, TestRun)
        assert run.metadata.report_format == "playwright"

    def test_extracts_tests_and_statuses(self, parser: PlaywrightReportParser) -> None:
        run = parser.parse(PW_JSON)
        statuses = [tc.status for tc in run.test_cases]

        assert len(run.test_cases) == 3
        assert statuses.count(TestStatus.PASSED) == 1
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1

    def test_extracts_owner_feature_tags_retry_and_failure(
        self,
        parser: PlaywrightReportParser,
    ) -> None:
        run = parser.parse(PW_JSON)
        credit_card = next(tc for tc in run.test_cases if tc.name.startswith("testCreditCard"))
        paypal = next(tc for tc in run.test_cases if tc.name.startswith("testPayPal"))

        assert credit_card.owner == "Payments Team"
        assert credit_card.feature == "Checkout"
        assert credit_card.tags == ["payments", "smoke"]
        assert credit_card.retry_count == 1
        assert credit_card.status == TestStatus.PASSED
        assert paypal.status == TestStatus.FAILED
        assert paypal.failure is not None
        assert paypal.failure.error_type == "TimeoutError"

    def test_parse_html_directory_uses_data_report_json(
        self,
        parser: PlaywrightReportParser,
    ) -> None:
        run = parser.parse(PW_HTML_DIR)
        assert len(run.test_cases) == 1
        assert run.test_cases[0].status == TestStatus.PASSED

    def test_raises_for_json_without_playwright_shape(
        self,
        parser: PlaywrightReportParser,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "report.json"
        path.write_text('{"suites":[]}', encoding="utf-8")

        with pytest.raises(ReportMalformedError):
            parser.parse(path)
