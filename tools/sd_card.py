"""Locate a 3DS SD card mounted on this computer and express paths relative to it.

A forwarder stores its ROM as a path relative to the 3DS SD card's root
(``sdmc:/`` on the console). To let a frontend offer a file picker instead of
typing that path by hand, this module finds mounted volumes that look like
a 3DS's SD card and converts a file picked on one into that relative form.

A volume counts as a 3DS card when its root contains a ``Nintendo 3DS``
folder or a ``boot.firm`` file (case-insensitive: FAT is). Only the usual
removable-media mount points of each OS are scanned, never the whole disk.
Standard library only, like the rest of ``tools/``.
"""

from __future__ import annotations

import glob
import os
import string
import sys
from pathlib import Path

CARD_MARKERS = frozenset({"nintendo 3ds", "boot.firm"})

_LINUX_MOUNT_PATTERNS = (
    "/run/media/*/*",  # udisks2 (systemd distros): /run/media/<user>/<label>
    "/media/*/*",  # udisks2 (older/Debian-style): /media/<user>/<label>
    "/media/*",  # legacy automounters: /media/<label>
)
_MACOS_MOUNT_PATTERNS = ("/Volumes/*",)


def default_mount_patterns() -> tuple[str, ...]:
    """Glob patterns matching where this OS mounts removable volumes."""
    if sys.platform.startswith("win"):
        return tuple(f"{letter}:\\" for letter in string.ascii_uppercase)
    if sys.platform == "darwin":
        return _MACOS_MOUNT_PATTERNS
    return _LINUX_MOUNT_PATTERNS


def is_3ds_sd_card(root: Path) -> bool:
    """Whether ``root`` looks like the top of a 3DS SD card."""
    try:
        with os.scandir(root) as entries:
            return any(entry.name.lower() in CARD_MARKERS for entry in entries)
    except OSError:  # not a directory, unmounted meanwhile, no permission...
        return False


def find_3ds_sd_cards(patterns: tuple[str, ...] | None = None) -> list[Path]:
    """Every mounted volume that looks like a 3DS SD card, in a stable order.

    ``patterns`` overrides where to look (glob patterns naming candidate
    volume roots); by default the current OS's removable-media mount points.
    """
    candidates: set[str] = set()
    for pattern in patterns if patterns is not None else default_mount_patterns():
        candidates.update(match for match in glob.glob(pattern) if os.path.isdir(match))
    return [Path(match) for match in sorted(candidates) if is_3ds_sd_card(Path(match))]


def sd_relative_path(sd_root: Path, file_path: Path) -> str:
    """The SD-card path (``roms/snes/game.sfc``) of ``file_path`` on the card at ``sd_root``.

    Always uses ``/`` separators, whatever the host OS. Raises ``ValueError``
    if ``file_path`` is not inside ``sd_root``.
    """
    for root, candidate in ((sd_root, file_path), (sd_root.resolve(), file_path.resolve())):
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            continue
    raise ValueError(f"'{file_path}' is not inside the SD card at '{sd_root}'.")
