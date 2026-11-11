"""Fonts picked by name (as Qt's font selector gives them) and found as files.

Pillow draws text from a font *file*, while the settings name a font the
way the system's font selector does: a family and a style ("FOT-Rodin NTLG
Pro", "DB"). :func:`font_path` turns a :class:`FontChoice` into the file:

1. a file picked explicitly (a font that is not installed) wins;
2. on systems with fontconfig (Linux), ``fc-match`` finds the family;
3. otherwise the system's font folders are scanned once and searched by the
   names stored inside each file.

Only the names are needed to find the font again on another machine; the
file is kept as well, so a font that is not installed keeps working.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

from forwarder3ds.core.logs import get_logger

_log = get_logger("fonts")

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")
_FC_TIMEOUT = 5

# OpenType "name" IDs: the typographic family/subfamily when the font has
# them (a family with many weights), else the legacy ones.
_FAMILY_IDS = (16, 1)
_STYLE_IDS = (17, 2)


@dataclass(frozen=True)
class FontChoice:
    """A font as the user picked it; all empty means the built-in font."""

    family: str = ""
    style: str = ""
    #: A font file picked directly (it may not be installed).
    file: str = ""

    @property
    def builtin(self) -> bool:
        """Nothing picked: the built-in font."""
        return not (self.family or self.file)

    def describe(self) -> str:
        """``Family Style`` (or the file name) for labels."""
        if self.family:
            return f"{self.family} {self.style}".strip()
        return Path(self.file).name if self.file else ""


def font_path(choice: FontChoice) -> str:
    """The file to draw ``choice`` with; empty for the built-in font (or if not found)."""
    if choice.file and Path(choice.file).is_file():
        return choice.file
    if not choice.family:
        return ""
    found = find_font(choice.family, choice.style)
    if found is None:
        _log.warning("Font %s not found: using the built-in one", choice.describe())
        return ""
    return str(found)


@lru_cache(maxsize=64)
def find_font(family: str, style: str = "") -> Path | None:
    """The installed file of ``family`` in ``style``, or ``None`` (looked up once)."""
    return _fontconfig_match(family, style) or _index_match(family, style)


def forget_fonts() -> None:
    """Look fonts up again (after fonts were installed)."""
    find_font.cache_clear()
    _index.cache_clear()


def _same(name: str, other: str) -> bool:
    return name.casefold().replace(" ", "") == other.casefold().replace(" ", "")


def _fontconfig_match(family: str, style: str) -> Path | None:
    """Ask fontconfig; it substitutes missing families, so check what it returns."""
    command = shutil.which("fc-match")
    if command is None:
        return None
    pattern = f"{family}:style={style}" if style else family
    try:
        result = subprocess.run(
            [command, "-f", "%{family}\n%{file}", pattern],
            capture_output=True,
            text=True,
            timeout=_FC_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    families, _, file = result.stdout.partition("\n")
    if result.returncode != 0 or not file:
        return None
    if not any(_same(name, family) for name in families.split(",")):
        return None
    return Path(file.strip())


def font_dirs() -> list[Path]:
    """Where the system and the user keep fonts."""
    home = Path.home()
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [windir / "Fonts", local / "Microsoft" / "Windows" / "Fonts"]
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        data / "fonts",
        home / ".fonts",
    ]


def _names(font: TTFont, ids: tuple[int, ...]) -> set[str]:
    table = font["name"] if "name" in font else None
    if table is None:
        return set()
    names = set()
    for record in table.names:
        if record.nameID in ids:
            try:
                names.add(record.toUnicode().strip())
            except UnicodeDecodeError:
                continue
    return names


def read_names(path: Path) -> list[tuple[set[str], set[str]]]:
    """``(families, styles)`` of each font in ``path`` (several in a collection)."""
    try:
        if path.suffix.lower() in (".ttc", ".otc"):
            fonts = list(TTCollection(str(path), lazy=True).fonts)
        else:
            fonts = [TTFont(str(path), lazy=True)]
    except (OSError, TTLibError, AssertionError, ValueError):
        return []
    found = []
    for font in fonts:
        try:
            found.append((_names(font, _FAMILY_IDS), _names(font, _STYLE_IDS)))
        except (TTLibError, AssertionError, ValueError, KeyError):
            continue
        finally:
            font.close()
    return found


@lru_cache(maxsize=1)
def _index() -> tuple[tuple[Path, tuple[str, ...], tuple[str, ...]], ...]:
    """Every font file in :func:`font_dirs` with its names (read once)."""
    entries = []
    for directory in font_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() in FONT_SUFFIXES:
                for families, styles in read_names(path):
                    entries.append((path, tuple(families), tuple(styles)))
    return tuple(entries)


def _index_match(family: str, style: str) -> Path | None:
    candidates = [entry for entry in _index() if any(_same(f, family) for f in entry[1])]
    if not candidates:
        return None
    for path, _families, styles in candidates:
        if not style or any(_same(name, style) for name in styles):
            return path
    regular = [path for path, _f, styles in candidates if any(_same(s, "Regular") for s in styles)]
    return regular[0] if regular else candidates[0][0]
