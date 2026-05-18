"""JUnit XML parser for QaLens.

Supports the common ``<testsuites>`` and ``<testsuite>`` report shapes emitted
by Maven Surefire, Gradle, pytest, Jest, Playwright, Cypress reporters, and
many CI systems.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path  # noqa: TC003
from uuid import uuid4

from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.models.warnings import WarningSeverity
from qalens.parsers.base import BaseParser, DetectionResult, ReportMalformedError
from qalens.security import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_STACK_TRACE_CHARS,
    MAX_TEST_NAME_CHARS,
    MAX_TESTS_PER_RUN,
)
from qalens.utils.text import sanitize_test_id, truncate


class JUnitXmlParser(BaseParser):
    """Parser for JUnit-compatible XML result files."""

    parser_key = "junit"
    parser_name = "JUnit XML Parser"

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Return a detection result for a JUnit XML file or directory."""
        files = _candidate_xml_files(report_path, max_files=10)
        if not files:
            return DetectionResult.no_match(
                self.parser_key,
                self.parser_name,
                "No XML files found.",
            )

        matched: list[Path] = []
        reasons: list[str] = []
        confidence = 0.0
        for file_path in files:
            try:
                root = ET.parse(file_path).getroot()
            except (ET.ParseError, OSError):
                continue
            root_name = _local_name(root.tag)
            if root_name in {"testsuite", "testsuites"}:
                testcase_count = len(root.findall(".//testcase"))
                if testcase_count > 0:
                    matched.append(file_path)
                    reasons.append(
                        f"{file_path.name} has <{root_name}> root and "
                        f"{testcase_count} testcase nodes."
                    )
                    confidence = max(confidence, 0.92)
                    break
                matched.append(file_path)
                reasons.append(f"{file_path.name} has <{root_name}> root.")
                confidence = max(confidence, 0.65)

        if confidence == 0.0:
            return DetectionResult.no_match(
                self.parser_key,
                self.parser_name,
                "XML files did not contain JUnit testsuite/testcase structure.",
            )

        return DetectionResult(
            parser_key=self.parser_key,
            parser_name=self.parser_name,
            confidence=confidence,
            reasons=reasons,
            matched_files=matched,
        )

    def parse(self, report_path: Path) -> TestRun:
        """Parse one or more JUnit XML files into a normalized test run."""
        files = _candidate_xml_files(report_path, max_files=1_000)
        if not files:
            raise ReportMalformedError(report_path, "No JUnit XML files found.")

        test_cases: list[TestCaseResult] = []
        suite_names: list[str] = []
        started_at: datetime | None = None
        total_duration_ms = 0

        for file_path in files:
            try:
                root = ET.parse(file_path).getroot()
            except ET.ParseError as exc:
                self._warn(
                    field="JUnitXmlParser.file",
                    reason=f"Skipping malformed XML file: {exc}",
                    severity=WarningSeverity.MEDIUM,
                    raw_value=str(file_path),
                )
                continue

            suites = _suite_elements(root)
            for suite in suites:
                suite_name = _attr(suite, "name")
                if suite_name:
                    suite_names.append(suite_name)
                suite_started = _parse_timestamp(_attr(suite, "timestamp"))
                if suite_started and (started_at is None or suite_started < started_at):
                    started_at = suite_started
                total_duration_ms += _duration_ms(_attr(suite, "time")) or 0
                for case in suite.findall("testcase"):
                    if len(test_cases) >= MAX_TESTS_PER_RUN:
                        self._warn(
                            field="TestRun.test_cases",
                            reason=f"Stopped after {MAX_TESTS_PER_RUN} JUnit test cases.",
                            severity=WarningSeverity.HIGH,
                        )
                        break
                    test_cases.append(
                        self._parse_testcase(
                            case,
                            suite_name=suite_name,
                            source_file=file_path,
                        )
                    )

        if not test_cases:
            raise ReportMalformedError(report_path, "No <testcase> elements found.")

        project = _common_project_name(files, suite_names)
        common_suite = _most_common(suite_names)
        custom_fields = {"suite": common_suite} if common_suite else {}
        metadata = RunMetadata(
            run_id=str(uuid4()),
            report_format=self.parser_key,
            report_path=str(report_path.resolve()),
            project=project,
            started_at=started_at,
            total_duration_ms=total_duration_ms or sum(
                tc.duration_ms or 0 for tc in test_cases
            ),
            custom_fields=custom_fields,
        )
        return TestRun(
            metadata=metadata,
            test_cases=test_cases,
            warnings=self._collect_warnings(),
        )

    def _parse_testcase(
        self,
        case: ET.Element,
        *,
        suite_name: str | None,
        source_file: Path,
    ) -> TestCaseResult:
        name = truncate(_attr(case, "name") or "unknown", MAX_TEST_NAME_CHARS)
        classname = _attr(case, "classname")
        display_name = f"{classname}.{name}" if classname else name
        status = _status(case)
        failure = _failure(case)
        owner = _property(case, "owner")
        feature = _property(case, "feature")
        story = _property(case, "story")
        tags = _tags(case)

        return TestCaseResult(
            test_id=sanitize_test_id(
                "::".join(part for part in [str(source_file), classname, name] if part)
            ),
            name=display_name,
            full_name=display_name,
            status=status,
            suite=suite_name or classname,
            feature=feature,
            story=story,
            owner=owner,
            tags=tags,
            duration_ms=_duration_ms(_attr(case, "time")),
            failure=failure,
            source_format=self.parser_key,
            raw_id=_attr(case, "id"),
        )


def _candidate_xml_files(path: Path, *, max_files: int) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".xml" else []
    if not path.is_dir():
        return []
    preferred = sorted(path.rglob("TEST-*.xml")) + sorted(path.rglob("*.xml"))
    deduped = list(dict.fromkeys(p for p in preferred if p.is_file()))
    return deduped[:max_files]


def _suite_elements(root: ET.Element) -> list[ET.Element]:
    root_name = _local_name(root.tag)
    if root_name == "testsuite":
        return [root]
    if root_name == "testsuites":
        return [child for child in root if _local_name(child.tag) == "testsuite"]
    return []


def _status(case: ET.Element) -> TestStatus:
    if case.find("skipped") is not None:
        return TestStatus.SKIPPED
    if case.find("error") is not None:
        return TestStatus.BROKEN
    if case.find("failure") is not None:
        return TestStatus.FAILED
    return TestStatus.PASSED


def _failure(case: ET.Element) -> FailureInfo | None:
    node = case.find("failure")
    if node is None:
        node = case.find("error")
    if node is None:
        return None
    error_type = _attr(node, "type") or _local_name(node.tag)
    message = _attr(node, "message") or (node.text or "").strip() or None
    stack_trace = (node.text or "").strip() or message
    return FailureInfo(
        error_type=truncate(error_type, 512),
        message=truncate(message, MAX_ERROR_MESSAGE_CHARS) if message else None,
        stack_trace=truncate(stack_trace, MAX_STACK_TRACE_CHARS) if stack_trace else None,
    )


def _property(case: ET.Element, name: str) -> str | None:
    for prop in case.findall("properties/property"):
        if _attr(prop, "name") == name:
            return _attr(prop, "value")
    return None


def _tags(case: ET.Element) -> list[str]:
    raw = _property(case, "tags") or _property(case, "tag")
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _attr(element: ET.Element, name: str) -> str | None:
    value = element.attrib.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _duration_ms(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value) * 1000)
    except ValueError:
        return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _common_project_name(files: list[Path], suite_names: list[str]) -> str | None:
    if len(files) == 1:
        return files[0].parent.name or files[0].stem
    return _most_common(suite_names)


def _most_common(values: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda value: counts[value])
