"""Extent HTML report parser for QALens.

Supports Extent Reports v4 and v5 (single-file and multi-file layouts).

Extraction strategy (in priority order):
1. ``var testdata = {...}`` embedded JSON blob  — most reliable for v5.
2. ``var reportConfig = {...}`` for run-level metadata.
3. DOM traversal of ``.test-content`` / ``.test-node`` elements — fallback.

Detection strategy (in order of precedence):
1. ``<meta name="generator" content="ExtentReports…">`` — confidence 0.95.
2. ``var reportConfig`` or ``var testdata`` in script tags — 0.85.
3. Known Extent CSS selectors in the DOM — 0.70.
4. Known Extent asset filenames — 0.65.
5. Known Extent directory names — 0.55.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bs4 import BeautifulSoup, Tag

from qalens.models.artifact_ref import ArtifactRef
from qalens.models.attachment import Attachment, AttachmentKind
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import StepResult, TestCaseResult, TestStatus
from qalens.models.warnings import WarningSeverity
from qalens.parsers.base import BaseParser, DetectionResult, ReportMalformedError
from qalens.utils.fs import find_entry_html, resolve_report_root, safe_join, safe_read_text
from qalens.utils.text import (
    clean_html_text,
    extract_error_type,
    first_nonempty,
    parse_duration_ms,
    parse_epoch_ms,
    sanitize_test_id,
    split_error_message,
    truncate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety limits for untrusted input
# ---------------------------------------------------------------------------

#: Maximum HTML file size accepted for ingestion (50 MB).
_MAX_HTML_BYTES: int = 50 * 1024 * 1024
#: Maximum characters in an extracted JSON blob before parsing (10 MB).
_MAX_JSON_BLOB_CHARS: int = 10 * 1024 * 1024
#: Maximum number of test-case nodes processed per report.
_MAX_TEST_NODES: int = 10_000
#: Maximum characters kept for any single string field extracted from the report.
_MAX_FIELD_LEN: int = 2048
#: Maximum characters kept for log/detail body text.
_MAX_LOG_LEN: int = 5_000
#: Maximum characters kept for error messages.
_MAX_MESSAGE_LEN: int = 10_000
#: Maximum characters kept for stack traces.
_MAX_STACK_LEN: int = 50_000
#: Maximum lines kept for stack traces (applied after the char cap).
_MAX_STACK_LINES: int = 200
#: Maximum decoded bytes for an embedded base64 screenshot.
_MAX_SCREENSHOT_BYTES: int = 5 * 1024 * 1024  # 5 MB
#: Matches ``data:<mime>;base64,<payload>`` URIs embedded in HTML reports.
_DATA_URI_RE = re.compile(r"^data:([^;,\s]+);base64,(.+)$", re.DOTALL)

_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}


def _mime_to_ext(mime: str) -> str:
    """Return a file extension for *mime*, defaulting to ``.bin``."""
    return _MIME_TO_EXT.get(mime.lower().strip(), ".bin")


class ExtentHtmlParser(BaseParser):
    """Parser for Extent HTML reports (v4 and v5).

    Phase 3: full extraction of run metadata and test cases.
    """

    parser_key: str = "extent"
    parser_name: str = "Extent HTML Report Parser"

    # ------------------------------------------------------------------
    # Detection signal constants
    # ------------------------------------------------------------------

    _META_GENERATOR_PREFIX: str = "ExtentReports"
    _SCRIPT_VARS: frozenset[str] = frozenset({"reportConfig", "testdata"})
    _EXTENT_DOM_CLASSES: frozenset[str] = frozenset(
        {"test-content", "test-node", "test-name", "test-status", "test-time"}
    )
    _ASSET_FILENAMES: frozenset[str] = frozenset(
        {"config.js", "spark-config.js", "extent.js", "spark.js"}
    )
    _ASSET_DIR_NAMES: frozenset[str] = frozenset({"spartan-sources", "spark", "assets"})

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, attachments_dir: Path | None = None) -> None:
        super().__init__()
        self._attachments_dir = attachments_dir

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Determine whether this is an Extent HTML report.

        Args:
            report_path: Path to a report directory or HTML file.

        Returns:
            A :class:`~qalens.parsers.base.DetectionResult` with confidence
            and evidence reasons.
        """
        try:
            root = resolve_report_root(report_path)
        except FileNotFoundError as exc:
            return DetectionResult.no_match(self.parser_key, self.parser_name, str(exc))

        reasons: list[str] = []
        matched_files: list[Path] = []
        det_warnings: list[str] = []
        confidence: float = 0.0

        entry_html: Path | None
        if report_path.is_file() and report_path.suffix.lower() in {".html", ".htm"}:
            entry_html = report_path
        else:
            entry_html = find_entry_html(root)

        if entry_html is None:
            return DetectionResult.no_match(
                self.parser_key, self.parser_name,
                "No entry HTML file found in report directory.",
            )

        html_content = safe_read_text(entry_html)
        if html_content is None:
            det_warnings.append(f"Could not read entry HTML: {entry_html}")
            html_content = ""
        else:
            matched_files.append(entry_html)

        meta_confidence = self._check_meta_generator(html_content)
        if meta_confidence > 0:
            confidence = max(confidence, meta_confidence)
            reasons.append(
                f"<meta name='generator' content='ExtentReports…'> found in {entry_html.name}"
            )

        script_vars_found = self._find_script_vars(html_content)
        if script_vars_found:
            confidence = max(confidence, 0.85)
            reasons.append(
                f"Extent script variables found in HTML: {', '.join(sorted(script_vars_found))}"
            )

        if confidence >= 0.90:
            return DetectionResult(
                parser_key=self.parser_key,
                parser_name=self.parser_name,
                confidence=confidence,
                reasons=reasons,
                matched_files=matched_files,
                warnings=det_warnings,
            )

        dom_classes_found = self._find_dom_classes(html_content)
        if dom_classes_found:
            confidence = max(confidence, 0.70)
            reasons.append(
                f"Extent DOM class signatures found: {', '.join(sorted(dom_classes_found))}"
            )

        cdn_found = self._find_cdn_urls(html_content)
        if cdn_found:
            confidence = max(confidence, 0.85)
            reasons.append("Extent CDN / framework URLs found in HTML (extent-github-cdn / spark-style.css)")

        asset_files = self._find_asset_files(root)
        if asset_files:
            confidence = max(confidence, 0.65)
            matched_files.extend(asset_files)
            reasons.append(
                f"Extent asset files found: {', '.join(f.name for f in asset_files)}"
            )

        asset_dirs = self._find_asset_dirs(root)
        if asset_dirs:
            confidence = max(confidence, 0.55)
            reasons.append(
                f"Extent asset directories found: {', '.join(d.name for d in asset_dirs)}"
            )

        if not reasons:
            return DetectionResult.no_match(
                self.parser_key, self.parser_name,
                f"No Extent signatures found in {root}.",
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
    # Parsing — Phase 3 full extraction
    # ------------------------------------------------------------------

    def parse(self, report_path: Path) -> TestRun:
        """Parse an Extent HTML report and return a normalized :class:`TestRun`.

        Extraction preference order:
        1. Embedded ``var testdata = {...}`` JSON blob.
        2. DOM traversal of ``.test-content`` / ``.test-node`` elements.

        Args:
            report_path: Path to the Extent report directory or HTML file.

        Returns:
            A :class:`~qalens.models.run.TestRun` with all extractable data.
            Partial results with :class:`~qalens.models.warnings.ExtractionWarning`
            entries are returned rather than raising on missing optional fields.

        Raises:
            ReportMalformedError: If no entry HTML can be located or read.
        """
        root = resolve_report_root(report_path)
        entry_html = self._resolve_entry_html(root, report_path)
        html_content, soup = self._load_entry_html(entry_html)

        report_config = self._extract_json_var(html_content, "reportConfig")
        test_data_raw = self._extract_json_var(html_content, "testdata")

        metadata = self._extract_run_metadata(
            root, soup, html_content, report_config, test_data_raw
        )

        if test_data_raw is not None:
            test_nodes = test_data_raw.get("tests") or []
            if len(test_nodes) > _MAX_TEST_NODES:
                logger.warning(
                    "Report contains %d test nodes; only the first %d will be processed.",
                    len(test_nodes), _MAX_TEST_NODES,
                )
                self._warn(
                    field="TestRun.test_cases",
                    reason=(
                        f"Report contains {len(test_nodes)} test nodes. "
                        f"Only the first {_MAX_TEST_NODES} were processed."
                    ),
                    severity=WarningSeverity.HIGH,
                )
                test_nodes = test_nodes[:_MAX_TEST_NODES]
            test_cases = [
                self._extract_test_case_from_node(node, root, metadata.report_format)
                for node in test_nodes
                if isinstance(node, dict)
            ]
        else:
            self._warn(
                field="TestRun.test_cases",
                reason=(
                    "Embedded testdata script variable not found. "
                    "Falling back to DOM traversal."
                ),
                severity=WarningSeverity.MEDIUM,
            )
            test_cases = self._extract_test_cases_from_dom(root, soup, metadata.report_format)

        return TestRun(
            metadata=metadata,
            test_cases=test_cases,
            warnings=self._collect_warnings(),
        )

    # ------------------------------------------------------------------
    # Internal helpers — detection
    # ------------------------------------------------------------------

    def _check_meta_generator(self, html_content: str) -> float:
        if not html_content:
            return 0.0
        soup = BeautifulSoup(html_content, "html.parser")
        meta = soup.find("meta", attrs={"name": "generator"})
        if meta and self._META_GENERATOR_PREFIX in (meta.get("content", "") or ""):  # type: ignore[operator]
            return 0.95
        return 0.0

    def _find_script_vars(self, html_content: str) -> set[str]:
        found: set[str] = set()
        for var in self._SCRIPT_VARS:
            pattern = rf"\b(?:var\s+{re.escape(var)}\s*=|window\.{re.escape(var)}\s*=)"
            if re.search(pattern, html_content):
                found.add(var)
        return found

    def _find_dom_classes(self, html_content: str) -> set[str]:
        if not html_content:
            return set()
        found: set[str] = set()
        for cls in self._EXTENT_DOM_CLASSES:
            # Match the class anywhere inside a class="..." attribute,
            # including multi-class values like class="test-content scrollable".
            if re.search(rf'class="[^"]*\b{re.escape(cls)}\b[^"]*"', html_content):
                found.add(cls)
        return found

    def _find_cdn_urls(self, html_content: str) -> bool:
        """Return True if the HTML references the Extent CDN or framework URLs."""
        return bool(
            re.search(r'extent-github-cdn|extent-framework|spark-style\.css', html_content)
        )

    def _find_asset_files(self, root: Path) -> list[Path]:
        return [root / name for name in self._ASSET_FILENAMES if (root / name).is_file()]

    def _find_asset_dirs(self, root: Path) -> list[Path]:
        return [root / name for name in self._ASSET_DIR_NAMES if (root / name).is_dir()]

    # ------------------------------------------------------------------
    # Internal helpers — entry point resolution
    # ------------------------------------------------------------------

    def _resolve_entry_html(self, root: Path, original_path: Path) -> Path:
        """Resolve the entry HTML file from the report root.

        Args:
            root: The report root directory.
            original_path: The caller-supplied path.

        Returns:
            Resolved entry HTML path.

        Raises:
            ReportMalformedError: If no HTML file is found.
        """
        if original_path.is_file():
            return original_path
        entry = find_entry_html(root)
        if entry is None:
            raise ReportMalformedError(
                original_path,
                "No entry HTML file found in Extent report directory.",
            )
        return entry

    def _load_entry_html(self, entry_html: Path) -> tuple[str, BeautifulSoup]:
        """Read and parse the entry HTML file.

        Args:
            entry_html: Path to the HTML file.

        Returns:
            A ``(html_content, soup)`` tuple.

        Raises:
            ReportMalformedError: If the file cannot be read.
        """
        content = safe_read_text(entry_html, max_bytes=_MAX_HTML_BYTES)
        if not content:
            raise ReportMalformedError(
                entry_html,
                f"Entry HTML file is empty, unreadable, or exceeds the "
                f"{_MAX_HTML_BYTES // 1024 // 1024} MB size limit: {entry_html}",
            )
        return content, BeautifulSoup(content, "html.parser")

    # ------------------------------------------------------------------
    # Internal helpers — JSON script variable extraction
    # ------------------------------------------------------------------

    def _extract_json_var(self, html_content: str, var_name: str) -> dict | None:
        """Extract a JSON object assigned to a named JS variable in the HTML.

        Uses bracket-counting to robustly locate the balanced ``{...}``
        after the ``var <name> =`` pattern.  This handles multi-line JSON
        without requiring a full JS parser.

        Args:
            html_content: Text of the HTML file.
            var_name: JavaScript variable name (e.g. ``"testdata"``).

        Returns:
            The parsed dict, or ``None`` if the variable is not found or
            the value is not valid JSON.
        """
        pattern = rf"var\s+{re.escape(var_name)}\s*=\s*"
        m = re.search(pattern, html_content)
        if not m:
            return None

        blob = self._extract_balanced_braces(html_content, m.end())
        if blob is None:
            return None

        if len(blob) > _MAX_JSON_BLOB_CHARS:
            logger.warning(
                "JSON blob for var '%s' exceeds %d-char limit (%d chars), skipping.",
                var_name, _MAX_JSON_BLOB_CHARS, len(blob),
            )
            return None

        try:
            parsed = json.loads(blob)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError as exc:
            logger.debug("Failed to parse JSON for var '%s': %s", var_name, exc)
            return None

    @staticmethod
    def _extract_balanced_braces(text: str, start: int) -> str | None:
        """Extract a balanced ``{...}`` JSON object starting at *start*.

        Correctly handles:
        - Nested objects and arrays.
        - String literals containing ``{``, ``}``, and escaped ``"``.

        Args:
            text: The full text to scan.
            start: Index where the ``{`` is expected (leading whitespace
                is skipped).

        Returns:
            The extracted JSON string, or ``None`` if no balanced object
            is found.
        """
        # Skip leading whitespace
        idx = start
        while idx < len(text) and text[idx] in " \t\r\n":
            idx += 1

        if idx >= len(text) or text[idx] != "{":
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i in range(idx, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[idx : i + 1]
        return None

    # ------------------------------------------------------------------
    # Internal helpers — run metadata extraction
    # ------------------------------------------------------------------

    def _extract_run_metadata(
        self,
        root: Path,
        soup: BeautifulSoup,
        html_content: str,
        report_config: dict | None,
        test_data: dict | None,
    ) -> RunMetadata:
        """Build :class:`~qalens.models.run.RunMetadata` from available sources.

        Tries (in order): ``reportConfig`` JSON blob, ``<title>`` tag,
        and timestamps derived from min/max of test start/end times.

        Args:
            root: Report root directory.
            soup: Parsed entry HTML.
            html_content: Raw entry HTML text.
            report_config: Parsed ``reportConfig`` dict, or ``None``.
            test_data: Parsed ``testdata`` dict, or ``None``.

        Returns:
            Populated :class:`~qalens.models.run.RunMetadata`.
        """
        project = self._extract_project_name(soup, report_config)
        report_version = self._extract_report_version(soup)
        started_at, finished_at = self._extract_run_timestamps(test_data)
        total_duration_ms: int | None = None
        if started_at and finished_at:
            total_duration_ms = int(
                (finished_at - started_at).total_seconds() * 1000
            )

        if project is None:
            self._warn(
                field="RunMetadata.project",
                reason="Could not find project name in Extent report config or title.",
            )

        return RunMetadata(
            run_id=self._stable_run_id(root, html_content),
            report_format=self.parser_key,
            report_version=report_version,
            report_path=str(root.resolve()),
            project=project,
            started_at=started_at,
            finished_at=finished_at,
            total_duration_ms=total_duration_ms,
        )

    def _stable_run_id(self, root: Path, html_content: str) -> str:
        """Return a deterministic id for idempotent Extent re-ingestion."""
        payload = f"{root.resolve()}\0{html_content}"
        digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()
        return f"extent-{digest[:16]}"

    def _extract_project_name(
        self, soup: BeautifulSoup, report_config: dict | None
    ) -> str | None:
        """Extract the project name from ``reportConfig`` or ``<title>``."""
        if report_config:
            name = first_nonempty(
                report_config.get("projectName"),
                report_config.get("reportName"),
            )
            if name:
                return name
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True) or None
        return None

    def _extract_report_version(self, soup: BeautifulSoup) -> str | None:
        """Extract ``X.Y.Z`` from the meta generator content."""
        meta = soup.find("meta", attrs={"name": "generator"})
        if meta:
            content = str(meta.get("content", "") or "")
            parts = content.split()
            if len(parts) >= 2:
                return parts[1]
        return None

    def _extract_run_timestamps(
        self, test_data: dict | None
    ) -> tuple[datetime | None, datetime | None]:
        """Derive run start/finish from the min/max of all test times."""
        if not test_data:
            return None, None
        tests = test_data.get("tests") or []
        starts: list[int] = []
        ends: list[int] = []
        for t in tests:
            if not isinstance(t, dict):
                continue
            s = parse_epoch_ms(t.get("startTime"))
            e = parse_epoch_ms(t.get("endTime"))
            if s:
                starts.append(s)
            if e:
                ends.append(e)
        started_at = (
            datetime.fromtimestamp(min(starts) / 1000.0, tz=timezone.utc)
            if starts
            else None
        )
        finished_at = (
            datetime.fromtimestamp(max(ends) / 1000.0, tz=timezone.utc)
            if ends
            else None
        )
        return started_at, finished_at

    # ------------------------------------------------------------------
    # Internal helpers — test case extraction from JSON
    # ------------------------------------------------------------------

    def _extract_test_case_from_node(
        self, node: dict, root: Path, source_format: str
    ) -> TestCaseResult:
        """Convert one Extent ``testdata.tests[]`` node to a :class:`TestCaseResult`.

        Args:
            node: A dict from the ``testdata.tests`` array.
            root: Report root for resolving attachment paths.
            source_format: Parser key for ``source_format`` field.

        Returns:
            A populated :class:`~qalens.models.test_case.TestCaseResult`.
        """
        name: str = truncate(str(node.get("name") or "Unnamed Test"), _MAX_FIELD_LEN)
        status = TestStatus.from_string(node.get("status") or "")
        raw_id = str(node.get("id", ""))[:128]  # limit raw_id length

        test_id = sanitize_test_id(f"{source_format}_{raw_id}_{name}") if raw_id else sanitize_test_id(f"{source_format}_{name}")

        started_at: datetime | None = None
        finished_at: datetime | None = None
        duration_ms: int | None = None

        start_ms = parse_epoch_ms(node.get("startTime"))
        end_ms = parse_epoch_ms(node.get("endTime"))
        if start_ms:
            started_at = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
        if end_ms:
            finished_at = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc)
        if started_at and finished_at:
            duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        else:
            duration_ms_raw = node.get("duration")
            if duration_ms_raw is not None:
                duration_ms = parse_duration_ms(duration_ms_raw)

        tags: list[str] = []
        for cat in node.get("categoryName") or []:
            if cat and str(cat).strip():
                tags.append(str(cat).strip())

        owner_raw = node.get("author") or []
        owner = str(owner_raw[0]).strip() if owner_raw and owner_raw[0] else None

        description_raw = node.get("description") or ""
        description = truncate(clean_html_text(str(description_raw)).strip(), _MAX_FIELD_LEN) or None

        failure = self._extract_failure(node, name)
        is_failing = status in (TestStatus.FAILED, TestStatus.BROKEN)

        # --- Artifact refs: collect in sequence order so that later (higher
        #     sequence_no) refs rank higher in the screenshot priority selector.
        # 1. Test-level detail refs (embedded base64 screenshots, sequence 0…)
        detail_atts, detail_refs = self._attachments_from_details(
            node.get("details") or [],
            source_format,
            is_from_failed_step=is_failing,
            base_sequence=0,
        )
        # 2. Test-level media file-path refs (continue sequence)
        media_refs = self._media_as_artifact_refs(
            node.get("media") or [],
            root,
            is_from_failed_step=is_failing,
            base_sequence=len(detail_refs),
        )
        # 3. Step-level refs (highest sequence numbers → nearest to failure)
        steps, step_refs = self._extract_steps(
            node.get("nodes") or [],
            root,
            source_format,
            start_seq=len(detail_refs) + len(media_refs),
        )

        attachments = self._extract_attachments(node.get("media") or [], root, source_format)
        attachments.extend(detail_atts)
        raw_artifact_refs: list[ArtifactRef] = detail_refs + media_refs + step_refs

        # Promote step-level Attachment objects to the test case (legacy path).
        for step in steps:
            attachments.extend(step.attachments)

        return TestCaseResult(
            test_id=test_id,
            name=name,
            full_name=None,  # Extent does not expose class#method in HTML
            status=status,
            suite=None,      # top-level Extent tests have no suite in testdata JSON
            owner=owner,
            tags=tags,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            steps=steps,
            failure=failure,
            attachments=attachments,
            raw_artifact_refs=raw_artifact_refs,
            source_format=source_format,
            raw_id=raw_id or None,
        )

    def _extract_steps(
        self,
        nodes: list,
        root: Path,
        source_format: str,
        *,
        start_seq: int = 0,
    ) -> tuple[list[StepResult], list[ArtifactRef]]:
        """Extract steps from Extent ``test.nodes`` array.

        Args:
            nodes: List of node dicts from ``testdata.tests[].nodes``.
            root: Report root for resolving attachment paths.
            source_format: Parser key for the source format.
            start_seq: Starting sequence number for artifact refs produced
                by steps.  Callers should pass the count of test-level refs
                already collected so that step refs have higher sequence
                numbers (= closer to the failure in priority ranking).

        Returns:
            ``(steps, step_artifact_refs)`` — ordered
            :class:`~qalens.models.test_case.StepResult` list plus any
            :class:`~qalens.models.artifact_ref.ArtifactRef` objects extracted
            from step-level screenshot details.
        """
        steps: list[StepResult] = []
        all_step_refs: list[ArtifactRef] = []
        running_seq = start_seq
        for node in nodes:
            if not isinstance(node, dict):
                continue
            name = truncate(str(node.get("name") or "Unnamed Step"), _MAX_FIELD_LEN)
            status = TestStatus.from_string(node.get("status") or "")

            start_ms = parse_epoch_ms(node.get("startTime"))
            end_ms = parse_epoch_ms(node.get("endTime"))
            started_at = (
                datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
                if start_ms
                else None
            )
            finished_at = (
                datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc)
                if end_ms
                else None
            )
            duration_ms: int | None = None
            if started_at and finished_at:
                duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

            # Collect log lines from details entries
            log_lines: list[str] = []
            for detail in node.get("details") or []:
                if isinstance(detail, dict) and detail.get("body"):
                    body = truncate(clean_html_text(str(detail["body"])).strip(), _MAX_LOG_LEN)
                    if body:
                        log_lines.append(body)
            log_output = "\n".join(log_lines) if log_lines else None

            attachments = self._extract_attachments(
                node.get("media") or [], root, source_format
            )
            step_is_failing = status in (TestStatus.FAILED, TestStatus.BROKEN)
            step_detail_atts, step_refs = self._attachments_from_details(
                node.get("details") or [],
                source_format,
                is_from_failed_step=step_is_failing,
                step_name=str(name),
                base_sequence=running_seq,
            )
            running_seq += len(step_refs)
            all_step_refs.extend(step_refs)
            attachments.extend(step_detail_atts)

            steps.append(
                StepResult(
                    name=str(name),
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    log_output=log_output,
                    attachments=attachments,
                    depth=0,
                )
            )
        return steps, all_step_refs

    def _extract_failure(self, node: dict, test_name: str) -> FailureInfo | None:
        """Extract :class:`~qalens.models.failure.FailureInfo` from a test node.

        Checks ``node.exception`` first, then falls back to ``node.details``
        entries with ``type == "fail"``.

        Args:
            node: Test node dict.
            test_name: The test name (used in warning messages).

        Returns:
            A :class:`~qalens.models.failure.FailureInfo`, or ``None`` if
            the test has no failure information.
        """
        status = TestStatus.from_string(node.get("status") or "")
        if not status.is_failing:
            return None

        exc = node.get("exception")
        if exc and isinstance(exc, dict):
            error_type = truncate(str(exc.get("type") or ""), _MAX_FIELD_LEN) or None
            message = truncate(str(exc.get("message") or ""), _MAX_MESSAGE_LEN) or None
            stack_trace_raw = exc.get("stackTrace") or None
            stack_trace = truncate(str(stack_trace_raw), _MAX_STACK_LEN) if stack_trace_raw else None
            if stack_trace:
                _lines = stack_trace.splitlines()
                if len(_lines) > _MAX_STACK_LINES:
                    stack_trace = "\n".join(_lines[:_MAX_STACK_LINES]) + "\n... [truncated]"

            # Derive error_type from stack_trace if not explicit
            if not error_type and stack_trace:
                error_type = extract_error_type(stack_trace)
            if not message and stack_trace:
                _, message = split_error_message(stack_trace)

            return FailureInfo(
                error_type=error_type,
                message=message,
                stack_trace=stack_trace,
            )

        # Fallback: look for a "fail"-type detail entry
        for detail in node.get("details") or []:
            if isinstance(detail, dict) and detail.get("type") == "fail":
                raw_body = clean_html_text(str(detail.get("body") or ""))
                if raw_body:
                    error_type, message = split_error_message(raw_body)
                    return FailureInfo(
                        error_type=error_type,
                        message=message or raw_body,
                        stack_trace=raw_body if "\n" in raw_body else None,
                    )

        # Check step-level fail details
        for step_node in node.get("nodes") or []:
            if not isinstance(step_node, dict):
                continue
            for detail in step_node.get("details") or []:
                if isinstance(detail, dict) and detail.get("type") == "fail":
                    raw_body = clean_html_text(str(detail.get("body") or ""))
                    if raw_body:
                        error_type, message = split_error_message(raw_body)
                        return FailureInfo(
                            error_type=error_type,
                            message=message or raw_body,
                            stack_trace=None,
                        )

        self._warn(
            field="FailureInfo",
            reason="Test is marked as failed/broken but no exception or failure detail was found.",
            test_name=test_name,
            severity=WarningSeverity.MEDIUM,
        )
        return FailureInfo()

    def _save_embedded_screenshot(self, data_uri: str) -> Path | None:
        """Decode a base64 data URI, write it to ``_attachments_dir``, and return the path.

        Returns ``None`` if ``_attachments_dir`` is unset, the URI is malformed,
        the decoded payload exceeds ``_MAX_SCREENSHOT_BYTES``, or any I/O error
        occurs.  The write is idempotent: a ``sha256[:16]`` filename means
        re-ingesting the same report does not create duplicate files.
        """
        if self._attachments_dir is None:
            return None
        m = _DATA_URI_RE.match(data_uri)
        if not m:
            return None
        mime, b64_data = m.group(1), m.group(2)
        # Guard against huge payloads *before* decoding (base64 overhead ~33 %)
        if len(b64_data) > _MAX_SCREENSHOT_BYTES * 4 // 3:
            logger.warning("Skipping embedded screenshot: base64 payload too large (%d chars)", len(b64_data))
            return None
        try:
            raw = base64.b64decode(b64_data, validate=True)
        except Exception:
            return None
        if len(raw) > _MAX_SCREENSHOT_BYTES:
            return None
        ext = _mime_to_ext(mime)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        dest = self._attachments_dir / f"{digest}{ext}"
        if not dest.exists():
            self._attachments_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        return dest

    # Matches data URIs inside HTML <img src="..."> attributes
    _IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']?(data:[^"\'>\s]+)["\']?', re.IGNORECASE)

    def _attachments_from_details(
        self,
        details: list,
        source_format: str,
        *,
        base_sequence: int = 0,
        is_from_failed_step: bool = False,
        step_name: str | None = None,
    ) -> tuple[list[Attachment], list[ArtifactRef]]:
        """Extract screenshot attachments and artifact refs from Extent ``details`` entries.

        Extent stores screenshots captured via ``addScreenCaptureFromBase64String``
        as detail entries with ``type == "img"``.  The ``body`` field holds either
        a raw ``data:image/...;base64,...`` URI or an ``<img src="data:...">`` tag.

        Args:
            details: List of detail dicts from ``testdata.tests[].details`` or
                ``testdata.tests[].nodes[].details``.
            source_format: Parser key (used only for legacy ``Attachment`` creation).
            base_sequence: Starting ``sequence_no`` for emitted
                :class:`~qalens.models.artifact_ref.ArtifactRef` objects.
            is_from_failed_step: Forward to ``ArtifactRef.is_from_failed_step``
                for every ref produced here.
            step_name: Name of the enclosing step, forwarded to
                ``ArtifactRef.step_name``.  ``None`` for test-level details.

        Returns:
            ``(attachments, artifact_refs)`` — legacy ``Attachment`` objects
            (only populated when ``_attachments_dir`` is set) plus policy-facing
            ``ArtifactRef`` objects (always populated for every data URI found).
        """
        attachments: list[Attachment] = []
        refs: list[ArtifactRef] = []
        seq = base_sequence
        for detail in details:
            if not isinstance(detail, dict):
                continue
            dtype = str(detail.get("type") or "").lower()
            body = str(detail.get("body") or "")
            if not body:
                continue
            # Extract the data URI: try raw match first, then img src attribute
            data_uri: str | None = None
            if _DATA_URI_RE.match(body):
                data_uri = body
            else:
                m = self._IMG_SRC_RE.search(body)
                if m:
                    data_uri = m.group(1)
            if data_uri is None and dtype != "img":
                continue
            if data_uri:
                m_uri = _DATA_URI_RE.match(data_uri)
                refs.append(
                    ArtifactRef(
                        source_uri=data_uri,
                        kind="screenshot",
                        sequence_no=seq,
                        is_from_failed_step=is_from_failed_step,
                        mime_type=m_uri.group(1) if m_uri else None,
                        step_name=step_name,
                    )
                )
                seq += 1
                # Legacy path: write to disk when attachments_dir configured
                if self._attachments_dir:
                    resolved = self._save_embedded_screenshot(data_uri)
                    if resolved:
                        attachments.append(Attachment(
                            name=resolved.name,
                            kind=AttachmentKind.SCREENSHOT,
                            path=str(resolved),
                            resolved_path=resolved,
                            source=source_format,
                        ))
        return attachments, refs

    def _media_as_artifact_refs(
        self,
        media_entries: list,
        root: Path,
        *,
        is_from_failed_step: bool = False,
        base_sequence: int = 0,
    ) -> list[ArtifactRef]:
        """Convert Extent ``media`` entries to :class:`~qalens.models.artifact_ref.ArtifactRef`.

        ``media`` entries in the Extent JSON blob reference screenshots via file
        paths (relative to the report root) or embedded ``data:`` URIs.  Only
        entries that look like image artifacts are converted; others are skipped.

        Args:
            media_entries: List of media dicts (``{"path": "...", "kind": "img"}``).
            root: Report root directory for resolving relative file paths.
            is_from_failed_step: Forwarded to every emitted ``ArtifactRef``.
            base_sequence: Starting sequence number.

        Returns:
            List of :class:`~qalens.models.artifact_ref.ArtifactRef` for image
            entries whose paths resolve to existing files (or are valid data URIs).
            Non-image entries and missing files are silently skipped.
        """
        refs: list[ArtifactRef] = []
        seq = base_sequence
        for entry in media_entries:
            if not isinstance(entry, dict):
                continue
            raw_path = str(entry.get("path") or "")[:512]
            if not raw_path:
                continue
            kind_hint = str(entry.get("kind") or "")
            is_img = "img" in kind_hint or AttachmentKind.from_path(raw_path) == AttachmentKind.SCREENSHOT

            if raw_path.startswith("data:"):
                # Embedded base64 data URI — emit as-is
                m_uri = _DATA_URI_RE.match(raw_path)
                refs.append(
                    ArtifactRef(
                        source_uri=raw_path,
                        kind="screenshot",
                        sequence_no=seq,
                        is_from_failed_step=is_from_failed_step,
                        mime_type=m_uri.group(1) if m_uri else None,
                    )
                )
                seq += 1
            elif is_img:
                # File-path based screenshot — resolve within report root
                resolved = safe_join(root, raw_path)
                if resolved and resolved.is_file():
                    refs.append(
                        ArtifactRef(
                            source_uri=str(resolved),
                            kind="screenshot",
                            name=Path(raw_path).name[:256],
                            sequence_no=seq,
                            is_from_failed_step=is_from_failed_step,
                        )
                    )
                    seq += 1
                else:
                    logger.debug(
                        "Skipping media artifact ref — file not found: %r", raw_path
                    )
        return refs

    def _extract_attachments(
        self, media_entries: list, root: Path, source_format: str
    ) -> list[Attachment]:
        """Build :class:`~qalens.models.attachment.Attachment` objects from
        Extent media entries.

        Args:
            media_entries: List of media dicts (``{"path": "...", "kind": "img"}``).
            root: Report root for resolving relative paths.
            source_format: Parser key.

        Returns:
            List of :class:`~qalens.models.attachment.Attachment` objects.
        """
        attachments: list[Attachment] = []
        for entry in media_entries:
            if not isinstance(entry, dict):
                continue
            raw_path = str(entry.get("path") or "")[:512]
            if not raw_path:
                continue
            kind_hint = str(entry.get("kind") or "")
            kind = AttachmentKind.SCREENSHOT if "img" in kind_hint else AttachmentKind.from_path(raw_path)
            if raw_path.startswith("data:"):
                # Embedded base64 data URI — extract to disk if attachments_dir is configured
                resolved = self._save_embedded_screenshot(raw_path)
                display_name = (f"{kind.value}_embedded" if resolved is None else resolved.name)[:256]
            else:
                # Path-traversal guard: only resolve if path stays within report root
                resolved = safe_join(root, raw_path)
                resolved = resolved if (resolved and resolved.is_file()) else None
                display_name = Path(raw_path).name[:256]
            attachments.append(
                Attachment(
                    name=display_name,
                    kind=kind,
                    path=raw_path if not raw_path.startswith("data:") else (str(resolved) if resolved else ""),
                    resolved_path=resolved,
                    source=source_format,
                )
            )
        return attachments

    # ------------------------------------------------------------------
    # Internal helpers — DOM fallback extraction
    # ------------------------------------------------------------------

    def _extract_test_cases_from_dom(
        self, root: Path, soup: BeautifulSoup, source_format: str
    ) -> list[TestCaseResult]:
        """DOM-based extraction fallback for reports without embedded JSON.

        Handles real Extent Spark v5 HTML where:
        - ``<li class="test-item" status="pass">`` — status is an attribute
        - ``<h5 class="test-status text-pass">`` — contains the test name
        - ``<span class="badge badge-success">`` — start timestamp
        - ``<span class="badge badge-danger">``  — end timestamp
        - ``<div class="node">`` inside ``<div class="card-title">`` — steps

        Falls back to generic selector families for older Extent versions.

        Args:
            root: Report root directory.
            soup: Parsed BeautifulSoup of the entry HTML.
            source_format: Parser key.

        Returns:
            List of :class:`~qalens.models.test_case.TestCaseResult`.
        """
        test_cases: list[TestCaseResult] = []

        # ------------------------------------------------------------------
        # Real Extent Spark v5: li.test-item with status attribute.
        # Scope to div.test-view to avoid picking up sidebar category/tag filter
        # items (div.category-view) which share the same li.test-item class but
        # have no real test content (names like "@scenario1", no steps, no status).
        spark_items = soup.select("div.test-view li.test-item")
        if not spark_items:
            # Fallback: any li.test-item that has a non-empty status attribute
            # and whose heading doesn't start with "@" (sidebar tag filter rows).
            spark_items = [
                el for el in soup.select("li.test-item")
                if str(el.get("status") or "").strip()
                and not any(
                    h5.get_text(strip=True).startswith("@")
                    for h5 in el.select("h5.test-status")
                )
            ]
        if spark_items:
            for item in spark_items:
                if not isinstance(item, Tag):
                    continue

                # Status comes from the status="pass|fail|skip" attribute
                status_str = str(item.get("status") or "")
                status = TestStatus.from_string(status_str)

                # Name is inside h5.test-status (confusingly named)
                name_el = item.select_one("h5.test-status")
                name = name_el.get_text(strip=True) if name_el else ""

                # Fallback: try .test-name or first heading
                if not name:
                    for sel in (".test-name", "h5", "h4", ".name"):
                        el = item.select_one(sel)
                        if el:
                            name = el.get_text(strip=True)
                            break
                if not name:
                    name = "Unknown Test"

                # Timestamps: badge-success = start, badge-danger = end
                started_at: datetime | None = None
                finished_at: datetime | None = None
                duration_ms: int | None = None
                start_span = item.select_one(".badge-success")
                end_span = item.select_one(".badge-danger")
                _fmt = "%m.%d.%Y %I:%M:%S %p"
                if start_span:
                    try:
                        started_at = datetime.strptime(
                            start_span.get_text(strip=True), _fmt
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                if end_span:
                    try:
                        finished_at = datetime.strptime(
                            end_span.get_text(strip=True), _fmt
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                if started_at and finished_at:
                    delta = finished_at - started_at
                    duration_ms = int(delta.total_seconds() * 1000)

                # Steps: div.node elements inside div.card-title
                steps: list[StepResult] = []
                for node_div in item.select("div.card-title div.node"):
                    if not isinstance(node_div, Tag):
                        continue
                    # Status from badge class: pass-bg → pass, fail-bg → fail
                    badge = node_div.select_one(".badge")
                    step_status = TestStatus.PASSED
                    if badge:
                        badge_text = badge.get_text(strip=True).lower()
                        step_status = TestStatus.from_string(badge_text)
                        # Remove the badge text from the node to get clean step name
                        badge.extract()
                    step_name = node_div.get_text(strip=True) or "step"
                    steps.append(
                        StepResult(
                            step_id=str(uuid4()),
                            name=step_name,
                            status=step_status,
                            depth=0,
                        )
                    )

                # Failure info: collect message from event-row trs with fail-bg badge
                failure: FailureInfo | None = None
                if status in (TestStatus.FAILED, TestStatus.BROKEN):
                    fail_message_parts: list[str] = []
                    for event_row in item.select("tr.event-row"):
                        if not isinstance(event_row, Tag):
                            continue
                        if not event_row.select_one(".fail-bg"):
                            continue
                        cells = event_row.select("td")
                        if len(cells) >= 3:
                            msg_cell = cells[2]
                            # Clone to avoid mutating the tree; strip nested screenshot links
                            import copy
                            msg_clone = copy.copy(msg_cell)
                            for a_tag in msg_clone.select("a[data-featherlight]"):
                                a_tag.decompose()
                            msg_text = msg_clone.get_text(separator=" ", strip=True)
                            if msg_text:
                                fail_message_parts.append(msg_text)
                    if fail_message_parts:
                        failure = FailureInfo(message=". ".join(fail_message_parts)[:2000])

                # Screenshots: find <a data-featherlight="image"> or <a href="data:image/...">
                attachments: list[Attachment] = []
                raw_artifact_refs: list[ArtifactRef] = []
                for seq_idx, a_tag in enumerate(
                    item.select("a[data-featherlight='image'], a[href^='data:image']")
                ):
                    if not isinstance(a_tag, Tag):
                        continue
                    href = str(a_tag.get("href") or "")
                    if not href.startswith("data:"):
                        continue
                    # Emit a parser-agnostic ArtifactRef (policy decides storage)
                    m_uri = _DATA_URI_RE.match(href)
                    raw_artifact_refs.append(
                        ArtifactRef(
                            source_uri=href,
                            kind="screenshot",
                            sequence_no=seq_idx,
                            is_from_failed_step=status in (TestStatus.FAILED, TestStatus.BROKEN),
                            mime_type=m_uri.group(1) if m_uri else None,
                        )
                    )
                    # Legacy path: also write to disk when attachments_dir is set
                    # (for backward compat with code that uses attachments_dir directly)
                    if self._attachments_dir:
                        resolved = self._save_embedded_screenshot(href)
                        display_name = resolved.name if resolved else "screenshot_embedded"
                        attachments.append(
                            Attachment(
                                name=display_name[:256],
                                kind=AttachmentKind.SCREENSHOT,
                                path=str(resolved) if resolved else "",
                                resolved_path=resolved,
                                source=source_format,
                            )
                        )

                test_id = sanitize_test_id(f"{source_format}_{name}")
                test_cases.append(
                    TestCaseResult(
                        test_id=test_id,
                        name=name,
                        status=status,
                        failure=failure,
                        attachments=attachments,
                        raw_artifact_refs=raw_artifact_refs,
                        steps=steps,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                        source_format=source_format,
                    )
                )
            return test_cases

        # ------------------------------------------------------------------
        # Generic fallback for older Extent versions
        # ------------------------------------------------------------------
        selectors: list[tuple[str, str, str]] = [
            (".test-node", ".test-name", ".test-status"),
            (".test", ".name", ".status"),
        ]
        node_els: list = []
        name_sel = ".test-name"
        status_sel = ".test-status"
        for parent_sel, n_sel, s_sel in selectors:
            node_els = soup.select(parent_sel)
            if node_els:
                name_sel, status_sel = n_sel, s_sel
                break

        for node_el in node_els:
            if not isinstance(node_el, Tag):
                continue
            name_el = node_el.select_one(name_sel)
            status_el = node_el.select_one(status_sel)
            name = name_el.get_text(strip=True) if name_el else "Unknown Test"
            # For older versions, try status attribute first, then text
            status_str = str(node_el.get("status") or "")
            if not status_str and status_el:
                # Inspect CSS classes for text-pass / text-fail hints
                classes = " ".join(status_el.get("class") or [])
                if "text-pass" in classes or "pass" in classes:
                    status_str = "pass"
                elif "text-fail" in classes or "fail" in classes:
                    status_str = "fail"
                elif "text-skip" in classes or "skip" in classes:
                    status_str = "skip"
                else:
                    status_str = status_el.get_text(strip=True)
            status = TestStatus.from_string(status_str)

            test_id = sanitize_test_id(f"{source_format}_{name}")
            test_cases.append(
                TestCaseResult(
                    test_id=test_id,
                    name=name,
                    status=status,
                    source_format=source_format,
                )
            )
        return test_cases
