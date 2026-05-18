"""Tests for :class:`~qalens.parsers.testng.TestNGXmlParser`."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalens.models.run import TestRun
from qalens.models.test_case import TestStatus
from qalens.parsers.base import ReportMalformedError
from qalens.parsers.testng import TestNGXmlParser

FIXTURES = Path(__file__).parent / "fixtures"
TESTNG_DIR = FIXTURES / "testng_sample"
TESTNG_XML = TESTNG_DIR / "testng-results.xml"
JUNIT_DIR = FIXTURES / "junit_sample"


@pytest.fixture()
def parser() -> TestNGXmlParser:
    return TestNGXmlParser()


class TestTestNGCanParse:
    def test_matches_testng_xml_file(self, parser: TestNGXmlParser) -> None:
        result = parser.can_parse(TESTNG_XML)
        assert result.matched, result.reasons
        assert result.parser_key == "testng"

    def test_matches_testng_directory(self, parser: TestNGXmlParser) -> None:
        result = parser.can_parse(TESTNG_DIR)
        assert result.matched, result.reasons
        assert result.confidence >= 0.90

    def test_does_not_match_junit_directory(self, parser: TestNGXmlParser) -> None:
        result = parser.can_parse(JUNIT_DIR)
        assert not result.matched

    def test_generic_xml_does_not_match(self, parser: TestNGXmlParser, tmp_path: Path) -> None:
        xml = tmp_path / "report.xml"
        xml.write_text("<report><item>not testng</item></report>", encoding="utf-8")

        result = parser.can_parse(xml)

        assert not result.matched


class TestTestNGParse:
    def test_parse_returns_test_run(self, parser: TestNGXmlParser) -> None:
        run = parser.parse(TESTNG_DIR)
        assert isinstance(run, TestRun)
        assert run.metadata.report_format == "testng"

    def test_extracts_test_cases_statuses_and_ignores_config_methods(
        self,
        parser: TestNGXmlParser,
    ) -> None:
        run = parser.parse(TESTNG_DIR)
        statuses = [tc.status for tc in run.test_cases]

        assert len(run.test_cases) == 3
        assert statuses.count(TestStatus.PASSED) == 1
        assert statuses.count(TestStatus.FAILED) == 1
        assert statuses.count(TestStatus.SKIPPED) == 1
        assert all(tc.name != "beforeMethod" for tc in run.test_cases)

    def test_extracts_failure_details(self, parser: TestNGXmlParser) -> None:
        run = parser.parse(TESTNG_DIR)
        failed = next(tc for tc in run.test_cases if tc.status == TestStatus.FAILED)

        assert failed.failure is not None
        assert failed.failure.error_type == "java.lang.AssertionError"
        assert "Expected confirmation banner" in (failed.failure.message or "")
        assert "CheckoutTest.java:42" in (failed.failure.stack_trace or "")

    def test_extracts_suite_owner_feature_story_and_tags(
        self,
        parser: TestNGXmlParser,
    ) -> None:
        run = parser.parse(TESTNG_DIR)
        paypal = next(tc for tc in run.test_cases if tc.name == "testPayPalRedirect")

        assert paypal.suite == "ShopNow Suite"
        assert paypal.full_name == "com.shopnow.checkout.CheckoutTest.testPayPalRedirect"
        assert paypal.owner == "Payments Team"
        assert paypal.feature == "Checkout"
        assert paypal.story == "PayPal redirect"
        assert paypal.tags == ["payments", "smoke", "regression"]

    def test_raises_for_xml_without_test_methods(
        self,
        parser: TestNGXmlParser,
        tmp_path: Path,
    ) -> None:
        xml = tmp_path / "testng-results.xml"
        xml.write_text("<testng-results><suite name='empty'/></testng-results>", encoding="utf-8")

        with pytest.raises(ReportMalformedError):
            parser.parse(xml)
