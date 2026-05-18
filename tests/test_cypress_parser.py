"""Tests for :class:`~qalens.parsers.cypress.CypressJsonParser`."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.models.run import TestRun
from qalens.models.test_case import TestStatus
from qalens.parsers.base import ReportMalformedError
from qalens.parsers.cypress import CypressJsonParser

FIXTURES = Path(__file__).parent / "fixtures"
MOCHAWESOME_DIR = FIXTURES / "cypress_mochawesome_sample"
CYPRESS_RUN_DIR = FIXTURES / "cypress_run_sample"
PLAYWRIGHT_DIR = FIXTURES / "playwright_json_sample"


@pytest.fixture()
def parser() -> CypressJsonParser:
    return CypressJsonParser()


class TestCypressCanParse:
    def test_matches_mochawesome_directory(self, parser: CypressJsonParser) -> None:
        result = parser.can_parse(MOCHAWESOME_DIR)
        assert result.matched, result.reasons
        assert result.parser_key == "cypress"

    def test_matches_cypress_run_directory(self, parser: CypressJsonParser) -> None:
        result = parser.can_parse(CYPRESS_RUN_DIR)
        assert result.matched, result.reasons
        assert result.parser_key == "cypress"

    def test_does_not_match_playwright_directory(self, parser: CypressJsonParser) -> None:
        result = parser.can_parse(PLAYWRIGHT_DIR)
        assert not result.matched

    def test_generic_json_does_not_match(self, parser: CypressJsonParser, tmp_path: Path) -> None:
        path = tmp_path / "report.json"
        path.write_text('{"results":[]}', encoding="utf-8")

        result = parser.can_parse(path)

        assert not result.matched


class TestCypressParse:
    def test_parse_mochawesome_returns_test_run(self, parser: CypressJsonParser) -> None:
        run = parser.parse(MOCHAWESOME_DIR)
        assert isinstance(run, TestRun)
        assert run.metadata.report_format == "cypress"

    def test_parse_mochawesome_extracts_statuses_and_failure(
        self,
        parser: CypressJsonParser,
    ) -> None:
        run = parser.parse(MOCHAWESOME_DIR)
        statuses = [tc.status for tc in run.test_cases]
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)

        assert len(run.test_cases) == 3
        assert statuses.count(TestStatus.PASSED) == 1
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1
        assert failed.failure is not None
        assert failed.failure.error_type == "AssertionError"
        assert failed.tags == ["payments"]

    def test_parse_cypress_run_extracts_retries_and_failures(
        self,
        parser: CypressJsonParser,
    ) -> None:
        run = parser.parse(CYPRESS_RUN_DIR)
        login = next(tc for tc in run.test_cases if tc.name == "testValidUserLogin")
        invalid = next(tc for tc in run.test_cases if tc.name.startswith("testInvalid"))

        assert len(run.test_cases) == 2
        assert login.status == TestStatus.PASSED
        assert login.retry_count == 1
        assert invalid.status == TestStatus.FAILED
        assert invalid.failure is not None
        assert invalid.failure.error_type == "AssertionError"
        assert invalid.tags == ["auth"]

    def test_raises_for_unsupported_json(self, parser: CypressJsonParser, tmp_path: Path) -> None:
        path = tmp_path / "report.json"
        path.write_text('{"stats":{}, "results":[]}', encoding="utf-8")

        with pytest.raises(ReportMalformedError):
            parser.parse(path)
