"""The consoles a game can be injected for, and the core each one uses.

The catalog is ``forwarder3ds/data/systems.json``. Console identifiers are
Batocera's ROM folder names (``gb``, ``snes``, ``megadrive``...): they also
name the game's save folder on the SD card, ``sdmc:/saves/<console>/<game>``.
CD-based systems only take single-file ``.chd`` images (or ``.pbp`` for the
PlayStation), so every game is exactly one file in the CIA.

Each system also names its libretro database (``libretro``, e.g.
``Nintendo - Game Boy``) and whether its games are identified against a
No-Intro dat (cartridges, by CRC) or a Redump one (discs, by name).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds.core.paths import bundled

DEFAULT_SYSTEMS_JSON = bundled("systems.json")


class SystemCatalogError(ValueError):
    """The catalog cannot be read, or a console is not in it."""


@dataclass(frozen=True)
class System:
    """One console: its identifier, display name, default core and file types."""

    console: str
    name: str
    core: str
    extensions: tuple[str, ...]
    libretro: str = ""
    database: str = "no-intro"

    @property
    def is_disc(self) -> bool:
        """True for CD systems (Redump dats, identified by name, not by CRC)."""
        return self.database == "redump"

    def accepts(self, rom: Path) -> bool:
        """True if ``rom``'s extension is one this console takes."""
        return rom.suffix.lower().lstrip(".") in self.extensions


class SystemCatalog:
    """In-memory view of ``systems.json``, keyed by console identifier."""

    def __init__(self, systems: dict[str, System]) -> None:
        self._systems = systems

    @classmethod
    def load(cls, path: Path = DEFAULT_SYSTEMS_JSON) -> "SystemCatalog":
        """Load and parse a ``systems.json`` file."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            systems = {
                console: System(
                    console=console,
                    name=data["name"],
                    core=data["core"],
                    extensions=tuple(ext.lower() for ext in data["extensions"]),
                    libretro=data.get("libretro", ""),
                    database=data.get("database", "no-intro"),
                )
                for console, data in raw.items()
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SystemCatalogError(f"Cannot read the system catalog {path}: {exc}") from exc
        return cls(systems)

    def get(self, console: str) -> System | None:
        """The system for ``console``, or ``None`` if unknown."""
        return self._systems.get(console)

    def require(self, console: str) -> System:
        """The system for ``console``; raise :class:`SystemCatalogError` if unknown."""
        system = self.get(console)
        if system is None:
            known = ", ".join(sorted(self._systems))
            raise SystemCatalogError(f"Unknown console '{console}' (known: {known}).")
        return system

    def candidates(self, rom: Path) -> list[System]:
        """Every console that takes ``rom``'s file type."""
        return [system for system in self._systems.values() if system.accepts(rom)]

    def guess(self, rom: Path) -> System | None:
        """The console for ``rom`` if its extension points to exactly one."""
        found = self.candidates(rom)
        return found[0] if len(found) == 1 else None

    def __iter__(self) -> Iterator[System]:
        return iter(self._systems.values())

    def __len__(self) -> int:
        return len(self._systems)
