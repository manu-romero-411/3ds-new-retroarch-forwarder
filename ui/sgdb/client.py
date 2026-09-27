"""client.py — Minimal SteamGridDB API v2 client (search + icons/heroes/logos).

Only the endpoints this project actually needs are wrapped:

    search:  GET /search/autocomplete/{term}
    icons:   GET /icons/game/{id}
    heroes:  GET /heroes/game/{id}
    logos:   GET /logos/game/{id}

Network/auth failures raise ``SGDBError`` with a message fit to show
directly in the UI, instead of failing silently; callers that just want a
best-effort empty list should catch it explicitly at the call site.
"""

from __future__ import annotations

import requests

from .models import ASSET_KIND_HERO, ASSET_KIND_ICON, ASSET_KIND_LOGO, GameCandidate, ImageCandidate

SGDB_API_URL = "https://www.steamgriddb.com/api/v2"
REQUEST_TIMEOUT = 20
VALID_ASSET_KINDS = (ASSET_KIND_ICON, ASSET_KIND_HERO, ASSET_KIND_LOGO)


class SGDBError(RuntimeError):
    """Raised when a SteamGridDB request fails in a way the UI should surface."""


class SGDBClient:
    """Thin wrapper around the SteamGridDB v2 API for one API key."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.api_key:
            raise SGDBError("No SteamGridDB API key configured.")
        try:
            response = self._session.get(
                f"{SGDB_API_URL}{path}", params=params, timeout=REQUEST_TIMEOUT
            )
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

    def search_games(self, query: str) -> list[GameCandidate]:
        """Autocomplete-search SteamGridDB for ``query``. May return []."""
        query = query.strip()
        if not query:
            return []
        payload = self._get(f"/search/autocomplete/{query}")
        results: list[GameCandidate] = []
        for item in payload.get("data") or []:
            results.append(
                GameCandidate(
                    id=int(item["id"]),
                    name=item.get("name", ""),
                    verified=bool(item.get("verified", False)),
                )
            )
        return results

    def get_assets(self, game_id: int, kind: str, limit: int = 48) -> list[ImageCandidate]:
        """Fetch up to ``limit`` assets of ``kind`` ("icons"/"heroes"/"logos") for a game."""
        if kind not in VALID_ASSET_KINDS:
            raise ValueError(f"Unknown SteamGridDB asset kind: {kind!r}")

        payload = self._get(f"/{kind}/game/{game_id}")
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
