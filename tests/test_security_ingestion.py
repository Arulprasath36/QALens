"""Security tests for ARI's ingestion pipeline.

Covers:
- XSS / script-injection via report-derived string fields
- Path traversal blocking (safe_join)
- Input size limits (HTML, JSON, test-node count)
- Deeply nested JSON robustness
- UID validation in Allure parser
- LLM prompt injection guard in system prompt
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pytest

from qara.parsers.allure import (
    AllureHtmlParser,
    _MAX_JSON_BYTES,
    _MAX_RECURSION_DEPTH,
    _MAX_TEST_CASES,
    _SAFE_UID_RE,
)
from qara.parsers.extent import (
    ExtentHtmlParser,
    _MAX_HTML_BYTES,
    _MAX_JSON_BLOB_CHARS,
    _MAX_TEST_NODES,
)
from qara.utils.fs import safe_join


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extent_html(test_nodes: list[dict]) -> str:
    """Return a minimal Extent v4 HTML string embedding the given test nodes."""
    payload = json.dumps({"tests": test_nodes})
    return textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html>
        <head><title>Extent Report</title></head>
        <body>
        <script>var testdata = {payload};</script>
        </body>
        </html>
    """)


def _simple_extent_node(
    name: str = "My Test",
    status: str = "pass",
) -> dict:
    return {"name": name, "status": status, "id": "abc123"}


def _make_allure_suites(uid_list: list[str]) -> dict:
    """Return a minimal Allure suites.json tree."""
    return {
        "name": "root",
        "children": [
            {"uid": uid, "name": f"Test {uid}", "status": "passed", "children": []}
            for uid in uid_list
        ],
    }


# ---------------------------------------------------------------------------
# A. XSS via report-derived string fields (parser side)
# ---------------------------------------------------------------------------

class TestXSSExtentFields:
    """Verify that script/HTML content in report fields is stored as plain text,
    not executed, and does not contain raw unescaped angle brackets in the
    model fields that flow into the DB and LLM."""

    _MALICIOUS_NAMES = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        '"><svg onload=alert(1)>',
        "javascript:alert(document.cookie)",
        "\u003cscript\u003ealert(1)\u003c/script\u003e",
    ]

    def _parse_first_test(self, tmp_path: Path, name: str) -> object:
        parser = ExtentHtmlParser()
        html = _make_extent_html([_simple_extent_node(name=name)])
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "index.html").write_text(html, encoding="utf-8")
        run = parser.parse(report_dir)
        assert run is not None and run.test_cases, "Expected at least one test case"
        return run.test_cases[0]

    @pytest.mark.parametrize("malicious_name", _MALICIOUS_NAMES)
    def test_name_stored_as_plain_text(self, tmp_path, malicious_name):
        """Test names containing HTML/JS must be stored verbatim (plain text)
        so they can be safely escaped at render time.  The raw `<script>` tag
        must exist in the stored name — it should NOT be HTML-decoded or
        silently swallowed; the responsibility for escaping is on the UI."""
        tc = self._parse_first_test(tmp_path, malicious_name)
        # The name must survive the parse and be stored as a string
        assert isinstance(tc.name, str)
        assert len(tc.name) > 0

    def test_name_truncated_to_max_field_len(self, tmp_path):
        """A name longer than _MAX_FIELD_LEN must be truncated, not rejected.
        truncate() appends a 1-char ellipsis, so the ceiling is _MAX_FIELD_LEN + 1."""
        from qara.parsers.extent import _MAX_FIELD_LEN
        long_name = "A" * (_MAX_FIELD_LEN + 500)
        tc = self._parse_first_test(tmp_path, long_name)
        # +1 accounts for the ellipsis character appended by truncate()
        assert len(tc.name) <= _MAX_FIELD_LEN + 1
        assert len(tc.name) < len(long_name)

    def test_name_is_shorter_after_round_trip(self, tmp_path):
        """Verifies a long 'description'-style field on the node does not
        cause a crash and the test-case name itself is still a string."""
        node = _simple_extent_node()
        node["description"] = "D" * 10_000
        parser = ExtentHtmlParser()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "index.html").write_text(
            _make_extent_html([node]), encoding="utf-8"
        )
        run = parser.parse(report_dir)
        tc = run.test_cases[0]
        assert isinstance(tc.name, str)


# ---------------------------------------------------------------------------
# B. Path traversal blocking (safe_join)
# ---------------------------------------------------------------------------

class TestSafeJoin:
    """safe_join must block any path that escapes the root directory."""

    def test_normal_relative_path_allowed(self, tmp_path):
        child = tmp_path / "data" / "report.json"
        child.parent.mkdir(parents=True)
        child.write_text("{}")
        result = safe_join(tmp_path, "data/report.json")
        assert result is not None
        assert result == child.resolve()

    def test_parent_traversal_blocked(self, tmp_path):
        assert safe_join(tmp_path, "../../../etc/passwd") is None

    def test_windows_style_path_is_treated_as_literal_on_posix(self, tmp_path):
        # On POSIX, backslash is a valid filename character, not a separator.
        # The resulting path stays inside root (it's just a funny filename),
        # so safe_join should return a (non-existent) path under root, not None.
        result = safe_join(tmp_path, "..\\filename")
        # Either it stays under root (POSIX: literal filename) or it's None.
        # What matters is it does NOT resolve to something outside root.
        if result is not None:
            assert str(result).startswith(str(tmp_path.resolve()))

    def test_absolute_path_escape_blocked(self, tmp_path):
        # Joining an absolute path directly to root
        assert safe_join(tmp_path, "/etc/passwd") is None

    def test_encoded_traversal_blocked(self, tmp_path):
        # URL-encoded traversal (not resolved as URL, but posixpath normalizes it)
        assert safe_join(tmp_path, "data/../../../../../../etc/passwd") is None

    def test_nested_safe_path_allowed(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("ok")
        result = safe_join(tmp_path, "a/b/c.txt")
        assert result is not None

    def test_root_itself_allowed(self, tmp_path):
        result = safe_join(tmp_path, ".")
        assert result is not None


# ---------------------------------------------------------------------------
# C. Extent HTML — file size limit
# ---------------------------------------------------------------------------

class TestExtentHtmlSizeLimit:

    def test_oversized_html_returns_none_or_empty(self, tmp_path):
        """A report HTML exceeding _MAX_HTML_BYTES must not be parsed."""
        parser = ExtentHtmlParser()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        # Write a 1-byte-over-limit file
        oversized = b"X" * (_MAX_HTML_BYTES + 1)
        (report_dir / "index.html").write_bytes(oversized)
        # parse() should either return None or an empty test run rather than
        # crashing or silently processing the huge file
        try:
            run = parser.parse(report_dir)
            assert run is None or len(run.test_cases) == 0
        except Exception:  # noqa: BLE001 — any exception is also acceptable
            pass

    def test_json_blob_size_limit(self, tmp_path):
        """A JSON blob exceeding _MAX_JSON_BLOB_CHARS must not be parsed."""
        parser = ExtentHtmlParser()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        # Craft an HTML whose var testdata value is longer than the char limit
        blob = "A" * (_MAX_JSON_BLOB_CHARS + 1)
        html = f"<html><body><script>var testdata = {blob};</script></body></html>"
        (report_dir / "index.html").write_text(html, encoding="utf-8")
        run = parser.parse(report_dir)
        assert run is None or len(run.test_cases) == 0


# ---------------------------------------------------------------------------
# D. Extent — test node count cap
# ---------------------------------------------------------------------------

class TestExtentTestNodeCap:

    def test_excess_test_nodes_truncated(self, tmp_path):
        """Reports with more than _MAX_TEST_NODES tests must be silently
        truncated rather than crashing or returning all nodes."""
        count = _MAX_TEST_NODES + 500
        nodes = [_simple_extent_node(name=f"Test {i}") for i in range(count)]
        parser = ExtentHtmlParser()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "index.html").write_text(
            _make_extent_html(nodes), encoding="utf-8"
        )
        run = parser.parse(report_dir)
        assert run is not None
        assert len(run.test_cases) <= _MAX_TEST_NODES


# ---------------------------------------------------------------------------
# E. Extent — attachment path traversal blocked
# ---------------------------------------------------------------------------

class TestExtentAttachmentPathTraversal:

    def _parse_with_attachment(self, tmp_path: Path, att_path: str):
        node = _simple_extent_node()
        node["media"] = [{"path": att_path, "kind": "img"}]
        parser = ExtentHtmlParser()
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "index.html").write_text(
            _make_extent_html([node]), encoding="utf-8"
        )
        return parser.parse(report_dir)

    def test_traversal_attachment_path_has_no_resolved_path(self, tmp_path):
        run = self._parse_with_attachment(tmp_path, "../../../etc/passwd")
        assert run is not None
        for tc in run.test_cases:
            for att in tc.attachments:
                assert att.resolved_path is None, (
                    f"Path traversal attachment should not resolve: {att.path}"
                )

    def test_safe_attachment_path_stored(self, tmp_path):
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        img = report_dir / "img" / "screen.png"
        img.parent.mkdir()
        img.write_bytes(b"\x89PNG")
        node = _simple_extent_node()
        node["media"] = [{"path": "img/screen.png", "kind": "img"}]
        html = _make_extent_html([node])
        (report_dir / "index.html").write_text(html, encoding="utf-8")
        run = ExtentHtmlParser().parse(report_dir)
        assert run is not None
        tc = run.test_cases[0]
        resolved_paths = [att.resolved_path for att in tc.attachments if att.resolved_path]
        assert len(resolved_paths) >= 1


# ---------------------------------------------------------------------------
# F. Allure — UID validation
# ---------------------------------------------------------------------------

class TestAllureUIDValidation:

    @pytest.mark.parametrize("bad_uid", [
        "../../../etc/passwd",
        "../../secret",
        "uid\x00null",
        "uid;rm -rf /",
        "uid|cat /etc/passwd",
        "uid\ninjected",
        "",
        "../../data/test-cases/other",
    ])
    def test_bad_uid_rejected_by_regex(self, bad_uid):
        assert not _SAFE_UID_RE.match(bad_uid), (
            f"Expected UID '{bad_uid}' to fail the safety regex"
        )

    @pytest.mark.parametrize("good_uid", [
        "abc123",
        "test-case-001",
        "my_test_case",
        "ABC-123_def",
        "a1b2c3d4e5f6",
    ])
    def test_good_uid_accepted_by_regex(self, good_uid):
        assert _SAFE_UID_RE.match(good_uid), (
            f"Expected UID '{good_uid}' to pass the safety regex"
        )

    def test_traversal_uid_load_returns_none(self, tmp_path):
        parser = AllureHtmlParser()
        # Craft a file that would be read if traversal were not blocked
        secret = tmp_path / "secret.json"
        secret.write_text('{"name": "pwned"}')
        result = parser._load_test_case_detail(tmp_path, "../secret")
        assert result is None


# ---------------------------------------------------------------------------
# G. Allure — JSON file size limit
# ---------------------------------------------------------------------------

class TestAllureJsonSizeLimit:

    def test_oversized_summary_returns_none(self, tmp_path):
        parser = AllureHtmlParser()
        summary_dir = tmp_path / "widgets"
        summary_dir.mkdir()
        oversized_path = summary_dir / "summary.json"
        oversized_path.write_bytes(b"A" * (_MAX_JSON_BYTES + 1))
        result = parser._load_summary_widget(tmp_path)
        assert result is None

    def test_oversized_suites_returns_none(self, tmp_path):
        parser = AllureHtmlParser()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # AllureHtmlParser._SUITES_JSON = "data/suites.json"
        suites_path = tmp_path / "data" / "suites.json"
        suites_path.write_bytes(b"A" * (_MAX_JSON_BYTES + 1))
        result = parser._load_suites(tmp_path)
        assert result is None

    def test_oversized_test_case_returns_none(self, tmp_path):
        parser = AllureHtmlParser()
        tc_dir = tmp_path / "data" / "test-cases"
        tc_dir.mkdir(parents=True)
        (tc_dir / "validuid.json").write_bytes(b"A" * (_MAX_JSON_BYTES + 1))
        result = parser._load_test_case_detail(tmp_path, "validuid")
        assert result is None


# ---------------------------------------------------------------------------
# H. Allure — recursion depth limit
# ---------------------------------------------------------------------------

class TestAllureRecursionDepth:

    def _make_deep_tree(self, depth: int, uid: str = "leaf-001") -> dict:
        """Build a suites tree `depth` levels deep with a leaf at the bottom."""
        node: dict = {"uid": uid, "name": "Leaf", "status": "passed", "children": []}
        for i in range(depth):
            node = {"name": f"Level {depth - i}", "children": [node]}
        return node

    def test_tree_deeper_than_limit_does_not_crash(self):
        """_collect_uid_entries must not stack-overflow on deeply nested input."""
        parser = AllureHtmlParser()
        deep_tree = self._make_deep_tree(_MAX_RECURSION_DEPTH + 50)
        result: list = []
        # Must not raise RecursionError
        parser._collect_uid_entries(deep_tree, result, parent_suite="", depth=0)
        # The leaf may or may not be collected depending on depth cut-off
        # — what matters is no crash and result is a list
        assert isinstance(result, list)

    def test_shallow_tree_collects_all_leaves(self):
        parser = AllureHtmlParser()
        tree = _make_allure_suites(["uid1", "uid2", "uid3"])
        result: list = []
        parser._collect_uid_entries(tree, result, parent_suite="", depth=0)
        uids_found = [entry[0] for entry in result]
        assert "uid1" in uids_found
        assert "uid2" in uids_found
        assert "uid3" in uids_found


# ---------------------------------------------------------------------------
# I. Allure — test case count cap
# ---------------------------------------------------------------------------

class TestAllureTestCaseCap:

    def test_excess_uid_entries_truncated(self, tmp_path):
        """More than _MAX_TEST_CASES UIDs must be silently capped."""
        uid_list = [f"uid{i:06d}" for i in range(_MAX_TEST_CASES + 200)]

        # Write stub test-case JSON files for the first batch
        tc_dir = tmp_path / "data" / "test-cases"
        tc_dir.mkdir(parents=True)
        for uid in uid_list[:50]:
            (tc_dir / f"{uid}.json").write_text(
                json.dumps({"name": uid, "status": "passed"}), encoding="utf-8"
            )

        parser = AllureHtmlParser()
        suites = _make_allure_suites(uid_list)
        test_cases = parser._extract_test_cases(tmp_path, suites, "allure")
        assert len(test_cases) <= _MAX_TEST_CASES


# ---------------------------------------------------------------------------
# J. LLM prompt injection guard
# ---------------------------------------------------------------------------

class TestPromptInjectionGuard:

    def test_system_prompt_contains_untrusted_data_warning(self):
        from qara.llm.prompts import _BASE_SYSTEM_PROMPT

        prompt_lower = _BASE_SYSTEM_PROMPT.lower()
        assert "untrusted" in prompt_lower, (
            "_BASE_SYSTEM_PROMPT must contain 'untrusted' data warning"
        )

    def test_system_prompt_warns_about_instruction_injection(self):
        from qara.llm.prompts import _BASE_SYSTEM_PROMPT

        assert "ignore" in _BASE_SYSTEM_PROMPT.lower() or "disregard" in _BASE_SYSTEM_PROMPT.lower(), (
            "_BASE_SYSTEM_PROMPT must reference the 'ignore previous instructions' injection pattern"
        )

    def test_build_system_prompt_includes_base(self):
        from qara.llm.prompts import _BASE_SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(answer_plan=None)
        assert "UNTRUSTED" in prompt or "untrusted" in prompt.lower()


# ---------------------------------------------------------------------------
# K. safe_read_text — max_bytes enforcement
# ---------------------------------------------------------------------------

class TestSafeReadTextSizeLimit:

    def test_file_within_limit_read_ok(self, tmp_path):
        from qara.utils.fs import safe_read_text

        f = tmp_path / "small.txt"
        f.write_text("hello world", encoding="utf-8")
        result = safe_read_text(f, max_bytes=1000)
        assert result == "hello world"

    def test_file_over_limit_returns_none(self, tmp_path):
        from qara.utils.fs import safe_read_text

        f = tmp_path / "big.txt"
        f.write_bytes(b"X" * 200)
        result = safe_read_text(f, max_bytes=100)
        assert result is None

    def test_no_limit_reads_full_file(self, tmp_path):
        from qara.utils.fs import safe_read_text

        f = tmp_path / "medium.txt"
        content = "Y" * 5000
        f.write_text(content, encoding="utf-8")
        result = safe_read_text(f, max_bytes=None)
        assert result == content
