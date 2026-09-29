"""Read an existing forwarder ``.cia`` back into the fields that built it.

The inverse of :func:`tools.build_forwarder.build_forwarder`: walks the CIA
container (header -> TMD -> NCCH -> ExeFS/RomFS) and recovers everything a
rebuild needs -- Title ID, core, ROM path, SMDH names, icon, banner image
and banner audio -- as a :class:`LoadedForwarder`.

Only what a forwarder built by this project contains is supported: a single
unencrypted NCCH content (``EnableCrypt: false`` in ``stub/forwarder.rsf``)
with a flat RomFS holding ``core.txt`` and ``content.path``. Anything else
raises :class:`CiaReadError` with a message meant to be shown to the user.
Standard library only, like the rest of ``tools/``.

Layout references: https://www.3dbrew.org/wiki/CIA, /wiki/TMD, /wiki/NCCH,
/wiki/ExeFS and /wiki/RomFS.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from tools.ctr_assets import (
    AssetDecodeError,
    decode_banner_audio,
    decode_banner_image,
    parse_smdh,
)
from tools.title_id import title_id_to_unique_id, unique_id_to_title_id


class CiaReadError(ValueError):
    """The file is not a CIA this project can read back."""


# ── CIA container ────────────────────────────────────────────────────────

CIA_ALIGNMENT = 0x40
CIA_HEADER_STRUCT = struct.Struct("<IHHIIIIQ")  # header size .. content size

# Total size of a TMD's signature block (type + signature + padding).
_TMD_SIGNATURE_BLOCK_SIZES = {
    0x10000: 0x240,  # RSA-4096 SHA-1
    0x10001: 0x140,  # RSA-2048 SHA-1
    0x10002: 0x80,  # ECDSA SHA-1
    0x10003: 0x240,  # RSA-4096 SHA-256
    0x10004: 0x140,  # RSA-2048 SHA-256
    0x10005: 0x80,  # ECDSA SHA-256
}
_TMD_TITLE_ID_OFFSET = 0x4C
_TMD_CONTENT_COUNT_OFFSET = 0x9E
_TMD_HEADER_SIZE = 0xC4
_TMD_CONTENT_INFO_RECORDS = 64
_TMD_CONTENT_INFO_RECORD_SIZE = 0x24
_TMD_CONTENT_CHUNK_STRUCT = struct.Struct(">IHHQ")  # id, index, type, size
_TMD_CONTENT_CHUNK_SIZE = 0x30
_CONTENT_TYPE_ENCRYPTED = 0x0001

# ── NCCH / ExeFS / RomFS ─────────────────────────────────────────────────

NCCH_MAGIC = b"NCCH"
_NCCH_MAGIC_OFFSET = 0x100
_NCCH_FLAGS_OFFSET = 0x188
_NCCH_FLAG_MEDIA_UNIT = 6
_NCCH_FLAG_CRYPTO = 7
_NCCH_NO_CRYPTO = 0x04
_NCCH_REGIONS_OFFSET = 0x1A0  # exefs offset/size, hash size, reserved, romfs offset/size
_MEDIA_UNIT_BASE = 0x200

_EXEFS_HEADER_SIZE = 0x200
_EXEFS_ENTRY_COUNT = 10
_EXEFS_ENTRY_STRUCT = struct.Struct("<8sII")
ICON_FILE = "icon"
BANNER_FILE = "banner"

_IVFC_MAGIC = b"IVFC"
_IVFC_HEADER_SIZE = 0x60
_IVFC_LEVEL3_BLOCK_SIZE_OFFSET = 0x4C
_IVFC_MASTER_HASH_SIZE_OFFSET = 0x08
_LEVEL3_HEADER_SIZE = 0x28
_LEVEL3_FILE_META_FIELDS = (7, 8, 9)  # meta table offset/size, file data offset
_FILE_META_STRUCT = struct.Struct("<IIQQII")  # parent, sibling, offset, size, hash, name len
_ROOT_DIR_OFFSET = 0

CORE_FILE = "core.txt"
CONTENT_PATH_FILE = "content.path"
_MAX_TEXT_FILE_SIZE = 4096
_MAX_EXEFS_FILE_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class LoadedAssets:
    """Paths of the artwork/audio files written by :meth:`LoadedForwarder.write_assets`."""

    icon: Path | None
    banner: Path | None
    audio: Path | None


@dataclass(frozen=True)
class LoadedForwarder:
    """Everything recovered from a forwarder CIA, ready to rebuild it.

    ``icon_png``/``banner_png``/``audio_wav`` are ``None`` when the CIA has
    no such asset or it could not be decoded (``warnings`` says why).
    ``audio_wav`` is also ``None`` for a silent jingle, i.e. "no custom audio".
    """

    unique_id: int
    core: str
    rom_path: str
    short_name: str
    long_name: str
    manufacturer: str
    icon_png: bytes | None = None
    banner_png: bytes | None = None
    audio_wav: bytes | None = None
    warnings: tuple[str, ...] = ()

    @property
    def title_id(self) -> int:
        """The full 64-bit Title ID this CIA installs as."""
        return unique_id_to_title_id(self.unique_id)

    def write_assets(self, directory: Path) -> LoadedAssets:
        """Write the recovered icon/banner/audio into ``directory``.

        Yields the plain file paths ``ForwarderRequest`` expects. Assets
        that were not recovered come back as ``None``.
        """
        directory.mkdir(parents=True, exist_ok=True)
        return LoadedAssets(
            icon=_write_optional(directory / "loaded_icon.png", self.icon_png),
            banner=_write_optional(directory / "loaded_banner.png", self.banner_png),
            audio=_write_optional(directory / "loaded_audio.wav", self.audio_wav),
        )


@dataclass(frozen=True)
class _Ncch:
    """Absolute file offsets/sizes of the regions of the main NCCH we read."""

    exefs_offset: int
    exefs_size: int
    romfs_offset: int
    romfs_size: int


def _write_optional(path: Path, data: bytes | None) -> Path | None:
    if data is None:
        return None
    path.write_bytes(data)
    return path


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _read_exact(handle: BinaryIO, offset: int, size: int, what: str) -> bytes:
    """Read exactly ``size`` bytes at ``offset`` or raise :class:`CiaReadError`."""
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise CiaReadError(f"Unexpected end of file while reading {what}. Is the CIA truncated?")
    return data


def _locate_main_content(handle: BinaryIO) -> tuple[int, int]:
    """Return ``(absolute offset of the main NCCH, Title ID)`` from the CIA/TMD."""
    header = _read_exact(handle, 0, CIA_HEADER_STRUCT.size, "the CIA header")
    header_size, _type, _version, cert_size, ticket_size, tmd_size, _meta, _content = (
        CIA_HEADER_STRUCT.unpack(header)
    )

    tmd_offset = _align(
        _align(_align(header_size, CIA_ALIGNMENT) + cert_size, CIA_ALIGNMENT) + ticket_size,
        CIA_ALIGNMENT,
    )
    content_offset = _align(tmd_offset + tmd_size, CIA_ALIGNMENT)

    signature_type = struct.unpack(">I", _read_exact(handle, tmd_offset, 4, "the TMD"))[0]
    if signature_type not in _TMD_SIGNATURE_BLOCK_SIZES:
        raise CiaReadError("This file does not look like a CIA (unrecognized TMD).")
    tmd_header = tmd_offset + _TMD_SIGNATURE_BLOCK_SIZES[signature_type]

    title_id = struct.unpack(
        ">Q", _read_exact(handle, tmd_header + _TMD_TITLE_ID_OFFSET, 8, "the Title ID")
    )[0]
    content_count = struct.unpack(
        ">H", _read_exact(handle, tmd_header + _TMD_CONTENT_COUNT_OFFSET, 2, "the TMD")
    )[0]
    if content_count == 0:
        raise CiaReadError("The CIA has no content.")

    chunks_offset = (
        tmd_header + _TMD_HEADER_SIZE + _TMD_CONTENT_INFO_RECORDS * _TMD_CONTENT_INFO_RECORD_SIZE
    )
    chunk = _read_exact(handle, chunks_offset, _TMD_CONTENT_CHUNK_STRUCT.size, "the TMD")
    _content_id, _index, content_type, _size = _TMD_CONTENT_CHUNK_STRUCT.unpack(chunk)
    if content_type & _CONTENT_TYPE_ENCRYPTED:
        raise CiaReadError(
            "This CIA's content is encrypted, so it was not built by this tool "
            "(its forwarders are stored unencrypted)."
        )
    return content_offset, title_id


def _parse_ncch(handle: BinaryIO, ncch_offset: int) -> _Ncch:
    """Validate the NCCH header and locate its ExeFS and RomFS."""
    header = _read_exact(handle, ncch_offset, 0x200, "the NCCH header")
    if header[_NCCH_MAGIC_OFFSET : _NCCH_MAGIC_OFFSET + 4] != NCCH_MAGIC:
        raise CiaReadError("The CIA's main content is not an NCCH (encrypted or unsupported).")
    if not header[_NCCH_FLAGS_OFFSET + _NCCH_FLAG_CRYPTO] & _NCCH_NO_CRYPTO:
        raise CiaReadError("The CIA's NCCH is encrypted, so it cannot be read.")

    unit = _MEDIA_UNIT_BASE << header[_NCCH_FLAGS_OFFSET + _NCCH_FLAG_MEDIA_UNIT]
    exefs_offset, exefs_size, _hash_size, _reserved, romfs_offset, romfs_size = struct.unpack_from(
        "<6I", header, _NCCH_REGIONS_OFFSET
    )
    if not romfs_offset or not romfs_size:
        raise CiaReadError("The CIA has no RomFS, so it is not a forwarder.")
    return _Ncch(
        exefs_offset=ncch_offset + exefs_offset * unit,
        exefs_size=exefs_size * unit,
        romfs_offset=ncch_offset + romfs_offset * unit,
        romfs_size=romfs_size * unit,
    )


def _read_exefs_file(handle: BinaryIO, ncch: _Ncch, wanted: str) -> bytes | None:
    """Return the contents of ExeFS file ``wanted``, or ``None`` if absent."""
    if not ncch.exefs_offset or not ncch.exefs_size:
        return None
    table = _read_exact(handle, ncch.exefs_offset, _EXEFS_HEADER_SIZE, "the ExeFS header")
    for index in range(_EXEFS_ENTRY_COUNT):
        raw_name, offset, size = _EXEFS_ENTRY_STRUCT.unpack_from(
            table, index * _EXEFS_ENTRY_STRUCT.size
        )
        if raw_name.rstrip(b"\x00").decode("ascii", errors="replace") != wanted:
            continue
        if size > _MAX_EXEFS_FILE_SIZE:
            raise CiaReadError(f"ExeFS file '{wanted}' has an implausible size ({size} bytes).")
        return _read_exact(
            handle, ncch.exefs_offset + _EXEFS_HEADER_SIZE + offset, size, f"ExeFS '{wanted}'"
        )
    return None


def _read_romfs_files(handle: BinaryIO, ncch: _Ncch, wanted: set[str]) -> dict[str, bytes]:
    """Read the named files that sit directly in the RomFS root directory."""
    romfs = ncch.romfs_offset
    ivfc = _read_exact(handle, romfs, _IVFC_HEADER_SIZE, "the RomFS header")
    if ivfc[:4] != _IVFC_MAGIC:
        raise CiaReadError("The CIA's RomFS is malformed (missing IVFC header).")

    master_hash_size = struct.unpack_from("<I", ivfc, _IVFC_MASTER_HASH_SIZE_OFFSET)[0]
    level3_block_size = 1 << struct.unpack_from("<I", ivfc, _IVFC_LEVEL3_BLOCK_SIZE_OFFSET)[0]
    level3 = romfs + _align(_IVFC_HEADER_SIZE + master_hash_size, level3_block_size)

    header = struct.unpack(
        "<10I", _read_exact(handle, level3, _LEVEL3_HEADER_SIZE, "the RomFS level 3 header")
    )
    if header[0] != _LEVEL3_HEADER_SIZE:
        raise CiaReadError("The CIA's RomFS is malformed (bad level 3 header).")
    meta_offset, meta_size, data_offset = (header[field] for field in _LEVEL3_FILE_META_FIELDS)
    meta = _read_exact(handle, level3 + meta_offset, meta_size, "the RomFS file table")

    found: dict[str, bytes] = {}
    position = 0
    while position + _FILE_META_STRUCT.size <= len(meta):
        parent, _sibling, offset, size, _hash, name_length = _FILE_META_STRUCT.unpack_from(
            meta, position
        )
        name_start = position + _FILE_META_STRUCT.size
        name = meta[name_start : name_start + name_length].decode("utf-16-le", errors="replace")
        position = name_start + _align(name_length, 4)
        if parent != _ROOT_DIR_OFFSET or name not in wanted:
            continue
        if size > _MAX_TEXT_FILE_SIZE:
            raise CiaReadError(f"RomFS file '{name}' has an implausible size ({size} bytes).")
        found[name] = _read_exact(handle, level3 + data_offset + offset, size, f"RomFS '{name}'")
    return found


def _decode_assets(
    icon_blob: bytes | None, banner_blob: bytes | None
) -> tuple[str, str, str, bytes | None, bytes | None, bytes | None, list[str]]:
    """Decode SMDH + banner blobs; asset failures become warnings, not errors."""
    warnings: list[str] = []
    short_name = long_name = manufacturer = ""
    icon_png = banner_png = audio_wav = None

    if icon_blob is None:
        warnings.append("The CIA has no icon/SMDH; names and icon were left empty.")
    else:
        try:
            smdh = parse_smdh(icon_blob)
        except AssetDecodeError as exc:
            warnings.append(f"Could not read the icon/SMDH: {exc}")
        else:
            short_name, long_name = smdh.short_name, smdh.long_name
            manufacturer, icon_png = smdh.publisher, smdh.icon_png

    if banner_blob is None:
        warnings.append("The CIA has no banner; banner image and audio were left empty.")
    else:
        try:
            banner_png = decode_banner_image(banner_blob)
        except AssetDecodeError as exc:
            warnings.append(f"Could not read the banner image: {exc}")
        try:
            audio_wav = decode_banner_audio(banner_blob)
        except AssetDecodeError as exc:
            warnings.append(f"Could not read the banner audio: {exc}")

    return short_name, long_name, manufacturer, icon_png, banner_png, audio_wav, warnings


def _read_text(files: dict[str, bytes], name: str) -> str:
    try:
        text = files[name].decode("utf-8").strip()
    except KeyError as exc:
        raise CiaReadError(
            f"The CIA has no '{name}' in its RomFS, so it is not a forwarder "
            "built by this tool."
        ) from exc
    except UnicodeDecodeError as exc:
        raise CiaReadError(f"'{name}' in the CIA's RomFS is not valid UTF-8.") from exc
    if not text:
        raise CiaReadError(f"'{name}' in the CIA's RomFS is empty.")
    return text


def read_forwarder_cia(path: Path) -> LoadedForwarder:
    """Load a forwarder ``.cia`` from ``path``.

    Raises :class:`CiaReadError` if it is unreadable, is not a CIA, or is
    not a (readable) forwarder built by this project.
    """
    try:
        with path.open("rb") as handle:
            ncch_offset, title_id = _locate_main_content(handle)
            try:
                unique_id = title_id_to_unique_id(title_id)
            except ValueError as exc:
                raise CiaReadError("The CIA is not an application title.") from exc

            ncch = _parse_ncch(handle, ncch_offset)
            files = _read_romfs_files(handle, ncch, {CORE_FILE, CONTENT_PATH_FILE})
            icon_blob = _read_exefs_file(handle, ncch, ICON_FILE)
            banner_blob = _read_exefs_file(handle, ncch, BANNER_FILE)
    except OSError as exc:
        raise CiaReadError(f"Cannot read '{path}': {exc.strerror or exc}") from exc

    core = _read_text(files, CORE_FILE)
    rom_path = _read_text(files, CONTENT_PATH_FILE)
    short_name, long_name, manufacturer, icon_png, banner_png, audio_wav, warnings = (
        _decode_assets(icon_blob, banner_blob)
    )
    return LoadedForwarder(
        unique_id=unique_id,
        core=core,
        rom_path=rom_path,
        short_name=short_name,
        long_name=long_name,
        manufacturer=manufacturer,
        icon_png=icon_png,
        banner_png=banner_png,
        audio_wav=audio_wav,
        warnings=tuple(warnings),
    )
