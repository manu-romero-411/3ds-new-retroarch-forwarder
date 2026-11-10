"""The catalog of RetroArch cores and the Title IDs of their CIAs.

The catalog is ``forwarder3ds/data/cores.json``, produced by
``scripts/parse_retroarch_cores.py`` from RetroArch's ``pkg/ctr/Makefile.cores``.
Game CIAs keep clear of the Unique IDs listed here, so installing one never
replaces an official RetroArch core CIA.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds.core.paths import bundled

DEFAULT_CORES_JSON = bundled("cores.json")


class CoreCatalogError(ValueError):
    """The catalog cannot be read, or a core is not in it."""


@dataclass(frozen=True)
class CoreEntry:
    """A single libretro core, as installed on the console as its own CIA."""

    libretro_name: str
    title: str
    author: str
    product_code: str
    unique_id: int
    title_id: int
    cia_filename: str
    cia_path_convention: str
    system_mode: str
    use_svchax: str

    @classmethod
    def from_json(cls, data: dict) -> "CoreEntry":
        """Build a ``CoreEntry`` from one value of the ``cores.json`` map."""
        return cls(
            libretro_name=data["libretro_name"],
            title=data.get("title", data["libretro_name"]),
            author=data.get("author", ""),
            product_code=data.get("product_code", ""),
            unique_id=int(data["unique_id"], 16),
            title_id=int(data["title_id"], 16),
            cia_filename=data["cia_filename"],
            cia_path_convention=data["cia_path_convention"],
            system_mode=data.get("system_mode", ""),
            use_svchax=data.get("use_svchax", ""),
        )


class CoreRegistry:
    """In-memory view of ``cores.json``, keyed by libretro core name."""

    def __init__(self, entries: dict[str, CoreEntry]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path = DEFAULT_CORES_JSON) -> "CoreRegistry":
        """Load and parse a ``cores.json`` file."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            entries = {name: CoreEntry.from_json(data) for name, data in raw.items()}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CoreCatalogError(f"Cannot read the core catalog {path}: {exc}") from exc
        return cls(entries)

    def get(self, libretro_name: str) -> CoreEntry | None:
        """Return the entry for ``libretro_name``, or ``None`` if unknown."""
        return self._entries.get(libretro_name)

    def require(self, libretro_name: str) -> CoreEntry:
        """Return the entry for ``libretro_name``; raise :class:`CoreCatalogError` if unknown."""
        entry = self.get(libretro_name)
        if entry is None:
            raise CoreCatalogError(f"Core '{libretro_name}' is not in the core catalog.")
        return entry

    def all_unique_ids(self) -> set[int]:
        """Every 3DS Unique ID already taken by a core CIA.

        Used as part of the reserved-ID set when generating game Title
        IDs, so a game can never collide with an installed core.
        """
        return {entry.unique_id for entry in self._entries.values()}

    def __iter__(self) -> Iterator[CoreEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)
