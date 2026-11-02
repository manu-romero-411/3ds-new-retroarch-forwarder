"""Derive a human-friendly forwarder title from a ROM file name.

ROM sets name files like ``Super Mario World (USA) (Rev 1) [!].sfc``: the
tags between parentheses/brackets describe the dump, not the game. This
strips them, along with the extension, to get a title suitable as the
default for the SMDH names.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# A real extension is short and has no spaces: ".sfc" yes, ". Driller" no.
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_TAG_GROUPS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_WHITESPACE = re.compile(r"\s+")
_TRAILING_SEPARATORS = " -_,.:;"


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
