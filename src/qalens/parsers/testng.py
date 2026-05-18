"""TestNG XML parser for QA Lens.

Supports the ``testng-results.xml`` format emitted by TestNG. The parser
normalizes executable ``test-method`` entries and ignores configuration methods
such as setup/teardown hooks.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path  # noqa: TC003
from uuid import uuid4

from defusedxml import ElementTree as ET

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


class TestNGXmlParser(BaseParser):
    """Parser for TestNG XML result files."""

    parser_key = "testng"
    parser_name = "TestNG XML Parser"

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Return a detection result for a TestNG XML file or directory."""
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
            if _local_name(root.tag) != "testng-results":
                continue

            method_count = len(root.findall(".//test-method"))
            matched.append(file_path)
            if method_count > 0:
                reasons.append(
                    f"{file_path.name} has <testng-results> root and "
                    f"{method_count} test-method nodes."
                )
                confidence = max(confidence, 0.94)
                break
            reasons.append(f"{file_path.name} has <testng-results> root.")
            confidence = max(confidence, 0.65)

        if confidence == 0.0:
            return DetectionResult.no_match(
                self.parser_key,
                self.parser_name,
                "XML files did not contain TestNG testng-results structure.",
            )

        return DetectionResult(
            parser_key=self.parser_key,
            parser_name=self.parser_name,
            confidence=confidence,
            reasons=reasons,
            matched_files=matched,
        )

    def parse(self, report_path: Path) -> TestRun:
        """Parse one or more TestNG XML files into a normalized test run."""
        files = _candidate_xml_files(report_path, max_files=1_000)
        if not files:
            raise ReportMalformedError(report_path, "No TestNG XML files found.")

        test_cases: list[TestCaseResult] = []
        suite_names: list[str] = []
        started_at: datetime | None = None
        total_duration_ms = 0

        for file_path in files:
            try:
                root = ET.parse(file_path).getroot()
            except ET.ParseError as exc:
                self._warn(
                    field="TestNGXmlParser.file",
                    reason=f"Skipping malformed XML file: {exc}",
                    severity=WarningSeverity.MEDIUM,
                    raw_value=str(file_path),
                )
                continue
            if _local_name(root.tag) != "testng-results":
                continue

            for suite in root.findall("suite"):
                suite_name = _attr(suite, "name")
                if suite_name:
                    suite_names.append(suite_name)
                suite_started = _parse_timestamp(_attr(suite, "started-at"))
                if suite_started and (started_at is None or suite_started < started_at):
                    started_at = suite_started
                total_duration_ms += _duration_ms(_attr(suite, "duration-ms")) or 0

                for test in suite.findall("test"):
                    test_name = _attr(test, "name")
                    for class_node in test.findall("class"):
                        class_name = _attr(class_node, "name")
                        for method in class_node.findall("test-method"):
                            if _is_config_method(method):
                                continue
                            if len(test_cases) >= MAX_TESTS_PER_RUN:
                                self._warn(
                                    field="TestRun.test_cases",
                                    reason=(
                                        f"Stopped after {MAX_TESTS_PER_RUN} "
                                        "TestNG test methods."
                                    ),
                                    severity=WarningSeverity.HIGH,
                                )
                                break
                            test_cases.append(
                                self._parse_method(
                                    method,
                                    suite_name=suite_name,
                                    test_name=test_name,
                                    class_name=class_name,
                                    source_file=file_path,
                                )
                            )

        if not test_cases:
            raise ReportMalformedError(report_path, "No TestNG test methods found.")

        project = _common_project_name(files, suite_names)
        common_suite = _most_common(suite_names)
        custom_fields = {"suite": common_suite} if common_suite else {}
        metadata = RunMetadata(
            run_id=str(uuid4()),
            report_format=self.parser_key,
            report_path=str(report_path.resolve()),
            project=project,
            started_at=started_at,
            total_duration_ms=total_duration_ms
            or sum(tc.duration_ms or 0 for tc in test_cases),
            custom_fields=custom_fields,
        )
        return TestRun(
            metadata=metadata,
            test_cases=test_cases,
            warnings=self._collect_warnings(),
        )

    def _parse_method(
        self,
        method: ET.Element,
        *,
        suite_name: str | None,
        test_name: str | None,
        class_name: str | None,
        source_file: Path,
    ) -> TestCaseResult:
        name = truncate(_attr(method, "name") or "unknown", MAX_TEST_NAME_CHARS)
        display_name = f"{class_name}.{name}" if class_name else name
        status = _status(_attr(method, "status"))
        owner = _attribute(method, "owner")
        feature = _attribute(method, "feature") or test_name
        story = _attribute(method, "story")
        tags = _tags(method)

        return TestCaseResult(
            test_id=sanitize_test_id(
                "::".join(part for part in [str(source_file), class_name, name] if part)
            ),
            name=name,
            full_name=display_name,
            status=status,
            suite=suite_name or test_name or class_name,
            feature=feature,
            story=story,
            owner=owner,
            tags=tags,
            started_at=_parse_timestamp(_attr(method, "started-at")),
            finished_at=_parse_timestamp(_attr(method, "finished-at")),
            duration_ms=_duration_ms(_attr(method, "duration-ms")),
            failure=_failure(method),
            source_format=self.parser_key,
            raw_id=_attr(method, "signature"),
        )


def _candidate_xml_files(path: Path, *, max_files: int) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".xml" else []
    if not path.is_dir():
        return []
    preferred = (
        sorted(path.rglob("testng-results.xml"))
        + sorted(path.rglob("*testng*.xml"))
        + sorted(path.rglob("*.xml"))
    )
    deduped = list(dict.fromkeys(p for p in preferred if p.is_file()))
    return deduped[:max_files]


def _is_config_method(method: ET.Element) -> bool:
    return (_attr(method, "is-config") or "").lower() == "true"


def _status(value: str | None) -> TestStatus:
    mapping = {
        "pass": TestStatus.PASSED,
        "passed": TestStatus.PASSED,
        "fail": TestStatus.FAILED,
        "failed": TestStatus.FAILED,
        "skip": TestStatus.SKIPPED,
        "skipped": TestStatus.SKIPPED,
    }
    return mapping.get((value or "").strip().lower(), TestStatus.UNKNOWN)


def _failure(method: ET.Element) -> FailureInfo | None:
    node = method.find("exception")
    if node is None:
        return None
    message = _node_text(node.find("message"))
    stack_trace = _node_text(node.find("full-stacktrace"))
    if message is None and stack_trace:
        message = stack_trace.splitlines()[0].strip()
    error_type = _attr(node, "class") or "exception"
    return FailureInfo(
        error_type=truncate(error_type, 512),
        message=truncate(message, MAX_ERROR_MESSAGE_CHARS) if message else None,
        stack_trace=truncate(stack_trace, MAX_STACK_TRACE_CHARS) if stack_trace else None,
    )


def _attribute(method: ET.Element, name: str) -> str | None:
    for attr in method.findall("attributes/attribute"):
        if (_attr(attr, "name") or "").lower() != name.lower():
            continue
        return _attr(attr, "value") or _node_text(attr.find("value")) or _node_text(attr)
    return None


def _tags(method: ET.Element) -> list[str]:
    values: list[str] = []
    raw = _attribute(method, "tags") or _attribute(method, "tag")
    if raw:
        values.extend(_split_tags(raw))
    for group in method.findall("groups/group"):
        group_name = _attr(group, "name") or _node_text(group)
        if group_name:
            values.extend(_split_tags(group_name))

    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _split_tags(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _attr(element: ET.Element, name: str) -> str | None:
    value = element.attrib.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _node_text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    cleaned = node.text.strip()
    return cleaned or None


def _duration_ms(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(float(value)))
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
