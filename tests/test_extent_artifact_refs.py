"""Tests for ArtifactRef extraction in the Extent HTML parser.

Covers:
- Test-level detail refs (embedded base64 screenshots)
- Step-level refs promoted to test case (is_from_failed_step, step_name, sequence_no)
- Media file-path refs converted to ArtifactRef
- Sequence numbering order (test-level < step-level)
- text-only mode: refs found but no DB records

These tests use minimal synthesized Extent JSON payloads; no real HTML file is required.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from qara.parsers.extent import ExtentHtmlParser
from qara.models.artifact_ref import ArtifactRef

# ---------------------------------------------------------------------------
# Minimal PNG helper (copy from test_artifact_pipeline.py to keep tests self-contained)
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(name: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def _minimal_png(width: int = 1, height: int = 1) -> bytes:
    ihdr = struct.pack(">II", width, height) + bytes([8, 2, 0, 0, 0])
    raw_row = b"\x00" + b"\x00\x00\x00" * width
    compressed = zlib.compress(raw_row * height)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _data_uri(data: bytes = _minimal_png(), mime: str = "image/png") -> str:
    return f"data:{mime};base64,{_b64(data)}"


# ---------------------------------------------------------------------------
# Helpers for synthesising Extent testdata JSON
# ---------------------------------------------------------------------------

_PNG = _minimal_png()


def _make_detail_img(data: bytes = _PNG, mime: str = "image/png") -> dict:
    """Return an Extent detail dict of type 'img' with a base64 data URI."""
    return {"type": "img", "body": _data_uri(data, mime)}


def _make_test_node(
    name: str = "My Test",
    status: str = "fail",
    details: list | None = None,
    nodes: list | None = None,
    media: list | None = None,
) -> dict:
    return {
        "id": "1",
        "name": name,
        "status": status,
        "startTime": 1_700_000_000_000,
        "endTime": 1_700_000_001_000,
        "details": details or [],
        "nodes": nodes or [],
        "media": media or [],
    }


def _make_step_node(
    name: str = "Step 1",
    status: str = "fail",
    details: list | None = None,
) -> dict:
    return {
        "name": name,
        "status": status,
        "details": details or [],
        "nodes": [],
        "media": [],
    }


def _parse_node(parser: ExtentHtmlParser, node: dict, root: Path) -> "TestCaseResult":  # type: ignore[name-defined]
    from qara.parsers.extent import ExtentHtmlParser
    return parser._extract_test_case_from_node(node, root, "extent")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def parser() -> ExtentHtmlParser:
    return ExtentHtmlParser()


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# Test-level detail refs
# ---------------------------------------------------------------------------

class TestTestLevelDetailRefs:
    def test_single_base64_screenshot_in_detail(self, parser, tmp_root):
        node = _make_test_node(details=[_make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        assert len(tc.raw_artifact_refs) == 1
        ref = tc.raw_artifact_refs[0]
        assert ref.kind == "screenshot"
        assert ref.source_uri.startswith("data:image/png;base64,")

    def test_mime_type_extracted_from_data_uri(self, parser, tmp_root):
        node = _make_test_node(details=[_make_detail_img(mime="image/jpeg")])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].mime_type == "image/jpeg"

    def test_multiple_test_level_screenshots(self, parser, tmp_root):
        node = _make_test_node(details=[_make_detail_img(), _make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        assert len(tc.raw_artifact_refs) == 2

    def test_test_level_refs_start_at_seq_zero(self, parser, tmp_root):
        node = _make_test_node(details=[_make_detail_img(), _make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        seq_nos = [r.sequence_no for r in tc.raw_artifact_refs]
        assert seq_nos == [0, 1]

    def test_is_from_failed_step_set_for_failing_test(self, parser, tmp_root):
        node = _make_test_node(status="fail", details=[_make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].is_from_failed_step is True

    def test_is_from_failed_step_false_for_passing_test(self, parser, tmp_root):
        node = _make_test_node(status="pass", details=[_make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].is_from_failed_step is False

    def test_step_name_none_for_test_level_refs(self, parser, tmp_root):
        node = _make_test_node(details=[_make_detail_img()])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].step_name is None


# ---------------------------------------------------------------------------
# Step-level refs promotion
# ---------------------------------------------------------------------------

class TestStepLevelRefsPromotion:
    def test_step_screenshot_promoted_to_test(self, parser, tmp_root):
        step = _make_step_node(details=[_make_detail_img()])
        node = _make_test_node(nodes=[step])
        tc = _parse_node(parser, node, tmp_root)
        assert len(tc.raw_artifact_refs) == 1

    def test_failed_step_ref_has_is_from_failed_step_true(self, parser, tmp_root):
        step = _make_step_node(status="fail", details=[_make_detail_img()])
        node = _make_test_node(nodes=[step])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].is_from_failed_step is True

    def test_passing_step_ref_has_is_from_failed_step_false(self, parser, tmp_root):
        step = _make_step_node(status="pass", details=[_make_detail_img()])
        node = _make_test_node(nodes=[step])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].is_from_failed_step is False

    def test_step_name_set_on_step_level_refs(self, parser, tmp_root):
        step = _make_step_node(name="Login Step", details=[_make_detail_img()])
        node = _make_test_node(nodes=[step])
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs[0].step_name == "Login Step"

    def test_multiple_steps_all_refs_collected(self, parser, tmp_root):
        steps = [
            _make_step_node(name=f"Step {i}", details=[_make_detail_img()])
            for i in range(3)
        ]
        node = _make_test_node(nodes=steps)
        tc = _parse_node(parser, node, tmp_root)
        assert len(tc.raw_artifact_refs) == 3

    def test_step_level_refs_have_higher_seq_than_test_level(self, parser, tmp_root):
        """Step refs must have higher sequence_no than test-level refs."""
        test_detail = _make_detail_img()
        step = _make_step_node(details=[_make_detail_img()])
        node = _make_test_node(details=[test_detail], nodes=[step])
        tc = _parse_node(parser, node, tmp_root)
        # Should have 2 refs: test-level (seq=0), step-level (seq=1)
        assert len(tc.raw_artifact_refs) == 2
        test_ref = next(r for r in tc.raw_artifact_refs if r.step_name is None)
        step_ref = next(r for r in tc.raw_artifact_refs if r.step_name is not None)
        assert step_ref.sequence_no > test_ref.sequence_no

    def test_mixed_passing_failing_steps(self, parser, tmp_root):
        """is_from_failed_step is set correctly per-step regardless of test status."""
        passing_step = _make_step_node(name="Pass", status="pass", details=[_make_detail_img()])
        failing_step = _make_step_node(name="Fail", status="fail", details=[_make_detail_img()])
        node = _make_test_node(status="fail", nodes=[passing_step, failing_step])
        tc = _parse_node(parser, node, tmp_root)
        assert len(tc.raw_artifact_refs) == 2
        pass_ref = next(r for r in tc.raw_artifact_refs if r.step_name == "Pass")
        fail_ref = next(r for r in tc.raw_artifact_refs if r.step_name == "Fail")
        assert pass_ref.is_from_failed_step is False
        assert fail_ref.is_from_failed_step is True


# ---------------------------------------------------------------------------
# Media (file-path) refs
# ---------------------------------------------------------------------------

class TestMediaFilePathRefs:
    def test_existing_screenshot_file_becomes_ref(self, parser, tmp_path):
        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(_minimal_png())
        node = _make_test_node(
            status="fail",
            media=[{"path": "screenshot.png", "kind": "img"}],
        )
        tc = _parse_node(parser, node, tmp_path)
        media_refs = [r for r in tc.raw_artifact_refs if not r.source_uri.startswith("data:")]
        assert len(media_refs) == 1
        assert media_refs[0].kind == "screenshot"
        assert media_refs[0].source_uri.endswith("screenshot.png")

    def test_missing_media_file_silently_skipped(self, parser, tmp_root):
        node = _make_test_node(
            media=[{"path": "nonexistent.png", "kind": "img"}],
        )
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs == []

    def test_media_file_name_preserved(self, parser, tmp_path):
        img_file = tmp_path / "my_screenshot.png"
        img_file.write_bytes(_minimal_png())
        node = _make_test_node(
            media=[{"path": "my_screenshot.png", "kind": "img"}],
        )
        tc = _parse_node(parser, node, tmp_path)
        media_refs = [r for r in tc.raw_artifact_refs if r.name]
        assert any("my_screenshot.png" in (r.name or "") for r in media_refs)

    def test_media_data_uri_becomes_ref(self, parser, tmp_root):
        node = _make_test_node(
            media=[{"path": _data_uri(), "kind": "img"}],
        )
        tc = _parse_node(parser, node, tmp_root)
        data_refs = [r for r in tc.raw_artifact_refs if r.source_uri.startswith("data:")]
        assert len(data_refs) == 1

    def test_media_non_image_entry_skipped(self, parser, tmp_root):
        node = _make_test_node(
            media=[{"path": "logfile.txt", "kind": "txt"}],
        )
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs == []

    def test_media_refs_have_lower_seq_than_step_refs(self, parser, tmp_path):
        img_file = tmp_path / "shot.png"
        img_file.write_bytes(_minimal_png())
        step = _make_step_node(details=[_make_detail_img()])
        node = _make_test_node(
            media=[{"path": "shot.png", "kind": "img"}],
            nodes=[step],
        )
        tc = _parse_node(parser, node, tmp_path)
        assert len(tc.raw_artifact_refs) == 2
        media_ref = next(r for r in tc.raw_artifact_refs if not r.source_uri.startswith("data:"))
        step_ref = next(r for r in tc.raw_artifact_refs if r.step_name is not None)
        assert step_ref.sequence_no > media_ref.sequence_no


# ---------------------------------------------------------------------------
# No refs for passing tests with no screenshots
# ---------------------------------------------------------------------------

class TestNoRefs:
    def test_passing_test_no_screenshots_yields_empty_refs(self, parser, tmp_root):
        node = _make_test_node(status="pass")
        tc = _parse_node(parser, node, tmp_root)
        assert tc.raw_artifact_refs == []

    def test_failing_test_no_screenshots_yields_empty_refs(self, parser, tmp_root):
        node = _make_test_node(
            status="fail",
            details=[{"type": "fail", "body": "AssertionError: expected true"}],
        )
        tc = _parse_node(parser, node, tmp_root)
        # Only a "fail" detail, no "img" detail → no refs
        assert tc.raw_artifact_refs == []
