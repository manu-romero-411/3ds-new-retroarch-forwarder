"""downloader.py — Fetching SteamGridDB assets: to memory, to disk, and in bulk.

Gallery previews always go through ``download_many_bytes`` against each
candidate's *thumbnail* URL (see ``ImageCandidate.thumb_url``), never the
full-resolution asset: it is both faster and matches the "preview in lower
quality" requirement for the picker.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

REQUEST_TIMEOUT = 30
PREVIEW_WORKERS = 6  # parallel thumbnail downloads for a gallery


def download_bytes(url: str) -> bytes | None:
    """Download ``url`` into memory. Returns ``None`` on any failure."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def download_many_bytes(urls: list[str]) -> list[bytes | None]:
    """Download several URLs in parallel, preserving input order.

    Used for gallery thumbnails, which otherwise take too long fetched one
    at a time in series.
    """
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(PREVIEW_WORKERS, len(urls))) as pool:
        return list(pool.map(download_bytes, urls))


def download_to_file(url: str, dest: Path) -> bool:
    """Stream ``url`` to ``dest``, creating parent directories. Returns success."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                handle.write(chunk)
        return True
    except requests.RequestException:
        return False
