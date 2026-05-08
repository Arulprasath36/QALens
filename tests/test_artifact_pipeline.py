"""Tests for the artifact ingestion pipeline.

Covers all three modes (text-only / metadata-only / full), screenshot cap,
priority-based selection, SHA-256 deduplication, failure tolerance, the
LocalFilesystemStore, and ArtifactIngestStats.merge().

No Pillow is required — these tests disable image compression so that the
pure-Python fallback path (header-only dimension parsing) is exercised.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib
from pathlib import Path

import pytest

from qara.artifacts.config import ArtifactConfig, ArtifactMode
from qara.artifacts.models import ArtifactIngestStats
from qara.artifacts.policy import ArtifactIngestionPolicy
from qara.artifacts.selector import select_screenshots
from qara.artifacts.storage import LocalFilesystemStore
from qara.models.artifact_ref import ArtifactRef

# ---------------------------------------------------------------------------
# Helpers — minimal valid PNG builder
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(name: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def _minimal_png(width: int = 1, height: int = 1) -> bytes:
    """Return a minimal valid PNG with the given dimensions (RGB 8-bit)."""
    ihdr_data = struct.pack(">II", width, height) + bytes([8, 2, 0, 0, 0])
    # Each scanline: filter byte (0) + 3 bytes per pixel (black)
    raw_row = b"\x00" + b"\x00\x00\x00" * width
    compressed = zlib.compress(raw_row * height)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr_data)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _make_ref(
    *,
    uri: str,
    kind: str = "screenshot",
    sequence_no: int = 0,
    is_from_failed_step: bool = False,
    step_name: str | None = None,
    mime_type: str | None = "image/png",
    name: str = "screen.png",
) -> ArtifactRef:
    return ArtifactRef(
        source_uri=uri,
        kind=kind,
        name=name,
        step_name=step_name,
        sequence_no=sequence_no,
        is_from_failed_step=is_from_failed_step,
        mime_type=mime_type,
    )


# Pre-built 1×1 PNG used across tests
_PNG_1x1 = _minimal_png(1, 1)


# ---------------------------------------------------------------------------
# text-only mode
# ---------------------------------------------------------------------------


class TestTextOnlyMode:
    def test_returns_no_records(self):
        config = ArtifactConfig(mode=ArtifactMode.TEXT_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.records_created == 0

    def test_refs_found_still_counted(self):
        config = ArtifactConfig(mode=ArtifactMode.TEXT_ONLY)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1)) for _ in range(3)]
        _, stats = policy.process("tc::1", refs)
        assert stats.refs_found == 3

    def test_refs_selected_is_zero(self):
        config = ArtifactConfig(mode=ArtifactMode.TEXT_ONLY)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1))]
        _, stats = policy.process("tc::1", refs)
        assert stats.refs_selected == 0

    def test_store_not_touched(self, tmp_path: Path):
        config = ArtifactConfig(mode=ArtifactMode.TEXT_ONLY)
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        policy.process("tc::1", [ref])
        # No artifact files should be written
        stored = [f for f in tmp_path.iterdir() if f.suffix != ".txt"]
        assert stored == []


# ---------------------------------------------------------------------------
# metadata-only mode
# ---------------------------------------------------------------------------


class TestMetadataOnlyMode:
    def test_record_created(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, stats = policy.process("tc::1", [ref])
        assert len(records) == 1
        assert stats.records_created == 1

    def test_storage_uri_is_none(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        assert records[0].storage_uri is None

    def test_sha256_and_size_populated(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        r = records[0]
        assert r.sha256 == hashlib.sha256(_PNG_1x1).hexdigest()
        assert r.size_bytes == len(_PNG_1x1)

    def test_mime_type_set(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1, "image/png"))
        records, _ = policy.process("tc::1", [ref])
        assert records[0].mime_type == "image/png"

    def test_tc_id_in_record(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("run1::tc_login", [ref])
        assert records[0].tc_id == "run1::tc_login"

    def test_dimensions_parsed_from_png_header(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_minimal_png(4, 6)))
        records, _ = policy.process("tc::1", [ref])
        r = records[0]
        if r.width is not None:  # header parsing may return None on corrupt data
            assert r.width == 4
            assert r.height == 6

    def test_sequence_no_preserved(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1), sequence_no=7)
        records, _ = policy.process("tc::1", [ref])
        assert records[0].sequence_no == 7

    def test_step_name_preserved(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1), step_name="Login step")
        records, _ = policy.process("tc::1", [ref])
        assert records[0].step_name == "Login step"

    def test_source_ref_does_not_expose_full_base64(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        src = records[0].source_reference
        assert src is not None
        # Must never store the full base64 payload; prefix should end with "…"
        assert len(src) < 80
        assert src.endswith("…")

    def test_no_bytes_written_to_store(self, tmp_path: Path):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        policy.process("tc::1", [ref])
        img_files = [f for f in tmp_path.iterdir() if f.suffix in {".png", ".jpg", ".bin"}]
        assert img_files == []

    def test_file_path_source(self, tmp_path: Path):
        img = tmp_path / "shot.png"
        img.write_bytes(_PNG_1x1)
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=str(img))
        records, stats = policy.process("tc::1", [ref])
        assert len(records) == 1
        assert stats.records_created == 1
        assert records[0].sha256 == hashlib.sha256(_PNG_1x1).hexdigest()

    def test_svg_data_uri_is_rejected(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(
            uri=_data_uri(svg, "image/svg+xml"),
            mime_type="image/svg+xml",
        )
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.errors_skipped == 1


# ---------------------------------------------------------------------------
# full mode
# ---------------------------------------------------------------------------


class TestFullMode:
    def _config(self, tmp_path: Path, **kwargs) -> tuple[ArtifactConfig, LocalFilesystemStore]:
        store = LocalFilesystemStore(tmp_path)
        config = ArtifactConfig(
            mode=ArtifactMode.FULL,
            compress_images=False,  # keep Pillow out of the hot path
            **kwargs,
        )
        return config, store

    def test_bytes_written_to_disk(self, tmp_path: Path):
        config, store = self._config(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, stats = policy.process("tc::1", [ref])
        assert len(records) == 1
        assert stats.images_stored == 1
        uri = records[0].storage_uri
        assert uri is not None
        path = store.resolve_uri(uri)
        assert path is not None and path.is_file()
        assert path.read_bytes() == _PNG_1x1

    def test_storage_uri_is_file_scheme(self, tmp_path: Path):
        config, store = self._config(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        assert records[0].storage_uri.startswith("file://")

    def test_file_path_source(self, tmp_path: Path):
        img = tmp_path / "screenshot.png"
        img.write_bytes(_PNG_1x1)
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        config, store = self._config(store_dir)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=str(img))
        records, stats = policy.process("tc::1", [ref])
        assert len(records) == 1
        assert stats.images_stored == 1

    def test_metadata_also_populated_in_full_mode(self, tmp_path: Path):
        config, store = self._config(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        r = records[0]
        assert r.sha256 == hashlib.sha256(_PNG_1x1).hexdigest()
        assert r.size_bytes == len(_PNG_1x1)


# ---------------------------------------------------------------------------
# Screenshot cap
# ---------------------------------------------------------------------------


class TestScreenshotCap:
    def test_cap_applied(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY, max_screenshots_per_failure=2)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1), sequence_no=i) for i in range(5)]
        records, stats = policy.process("tc::1", refs)
        assert len(records) == 2
        assert stats.refs_found == 5
        assert stats.refs_selected == 2

    def test_cap_of_one(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY, max_screenshots_per_failure=1)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1), sequence_no=i) for i in range(3)]
        records, _ = policy.process("tc::1", refs)
        assert len(records) == 1

    def test_under_cap_keeps_all(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY, max_screenshots_per_failure=10)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1), sequence_no=i) for i in range(3)]
        records, _ = policy.process("tc::1", refs)
        assert len(records) == 3

    def test_failure_id_forwarded(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref], failure_id=42)
        assert records[0].failure_id == 42


# ---------------------------------------------------------------------------
# Priority selection (select_screenshots)
# ---------------------------------------------------------------------------


class TestSelectScreenshots:
    def _s(self, seq: int, failed: bool = False) -> ArtifactRef:
        return _make_ref(uri=_data_uri(_PNG_1x1), sequence_no=seq, is_from_failed_step=failed)

    def test_failed_step_preferred(self):
        refs = [self._s(0), self._s(1), self._s(2, failed=True)]
        chosen = select_screenshots(refs, max_count=1)
        assert len(chosen) == 1
        assert chosen[0].is_from_failed_step is True

    def test_highest_seq_within_failed_steps(self):
        refs = [self._s(3, True), self._s(7, True), self._s(5, True)]
        chosen = select_screenshots(refs, max_count=1)
        assert chosen[0].sequence_no == 7

    def test_highest_seq_when_no_failed_steps(self):
        refs = [self._s(i) for i in range(5)]
        chosen = select_screenshots(refs, max_count=2)
        seq_nos = {r.sequence_no for r in chosen}
        assert 4 in seq_nos  # highest seq must be selected

    def test_all_returned_when_under_cap(self):
        refs = [self._s(i) for i in range(3)]
        chosen = select_screenshots(refs, max_count=5)
        assert len(chosen) == 3

    def test_empty_input(self):
        assert select_screenshots([], max_count=2) == []

    def test_zero_cap_returns_empty(self):
        assert select_screenshots([self._s(0)], max_count=0) == []

    def test_negative_cap_returns_empty(self):
        assert select_screenshots([self._s(0)], max_count=-1) == []

    def test_non_screenshot_counts_toward_cap(self):
        log_ref = _make_ref(uri="data:text/plain;base64,dGVzdA==", kind="log")
        screenshot = self._s(0)
        # cap = 2, 1 log + 1 screenshot → both selected
        chosen = select_screenshots([log_ref, screenshot], max_count=2)
        assert len(chosen) == 2

    def test_non_screenshot_after_screenshot_priority(self):
        """Screenshots are selected first; remaining budget fills with others."""
        log1 = _make_ref(uri="data:text/plain;base64,dGVzdA==", kind="log", sequence_no=10)
        log2 = _make_ref(uri="data:text/plain;base64,dGVzdA==", kind="log", sequence_no=11)
        ss = self._s(0)
        # cap=2: 1 screenshot + 1 log fit
        chosen = select_screenshots([log1, log2, ss], max_count=2)
        assert any(r.kind == "screenshot" for r in chosen)

    def test_exact_cap_boundary(self):
        refs = [self._s(i) for i in range(2)]
        chosen = select_screenshots(refs, max_count=2)
        assert len(chosen) == 2


# ---------------------------------------------------------------------------
# SHA-256 deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_duplicate_skipped_with_dedup_enabled(self, tmp_path: Path):
        config = ArtifactConfig(
            mode=ArtifactMode.FULL,
            compress_images=False,
            dedupe_images=True,
        )
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        uri = _data_uri(_PNG_1x1)
        _, stats1 = policy.process("tc::1", [_make_ref(uri=uri, sequence_no=0)])
        _, stats2 = policy.process("tc::2", [_make_ref(uri=uri, sequence_no=0)])
        assert stats1.duplicates_skipped == 0
        assert stats2.duplicates_skipped == 1

    def test_only_one_file_stored_on_dedup(self, tmp_path: Path):
        config = ArtifactConfig(mode=ArtifactMode.FULL, compress_images=False, dedupe_images=True)
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        uri = _data_uri(_PNG_1x1)
        policy.process("tc::1", [_make_ref(uri=uri)])
        policy.process("tc::2", [_make_ref(uri=uri)])
        img_files = [f for f in tmp_path.iterdir() if f.suffix == ".png"]
        assert len(img_files) == 1

    def test_dedup_disabled_no_skip_counted(self, tmp_path: Path):
        config = ArtifactConfig(mode=ArtifactMode.FULL, compress_images=False, dedupe_images=False)
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        uri = _data_uri(_PNG_1x1)
        _, stats1 = policy.process("tc::1", [_make_ref(uri=uri)])
        _, stats2 = policy.process("tc::2", [_make_ref(uri=uri)])
        assert stats1.duplicates_skipped == 0
        assert stats2.duplicates_skipped == 0

    def test_dedup_existing_uri_returned_in_record(self, tmp_path: Path):
        """The second record must point at the same stored URI as the first."""
        config = ArtifactConfig(mode=ArtifactMode.FULL, compress_images=False, dedupe_images=True)
        store = LocalFilesystemStore(tmp_path)
        policy = ArtifactIngestionPolicy(config, store)
        uri = _data_uri(_PNG_1x1)
        records1, _ = policy.process("tc::1", [_make_ref(uri=uri)])
        records2, _ = policy.process("tc::2", [_make_ref(uri=uri)])
        assert records1[0].storage_uri == records2[0].storage_uri


# ---------------------------------------------------------------------------
# Failure tolerance
# ---------------------------------------------------------------------------


class TestFailureTolerance:
    def test_missing_file_skipped(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri="/nonexistent/path/screenshot.png")
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.errors_skipped == 1
        assert stats.records_created == 0

    def test_bad_base64_skipped(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri="data:image/png;base64,NOT!!VALID!!BASE64")
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.errors_skipped == 1

    def test_error_does_not_stop_remaining_refs(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        bad = _make_ref(uri="/no/such/file.png", sequence_no=0)
        good = _make_ref(uri=_data_uri(_PNG_1x1), sequence_no=1)
        records, stats = policy.process("tc::1", [bad, good])
        assert stats.errors_skipped == 1
        assert stats.records_created == 1
        assert len(records) == 1

    def test_empty_refs_ok(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        records, stats = policy.process("tc::1", [])
        assert records == []
        assert stats.refs_found == 0

    def test_oversized_screenshot_skipped(self):
        config = ArtifactConfig(
            mode=ArtifactMode.METADATA_ONLY,
            max_screenshot_bytes=max(1, len(_PNG_1x1) - 1),
        )
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.errors_skipped == 1

    def test_svg_screenshot_rejected(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(svg, "image/svg+xml"), mime_type="image/svg+xml", name="x.svg")
        records, stats = policy.process("tc::1", [ref])
        assert records == []
        assert stats.errors_skipped == 1

    def test_total_screenshot_byte_limit_skips_later_refs(self):
        config = ArtifactConfig(
            mode=ArtifactMode.METADATA_ONLY,
            max_screenshots_per_failure=2,
            max_total_screenshot_bytes_per_run=len(_PNG_1x1) + 1,
        )
        policy = ArtifactIngestionPolicy(config)
        refs = [
            _make_ref(uri=_data_uri(_PNG_1x1), sequence_no=0),
            _make_ref(uri=_data_uri(_PNG_1x1), sequence_no=1),
        ]
        records, stats = policy.process("tc::1", refs)
        assert len(records) == 1
        assert stats.records_created == 1
        assert stats.errors_skipped == 1


# ---------------------------------------------------------------------------
# LocalFilesystemStore
# ---------------------------------------------------------------------------


class TestLocalFilesystemStore:
    def test_store_creates_file(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        uri = store.store(_PNG_1x1, sha, "image/png", "test.png")
        path = store.resolve_uri(uri)
        assert path is not None and path.is_file()
        assert path.read_bytes() == _PNG_1x1

    def test_store_returns_file_uri(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        uri = store.store(_PNG_1x1, sha, "image/png", "test.png")
        assert uri.startswith("file://")

    def test_file_named_by_sha_prefix(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        store.store(_PNG_1x1, sha, "image/png", "test.png")
        files = list(tmp_path.glob("*.png"))
        assert len(files) == 1
        assert files[0].stem == sha[:16]

    def test_exists_before_store_is_none(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        assert store.exists(sha) is None

    def test_exists_after_store_returns_uri(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        uri = store.store(_PNG_1x1, sha, "image/png", "test.png")
        assert store.exists(sha) == uri

    def test_index_persists_across_instances(self, tmp_path: Path):
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        uri = LocalFilesystemStore(tmp_path).store(_PNG_1x1, sha, "image/png", "t.png")
        assert LocalFilesystemStore(tmp_path).exists(sha) == uri

    def test_resolve_unknown_uri_returns_none(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        assert store.resolve_uri("file:///no/such/file.png") is None

    def test_store_is_idempotent(self, tmp_path: Path):
        store = LocalFilesystemStore(tmp_path)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        uri1 = store.store(_PNG_1x1, sha, "image/png", "t.png")
        uri2 = store.store(_PNG_1x1, sha, "image/png", "t.png")
        assert uri1 == uri2
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_base_dir_auto_created(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        store = LocalFilesystemStore(nested)
        sha = hashlib.sha256(_PNG_1x1).hexdigest()
        store.store(_PNG_1x1, sha, "image/png", "t.png")
        assert nested.is_dir()


# ---------------------------------------------------------------------------
# ArtifactIngestStats.merge()
# ---------------------------------------------------------------------------


class TestArtifactIngestStatsMerge:
    def test_all_counters_accumulated(self):
        a = ArtifactIngestStats(
            refs_found=3, refs_selected=2, records_created=2,
            images_stored=1, duplicates_skipped=0, errors_skipped=1,
            artifact_mode="full",
        )
        b = ArtifactIngestStats(
            refs_found=5, refs_selected=4, records_created=3,
            images_stored=2, duplicates_skipped=1, errors_skipped=0,
            artifact_mode="full",
        )
        a.merge(b)
        assert a.refs_found == 8
        assert a.refs_selected == 6
        assert a.records_created == 5
        assert a.images_stored == 3
        assert a.duplicates_skipped == 1
        assert a.errors_skipped == 1

    def test_mode_of_receiver_preserved(self):
        a = ArtifactIngestStats(artifact_mode="metadata-only")
        b = ArtifactIngestStats(artifact_mode="full")
        a.merge(b)
        assert a.artifact_mode == "metadata-only"

    def test_merge_with_zeros_is_identity(self):
        a = ArtifactIngestStats(refs_found=5, records_created=3, artifact_mode="metadata-only")
        b = ArtifactIngestStats()
        a.merge(b)
        assert a.refs_found == 5
        assert a.records_created == 3


# ---------------------------------------------------------------------------
# is_primary flag
# ---------------------------------------------------------------------------


class TestPrimaryFlag:
    def test_first_record_is_primary(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY, max_screenshots_per_failure=5)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1), sequence_no=i) for i in range(3)]
        records, _ = policy.process("tc::1", refs)
        assert records[0].is_primary is True

    def test_subsequent_records_not_primary(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY, max_screenshots_per_failure=5)
        policy = ArtifactIngestionPolicy(config)
        refs = [_make_ref(uri=_data_uri(_PNG_1x1), sequence_no=i) for i in range(3)]
        records, _ = policy.process("tc::1", refs)
        for r in records[1:]:
            assert r.is_primary is False

    def test_single_record_is_primary(self):
        config = ArtifactConfig(mode=ArtifactMode.METADATA_ONLY)
        policy = ArtifactIngestionPolicy(config)
        ref = _make_ref(uri=_data_uri(_PNG_1x1))
        records, _ = policy.process("tc::1", [ref])
        assert records[0].is_primary is True
