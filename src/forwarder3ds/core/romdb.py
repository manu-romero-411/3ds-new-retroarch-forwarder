"""Identify ROMs against the libretro database (No-Intro and Redump dats).

libretro-database keeps, per system, the dat of every known dump
(``metadat/no-intro`` for cartridges, ``metadat/redump`` for discs) plus
side dats keyed by CRC with the publisher, developer and release year.
This module parses those clrmamepro-format files and matches a ROM:

* **cartridges** by CRC32 of the file -- also without a copier/iNES/fwNES
  header, so headered and headerless dumps both match;
* **discs** (``.chd``/``.pbp``) by name: hashing a CHD's tracks is not
  practical, so the file name is compared with the dat's game names. Such a
  match is only a guess and is reported as such.

A ROM that does not match (a hack, a translation, a bad dump) is reported
as unknown; the user can still pick its entry by hand (:meth:`GameDatabase.search`).
Downloading the dats is :mod:`forwarder3ds.artwork.libretro`'s job; this
module is pure and works on text.
"""

from __future__ import annotations

import enum
import re
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

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


class MatchKind(enum.Enum):
    """How a ROM was tied to its database entry."""

    CRC = "crc"  # the file's checksum is in the dat: certain
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
        for game in self._games:
            for crc in game.crcs:
                self._by_crc.setdefault(crc, game)

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
                    publisher=extra.get("publisher", ""),
                    developer=extra.get("developer", ""),
                    year=extra.get("releaseyear", ""),
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


def _crc32(path: Path, skip: int = 0) -> int:
    crc = 0
    with path.open("rb") as handle:
        handle.seek(skip)
        while chunk := handle.read(_CHUNK):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def rom_crcs(path: Path) -> list[int]:
    """CRC32 of the file, then of its data without a known header if it has one."""
    crcs = [_crc32(path)]
    size = path.stat().st_size
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic in (_INES_MAGIC, _FWNES_MAGIC) and size > _NES_HEADER:
        crcs.append(_crc32(path, _NES_HEADER))
    if size % 1024 == _SNES_COPIER_HEADER:
        crcs.append(_crc32(path, _SNES_COPIER_HEADER))
    return crcs


def identify(path: Path, system: System, database: GameDatabase) -> Identification:
    """Match ``path`` (a ROM of ``system``) against ``database``."""
    if system.is_disc:
        candidates = database.like(path.stem)
        if not candidates:
            return Identification(MatchKind.NONE)
        return Identification(MatchKind.NAME, candidates[0], candidates=tuple(candidates))

    crcs = rom_crcs(path)
    for crc in crcs:
        game = database.by_crc(crc)
        if game is not None:
            return Identification(MatchKind.CRC, game, crc)
    return Identification(MatchKind.NONE, crc=crcs[0])
