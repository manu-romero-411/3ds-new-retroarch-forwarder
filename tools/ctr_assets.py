"""Decoders for the icon, banner and jingle formats stored inside a 3DS CIA.

This is the inverse of what ``bannertool`` writes (see ``build_forwarder.py``
and ``media_prep.py``): given the raw ``icon`` (SMDH) and ``banner`` (CBMD)
files found in a CIA's ExeFS, recover the names, a PNG of the icon, a PNG of
the banner and a WAV of the banner jingle.

Only the layouts ``bannertool`` produces are understood: a 48x48 RGB565
icon, a single LZ11-compressed CGFX holding one 256x128 RGBA4444 texture,
and an uncompressed PCM CWAV. Anything else (e.g. an ETC1 banner from an
official title) raises :class:`AssetDecodeError` instead of being guessed at.
Standard library only, like the rest of ``tools/``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from tools.media_prep import BANNER_HEIGHT, BANNER_WIDTH, ICON_HEIGHT, ICON_WIDTH
from tools.png_codec import encode_png


class AssetDecodeError(ValueError):
    """An icon/banner/audio blob is malformed or uses an unsupported layout."""


# ── SMDH (icon + names) ──────────────────────────────────────────────────

SMDH_MAGIC = b"SMDH"
SMDH_TITLES_OFFSET = 0x08
SMDH_TITLE_SIZE = 0x200
SMDH_SHORT_NAME_SIZE = 0x80
SMDH_LONG_NAME_SIZE = 0x100
SMDH_LANGUAGE_COUNT = 16
SMDH_ENGLISH_SLOT = 1
SMDH_LARGE_ICON_OFFSET = 0x24C0
SMDH_SIZE = 0x36C0

# ── CBMD banner container ────────────────────────────────────────────────

CBMD_MAGIC = b"CBMD"
CBMD_CGFX_TABLE_OFFSET = 0x08
CBMD_CGFX_COUNT = 14
CBMD_CWAV_OFFSET_FIELD = 0x84
CBMD_HEADER_SIZE = 0x88

# bannertool prepends a fixed-size CGFX header to the raw texture data.
BANNERTOOL_CGFX_HEADER_SIZE = 0x1580
CGFX_MAGIC = b"CGFX"

# ── CWAV audio ───────────────────────────────────────────────────────────

CWAV_MAGIC = b"CWAV"
CWAV_LITTLE_ENDIAN = 0xFEFF
CWAV_ENCODING_PCM8 = 0
CWAV_ENCODING_PCM16 = 1

# The GPU stores textures in 8x8 tiles, Morton-ordered inside each tile.
_TILE_SIZE = 8


def _morton_index(x: int, y: int) -> int:
    """Position of pixel ``(x, y)`` inside its 8x8 tile (Z-order curve)."""
    return (
        (x & 1)
        | ((y & 1) << 1)
        | ((x & 2) << 1)
        | ((y & 2) << 2)
        | ((x & 4) << 2)
        | ((y & 4) << 3)
    )


_TILE_LOOKUP = [_morton_index(x, y) for y in range(_TILE_SIZE) for x in range(_TILE_SIZE)]
_EXPAND_5_BITS = [(value << 3) | (value >> 2) for value in range(32)]
_EXPAND_6_BITS = [(value << 2) | (value >> 4) for value in range(64)]


@dataclass(frozen=True)
class SmdhInfo:
    """What the SMDH holds that a forwarder cares about."""

    short_name: str
    long_name: str
    publisher: str
    icon_png: bytes


def lz11_decompress(data: bytes) -> bytes:
    """Decompress an LZ11 stream (the compression CGFX banners use)."""
    if len(data) < 4 or data[0] != 0x11:
        raise AssetDecodeError("Not an LZ11 stream.")
    size = int.from_bytes(data[1:4], "little")
    pos = 4
    if size == 0:
        size = int.from_bytes(data[4:8], "little")
        pos = 8

    out = bytearray()
    try:
        while len(out) < size:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if len(out) >= size:
                    break
                if not flags & (0x80 >> bit):
                    out.append(data[pos])
                    pos += 1
                    continue
                first = data[pos]
                indicator = first >> 4
                if indicator == 0:
                    length = (((first & 0xF) << 4) | (data[pos + 1] >> 4)) + 0x11
                    distance = (((data[pos + 1] & 0xF) << 8) | data[pos + 2]) + 1
                    pos += 3
                elif indicator == 1:
                    length = (
                        ((first & 0xF) << 12) | (data[pos + 1] << 4) | (data[pos + 2] >> 4)
                    ) + 0x111
                    distance = (((data[pos + 2] & 0xF) << 8) | data[pos + 3]) + 1
                    pos += 4
                else:
                    length = indicator + 1
                    distance = (((first & 0xF) << 8) | data[pos + 1]) + 1
                    pos += 2
                if distance > len(out):
                    raise AssetDecodeError("Corrupt LZ11 stream (bad back-reference).")
                for _ in range(length):  # byte by byte: the ranges may overlap
                    out.append(out[-distance])
    except IndexError as exc:
        raise AssetDecodeError("Truncated LZ11 stream.") from exc
    return bytes(out[:size])


def _untile(data: bytes, width: int, height: int) -> list[int]:
    """Read ``width``x``height`` tiled 16-bit texels back into raster order."""
    count = width * height
    if len(data) < count * 2:
        raise AssetDecodeError("Texture data is shorter than its dimensions imply.")
    texels = struct.unpack_from(f"<{count}H", data)
    tiles_per_row = width // _TILE_SIZE
    raster = [0] * count
    for y in range(height):
        tile_row = (y // _TILE_SIZE) * tiles_per_row
        lookup_row = (y % _TILE_SIZE) * _TILE_SIZE
        for x in range(width):
            tile = tile_row + x // _TILE_SIZE
            raster[y * width + x] = texels[
                (tile << 6) + _TILE_LOOKUP[lookup_row + x % _TILE_SIZE]
            ]
    return raster


def _rgb565_png(data: bytes, width: int, height: int) -> bytes:
    """Decode a tiled RGB565 texture into a PNG."""
    pixels = bytearray()
    for texel in _untile(data, width, height):
        pixels.append(_EXPAND_5_BITS[texel >> 11])
        pixels.append(_EXPAND_6_BITS[(texel >> 5) & 0x3F])
        pixels.append(_EXPAND_5_BITS[texel & 0x1F])
    return encode_png(width, height, bytes(pixels))


def _rgba4444_png(data: bytes, width: int, height: int) -> bytes:
    """Decode a tiled RGBA4444 texture into a PNG."""
    pixels = bytearray()
    for texel in _untile(data, width, height):
        pixels.append(((texel >> 12) & 0xF) * 0x11)
        pixels.append(((texel >> 8) & 0xF) * 0x11)
        pixels.append(((texel >> 4) & 0xF) * 0x11)
        pixels.append((texel & 0xF) * 0x11)
    return encode_png(width, height, bytes(pixels), has_alpha=True)


def _decode_utf16(raw: bytes) -> str:
    """Decode a NUL-terminated UTF-16LE field."""
    return raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0]


def parse_smdh(data: bytes) -> SmdhInfo:
    """Extract names and the 48x48 icon from an SMDH (``icon`` file in ExeFS).

    ``bannertool`` writes the same names into every language slot; the
    English one is preferred and the first non-empty slot is the fallback.
    """
    if len(data) < SMDH_SIZE or data[:4] != SMDH_MAGIC:
        raise AssetDecodeError("Not a valid SMDH.")

    slots = []
    for index in range(SMDH_LANGUAGE_COUNT):
        base = SMDH_TITLES_OFFSET + index * SMDH_TITLE_SIZE
        short = _decode_utf16(data[base : base + SMDH_SHORT_NAME_SIZE])
        long = _decode_utf16(
            data[base + SMDH_SHORT_NAME_SIZE : base + SMDH_SHORT_NAME_SIZE + SMDH_LONG_NAME_SIZE]
        )
        publisher = _decode_utf16(
            data[base + SMDH_SHORT_NAME_SIZE + SMDH_LONG_NAME_SIZE : base + SMDH_TITLE_SIZE]
        )
        slots.append((short, long, publisher))

    english = slots[SMDH_ENGLISH_SLOT]
    short_name, long_name, publisher = (
        english if any(english) else next((slot for slot in slots if any(slot)), english)
    )
    icon_png = _rgb565_png(data[SMDH_LARGE_ICON_OFFSET:SMDH_SIZE], ICON_WIDTH, ICON_HEIGHT)
    return SmdhInfo(short_name, long_name, publisher, icon_png)


def decode_banner_image(bnr: bytes) -> bytes:
    """Decode the banner texture of a ``bannertool``-built BNR into a PNG."""
    if len(bnr) < CBMD_HEADER_SIZE or bnr[:4] != CBMD_MAGIC:
        raise AssetDecodeError("Not a valid banner (missing CBMD header).")

    offsets = struct.unpack_from(f"<{CBMD_CGFX_COUNT}I", bnr, CBMD_CGFX_TABLE_OFFSET)
    cgfx_offset = next((offset for offset in offsets if offset), 0)
    if not cgfx_offset:
        raise AssetDecodeError("The banner contains no image.")

    cgfx = lz11_decompress(bnr[cgfx_offset:])
    texture_size = BANNER_WIDTH * BANNER_HEIGHT * 2
    if cgfx[:4] != CGFX_MAGIC or len(cgfx) != BANNERTOOL_CGFX_HEADER_SIZE + texture_size:
        raise AssetDecodeError(
            "The banner image layout is not the one bannertool writes "
            "(256x128 RGBA4444); it cannot be decoded."
        )
    return _rgba4444_png(cgfx[BANNERTOOL_CGFX_HEADER_SIZE:], BANNER_WIDTH, BANNER_HEIGHT)


def _wav_file(sample_rate: int, channels: int, pcm16: bytes) -> bytes:
    """Wrap interleaved 16-bit PCM samples in a canonical WAV container."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm16),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        sample_rate * channels * 2,
        channels * 2,
        16,
        b"data",
        len(pcm16),
    )
    return header + pcm16


def _cwav_to_wav(cwav: bytes) -> bytes:
    """Convert an uncompressed-PCM CWAV into a 16-bit WAV file."""
    if len(cwav) < 0x2C or cwav[:4] != CWAV_MAGIC:
        raise AssetDecodeError("Not a valid CWAV.")
    if struct.unpack_from("<H", cwav, 4)[0] != CWAV_LITTLE_ENDIAN:
        raise AssetDecodeError("Big-endian CWAV is not supported.")

    info_offset = struct.unpack_from("<I", cwav, 0x18)[0]
    data_offset, data_size = struct.unpack_from("<II", cwav, 0x24)
    try:
        encoding = cwav[info_offset + 8]
        sample_rate, _loop_start, loop_end = struct.unpack_from("<III", cwav, info_offset + 0xC)
        table = info_offset + 0x1C  # channel reference table; offsets are relative to it
        channels = struct.unpack_from("<I", cwav, table)[0]
        starts = []
        for channel in range(channels):
            info_ref = struct.unpack_from("<I", cwav, table + 4 + channel * 8 + 4)[0]
            sample_ref = struct.unpack_from("<I", cwav, table + info_ref + 4)[0]
            starts.append(data_offset + 8 + sample_ref)  # 8 = DATA block header
    except (IndexError, struct.error) as exc:
        raise AssetDecodeError("Truncated CWAV.") from exc

    if encoding not in (CWAV_ENCODING_PCM8, CWAV_ENCODING_PCM16):
        raise AssetDecodeError("Only PCM banner audio is supported (found an ADPCM CWAV).")
    if not 1 <= channels <= 2 or not starts:
        raise AssetDecodeError(f"Unsupported CWAV channel count: {channels}.")

    width = 1 if encoding == CWAV_ENCODING_PCM8 else 2
    frames = (data_offset + data_size - starts[0]) // (channels * width)
    if 0 < loop_end < frames:
        frames = loop_end
    chunks = [cwav[start : start + frames * width] for start in starts]
    if any(len(chunk) != frames * width for chunk in chunks):
        raise AssetDecodeError("Truncated CWAV sample data.")

    if width == 1:  # signed 8-bit -> signed 16-bit
        # PCM8 is signed; widen to 16 bits by using the sample as the high byte.
        chunks = [b"".join(b"\x00" + bytes((byte,)) for byte in chunk) for chunk in chunks]
    interleaved = bytearray(frames * channels * 2)
    for channel, chunk in enumerate(chunks):
        for byte_index in range(2):
            interleaved[channel * 2 + byte_index :: channels * 2] = chunk[byte_index::2]
    return _wav_file(sample_rate, channels, bytes(interleaved))


def decode_banner_audio(bnr: bytes) -> bytes | None:
    """Decode the banner jingle of a ``bannertool``-built BNR into a WAV.

    Returns ``None`` when the banner has no audio or it is pure silence,
    which is exactly what a build without a custom jingle produces. That
    way reloading such a CIA leaves the audio field on "default" instead
    of turning it into an explicit (silent) file.
    """
    if len(bnr) < CBMD_HEADER_SIZE or bnr[:4] != CBMD_MAGIC:
        raise AssetDecodeError("Not a valid banner (missing CBMD header).")
    cwav_offset = struct.unpack_from("<I", bnr, CBMD_CWAV_OFFSET_FIELD)[0]
    if not cwav_offset:
        return None

    wav = _cwav_to_wav(bnr[cwav_offset:])
    samples = wav[44:]
    return None if samples.count(0) == len(samples) else wav
