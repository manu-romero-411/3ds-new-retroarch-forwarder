"""Identify ROMs against the libretro database (No-Intro and Redump dats).

libretro-database keeps, per system, the dat of every known dump
(``metadat/no-intro`` for cartridges, ``metadat/redump`` for discs) plus
side dats keyed by CRC with the publisher, developer and release year.
This module parses those clrmamepro-format files and matches a ROM:

* **cartridges** by CRC32 of the file -- also without a copier/iNES/fwNES
  header, so headered and headerless dumps both match. A zipped ROM uses
  the CRC32 the zip stores for it;
* **discs** (``.chd``/``.pbp``) by name: hashing a CHD's tracks is not
  practical, so the file name is compared with the dat's game names. Such a
  match is only a guess and is reported as such;
* **arcade romsets** by the zip's name (``sf2.zip``), which is what the
  emulator itself goes by. Arcade dats carry the year and maker inline.

A ROM that does not match (a hack, a translation, a bad dump) is reported
as unknown; the user can still pick its entry by hand (:meth:`GameDatabase.search`).
Downloading the dats is :mod:`forwarder3ds.artwork.libretro`'s job; this
module is pure and works on text.
"""

from __future__ import annotations

import enum
import re
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from forwarder3ds.core.archives import ArchiveError, is_archive, rom_member
from forwarder3ds.core.names import database_title, strip_tags
from forwarder3ds.core.systems import System

_TOKEN = re.compile(r'"([^"]*)"|(\()|(\))|([^\s()"]+)')
_CHUNK = 1024 * 1024
#: Side dats merged into the main one, by the field each one provides.
METADATA_FIELDS = ("publisher", "developer", "releaseyear")
_SEARCH_LIMIT = 200

# Headers some dumps carry in front of the ROM data.
_SNES_COPIER_HEADER = 512
_INES_MAGIC, _FWNES_MAGIC, _NES_HEADER = b"NES\x1a", b"FDS\x1a", 16
_A78_MAGIC, _A78_HEADER = b"ATARI7800", 128  # at offset 1
_LYNX_MAGIC, _LYNX_HEADER = b"LYNX", 64


class MatchKind(enum.Enum):
    """How a ROM was tied to its database entry."""

    CRC = "crc"  # the file's checksum is in the dat: certain
    SET = "set"  # arcade: the romset's name is in the dat
    NAME = "name"  # discs: the file name looks like a dat entry: a guess
    MANUAL = "manual"  # chosen by the user
    NONE = "none"  # not in the database


@dataclass(frozen=True)
class DbGame:
    """One game of a dat, with what the side dats know about it."""

    name: str
    crcs: tuple[int, ...] = ()
    serial: str = ""
    publisher: str = ""
    developer: str = ""
    year: str = ""
    #: The dat's ROM file names, lower case (an arcade entry's ``set.zip``).
    files: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        """Display title: the name without tags, article in front."""
        return database_title(self.name)


@dataclass(frozen=True)
class Identification:
    """The outcome of matching one ROM."""

    kind: MatchKind
    game: DbGame | None = None
    crc: int | None = None
    #: For a name match: every entry that looked right, best first.
    candidates: tuple[DbGame, ...] = field(default=())

    @property
    def matched(self) -> bool:
        """True when there is an entry, whether certain, guessed or chosen."""
        return self.game is not None


# ── clrmamepro dat parsing ───────────────────────────────────────────────


def _tokens(text: str) -> Iterator[str | None]:
    """Strings and bare words as ``str``; ``(`` and ``)`` as ``None`` markers."""
    for quoted, opening, closing, bare in _TOKEN.findall(text):
        if opening:
            yield "("
        elif closing:
            yield ")"
        else:
            yield quoted if quoted or not bare else bare


def _parse_block(tokens: Iterator[str | None]) -> dict[str, object]:
    """Read ``key value`` pairs up to the matching ``)``; nested blocks become lists."""
    block: dict[str, object] = {}
    for key in tokens:
        if key == ")":
            break
        value = next(tokens, ")")
        if value == "(":
            children = block.setdefault(str(key), [])
            assert isinstance(children, list)
            children.append(_parse_block(tokens))
        elif value != ")":
            block.setdefault(str(key), value)
    return block


def parse_dat(text: str) -> list[dict[str, object]]:
    """Every ``game ( ... )`` block of a clrmamepro dat, as nested dicts.

    A block's ``rom ( ... )`` entries are collected under ``"rom"`` as a list.
    """
    tokens = _tokens(text)
    games: list[dict[str, object]] = []
    for token in tokens:
        if token in ("game", "machine") and next(tokens, None) == "(":
            games.append(_parse_block(tokens))
    return games


def _crc(value: object) -> int | None:
    try:
        return int(str(value), 16)
    except ValueError:
        return None


def _rom_crcs(block: dict[str, object]) -> tuple[int, ...]:
    roms = block.get("rom", [])
    found = [_crc(rom.get("crc", "")) for rom in roms if isinstance(rom, dict)]
    return tuple(crc for crc in found if crc is not None)


def _rom_files(block: dict[str, object]) -> tuple[str, ...]:
    roms = block.get("rom", [])
    names = [str(rom.get("name", "")) for rom in roms if isinstance(rom, dict)]
    return tuple(name.casefold() for name in names if name)


def _inline(block: dict[str, object], *keys: str) -> str:
    """The first of ``keys`` the entry itself has (arcade dats keep the year and maker inline)."""
    for key in keys:
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _rom_serial(block: dict[str, object]) -> str:
    serial = block.get("serial", "")
    if serial:
        return str(serial)
    for rom in block.get("rom", []):
        if isinstance(rom, dict) and rom.get("serial"):
            return str(rom["serial"])
    return ""


# ── Database ─────────────────────────────────────────────────────────────


class GameDatabase:
    """One system's dat with its side dats merged in, indexed by CRC."""

    def __init__(self, games: list[DbGame]) -> None:
        self._games = sorted(games, key=lambda game: game.name.casefold())
        self._by_crc: dict[int, DbGame] = {}
        self._by_file: dict[str, DbGame] = {}
        for game in self._games:
            for crc in game.crcs:
                self._by_crc.setdefault(crc, game)
            for name in game.files:
                self._by_file.setdefault(name, game)

    @classmethod
    def from_dats(cls, main: str, extras: dict[str, str] | None = None) -> "GameDatabase":
        """Build from the main dat's text and the side dats (``METADATA_FIELDS`` -> text)."""
        metadata: dict[int, dict[str, str]] = {}
        for field_name, text in (extras or {}).items():
            for block in parse_dat(text):
                value = str(block.get(field_name, ""))
                for crc in _rom_crcs(block):
                    if value:
                        metadata.setdefault(crc, {})[field_name] = value

        games = []
        for block in parse_dat(main):
            name = str(block.get("name", "")).strip()
            if not name:
                continue
            crcs = _rom_crcs(block)
            extra: dict[str, str] = {}
            for crc in crcs:
                extra = {**metadata.get(crc, {}), **extra}
            games.append(
                DbGame(
                    name=name,
                    crcs=crcs,
                    serial=_rom_serial(block),
                    publisher=extra.get("publisher", "")
                    or _inline(block, "publisher", "manufacturer"),
                    developer=extra.get("developer", "") or _inline(block, "developer"),
                    year=extra.get("releaseyear", "") or _inline(block, "releaseyear", "year"),
                    files=_rom_files(block),
                )
            )
        return cls(games)

    @property
    def games(self) -> list[DbGame]:
        """Every entry, sorted by name."""
        return list(self._games)

    def __len__(self) -> int:
        return len(self._games)

    def by_crc(self, crc: int) -> DbGame | None:
        """The entry with a ROM of this CRC32, or ``None``."""
        return self._by_crc.get(crc)

    def by_file(self, file_name: str) -> DbGame | None:
        """The entry with a ROM file called ``file_name`` (an arcade set's zip), or ``None``."""
        return self._by_file.get(file_name.casefold())

    def by_name(self, name: str) -> DbGame | None:
        """The entry called exactly ``name`` (case-insensitive), or ``None``."""
        wanted = name.casefold()
        return next((game for game in self._games if game.name.casefold() == wanted), None)

    def search(self, text: str, limit: int = _SEARCH_LIMIT) -> list[DbGame]:
        """Entries whose name contains every word of ``text``; names starting with it first."""
        words = text.casefold().split()
        if not words:
            return self._games[:limit]
        hits = [game for game in self._games if all(w in game.name.casefold() for w in words)]
        prefix = text.casefold().strip()
        hits.sort(key=lambda game: not game.title.casefold().startswith(prefix))
        return hits[:limit]

    def like(self, file_stem: str) -> list[DbGame]:
        """Entries a file name points to: its exact dat name first, then same title."""
        exact = self.by_name(file_stem)
        title = strip_tags(file_stem).casefold()
        same_title = [
            game
            for game in self._games
            if game is not exact and strip_tags(game.name).casefold() == title
        ]
        return ([exact] if exact else []) + same_title


# ── Identification ───────────────────────────────────────────────────────


def _crc32(handle: BinaryIO, skip: int) -> int:
    """CRC32 of what ``handle`` holds past its first ``skip`` bytes."""
    handle.read(skip)
    crc = 0
    while chunk := handle.read(_CHUNK):
        crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


@contextmanager
def _open_rom(path: Path, member: zipfile.ZipInfo | None) -> Iterator[BinaryIO]:
    """The ROM's bytes: ``path`` itself, or ``member`` of the zip ``path``."""
    if member is None:
        with path.open("rb") as handle:
            yield handle
    else:
        with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
            yield handle


def rom_crcs(path: Path, extensions: Iterable[str] = ()) -> list[int]:
    """CRC32 of the ROM, then of its data without a known header if it has one.

    For a ``.zip``, the ROM is its one member of a type in ``extensions``.
    Raises :class:`~forwarder3ds.core.archives.ArchiveError` for a bad archive.
    """
    member = rom_member(path, extensions) if is_archive(path) else None
    with _open_rom(path, member) as handle:
        magic = handle.read(10)
    if member is not None:  # the zip already knows the CRC of the whole ROM
        size, crcs = member.file_size, [member.CRC]
    else:
        with _open_rom(path, member) as handle:
            size, crcs = path.stat().st_size, [_crc32(handle, 0)]
    skips = []
    if magic[:4] in (_INES_MAGIC, _FWNES_MAGIC) and size > _NES_HEADER:
        skips.append(_NES_HEADER)
    if magic[1:10] == _A78_MAGIC and size > _A78_HEADER:
        skips.append(_A78_HEADER)
    if magic[:4] == _LYNX_MAGIC and size > _LYNX_HEADER:
        skips.append(_LYNX_HEADER)
    if size % 1024 == _SNES_COPIER_HEADER:
        skips.append(_SNES_COPIER_HEADER)
    for skip in skips:
        with _open_rom(path, member) as handle:
            crcs.append(_crc32(handle, skip))
    return crcs


def identify(path: Path, system: System, database: GameDatabase) -> Identification:
    """Match ``path`` (a ROM of ``system``) against ``database``."""
    if system.arcade:
        game = database.by_file(path.name)
        return Identification(MatchKind.SET, game) if game else Identification(MatchKind.NONE)
    if system.is_disc:
        candidates = database.like(path.stem)
        if not candidates:
            return Identification(MatchKind.NONE)
        return Identification(MatchKind.NAME, candidates[0], candidates=tuple(candidates))

    try:
        crcs = rom_crcs(path, system.extensions)
    except ArchiveError:
        return Identification(MatchKind.NONE)
    for crc in crcs:
        game = database.by_crc(crc)
        if game is not None:
            return Identification(MatchKind.CRC, game, crc)
    return Identification(MatchKind.NONE, crc=crcs[0])
