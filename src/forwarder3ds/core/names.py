"""Derive human-friendly names from a ROM file name.

ROM sets name files like ``Super Mario World (USA) (Rev 1) [!].sfc``: the
tags between parentheses/brackets describe the dump, not the game. This
strips them, along with the extension, to get a title suitable as the
default for the SMDH names, and turns a title into the name of the game's
save folder on the SD card.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# A real extension is short and has no spaces: ".sfc" yes, ". Driller" no.
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_TAG_GROUPS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_WHITESPACE = re.compile(r"\s+")
_TRAILING_SEPARATORS = " -_,.:;"
# Not allowed in FAT32 file names (the 3DS SD card), plus control characters.
_FAT_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FALLBACK_FOLDER = "game"


def suggest_title(rom_path: str) -> str:
    """Title for ``rom_path``: its file name without extension nor ``(...)``/``[...]`` tags.

    Both ``/`` and ``\\`` separate directories. If stripping the tags would
    leave nothing (a file named only ``(Something)``) the name without its
    extension is returned as is. A path ending in a separator (a directory)
    or an empty one gives an empty string.
    """
    normalized = rom_path.strip().replace("\\", "/")
    if normalized.endswith("/"):  # a directory (e.g. half-typed path), not a ROM
        return ""
    name = PurePosixPath(normalized).name
    stem = _EXTENSION.sub("", name)

    title = stem
    while True:  # repeat: tags may sit next to each other, or one inside another
        stripped = _TAG_GROUPS.sub(" ", title)
        if stripped == title:
            break
        title = stripped
    title = _WHITESPACE.sub(" ", title).strip().rstrip(_TRAILING_SEPARATORS).strip()
    return title or stem.strip()


def save_folder_name(title: str) -> str:
    """Name of a game's save folder: ``title`` made safe for a FAT32 SD card.

    Characters FAT32 forbids become spaces, runs of whitespace collapse, and
    leading/trailing dots and spaces go (Windows would drop them). An empty
    result gives :data:`FALLBACK_FOLDER`.
    """
    clean = _WHITESPACE.sub(" ", _FAT_FORBIDDEN.sub(" ", title)).strip(" .")
    return clean or FALLBACK_FOLDER
