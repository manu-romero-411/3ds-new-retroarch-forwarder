"""Minimal PNG encoder built on the standard library only.

``tools/`` deliberately avoids third-party dependencies (the Docker image
ships none for it), so anything that needs to emit a PNG -- placeholder
assets, icons/banners decoded out of an existing CIA -- goes through here
instead of pulling in Pillow.
"""

from __future__ import annotations

import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOR_TYPE_RGB = 2
_COLOR_TYPE_RGBA = 6


def _chunk(tag: bytes, data: bytes) -> bytes:
    """Serialize one PNG chunk (length, tag, data, CRC)."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes, has_alpha: bool = False) -> bytes:
    """Encode raw 8-bit pixels as a PNG.

    ``pixels`` is row-major, top row first, three bytes per pixel (RGB) or
    four (RGBA) when ``has_alpha`` is set. Raises ``ValueError`` if its
    length does not match ``width`` x ``height``.
    """
    channels = 4 if has_alpha else 3
    stride = width * channels
    if len(pixels) != stride * height:
        raise ValueError(
            f"expected {stride * height} bytes of pixel data for a "
            f"{width}x{height} image, got {len(pixels)}"
        )

    color_type = _COLOR_TYPE_RGBA if has_alpha else _COLOR_TYPE_RGB
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    # Every scanline is prefixed with filter type 0 ("None").
    raw = b"".join(
        b"\x00" + pixels[row * stride : (row + 1) * stride] for row in range(height)
    )
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
