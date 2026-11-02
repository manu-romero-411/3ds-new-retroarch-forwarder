"""SteamGridDB API v2 client: the only source of artwork.

Only the endpoints this program needs are wrapped::

    search:  GET /search/autocomplete/{term}
    icons:   GET /icons/game/{id}
    heroes:  GET /heroes/game/{id}
    logos:   GET /logos/game/{id}

Failures raise :class:`SGDBError` with a message fit to show to the user.
:func:`pick_game` and :func:`fetch_best_artwork` hold the non-interactive
matching used by the command line (the GUI asks instead).
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

import requests

from forwarder3ds import __version__

API_URL = "https://www.steamgriddb.com/api/v2"
API_KEY_HELP_URL = "https://www.steamgriddb.com/profile/preferences/api"
REQUEST_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 30
PREVIEW_WORKERS = 6
_USER_AGENT = f"3ds-forwarder/{__version__}"


class AssetKind(StrEnum):
    """The SteamGridDB asset types a forwarder uses (values are API path names)."""

    ICON = "icons"
    HERO = "heroes"
    LOGO = "logos"

    @property
    def label(self) -> str:
        """Human-readable name."""
        return {"icons": "Icon", "heroes": "Hero", "logos": "Logo"}[self.value]


class SGDBError(RuntimeError):
    """A SteamGridDB request failed in a way the user should see."""


@dataclass
class GameCandidate:
    """One game result from SteamGridDB's autocomplete search."""

    id: int
    name: str
    verified: bool = False


@dataclass
class ImageCandidate:
    """One asset of a game. ``thumb_url`` is SteamGridDB's small rendition."""

    id: int
    url: str
    thumb_url: str
    width: int | None = None
    height: int | None = None
    style: str = ""
    author: str = ""
    preview: bytes | None = None


@dataclass
class Artwork:
    """Downloaded icon, hero and logo (any may be missing) and the game they belong to."""

    game: GameCandidate
    icon: bytes | None = None
    hero: bytes | None = None
    logo: bytes | None = None


class SGDBClient:
    """Thin wrapper around the SteamGridDB v2 API for one API key."""

    def __init__(self, api_key: str, nsfw: bool = False, humor: bool = True) -> None:
        self.api_key = api_key.strip()
        self._filters = {"nsfw": "any" if nsfw else "false", "humor": "any" if humor else "false"}
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {self.api_key}", "User-Agent": _USER_AGENT}
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.api_key:
            raise SGDBError("No SteamGridDB API key configured (Settings › SteamGridDB).")
        try:
            response = self._session.get(f"{API_URL}{path}", params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise SGDBError(f"Network error contacting SteamGridDB: {exc}") from exc

        if response.status_code == 401:
            raise SGDBError("SteamGridDB rejected the API key (401 Unauthorized).")
        if response.status_code == 404:
            return {"success": True, "data": []}
        if not response.ok:
            raise SGDBError(f"SteamGridDB request failed (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SGDBError("SteamGridDB returned a non-JSON response.") from exc
        if not payload.get("success", True):
            errors = "; ".join(payload.get("errors", [])) or "unknown error"
            raise SGDBError(f"SteamGridDB reported an error: {errors}")
        return payload

    def check(self) -> None:
        """Raise :class:`SGDBError` unless the key works (one cheap search)."""
        self._get("/search/autocomplete/tetris")

    def search_games(self, query: str) -> list[GameCandidate]:
        """Autocomplete search for ``query``; may return ``[]``."""
        query = query.strip()
        if not query:
            return []
        payload = self._get(f"/search/autocomplete/{quote(query, safe='')}")
        return [
            GameCandidate(
                id=int(item["id"]),
                name=item.get("name", ""),
                verified=bool(item.get("verified", False)),
            )
            for item in payload.get("data") or []
        ]

    def get_assets(self, game_id: int, kind: AssetKind, limit: int = 48) -> list[ImageCandidate]:
        """Up to ``limit`` assets of ``kind`` for a game, in SteamGridDB's order."""
        payload = self._get(f"/{AssetKind(kind).value}/game/{game_id}", params=self._filters)
        candidates: list[ImageCandidate] = []
        for item in payload.get("data") or []:
            url = item.get("url")
            if not url:
                continue
            author = item.get("author")
            candidates.append(
                ImageCandidate(
                    id=int(item.get("id", 0) or 0),
                    url=url,
                    thumb_url=item.get("thumb") or url,
                    width=item.get("width"),
                    height=item.get("height"),
                    style=item.get("style", ""),
                    author=author.get("name", "") if isinstance(author, dict) else "",
                )
            )
        return candidates[:limit]


def download_bytes(url: str) -> bytes | None:
    """Download ``url`` into memory; ``None`` on any failure."""
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response.content


def download_many_bytes(urls: Sequence[str]) -> list[bytes | None]:
    """Download several URLs in parallel, preserving their order."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(PREVIEW_WORKERS, len(urls))) as pool:
        return list(pool.map(download_bytes, urls))


def pick_game(query: str, results: Sequence[GameCandidate]) -> GameCandidate | None:
    """The unambiguous match for ``query``: the only result, or the only exact name.

    ``None`` when the choice has to be made by the user.
    """
    if len(results) == 1:
        return results[0]
    exact = [game for game in results if game.name.casefold() == query.strip().casefold()]
    return exact[0] if len(exact) == 1 else None


def fetch_best_artwork(client: SGDBClient, query: str, game_id: int | None = None) -> Artwork:
    """Non-interactive artwork: the first icon, hero and logo of the matching game.

    Without ``game_id`` the game is chosen with :func:`pick_game`, falling
    back to the first (best ranked) result. Raises :class:`SGDBError` if no
    game matches.
    """
    if game_id is not None:
        game = GameCandidate(id=game_id, name=query)
    else:
        results = client.search_games(query)
        if not results:
            raise SGDBError(f"No SteamGridDB game matches “{query}”.")
        game = pick_game(query, results) or results[0]
    artwork = Artwork(game=game)
    for kind in AssetKind:
        candidates = client.get_assets(game.id, kind, limit=1)
        data = download_bytes(candidates[0].url) if candidates else None
        setattr(artwork, kind.name.lower(), data)
    return artwork
