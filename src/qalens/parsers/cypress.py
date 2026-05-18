"""Cypress/Mocha JSON report parser for QALens.

Supports common Mochawesome JSON reports and Cypress run-result JSON payloads.
"""
# ruff: noqa: ANN401

from __future__ import annotations

import json
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


class CypressJsonParser(BaseParser):
    """Parser for Cypress/Mocha JSON reports."""

    parser_key = "cypress"
    parser_name = "Cypress/Mocha JSON Parser"

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Return a detection result for Cypress/Mocha JSON reports."""
        payload_file = _find_payload_file(report_path)
        if payload_file is None:
            return DetectionResult.no_match(
                self.parser_key,
                self.parser_name,
                "No Cypress/Mocha JSON payload found.",
            )

        payload = _load_json(payload_file)
        if _is_mochawesome(payload):
            return DetectionResult(
                parser_key=self.parser_key,
                parser_name=self.parser_name,
                confidence=0.93,
                reasons=[f"{payload_file.name} has Mochawesome stats/results data."],
                matched_files=[payload_file],
            )
        if _is_cypress_run_payload(payload):
            return DetectionResult(
                parser_key=self.parser_key,
                parser_name=self.parser_name,
                confidence=0.90,
                reasons=[f"{payload_file.name} has Cypress runs/spec/tests data."],
                matched_files=[payload_file],
            )

        return DetectionResult.no_match(
            self.parser_key,
            self.parser_name,
            "JSON did not match known Cypress/Mocha report structures.",
        )

    def parse(self, report_path: Path) -> TestRun:
        """Parse a Cypress/Mocha JSON report into a normalized test run."""
        payload_file = _find_payload_file(report_path)
        if payload_file is None:
            raise ReportMalformedError(report_path, "No Cypress/Mocha JSON payload found.")
        payload = _load_json(payload_file)

        tests: list[TestCaseResult] = []
        if _is_mochawesome(payload):
            _collect_mochawesome(payload, out=tests, source=self.parser_key)
        elif _is_cypress_run_payload(payload):
            _collect_cypress_runs(payload, out=tests, source=self.parser_key)
        else:
            raise ReportMalformedError(
                report_path,
                "JSON does not look like Cypress/Mocha report output.",
            )

        if not tests:
            raise ReportMalformedError(report_path, "No Cypress/Mocha tests found.")

        metadata = RunMetadata(
            run_id=str(uuid4()),
            report_format=self.parser_key,
            report_path=str(report_path.resolve()),
            project=_project_name(payload, payload_file),
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


def _find_payload_file(path: Path) -> Path | None:
    if path.is_file():
        return path if path.suffix.lower() == ".json" else None
    if not path.is_dir():
        return None

    preferred = [
        path / "mochawesome.json",
        path / "cypress-results.json",
        path / "results.json",
        path / "report.json",
    ]
    for candidate in preferred:
        if candidate.is_file() and _looks_supported(_load_json(candidate)):
            return candidate

    for candidate in sorted(path.rglob("*.json"))[:50]:
        if _looks_supported(_load_json(candidate)):
            return candidate
    return None


def _looks_supported(payload: Any) -> bool:
    return _is_mochawesome(payload) or _is_cypress_run_payload(payload)


def _is_mochawesome(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    stats = payload.get("stats")
    results = payload.get("results")
    if not isinstance(stats, dict) or not isinstance(results, list):
        return False
    text = json.dumps(payload)[:20_000].lower()
    return "mochawesome" in text or '"suites"' in text and '"tests"' in text


def _is_cypress_run_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return False
    text = json.dumps(payload)[:20_000].lower()
    return '"spec"' in text and '"tests"' in text and ("cypress" in text or '"attempts"' in text)


def _collect_mochawesome(
    payload: dict[str, Any],
    *,
    out: list[TestCaseResult],
    source: str,
) -> None:
    results = payload.get("results")
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, dict):
            continue
        file_name = _str(result.get("file")) or _str(result.get("fullFile"))
        suites = result.get("suites")
        if isinstance(suites, list):
            for suite in suites:
                if isinstance(suite, dict):
                    _collect_mocha_suite(
                        suite,
                        suite_path=[],
                        file_name=file_name,
                        out=out,
                        source=source,
                    )


def _collect_mocha_suite(
    suite: dict[str, Any],
    *,
    suite_path: list[str],
    file_name: str | None,
    out: list[TestCaseResult],
    source: str,
) -> None:
    title = _str(suite.get("title"))
    next_path = [*suite_path, title] if title else suite_path
    tests = suite.get("tests")
    if isinstance(tests, list):
        for test in tests:
            if isinstance(test, dict):
                out.append(
                    _mocha_test_case(
                        test,
                        suite_path=next_path,
                        file_name=file_name,
                        source=source,
                    )
                )
                if len(out) >= MAX_TESTS_PER_RUN:
                    return

    children = suite.get("suites")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _collect_mocha_suite(
                    child,
                    suite_path=next_path,
                    file_name=file_name,
                    out=out,
                    source=source,
                )


def _mocha_test_case(
    test: dict[str, Any],
    *,
    suite_path: list[str],
    file_name: str | None,
    source: str,
) -> TestCaseResult:
    title = truncate(_str(test.get("title")) or "unknown", MAX_TEST_NAME_CHARS)
    full_title = _str(test.get("fullTitle")) or " ".join([*suite_path, title])
    status = _mocha_status(test)
    failure = _mocha_failure(test)
    tags = _extract_tags(full_title)
    return TestCaseResult(
        test_id=sanitize_test_id("::".join(part for part in [file_name, full_title] if part)),
        name=title,
        full_name=full_title,
        status=status,
        suite=" › ".join(suite_path) or file_name,
        feature=_first_suite_part(suite_path),
        tags=tags,
        duration_ms=_int(test.get("duration")),
        failure=failure,
        source_format=source,
        raw_id=_str(test.get("uuid")) or _str(test.get("code")),
    )


def _collect_cypress_runs(
    payload: dict[str, Any],
    *,
    out: list[TestCaseResult],
    source: str,
) -> None:
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return
    for run in runs:
        if not isinstance(run, dict):
            continue
        spec = run.get("spec")
        spec_name = _spec_name(spec)
        tests = run.get("tests")
        if not isinstance(tests, list):
            continue
        for test in tests:
            if isinstance(test, dict):
                out.append(_cypress_test_case(test, spec_name=spec_name, source=source))
                if len(out) >= MAX_TESTS_PER_RUN:
                    return


def _cypress_test_case(
    test: dict[str, Any],
    *,
    spec_name: str | None,
    source: str,
) -> TestCaseResult:
    title_parts = test.get("title")
    parts = (
        [str(part).strip() for part in title_parts if str(part).strip()]
        if isinstance(title_parts, list)
        else []
    )
    raw_title = parts[-1] if parts else _str(test.get("title")) or "unknown"
    title = truncate(raw_title, MAX_TEST_NAME_CHARS)
    suite_path = parts[:-1]
    attempts = test.get("attempts")
    attempt_items = (
        [item for item in attempts if isinstance(item, dict)]
        if isinstance(attempts, list)
        else []
    )
    final_attempt = attempt_items[-1] if attempt_items else {}
    state = _str(final_attempt.get("state")) or _str(test.get("state"))
    full_name = " ".join([*suite_path, title])
    return TestCaseResult(
        test_id=sanitize_test_id("::".join(part for part in [spec_name, full_name] if part)),
        name=title,
        full_name=full_name,
        status=_state_status(state),
        suite=" › ".join(suite_path) or spec_name,
        feature=_first_suite_part(suite_path),
        tags=_extract_tags(full_name),
        duration_ms=sum(_int(item.get("duration")) or 0 for item in attempt_items),
        failure=_cypress_failure(final_attempt),
        retry_count=max(0, len(attempt_items) - 1),
        source_format=source,
        raw_id=_str(test.get("testId")) or _str(test.get("id")),
    )


def _mocha_status(test: dict[str, Any]) -> TestStatus:
    state = _str(test.get("state"))
    if state:
        return _state_status(state)
    if test.get("pass") is True:
        return TestStatus.PASSED
    if test.get("fail") is True:
        return TestStatus.FAILED
    if test.get("pending") is True:
        return TestStatus.SKIPPED
    return TestStatus.UNKNOWN


def _state_status(value: str | None) -> TestStatus:
    normalized = (value or "").lower()
    if normalized in {"passed", "pass"}:
        return TestStatus.PASSED
    if normalized in {"failed", "fail"}:
        return TestStatus.FAILED
    if normalized in {"pending", "skipped", "skip"}:
        return TestStatus.SKIPPED
    return TestStatus.UNKNOWN


def _mocha_failure(test: dict[str, Any]) -> FailureInfo | None:
    err = test.get("err")
    if not isinstance(err, dict) or not err:
        return None
    message = _str(err.get("message"))
    stack = _str(err.get("estack")) or _str(err.get("stack")) or message
    return FailureInfo(
        error_type=_error_type(message, stack),
        message=truncate(message, MAX_ERROR_MESSAGE_CHARS) if message else None,
        stack_trace=truncate(stack, MAX_STACK_TRACE_CHARS) if stack else None,
    )


def _cypress_failure(attempt: dict[str, Any]) -> FailureInfo | None:
    error = attempt.get("error")
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
    return "CypressError" if first else None


def _extract_tags(value: str) -> list[str]:
    return [part[1:] for part in value.split() if part.startswith("@") and len(part) > 1]


def _first_suite_part(parts: list[str]) -> str | None:
    return parts[0] if parts else None


def _spec_name(spec: Any) -> str | None:
    if isinstance(spec, dict):
        return _str(spec.get("relative")) or _str(spec.get("name")) or _str(spec.get("file"))
    return None


def _project_name(payload: Any, payload_file: Path) -> str:
    if isinstance(payload, dict):
        browser = payload.get("browserName") or payload.get("browserPath")
        if browser:
            return f"Cypress {browser}"
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


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
