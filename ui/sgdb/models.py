"""models.py — Data types shared by the SteamGridDB client, downloader and UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GameCandidate:
    """One game result from SteamGridDB's autocomplete search."""

    id: int
    name: str
    verified: bool = False


@dataclass
class ImageCandidate:
    """One asset (icon / hero / logo) belonging to a resolved SGDB game.

    ``thumb_url`` is a smaller, lower-quality rendition SteamGridDB serves
    alongside the full asset; the gallery preview always downloads this one
    instead of ``url``, since a picker only needs to be recognizable, not
    full resolution. ``preview`` is filled in later, once the thumbnail has
    actually been downloaded.
    """

    id: int
    url: str
    thumb_url: str
    width: int | None = None
    height: int | None = None
    style: str = ""
    author: str = ""
    preview: bytes | None = None


ASSET_KIND_ICON = "icons"
ASSET_KIND_HERO = "heroes"
ASSET_KIND_LOGO = "logos"

ASSET_KIND_LABELS = {
    ASSET_KIND_ICON: "Icon",
    ASSET_KIND_HERO: "Hero (banner background)",
    ASSET_KIND_LOGO: "Logo (banner overlay)",
}
