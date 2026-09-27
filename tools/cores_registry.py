"""Shared helpers for loading and querying the RetroArch core registry.

The registry is ``data/cores.json``, produced by
``parse_retroarch_cores.py`` from RetroArch's own ``Makefile.cores``. Every
tool that needs to know which libretro cores exist, and what 3DS Title ID
their pre-built CIA uses, should go through this module instead of
re-implementing JSON loading and lookups.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORES_JSON = PROJECT_ROOT / "data" / "cores.json"


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
        if not path.exists():
            print(f"ERROR: core registry not found: {path}", file=sys.stderr)
            sys.exit(1)
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        entries = {name: CoreEntry.from_json(data) for name, data in raw.items()}
        return cls(entries)

    def get(self, libretro_name: str) -> CoreEntry | None:
        """Return the entry for ``libretro_name``, or ``None`` if unknown."""
        return self._entries.get(libretro_name)

    def require(self, libretro_name: str) -> CoreEntry:
        """Return the entry for ``libretro_name`` or exit with an error."""
        entry = self.get(libretro_name)
        if entry is None:
            print(
                f"ERROR: core '{libretro_name}' is not in the core registry.",
                file=sys.stderr,
            )
            sys.exit(1)
        return entry

    def all_unique_ids(self) -> set[int]:
        """Every 3DS Unique ID already taken by a core CIA.

        Used as part of the reserved-ID set when generating forwarder Title
        IDs, so a forwarder can never collide with an installed core.
        """
        return {entry.unique_id for entry in self._entries.values()}

    def __iter__(self):
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)
