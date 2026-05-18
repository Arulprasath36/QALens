"""Image dimension parsing and optional compression.

Dimension parsing uses raw header inspection — no Pillow required.
Supports PNG, JPEG (JFIF/Exif), and WebP.

Compression uses Pillow when available.  If Pillow is not installed, or if
any error occurs during processing, the original bytes are returned unchanged
and a DEBUG-level log message is emitted.  Ingestion never fails because of
image processing problems.
"""

from __future__ import annotations

import logging
import struct

logger = logging.getLogger(__name__)

# Optional Pillow import — not a hard dependency
try:
    from PIL import Image as _PILImage  # type: ignore[import-untyped]

    _PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PILLOW_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return ``(width, height)`` from image header bytes without Pillow.

    Inspects the first few hundred bytes only.  Supports PNG, JPEG, and WebP.

    Args:
        data: Raw image bytes (the first 32+ bytes is usually sufficient).

    Returns:
        ``(width, height)`` tuple, or ``None`` if the format is unrecognised
        or the header cannot be parsed.
    """
    try:
        if _is_png(data):
            return _png_dimensions(data)
        if _is_jpeg(data):
            return _jpeg_dimensions(data)
        if _is_webp(data):
            return _webp_dimensions(data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse image dimensions: %s", exc)
    return None


def compress_image(
    data: bytes,
    mime_type: str,
    *,
    max_width: int = 1600,
    jpeg_quality: int = 80,
) -> tuple[bytes, str]:
    """Optionally resize and re-encode *data* if Pillow is available.

    Rules applied in order:

    1. **Resize**: if ``image.width > max_width``, scale down preserving
       aspect ratio.  Never upscale.
    2. **Re-encode**: JPEG/WebP are saved at *jpeg_quality*.  PNG is
       losslessly re-encoded (``optimize=True``).
    3. **Size guard**: if the output is larger than the input, the original
       bytes are returned unchanged.

    If Pillow is not installed or any exception occurs, the original bytes
    and MIME type are returned unchanged.

    Args:
        data: Raw image bytes.
        mime_type: MIME type of the input (e.g. ``"image/png"``).
        max_width: Maximum output width in pixels.
        jpeg_quality: JPEG/WebP quality setting (1–95).

    Returns:
        ``(output_bytes, output_mime_type)`` — may be the originals if
        compression was skipped or failed.
    """
    if not _PILLOW_AVAILABLE:
        return data, mime_type

    try:
        import io

        from PIL import Image  # type: ignore[import-untyped]

        img = Image.open(io.BytesIO(data))

        resized = False
        if img.width > max_width:
            new_h = max(1, round(img.height * max_width / img.width))
            img = img.resize((max_width, new_h), Image.LANCZOS)  # type: ignore[attr-defined]
            resized = True

        # For non-PNG formats that weren't resized, skip re-encoding to avoid
        # lossy artefact amplification on already-compressed images.
        if not resized and mime_type != "image/png":
            return data, mime_type

        out = io.BytesIO()
        if mime_type in ("image/jpeg",):
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
            out_mime = "image/jpeg"
        elif mime_type == "image/webp":
            if img.mode in ("P", "LA"):
                img = img.convert("RGBA")
            img.save(out, format="WEBP", quality=jpeg_quality, method=4)
            out_mime = "image/webp"
        else:
            # PNG (or unknown) — keep as PNG losslessly
            img.save(out, format="PNG", optimize=True)
            out_mime = "image/png"

        compressed = out.getvalue()
        if len(compressed) >= len(data):
            # Re-encoding made it bigger — return the original
            return data, mime_type

        return compressed, out_mime

    except Exception as exc:  # noqa: BLE001
        logger.debug("Image compression failed, using original: %s", exc)
        return data, mime_type


# ---------------------------------------------------------------------------
# Header-inspection helpers (no external dependencies)
# ---------------------------------------------------------------------------


def _is_png(data: bytes) -> bool:
    return len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n"


def _is_jpeg(data: bytes) -> bool:
    return len(data) >= 2 and data[:2] == b"\xff\xd8"


def _is_webp(data: bytes) -> bool:
    return (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse PNG IHDR chunk for width × height."""
    # Layout: 8-byte signature + 4 (chunk length) + 4 (IHDR) + 4 (w) + 4 (h)
    if len(data) < 24:
        return None
    w = struct.unpack(">I", data[16:20])[0]
    h = struct.unpack(">I", data[20:24])[0]
    return (w, h) if w > 0 and h > 0 else None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Scan JPEG markers for SOF0/SOF1/SOF2 to retrieve frame dimensions."""
    i = 2  # skip initial FF D8
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        # SOF0=0xC0, SOF1=0xC1, SOF2=0xC2 (baseline + progressive)
        if marker in (0xC0, 0xC1, 0xC2):
            if i + 9 <= len(data):
                h = struct.unpack(">H", data[i + 5 : i + 7])[0]
                w = struct.unpack(">H", data[i + 7 : i + 9])[0]
                return (w, h) if w > 0 and h > 0 else None
            break
        if marker == 0xD9:  # EOI — end of image
            break
        if i + 4 > len(data):
            break
        segment_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + segment_len
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse WebP VP8 / VP8L / VP8X chunk headers for frame dimensions."""
    if len(data) < 30:
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        # Lossy: bitstream frame tag at offset 23
        if len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            return (w, h) if w > 0 and h > 0 else None
    elif chunk == b"VP8L":
        # Lossless: signature byte 0x2F at offset 20
        if len(data) >= 25 and data[20] == 0x2F:
            bits = struct.unpack("<I", data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return (w, h) if w > 0 and h > 0 else None
    elif chunk == b"VP8X":
        # Extended: 24-bit width/height starting at offset 24
        if len(data) >= 30:
            w = (struct.unpack("<I", data[24:27] + b"\x00")[0] & 0xFFFFFF) + 1
            h = (struct.unpack("<I", data[27:30] + b"\x00")[0] & 0xFFFFFF) + 1
            return (w, h) if w > 0 and h > 0 else None
    return None
