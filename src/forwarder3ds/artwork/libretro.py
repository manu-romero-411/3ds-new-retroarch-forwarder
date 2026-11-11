"""Download the libretro database dats and the libretro thumbnails.

* Dats come from `libretro-database <https://github.com/libretro/libretro-database>`_
  (``metadat/no-intro``, ``metadat/redump`` and the side dats with publisher,
  developer and release year). They are cached under the user cache folder
  and refreshed when older than :data:`DAT_MAX_AGE`; without network the
  cached copy is used, however old.
* Thumbnails come from ``thumbnails.libretro.com``: box art, title screen and
  in-game snapshot of each dat entry, named after it. Downloads are cached.

Everything here blocks; the GUI runs it on a worker thread.
"""

from __future__ import annotations

import time
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

import requests

from forwarder3ds import __version__
from forwarder3ds.core import paths
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.romdb import METADATA_FIELDS, GameDatabase
from forwarder3ds.core.systems import System

_log = get_logger("libretro")

DAT_BASE_URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat"
THUMBNAIL_BASE_URL = "https://thumbnails.libretro.com"
DAT_MAX_AGE = 30 * 24 * 3600
REQUEST_TIMEOUT = 30
_USER_AGENT = f"3ds-forwarder/{__version__}"
# Characters RetroArch replaces with "_" in thumbnail file names.
_THUMBNAIL_FORBIDDEN = str.maketrans({char: "_" for char in '&*/:`<>?\\|"'})


class ThumbnailKind(StrEnum):
    """The thumbnail sets libretro keeps per system."""

    BOXART = "Named_Boxarts"
    TITLE = "Named_Titles"
    SNAP = "Named_Snaps"

    @property
    def label(self) -> str:
        """Human-readable name."""
        return {"Named_Boxarts": "Box art", "Named_Titles": "Title screen"}.get(
            self.value, "Screenshot"
        )


class DatabaseUnavailableError(RuntimeError):
    """The system's dat could not be downloaded and is not cached either."""


def _cache_root() -> Path:
    return paths.cache_dir() / "libretro"


def _get(url: str) -> bytes | None:
    """``url``'s body; ``None`` for a 404; raises ``requests.RequestException`` otherwise."""
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _cached_dat(folder: str, system: System, refresh: bool) -> str | None:
    """A dat's text, from the cache or freshly downloaded; ``None`` if it does not exist.

    Missing side dats are remembered as empty files so they are not asked for again.
    """
    cached = _cache_root() / "dats" / folder / f"{system.libretro}.dat"
    fresh = cached.is_file() and time.time() - cached.stat().st_mtime < DAT_MAX_AGE
    if not fresh or refresh:
        url = f"{DAT_BASE_URL}/{folder}/{quote(system.libretro)}.dat"
        try:
            data = _get(url)
        except requests.RequestException as exc:
            if not cached.is_file():
                raise DatabaseUnavailableError(f"Cannot download {url}: {exc}") from exc
            _log.warning("Using the cached %s dat (download failed: %s)", folder, exc)
        else:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data or b"")
    text = cached.read_text(encoding="utf-8", errors="replace") if cached.is_file() else ""
    return text or None


def load_database(system: System, refresh: bool = False) -> GameDatabase:
    """The libretro database of ``system`` (downloading it the first time).

    Raises :class:`DatabaseUnavailableError` without network and without cache.
    """
    if not system.libretro:
        raise DatabaseUnavailableError(f"{system.name} has no libretro database.")
    main = _cached_dat(system.database, system, refresh)
    if main is None:
        raise DatabaseUnavailableError(f"libretro has no {system.database} dat for {system.name}.")
    extras = {}
    # Arcade dats carry the year and maker themselves; there are no side dats.
    for field_name in () if system.arcade else METADATA_FIELDS:
        try:
            text = _cached_dat(field_name, system, refresh)
        except DatabaseUnavailableError as exc:
            _log.warning("%s", exc)
            continue
        if text:
            extras[field_name] = text
    database = GameDatabase.from_dats(main, extras)
    _log.info("libretro database: %d %s games", len(database), system.name)
    return database


def thumbnail_url(system: System, game_name: str, kind: ThumbnailKind) -> str:
    """Where libretro keeps ``kind`` for the dat entry ``game_name``."""
    file_name = game_name.translate(_THUMBNAIL_FORBIDDEN) + ".png"
    return f"{THUMBNAIL_BASE_URL}/{quote(system.thumbnail_system)}/{kind.value}/{quote(file_name)}"


def fetch_thumbnail(system: System, game_name: str, kind: ThumbnailKind) -> bytes | None:
    """The PNG of ``kind`` for ``game_name`` (cached), or ``None`` if libretro has none."""
    file_name = game_name.translate(_THUMBNAIL_FORBIDDEN) + ".png"
    cached = _cache_root() / "thumbnails" / system.thumbnail_system / kind.value / file_name
    if cached.is_file():
        return cached.read_bytes()
    try:
        data = _get(thumbnail_url(system, game_name, kind))
    except requests.RequestException as exc:
        _log.warning("Cannot download the %s: %s", kind.label.lower(), exc)
        return None
    if data:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data
