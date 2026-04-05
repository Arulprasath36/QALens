"""Allure HTML report parser for ARI.

Supports Allure Report v2.x (single-page-app layout) and the older
Allure v1.x flat HTML layout.

Detection strategy (in order of precedence):
1. ``widgets/summary.json`` exists in the report directory
   — definitive signal, confidence 0.90.
2. ``data/suites.json`` exists — strong signal, confidence 0.85.
3. Both ``widgets/summary.json`` *and* ``data/suites.json`` present
   — combined signal bumped to 0.96.
4. ``app.js`` contains the string "allure" — medium, confidence 0.75.
5. Entry HTML contains allure-specific markers
   (``ng-app``, ``data-ng-app``, ``allure`` in script src, etc.)
   — medium, confidence 0.70.
6. ``index.html`` with ``<title>Allure Report</title>`` — medium, 0.68.

Phase 3: full extraction of test cases, steps, failures, attachments,
and label-based metadata from ``data/test-cases/<uid>.json`` files.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bs4 import BeautifulSoup

from qara.models.artifact_ref import ArtifactRef
from qara.models.attachment import Attachment, AttachmentKind
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import StepResult, TestCaseResult, TestStatus
from qara.models.warnings import WarningSeverity
from qara.parsers.base import BaseParser, DetectionResult, ReportMalformedError
from qara.utils.fs import (
    file_contains,
    find_entry_html,
    resolve_report_root,
    safe_join,
    safe_read_text,
)
from qara.utils.text import (
    extract_error_type,
    parse_epoch_ms,
    sanitize_test_id,
    split_error_message,
    truncate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety limits for untrusted input
# ---------------------------------------------------------------------------

#: Maximum JSON file size for any single report data file (10 MB).
_MAX_JSON_BYTES: int = 10 * 1024 * 1024
#: Maximum number of test cases extracted per report.
_MAX_TEST_CASES: int = 10_000
#: Maximum recursion depth when walking the suites tree.
_MAX_RECURSION_DEPTH: int = 20
#: Maximum characters for any single string field extracted from the report.
_MAX_FIELD_LEN: int = 2048
#: Maximum characters for error message fields.
_MAX_MESSAGE_LEN: int = 10_000
#: Maximum characters for stack trace fields.
_MAX_STACK_LEN: int = 50_000
#: Allowed characters in a test UID (alphanumeric, hyphens, underscores).
_SAFE_UID_RE = re.compile(r'^[\w\-]+$')


class AllureHtmlParser(BaseParser):
    """Parser for Allure HTML reports (v2.x and v1.x).

    Allure v2 produces a single-page app in a flat directory. The
    authoritative data lives in ``widgets/`` and ``data/`` JSON files;
    ``index.html`` is a minimal SPA shell.

    Full extraction is added in Phase 3.
    """

    parser_key: str = "allure"
    parser_name: str = "Allure HTML Report Parser"

    # ------------------------------------------------------------------
    # Detection signal constants
    # ------------------------------------------------------------------

    #: Relative path of the summary widget — definitive for Allure v2.
    _SUMMARY_JSON: str = "widgets/summary.json"

    #: Relative path of the suites data file — definitive for Allure v2.
    _SUITES_JSON: str = "data/suites.json"

    #: Other data-layer JSON files that strongly suggest Allure v2.
    _DATA_JSON_FILES: frozenset[str] = frozenset(
        {
            "data/behaviors.json",
            "data/categories.json",
            "data/packages.json",
        }
    )

    #: Strings inside ``app.js`` that indicate Allure.
    _APP_JS_MARKERS: frozenset[str] = frozenset({"allure", "Allure"})

    #: HTML attribute/content markers in the entry HTML.
    _HTML_ALLURE_MARKERS: frozenset[str] = frozenset(
        {
            "ng-app",           # Allure v2 uses AngularJS
            "data-ng-app",
            "allure",
        }
    )

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Determine whether this is an Allure HTML report.

        Args:
            report_path: Path to a report directory or ``index.html``.

        Returns:
            A :class:`~ari.parsers.base.DetectionResult` with confidence
            and evidence reasons.
        """
        try:
            root = resolve_report_root(report_path)
        except FileNotFoundError as exc:
            return DetectionResult.no_match(
                self.parser_key, self.parser_name, str(exc)
            )

        reasons: list[str] = []
        matched_files: list[Path] = []
        det_warnings: list[str] = []
        confidence: float = 0.0

        # --- Signal 1+2+3: JSON data files (most reliable) ---
        has_summary, has_suites = self._check_data_files(root, matched_files, reasons)

        if has_summary and has_suites:
            confidence = max(confidence, 0.96)
        elif has_summary:
            confidence = max(confidence, 0.90)
        elif has_suites:
            confidence = max(confidence, 0.85)

        # --- Signal 4: extra data-layer JSON files ---
        extra_json = self._find_extra_data_json(root)
        if extra_json:
            confidence = max(confidence, max(confidence, 0.80))
            matched_files.extend(extra_json)
            reasons.append(
                f"Allure data JSON files found: "
                f"{', '.join(f.relative_to(root).as_posix() for f in extra_json)}"
            )

        # --- Early exit: already high confidence ---
        if confidence >= 0.90:
            return DetectionResult(
                parser_key=self.parser_key,
                parser_name=self.parser_name,
                confidence=confidence,
                reasons=reasons,
                matched_files=matched_files,
                warnings=det_warnings,
            )

        # --- Signal 5: app.js containing "allure" ---
        app_js = root / "app.js"
        if app_js.is_file():
            for marker in self._APP_JS_MARKERS:
                if file_contains(app_js, marker, case_sensitive=True):
                    confidence = max(confidence, 0.75)
                    matched_files.append(app_js)
                    reasons.append(f"app.js contains Allure marker '{marker}'.")
                    break

        # --- Signal 6: entry HTML markers ---
        entry_html: Path | None
        if report_path.is_file() and report_path.suffix.lower() in {".html", ".htm"}:
            entry_html = report_path
        else:
            entry_html = find_entry_html(root)

        if entry_html is not None:
            html_content = safe_read_text(entry_html) or ""
            html_confidence, html_reasons = self._check_html_markers(
                html_content, entry_html
            )
            if html_confidence > 0:
                confidence = max(confidence, html_confidence)
                matched_files.append(entry_html)
                reasons.extend(html_reasons)

        if not reasons:
            return DetectionResult.no_match(
                self.parser_key,
                self.parser_name,
                f"No Allure signatures found in {root}.",
            )

        return DetectionResult(
            parser_key=self.parser_key,
            parser_name=self.parser_name,
            confidence=confidence,
            reasons=reasons,
            matched_files=matched_files,
            warnings=det_warnings,
        )

    # ------------------------------------------------------------------
    # Parsing (Phase 3: full extraction)
    # ------------------------------------------------------------------

    def parse(self, report_path: Path) -> TestRun:
        """Parse an Allure HTML report and return a normalized :class:`TestRun`.

        Loads ``widgets/summary.json`` for run-level metadata then walks
        ``data/suites.json`` to discover test UIDs. For each UID, reads
        ``data/test-cases/<uid>.json`` for full test data including steps,
        failure details, and attachments.

        Args:
            report_path: Path to the Allure report directory or index.html.

        Returns:
            A fully populated :class:`~ari.models.run.TestRun`.

        Raises:
            ReportMalformedError: If the path cannot be resolved.
        """
        root = resolve_report_root(report_path)
        source_format = self.parser_key

        summary_data = self._load_summary_widget(root)
        metadata = self._build_metadata(root, summary_data)

        suites_data = self._load_suites(root)
        test_cases: list[TestCaseResult] = []
        if suites_data is not None:
            test_cases = self._extract_test_cases(root, suites_data, source_format)
        else:
            self._warn(
                field="TestRun.test_cases",
                reason=f"Could not load {self._SUITES_JSON}; no test cases extracted.",
                severity=WarningSeverity.HIGH,
            )

        return TestRun(
            metadata=metadata,
            test_cases=test_cases,
            warnings=self._collect_warnings(),
        )

    # ------------------------------------------------------------------
    # Internal helpers — detection
    # ------------------------------------------------------------------

    def _check_data_files(
        self,
        root: Path,
        matched_files: list[Path],
        reasons: list[str],
    ) -> tuple[bool, bool]:
        """Check for the two primary Allure v2 data files.

        Mutates *matched_files* and *reasons* in place.

        Args:
            root: The report root directory.
            matched_files: Accumulator for evidence file paths.
            reasons: Accumulator for human-readable evidence strings.

        Returns:
            A ``(has_summary, has_suites)`` tuple of booleans.
        """
        has_summary = False
        has_suites = False

        summary_path = root / self._SUMMARY_JSON
        if summary_path.is_file():
            has_summary = True
            matched_files.append(summary_path)
            reasons.append(f"{self._SUMMARY_JSON} exists — definitive Allure v2 signal.")

        suites_path = root / self._SUITES_JSON
        if suites_path.is_file():
            has_suites = True
            matched_files.append(suites_path)
            reasons.append(f"{self._SUITES_JSON} exists — strong Allure v2 signal.")

        return has_summary, has_suites

    def _find_extra_data_json(self, root: Path) -> list[Path]:
        """Return any additional Allure data-layer JSON files that exist."""
        return [root / rel for rel in self._DATA_JSON_FILES if (root / rel).is_file()]

    def _check_html_markers(
        self, html_content: str, entry_html: Path
    ) -> tuple[float, list[str]]:
        """Check the entry HTML for Allure-specific markers.

        Args:
            html_content: Text content of the entry HTML file.
            entry_html: The path to the entry HTML (used in messages).

        Returns:
            A ``(confidence, reasons)`` tuple. Confidence is 0.0 if no
            markers are found.
        """
        if not html_content:
            return 0.0, []

        reasons: list[str] = []
        found: list[str] = []

        soup = BeautifulSoup(html_content, "html.parser")

        # ng-app / data-ng-app
        ng_app = soup.find(attrs={"ng-app": True}) or soup.find(
            attrs={"data-ng-app": True}
        )
        if ng_app:
            found.append("ng-app (AngularJS marker used by Allure v2)")

        # <title>Allure Report</title>
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            if "allure" in title_text.lower():
                found.append(f"<title>{title_text}</title> contains 'allure'")

        # script src containing "allure"
        for script in soup.find_all("script", src=True):
            src = script.get("src", "")
            if src and "allure" in src.lower():
                found.append(f"script src='{src}' references Allure")
                break  # one is enough

        if found:
            confidence = 0.70 if len(found) >= 2 else 0.65
            reasons.append(
                f"Allure HTML markers in {entry_html.name}: {'; '.join(found)}"
            )
            return confidence, reasons

        return 0.0, []

    # ------------------------------------------------------------------
    # Internal helpers — parsing
    # ------------------------------------------------------------------

    def _load_summary_widget(self, root: Path) -> dict | None:
        """Load and parse ``widgets/summary.json``.

        Args:
            root: The report root directory.

        Returns:
            The parsed JSON mapping, or ``None`` if the file is missing
            or cannot be parsed.
        """
        summary_path = root / self._SUMMARY_JSON
        content = safe_read_text(summary_path, max_bytes=_MAX_JSON_BYTES)
        if content is None:
            return None
        try:
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError as exc:
            self._warn(
                field="RunMetadata",
                reason=f"Could not parse {self._SUMMARY_JSON}: {exc}",
                severity=WarningSeverity.MEDIUM,
            )
            return None

    def _build_metadata(
        self, root: Path, summary_data: dict | None
    ) -> RunMetadata:
        """Build :class:`~ari.models.run.RunMetadata` from the summary widget.

        Extracts project name, report start/stop times, and the Allure
        framework version from the ``widgets/summary.json`` payload.

        Args:
            root: The report root directory.
            summary_data: Parsed ``summary.json`` dict, or ``None``.

        Returns:
            A populated :class:`~ari.models.run.RunMetadata`.
        """
        project: str | None = None
        report_version: str | None = None
        started_at: datetime | None = None
        finished_at: datetime | None = None

        if summary_data:
            project = summary_data.get("reportName") or summary_data.get("name")

            time_block: dict = summary_data.get("time", {}) or {}
            start_ms: int | None = time_block.get("start")
            stop_ms: int | None = time_block.get("stop")

            if start_ms is not None:
                try:
                    started_at = datetime.fromtimestamp(
                        start_ms / 1000.0, tz=timezone.utc
                    )
                except (OSError, OverflowError, ValueError):
                    self._warn(
                        field="RunMetadata.started_at",
                        reason=f"Invalid epoch ms value for start time: {start_ms}",
                    )
            if stop_ms is not None:
                try:
                    finished_at = datetime.fromtimestamp(
                        stop_ms / 1000.0, tz=timezone.utc
                    )
                except (OSError, OverflowError, ValueError):
                    self._warn(
                        field="RunMetadata.finished_at",
                        reason=f"Invalid epoch ms value for stop time: {stop_ms}",
                    )

        if project is None:
            self._warn(
                field="RunMetadata.project",
                reason=(
                    "Could not determine project name from Allure summary widget. "
                    f"Expected 'reportName' key in {self._SUMMARY_JSON}."
                ),
            )

        return RunMetadata(
            report_format=self.parser_key,
            report_version=report_version,
            report_path=str(root.resolve()),
            project=project,
            started_at=started_at,
            finished_at=finished_at,
        )

    # ------------------------------------------------------------------
    # Internal helpers — parsing (loading)
    # ------------------------------------------------------------------

    def _load_suites(self, root: Path) -> dict | None:
        """Load and parse ``data/suites.json``.

        Args:
            root: The report root directory.

        Returns:
            The parsed suites tree dict, or ``None`` on failure.
        """
        content = safe_read_text(root / self._SUITES_JSON, max_bytes=_MAX_JSON_BYTES)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            self._warn(
                field="TestRun.test_cases",
                reason=f"Could not parse {self._SUITES_JSON}: {exc}",
                severity=WarningSeverity.HIGH,
            )
            return None

    def _load_test_case_detail(self, root: Path, uid: str) -> dict | None:
        """Load the detail JSON for a single test case by UID.

        Allure v2 stores per-test data in ``data/test-cases/<uid>.json``.

        Args:
            root: The report root directory.
            uid: The unique identifier of the test case.

        Returns:
            The parsed test case detail dict, or ``None``.
        """
        # Path-traversal guard: reject UIDs containing anything other than
        # word characters and hyphens before using as a file-path component.
        if not _SAFE_UID_RE.match(uid):
            logger.warning("Unsafe test UID rejected (contains illegal chars): %r", uid[:80])
            return None
        detail_path = safe_join(root / "data" / "test-cases", f"{uid}.json")
        if detail_path is None:
            return None
        content = safe_read_text(detail_path, max_bytes=_MAX_JSON_BYTES)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            self._warn(
                field="TestCaseResult",
                reason=f"Could not parse data/test-cases/{uid}.json: {exc}",
                severity=WarningSeverity.MEDIUM,
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers — test case extraction
    # ------------------------------------------------------------------

    def _extract_test_cases(
        self,
        root: Path,
        suites_data: dict,
        source_format: str,
    ) -> list[TestCaseResult]:
        """Walk the suites tree and extract all test cases.

        Args:
            root: The report root directory.
            suites_data: Parsed ``data/suites.json`` root dict.
            source_format: Parser key string (``"allure"``).

        Returns:
            List of :class:`~ari.models.test_case.TestCaseResult` objects.
        """
        # Collect (uid, name, status_str, suite_name) tuples from the tree
        uid_entries: list[tuple[str, str, str, str]] = []
        self._collect_uid_entries(suites_data, uid_entries, parent_suite="", depth=0)
        if len(uid_entries) > _MAX_TEST_CASES:
            logger.warning(
                "Report contains %d test entries; only the first %d will be processed.",
                len(uid_entries), _MAX_TEST_CASES,
            )
            self._warn(
                field="TestRun.test_cases",
                reason=(
                    f"Report contains {len(uid_entries)} test entries. "
                    f"Only the first {_MAX_TEST_CASES} were processed."
                ),
                severity=WarningSeverity.HIGH,
            )
            uid_entries = uid_entries[:_MAX_TEST_CASES]
        test_cases: list[TestCaseResult] = []
        for uid, name, status_str, suite_name in uid_entries:
            tc = self._extract_single_test_case(
                root=root,
                uid=uid,
                summary_name=name,
                summary_status=status_str,
                suite_name=suite_name,
                source_format=source_format,
            )
            if tc is not None:
                test_cases.append(tc)
        return test_cases

    def _collect_uid_entries(
        self,
        node: dict,
        result: list[tuple[str, str, str, str]],
        parent_suite: str,
        depth: int = 0,
    ) -> None:
        """Recursively walk a suites tree node collecting leaf UID entries.

        Leaf nodes have a ``uid`` key; branch nodes have ``children``.

        Args:
            node: Current tree node dict.
            result: Accumulator list mutated in place.
            parent_suite: Suite name inherited from ancestors.
            depth: Current recursion depth; stops at ``_MAX_RECURSION_DEPTH``.
        """
        if depth > _MAX_RECURSION_DEPTH:
            logger.warning(
                "Suites tree exceeds max depth (%d); truncating branch.",
                _MAX_RECURSION_DEPTH,
            )
            return
        uid = node.get("uid", "")
        name = node.get("name", "") or ""
        status_str = node.get("status", "") or ""
        children: list[dict] = node.get("children") or []

        if uid and not children:
            # Leaf test node
            result.append((uid, name, status_str, parent_suite))
            return

        # Determine suite name from this node if it has children
        suite_name = name if children else parent_suite
        for child in children:
            self._collect_uid_entries(child, result, suite_name, depth=depth + 1)

    def _extract_single_test_case(
        self,
        root: Path,
        uid: str,
        summary_name: str,
        summary_status: str,
        suite_name: str,
        source_format: str,
    ) -> TestCaseResult | None:
        """Load and convert one test-case detail JSON into a
        :class:`~ari.models.test_case.TestCaseResult`.

        Falls back to summary-level data when the detail file is missing.

        Args:
            root: Report root directory.
            uid: Allure test UID.
            summary_name: Test name from suites.json (fallback).
            summary_status: Status string from suites.json (fallback).
            suite_name: Suite name inherited from the suites tree.
            source_format: Parser key string.

        Returns:
            A :class:`~ari.models.test_case.TestCaseResult`, or ``None``
            on unrecoverable error.
        """
        tc_data = self._load_test_case_detail(root, uid)

        # --- Core identity ---
        name: str = summary_name
        full_name: str | None = None
        status_str: str = summary_status
        started_at: datetime | None = None
        finished_at: datetime | None = None
        duration_ms: int | None = None

        if tc_data:
            name = truncate(str(tc_data.get("name") or summary_name), _MAX_FIELD_LEN)
            full_name = truncate(str(fn), _MAX_FIELD_LEN) if (fn := tc_data.get("fullName")) else None
            status_str = tc_data.get("status") or summary_status

            time_block: dict = tc_data.get("time") or {}
            start_ms = time_block.get("start")
            stop_ms = time_block.get("stop")
            dur_ms = time_block.get("duration")

            started_at = parse_epoch_ms(start_ms)
            finished_at = parse_epoch_ms(stop_ms)
            if dur_ms is not None:
                try:
                    duration_ms = int(dur_ms)
                except (TypeError, ValueError):
                    pass
            elif started_at and finished_at:
                delta = finished_at - started_at
                duration_ms = int(delta.total_seconds() * 1000)

        # --- Status ---
        status = TestStatus.from_string(status_str)

        # --- Labels → suite/feature/story/owner/tags ---
        labels_raw: list[dict] = (tc_data or {}).get("labels") or []
        label_suite, feature, story, owner, tags = self._extract_labels(
            labels_raw, suite_name
        )

        # --- Parameters ---
        params_raw: list[dict] = (tc_data or {}).get("parameters") or []
        parameters: dict[str, str] = {
            str(p.get("name", "?")): str(p.get("value", ""))
            for p in params_raw
            if isinstance(p, dict)
        }

        # --- Links ---
        links_raw: list[dict] = (tc_data or {}).get("links") or []
        links: list[str] = self._extract_links(links_raw)

        # --- Steps (before-hooks + body steps + after-hooks) ---
        # Real Allure 2.x reports store setup/teardown in beforeStages and
        # afterStages alongside the main steps array. Combine all three so
        # that fixture failures are visible in the extracted step list.
        before_raw: list[dict] = (tc_data or {}).get("beforeStages") or []
        steps_raw: list[dict] = (tc_data or {}).get("steps") or []
        after_raw: list[dict] = (tc_data or {}).get("afterStages") or []
        combined_steps_raw: list[dict] = before_raw + steps_raw + after_raw
        steps: list[StepResult] = (
            self._extract_steps(combined_steps_raw, source_format, depth=0)
            if combined_steps_raw
            else []
        )

        # --- Failure ---
        failure: FailureInfo | None = None
        if tc_data and status in {TestStatus.FAILED, TestStatus.BROKEN}:
            failure = self._extract_failure(tc_data, steps)

        # --- Attachments on the test case itself ---
        attach_raw: list[dict] = (tc_data or {}).get("attachments") or []
        attachments: list[Attachment] = self._extract_attachments(
            attach_raw, root, source_format
        )

        # --- ArtifactRefs for the policy layer ---
        # Build ArtifactRef objects for every screenshot attachment so that the
        # artifact ingestion policy can apply mode / cap / dedup logic without
        # knowing Allure internals.
        raw_artifact_refs: list[ArtifactRef] = []
        seq = 0
        # TC-level screenshots have resolved paths from _extract_attachments.
        for att in attachments:
            if att.kind != AttachmentKind.SCREENSHOT:
                continue
            source = att.resolved_path or att.path
            if source:
                raw_artifact_refs.append(
                    ArtifactRef(
                        source_uri=source,
                        kind="screenshot",
                        name=att.name,
                        mime_type=att.mime_type,
                        sequence_no=seq,
                        is_from_failed_step=False,
                    )
                )
                seq += 1
        # Step-level screenshots: resolve against root (which is available here
        # but not inside _extract_steps) and flag failure-adjacent ones.
        for step in steps:
            is_fail = step.status in {TestStatus.FAILED, TestStatus.BROKEN}
            for att in step.attachments:
                if att.kind != AttachmentKind.SCREENSHOT:
                    continue
                # Try to resolve relative att.path within the report data dir.
                source: str | None = att.resolved_path
                if not source and att.path:
                    candidate = safe_join(root / "data", att.path)
                    if candidate and candidate.is_file():
                        source = str(candidate)
                if not source:
                    source = att.path  # keep raw relative path as last resort
                if not source:
                    continue
                raw_artifact_refs.append(
                    ArtifactRef(
                        source_uri=source,
                        kind="screenshot",
                        name=att.name,
                        step_name=step.name,
                        mime_type=att.mime_type,
                        sequence_no=seq,
                        is_from_failed_step=is_fail,
                    )
                )
                seq += 1

        # --- Retry info ---
        retry_count: int = 0
        if tc_data:
            try:
                retry_count = int(tc_data.get("retriesCount") or 0)
            except (TypeError, ValueError):
                pass
        is_retry: bool = bool(tc_data and tc_data.get("isRetry"))

        # --- test_id / raw_id ---
        raw_id = uid
        test_id = sanitize_test_id(full_name or name)

        return TestCaseResult(
            test_id=test_id,
            name=name,
            full_name=full_name,
            status=status,
            suite=label_suite,
            feature=feature,
            story=story,
            owner=owner,
            tags=tags,
            parameters=parameters,
            links=links,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            steps=steps,
            failure=failure,
            attachments=attachments,
            raw_artifact_refs=raw_artifact_refs,
            retry_count=retry_count,
            is_retry=is_retry,
            source_format=source_format,
            raw_id=raw_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers — labels and links
    # ------------------------------------------------------------------

    def _extract_labels(
        self,
        labels: list[dict],
        fallback_suite: str,
    ) -> tuple[str | None, str | None, str | None, str | None, list[str]]:
        """Map Allure label objects to canonical model fields.

        Allure labels use ``{"name": "<label_name>", "value": "<value>"}``.
        Standard label names: ``suite``, ``feature``, ``story``,
        ``severity``, ``owner``, ``tag``, ``package``, ``testClass``.

        Args:
            labels: List of label dicts from the test-case JSON.
            fallback_suite: Suite name from the suites tree (used when
                no ``suite`` label exists).

        Returns:
            A ``(suite, feature, story, owner, tags)`` tuple.
        """
        suite: str | None = None
        feature: str | None = None
        story: str | None = None
        owner: str | None = None
        tags: list[str] = []

        for lbl in labels:
            if not isinstance(lbl, dict):
                continue
            lname = (lbl.get("name") or "").lower().strip()
            lvalue = (lbl.get("value") or "").strip()
            if not lvalue:
                continue
            if lname == "suite":
                suite = lvalue
            elif lname == "feature":
                feature = lvalue
            elif lname == "story":
                story = lvalue
            elif lname == "owner":
                owner = lvalue
            elif lname == "tag":
                tags.append(lvalue)

        if suite is None and fallback_suite:
            suite = fallback_suite

        return suite, feature, story, owner, tags

    def _extract_links(self, links: list[dict]) -> list[str]:
        """Convert Allure link objects to plain URL strings.

        Allure links use ``{"name": "...", "url": "...", "type": "..."}``.

        Args:
            links: List of link dicts from the test-case JSON.

        Returns:
            List of URL strings (empty items filtered out).
        """
        result: list[str] = []
        for link in links:
            if not isinstance(link, dict):
                continue
            url = (link.get("url") or "").strip()
            if url:
                result.append(url)
        return result

    # ------------------------------------------------------------------
    # Internal helpers — steps
    # ------------------------------------------------------------------

    def _extract_steps(
        self,
        steps: list[dict],
        source_format: str,
        depth: int = 0,
    ) -> list[StepResult]:
        """Recursively convert Allure step nodes into :class:`StepResult` objects.

        Args:
            steps: List of step dicts (may contain nested ``steps``).
            source_format: Parser key string.
            depth: Current nesting depth (0 = top-level).

        Returns:
            Flat list of :class:`~ari.models.test_case.StepResult` objects
            in tree order (parent before children).
        """
        results: list[StepResult] = []
        for step in steps:
            if not isinstance(step, dict):
                continue

            s_name = step.get("name") or "unnamed step"
            s_status_str = step.get("status") or "unknown"
            s_status = TestStatus.from_string(s_status_str)

            time_block: dict = step.get("time") or {}
            started_at = parse_epoch_ms(time_block.get("start"))
            finished_at = parse_epoch_ms(time_block.get("stop"))
            duration_ms: int | None = None
            dur_raw = time_block.get("duration")
            if dur_raw is not None:
                try:
                    duration_ms = int(dur_raw)
                except (TypeError, ValueError):
                    pass
            elif started_at and finished_at:
                delta = finished_at - started_at
                duration_ms = int(delta.total_seconds() * 1000)

            # Step-level failure (only if step failed)
            step_failure: FailureInfo | None = None
            if s_status in {TestStatus.FAILED, TestStatus.BROKEN}:
                msg = step.get("statusMessage") or step.get("description") or ""
                trace = step.get("statusTrace") or ""
                if msg or trace:
                    err_type = extract_error_type(trace) if trace else None
                    step_failure = FailureInfo(
                        error_type=err_type,
                        message=truncate(msg, 2000) if msg else None,
                        stack_trace=trace or None,
                    )

            # Step-level attachments
            attach_raw: list[dict] = step.get("attachments") or []
            # We don't have root here; collect names only
            step_attachments: list[Attachment] = []
            for att in attach_raw:
                if not isinstance(att, dict):
                    continue
                att_name = att.get("name") or "attachment"
                att_source = att.get("source") or ""
                kind = self._mime_to_kind(att.get("type") or "")
                step_attachments.append(
                    Attachment(
                        name=att_name,
                        kind=kind,
                        path=att_source,
                        resolved_path=None,
                        mime_type=att.get("type"),
                        source=source_format,
                    )
                )

            step_result = StepResult(
                step_id=str(uuid4()),
                name=s_name,
                status=s_status,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                failure=step_failure,
                attachments=step_attachments,
                depth=depth,
            )
            results.append(step_result)

            # Recurse into nested steps
            nested: list[dict] = step.get("steps") or []
            if nested:
                results.extend(
                    self._extract_steps(nested, source_format, depth=depth + 1)
                )

        return results

    # ------------------------------------------------------------------
    # Internal helpers — failure
    # ------------------------------------------------------------------

    def _extract_failure(
        self,
        tc_data: dict,
        steps: list[StepResult],
    ) -> FailureInfo | None:
        """Build a :class:`~ari.models.failure.FailureInfo` from test-case data.

        Allure stores the primary failure in ``statusMessage`` and
        ``statusTrace`` at the test-case level.

        Args:
            tc_data: Parsed test-case detail dict.
            steps: Already-extracted steps (used to find ``failed_step``).

        Returns:
            A :class:`~ari.models.failure.FailureInfo`, or ``None`` if
            there is no useful failure data.
        """
        message: str = tc_data.get("statusMessage") or ""
        trace: str = tc_data.get("statusTrace") or ""

        if not message and not trace:
            return None

        err_type: str | None = None
        if trace:
            err_type = extract_error_type(trace)
        elif message:
            err_type, message = split_error_message(message)

        # Find the first failed step name for failed_step
        failed_step: str | None = None
        for step in steps:
            if step.status in {TestStatus.FAILED, TestStatus.BROKEN}:
                failed_step = step.name
                break

        return FailureInfo(
            error_type=truncate(err_type, _MAX_FIELD_LEN) if err_type else None,
            message=truncate(message, _MAX_MESSAGE_LEN) if message else None,
            stack_trace=truncate(trace, _MAX_STACK_LEN) if trace else None,
            failed_step=failed_step,
        )

    # ------------------------------------------------------------------
    # Internal helpers — attachments
    # ------------------------------------------------------------------

    def _extract_attachments(
        self,
        attachments: list[dict],
        root: Path,
        source_format: str,
    ) -> list[Attachment]:
        """Convert Allure attachment objects to :class:`~ari.models.attachment.Attachment`.

        Allure v2 attachment format:
        ``{"name": "...", "source": "<hash>-attachment.ext", "type": "image/png"}``

        Files reside in ``data/<source>``.

        Args:
            attachments: List of attachment dicts from the test JSON.
            root: Report root directory used to resolve absolute paths.
            source_format: Parser key string.

        Returns:
            List of :class:`~ari.models.attachment.Attachment` objects.
        """
        results: list[Attachment] = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_name = att.get("name") or "attachment"
            att_source = att.get("source") or ""
            mime = att.get("type") or None
            kind = self._mime_to_kind(mime or "")

            resolved: Path | None = None
            if att_source:
                # Path-traversal guard: resolve only within report root
                candidate = safe_join(root / "data", att_source)
                if candidate and candidate.is_file():
                    resolved = candidate

            results.append(
                Attachment(
                    name=att_name,
                    kind=kind,
                    path=att_source,
                    resolved_path=str(resolved) if resolved else None,
                    mime_type=mime,
                    source=source_format,
                )
            )
        return results

    def _mime_to_kind(self, mime: str) -> AttachmentKind:
        """Map a MIME type string to an :class:`~ari.models.attachment.AttachmentKind`.

        Args:
            mime: MIME type string (e.g. ``"image/png"``).

        Returns:
            The most appropriate :class:`~ari.models.attachment.AttachmentKind`.
        """
        mime = (mime or "").lower()
        if mime.startswith("image/"):
            return AttachmentKind.SCREENSHOT
        if "html" in mime:
            return AttachmentKind.HTML
        if "json" in mime:
            return AttachmentKind.JSON
        if "xml" in mime:
            return AttachmentKind.XML
        if "text" in mime or "log" in mime:
            return AttachmentKind.LOG
        if "video" in mime:
            return AttachmentKind.VIDEO
        return AttachmentKind.OTHER

    def _resolve_attachment(self, root: Path, source: str) -> Path | None:
        """Resolve an Allure attachment source path to an absolute path.

        Allure v2 stores attachments in the ``data/`` directory with
        filenames like ``<hash>-attachment.png``.

        Args:
            root: The report root directory.
            source: The relative source path from the attachment metadata.

        Returns:
            The absolute :class:`~pathlib.Path` if the file exists,
            ``None`` otherwise.
        """
        resolved = root / "data" / source
        return resolved if resolved.is_file() else None
