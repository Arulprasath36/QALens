"""Tests for :class:`~qalens.parsers.junit.JUnitXmlParser`."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.models.run import TestRun
from qalens.models.test_case import TestStatus
from qalens.parsers.base import ReportMalformedError
from qalens.parsers.junit import JUnitXmlParser

FIXTURES = Path(__file__).parent / "fixtures"
JUNIT_DIR = FIXTURES / "junit_sample"
JUNIT_XML = JUNIT_DIR / "TEST-shopnow.xml"
ALLURE_DIR = FIXTURES / "allure_sample"


@pytest.fixture()
def parser() -> JUnitXmlParser:
    return JUnitXmlParser()


class TestJUnitCanParse:
    def test_matches_junit_xml_file(self, parser: JUnitXmlParser) -> None:
        result = parser.can_parse(JUNIT_XML)
        assert result.matched, result.reasons
        assert result.parser_key == "junit"

    def test_matches_junit_directory(self, parser: JUnitXmlParser) -> None:
        result = parser.can_parse(JUNIT_DIR)
        assert result.matched, result.reasons
        assert result.confidence >= 0.90

    def test_does_not_match_allure_directory(self, parser: JUnitXmlParser) -> None:
        result = parser.can_parse(ALLURE_DIR)
        assert not result.matched

    def test_generic_xml_does_not_match(self, parser: JUnitXmlParser, tmp_path: Path) -> None:
        xml = tmp_path / "report.xml"
        xml.write_text("<report><item>not junit</item></report>", encoding="utf-8")

        result = parser.can_parse(xml)

        assert not result.matched


class TestJUnitParse:
    def test_parse_returns_test_run(self, parser: JUnitXmlParser) -> None:
        run = parser.parse(JUNIT_DIR)
        assert isinstance(run, TestRun)
        assert run.metadata.report_format == "junit"

    def test_extracts_test_cases_and_statuses(self, parser: JUnitXmlParser) -> None:
        run = parser.parse(JUNIT_DIR)
        statuses = [tc.status for tc in run.test_cases]

        assert len(run.test_cases) == 4
        assert statuses.count(TestStatus.PASSED) == 1
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.BROKEN) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1

    def test_extracts_failure_and_error_details(self, parser: JUnitXmlParser) -> None:
        run = parser.parse(JUNIT_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)
        broken = next(tc for tc in run.test_cases if tc.status == TestStatus.BROKEN)

        assert failed.failure is not None
        assert failed.failure.error_type == "java.lang.AssertionError"
        assert "Expected validation error" in (failed.failure.message or "")
        assert broken.failure is not None
        assert broken.failure.error_type == "org.openqa.selenium.TimeoutException"

    def test_extracts_suite_owner_feature_and_tags(self, parser: JUnitXmlParser) -> None:
        run = parser.parse(JUNIT_DIR)
        login = next(tc for tc in run.test_cases if tc.name.endswith("testValidUserLogin"))

        assert login.suite == "Authentication Tests"
        assert login.owner == "Authentication Team"
        assert login.feature == "Authentication"
        assert login.tags == ["auth", "smoke"]

    def test_raises_for_xml_without_testcases(
        self,
        parser: JUnitXmlParser,
        tmp_path: Path,
    ) -> None:
        xml = tmp_path / "TEST-empty.xml"
        xml.write_text("<testsuite name='empty'/>", encoding="utf-8")

        with pytest.raises(ReportMalformedError):
            parser.parse(xml)
