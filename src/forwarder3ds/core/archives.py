"""ROMs inside ``.zip`` archives (how No-Intro sets are usually distributed).

A zipped ROM is treated as the file it contains: the console is guessed from
the inner file's extension, the database match uses its CRC32 (stored in the
zip, so nothing has to be decompressed for the usual case) and the build
packs the uncompressed ROM, so RetroArch never has to extract anything on
the console. The archive must hold exactly one file of a known ROM type
(text files and the like next to it are ignored).
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ARCHIVE_EXTENSIONS = (".zip",)


class ArchiveError(ValueError):
    """The archive cannot be read, or does not hold exactly one ROM."""


def is_archive(path: Path) -> bool:
    """True for a ``.zip`` file."""
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def _members(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as archive:
            return [info for info in archive.infolist() if not info.is_dir()]
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Cannot read the archive {path.name}: {exc}") from exc


def rom_member(path: Path, extensions: Iterable[str]) -> zipfile.ZipInfo:
    """The one member of ``path`` whose extension is in ``extensions`` (no dots).

    Raises :class:`ArchiveError` if there is none or more than one.
    """
    wanted = {ext.lower().lstrip(".") for ext in extensions}
    found = [
        info
        for info in _members(path)
        if PurePosixPath(info.filename).suffix.lower().lstrip(".") in wanted
    ]
    if not found:
        raise ArchiveError(f"{path.name} holds no ROM of a known type.")
    if len(found) > 1:
        names = ", ".join(PurePosixPath(info.filename).name for info in found)
        raise ArchiveError(f"{path.name} holds several ROMs ({names}): extract the one you want.")
    return found[0]


def inner_name(path: Path, extensions: Iterable[str]) -> str:
    """The ROM's own file name: the member's for an archive, ``path``'s otherwise."""
    if not is_archive(path):
        return path.name
    return PurePosixPath(rom_member(path, extensions).filename).name


def extract(path: Path, extensions: Iterable[str], target: Path) -> Path:
    """Write the archive's ROM to ``target`` (a file path) and return it."""
    member = rom_member(path, extensions)
    try:
        with zipfile.ZipFile(path) as archive, archive.open(member) as src:
            with target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Cannot extract {member.filename} from {path.name}: {exc}") from exc
    return target
