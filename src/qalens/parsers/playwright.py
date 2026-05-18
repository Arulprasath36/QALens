"""Playwright JSON/HTML report parser for QALens.

The Playwright JSON reporter is the most stable structured input.  Playwright
HTML report folders are supported when they include the same JSON payload in a
common report data location such as ``data/report.json``.
"""
# ruff: noqa: ANN401

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import Any
from uuid import uuid4

from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.parsers.base import BaseParser, DetectionResult, ReportMalformedError
from qalens.security import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_STACK_TRACE_CHARS,
    MAX_TEST_NAME_CHARS,
    MAX_TESTS_PER_RUN,
)
from qalens.utils.text import sanitize_test_id, truncate


class PlaywrightReportParser(BaseParser):
    """Parser for Playwright JSON reports and JSON-backed HTML reports."""

    parser_key = "playwright"
    parser_name = "Playwright JSON/HTML Report Parser"

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Return a detection result for Playwright report inputs."""
        json_file = _find_payload_file(report_path)
        reasons: list[str] = []
        matched: list[Path] = []

        if json_file:
            payload = _load_json(json_file)
            if _looks_like_playwright_payload(payload):
                matched.append(json_file)
                reasons.append(f"{json_file.name} has Playwright suites/specs/tests data.")
                confidence = 0.92
                if _has_playwright_html_marker(report_path):
                    confidence = 0.95
                    reasons.append("HTML report marker also references Playwright.")
                return DetectionResult(
                    parser_key=self.parser_key,
                    parser_name=self.parser_name,
                    confidence=confidence,
                    reasons=reasons,
                    matched_files=matched,
                )

        if _has_playwright_html_marker(report_path):
            html = _entry_html(report_path)
            return DetectionResult(
                parser_key=self.parser_key,
                parser_name=self.parser_name,
                confidence=0.35,
                reasons=[
                    "Playwright HTML marker found, but no supported JSON payload was found."
                ],
                matched_files=[html] if html else [],
            )

        return DetectionResult.no_match(
            self.parser_key,
            self.parser_name,
            "No Playwright JSON or HTML report markers found.",
        )

    def parse(self, report_path: Path) -> TestRun:
        """Parse a Playwright report into a normalized test run."""
        payload_file = _find_payload_file(report_path)
        if payload_file is None:
            raise ReportMalformedError(report_path, "No Playwright JSON payload found.")

        payload = _load_json(payload_file)
        if not _looks_like_playwright_payload(payload):
            raise ReportMalformedError(report_path, "JSON does not look like a Playwright report.")

        suites = payload.get("suites") if isinstance(payload, dict) else None
        if not isinstance(suites, list):
            raise ReportMalformedError(report_path, "Playwright report has no suites array.")

        tests: list[TestCaseResult] = []
        for suite in suites:
            if isinstance(suite, dict):
                _collect_suite_tests(suite, suite_path=[], out=tests, source=self.parser_key)
            if len(tests) >= MAX_TESTS_PER_RUN:
                break

        if not tests:
            raise ReportMalformedError(report_path, "No Playwright tests found.")

        started_at = _earliest_start_time(tests)
        metadata = RunMetadata(
            run_id=str(uuid4()),
            report_format=self.parser_key,
            report_path=str(report_path.resolve()),
            project=_project_name(payload, payload_file),
            started_at=started_at,
            total_duration_ms=sum(tc.duration_ms or 0 for tc in tests),
            custom_fields={"suite": _most_common([tc.suite for tc in tests if tc.suite]) or ""},
        )
        if not metadata.custom_fields["suite"]:
            metadata.custom_fields = {}

        return TestRun(
            metadata=metadata,
            test_cases=tests,
            warnings=self._collect_warnings(),
        )


def _collect_suite_tests(
    suite: dict[str, Any],
    *,
    suite_path: list[str],
    out: list[TestCaseResult],
    source: str,
) -> None:
    title = _str(suite.get("title"))
    next_path = [*suite_path, title] if title else suite_path

    specs = suite.get("specs")
    if isinstance(specs, list):
        for spec in specs:
            if isinstance(spec, dict):
                _collect_spec_tests(spec, suite_path=next_path, out=out, source=source)

    children = suite.get("suites")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _collect_suite_tests(child, suite_path=next_path, out=out, source=source)


def _collect_spec_tests(
    spec: dict[str, Any],
    *,
    suite_path: list[str],
    out: list[TestCaseResult],
    source: str,
) -> None:
    spec_title = truncate(_str(spec.get("title")) or "unknown", MAX_TEST_NAME_CHARS)
    file_name = _str(spec.get("file"))
    spec_tags = _tag_values(spec.get("tags"))
    tests = spec.get("tests")
    if not isinstance(tests, list):
        return

    for test in tests:
        if not isinstance(test, dict):
            continue
        project_name = _str(test.get("projectName"))
        results = test.get("results")
        result_items = (
            [item for item in results if isinstance(item, dict)]
            if isinstance(results, list)
            else []
        )
        final_result = result_items[-1] if result_items else {}
        annotations = _annotations(test.get("annotations")) + _annotations(spec.get("annotations"))
        owner = _annotation_value(annotations, "owner")
        feature = _annotation_value(annotations, "feature")
        story = _annotation_value(annotations, "story")
        tags = sorted(set(spec_tags + _annotation_tags(annotations)))
        status = _status(_str(final_result.get("status")) or _str(test.get("expectedStatus")))
        failure = _failure(final_result)
        duration_ms = sum(int(item.get("duration") or 0) for item in result_items)
        if duration_ms == 0:
            duration_ms = int(final_result.get("duration") or 0)

        display_name = spec_title if not project_name else f"{spec_title} [{project_name}]"
        full_name = " › ".join(part for part in [file_name, *suite_path, display_name] if part)
        out.append(
            TestCaseResult(
                test_id=sanitize_test_id(full_name or display_name),
                name=display_name,
                full_name=full_name or display_name,
                status=status,
                suite=" › ".join(suite_path) or file_name,
                feature=feature,
                story=story,
                owner=owner,
                tags=tags,
                duration_ms=duration_ms,
                failure=failure,
                retry_count=max(0, len(result_items) - 1),
                source_format=source,
                raw_id=_str(test.get("testId")),
            )
        )


def _find_payload_file(path: Path) -> Path | None:
    if path.is_file():
        if path.suffix.lower() != ".json":
            return None
        return path
    if not path.is_dir():
        return None

    preferred = [
        path / "report.json",
        path / "results.json",
        path / "playwright-report.json",
        path / "data" / "report.json",
        path / "data" / "results.json",
    ]
    for candidate in preferred:
        if candidate.is_file() and _looks_like_playwright_payload(_load_json(candidate)):
            return candidate

    for candidate in sorted(path.rglob("*.json"))[:50]:
        if _looks_like_playwright_payload(_load_json(candidate)):
            return candidate
    return None


def _looks_like_playwright_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    suites = payload.get("suites")
    if not isinstance(suites, list):
        return False
    text = json.dumps(payload)[:20_000].lower()
    return (
        "projectname" in text
        or "expectedstatus" in text
        or '"specs"' in text and '"tests"' in text and '"results"' in text
    )


def _has_playwright_html_marker(path: Path) -> bool:
    html = _entry_html(path)
    if html is None:
        return False
    try:
        text = html.read_text(encoding="utf-8", errors="ignore")[:100_000].lower()
    except OSError:
        return False
    return "playwright" in text and ("html report" in text or "playwright-report" in text)


def _entry_html(path: Path) -> Path | None:
    if path.is_file() and path.suffix.lower() in {".html", ".htm"}:
        return path
    if path.is_dir():
        candidate = path / "index.html"
        return candidate if candidate.is_file() else None
    return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _status(value: str | None) -> TestStatus:
    normalized = (value or "").lower()
    if normalized == "passed":
        return TestStatus.PASSED
    if normalized == "skipped":
        return TestStatus.SKIPPED
    if normalized in {"failed", "timedout", "timed_out"}:
        return TestStatus.FAILED
    if normalized in {"interrupted", "crashed"}:
        return TestStatus.BROKEN
    return TestStatus.UNKNOWN


def _failure(result: dict[str, Any]) -> FailureInfo | None:
    error = result.get("error")
    if not isinstance(error, dict):
        errors = result.get("errors")
        if isinstance(errors, list):
            error = next((item for item in errors if isinstance(item, dict)), None)
    if not isinstance(error, dict):
        return None
    message = _str(error.get("message"))
    stack = _str(error.get("stack")) or message
    return FailureInfo(
        error_type=_error_type(message, stack),
        message=truncate(message, MAX_ERROR_MESSAGE_CHARS) if message else None,
        stack_trace=truncate(stack, MAX_STACK_TRACE_CHARS) if stack else None,
    )


def _error_type(message: str | None, stack: str | None) -> str | None:
    first = (stack or message or "").splitlines()[0].strip()
    if ":" in first:
        return first.split(":", 1)[0].strip() or None
    return "PlaywrightError" if first else None


def _annotations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    annotations = []
    for item in value:
        if not isinstance(item, dict):
            continue
        annotations.append({
            "type": _str(item.get("type")) or "",
            "description": _str(item.get("description")) or "",
        })
    return annotations


def _annotation_value(annotations: list[dict[str, str]], key: str) -> str | None:
    for annotation in annotations:
        if annotation["type"].lower() == key:
            return annotation["description"] or None
    return None


def _annotation_tags(annotations: list[dict[str, str]]) -> list[str]:
    tags = []
    for annotation in annotations:
        if annotation["type"].lower() == "tag" and annotation["description"]:
            tags.append(annotation["description"])
    return tags


def _tag_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        if isinstance(item, str):
            tags.append(item.lstrip("@"))
        elif isinstance(item, dict):
            tag = _str(item.get("name")) or _str(item.get("title"))
            if tag:
                tags.append(tag.lstrip("@"))
    return tags


def _earliest_start_time(tests: list[TestCaseResult]) -> datetime | None:
    # Playwright JSON stores startTime per result; QALens does not currently keep
    # per-test start times, so run-level started_at is best-effort for now.
    return None


def _project_name(payload: Any, payload_file: Path) -> str:
    if isinstance(payload, dict):
        config = payload.get("config")
        if isinstance(config, dict):
            name = _str(config.get("rootDir")) or _str(config.get("name"))
            if name:
                return Path(name).name or name
    return payload_file.parent.name or payload_file.stem


def _most_common(values: list[str | None]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda item: counts[item])


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
