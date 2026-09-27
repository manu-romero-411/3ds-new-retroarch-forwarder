"""Deterministic 3DS Title ID generation for forwarders.

Background on the format
-------------------------
A 3DS Title ID is a 64-bit value::

    TitleID = (High32 << 32) | (UniqueID << 8) | Variation

``High32`` is ``0x00040000`` for a normal application (this project never
changes it). ``Variation`` is a single byte, ``0x00`` for the base title;
this project also never changes it. That leaves ``UniqueID``, a 20-bit
value (``0x00000``-``0xFFFFF``), as the only part a forwarder can pick.

Reserved namespace
------------------
The pre-built RetroArch core CIAs already occupy the ``0xBAC00``-``0xBACFF``
block (see ``data/cores.json``); this project must never generate a
forwarder ID inside that block. Nintendo does not publish the ranges it has
assigned to retail/eShop titles, so no unofficial generator can *guarantee*
zero collision with a real title. This module manages the risk instead of
ignoring it:

* Forwarder IDs are drawn from ``FORWARDER_NAMESPACE`` (``0xF0000``-
  ``0xFFFFF``), a block conventionally used by homebrew/scene tools for
  exactly this purpose, kept well away from the RetroArch core block above.
* Every ID handed out is written to a persistent registry
  (``data/title_id_registry.json`` by default) together with the exact
  inputs that produced it, so a second run with the same inputs always
  reproduces the same ID (idempotent), and a genuine collision against
  anything already known (a core CIA or an earlier forwarder) is detected
  and resolved deterministically rather than silently overwritten.

Determinism
-----------
The ID is derived from a SHA-256 hash of the game's own identifying
fields -- name, short name, long name, manufacturer, emulator core and ROM
path -- so the same forwarder always gets the same ID across machines and
runs, without needing a shared counter. On a genuine collision, a small
deterministic "nonce" is folded into the hash input and the search
continues; this only changes the outcome for the game that actually
collided, and the result is still 100% reproducible for that exact set of
inputs plus the current registry contents.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "title_id_registry.json"

HIGH32_APPLICATION = 0x00040000
VARIATION_BASE = 0x00

# Reserved block for this project's forwarders: 0xF0000-0xFFFFF (2**16 slots).
# Kept clear of the RetroArch core CIAs (0xBAC00-0xBACFF) and outside the
# lower ranges Nintendo is known to have used for retail/eShop titles.
FORWARDER_NAMESPACE = 0xF0000
FORWARDER_NAMESPACE_SIZE = 0x10000
MAX_UNIQUE_ID = 0xFFFFF


@dataclass(frozen=True)
class ForwarderIdentity:
    """The fields that make a forwarder unique, in generation order.

    ``name`` is the internal/display identifier (also used as the default
    output filename); ``short_name``/``long_name``/``manufacturer`` map
    straight onto the SMDH fields bannertool needs (``-s``/``-l``/``-p``).
    """

    name: str
    short_name: str
    long_name: str
    manufacturer: str
    core: str
    rom_path: str

    def canonical_key(self, nonce: int = 0) -> str:
        """A stable string uniquely identifying this exact combination."""
        parts = [
            self.name,
            self.short_name,
            self.long_name,
            self.manufacturer,
            self.core,
            self.rom_path,
        ]
        key = "\x1f".join(parts)  # unit separator: safe even if fields contain '|'
        if nonce:
            key = f"{key}\x1f#{nonce}"
        return key

    def digest_offset(self, nonce: int = 0) -> int:
        """A value in ``[0, FORWARDER_NAMESPACE_SIZE)`` derived from SHA-256."""
        digest = hashlib.sha256(self.canonical_key(nonce).encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % FORWARDER_NAMESPACE_SIZE


@dataclass
class TitleIdRegistry:
    """Persistent map of forwarder identity -> assigned Unique ID.

    Two lookup paths are kept in sync: ``by_key`` (canonical identity
    string -> unique_id) makes regenerating the same forwarder idempotent;
    ``assigned_ids`` (the set of ids already handed out) is what new
    lookups are checked against to avoid collisions.
    """

    path: Path
    by_key: dict[str, int] = field(default_factory=dict)
    entries: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTRY_PATH) -> "TitleIdRegistry":
        """Load the registry from disk, or start an empty one."""
        if not path.exists():
            return cls(path=path)
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        by_key = {entry["key"]: entry["unique_id"] for entry in raw}
        return cls(path=path, by_key=by_key, entries=raw)

    def save(self) -> None:
        """Persist the registry to disk, creating parent directories."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.entries, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    def assigned_ids(self) -> set[int]:
        """Every Unique ID this registry has already handed out."""
        return set(self.by_key.values())

    def resolve(self, identity: ForwarderIdentity, reserved_ids: set[int]) -> int:
        """Return the Unique ID for ``identity``, assigning one if new.

        ``reserved_ids`` is the full set of IDs that must not be reused
        (typically the core CIAs' IDs plus everything already in this
        registry); it is checked in addition to this registry's own IDs so
        callers only need to pass in registry entries once.
        """
        exact_key = identity.canonical_key(nonce=0)
        if exact_key in self.by_key:
            return self.by_key[exact_key]

        taken = reserved_ids | self.assigned_ids()
        nonce = 0
        while True:
            candidate = FORWARDER_NAMESPACE | identity.digest_offset(nonce)
            if candidate not in taken:
                break
            nonce += 1

        record_key = identity.canonical_key(nonce=0)
        self.by_key[record_key] = candidate
        self.entries.append(
            {
                "key": record_key,
                "unique_id": candidate,
                "name": identity.name,
                "core": identity.core,
                "rom_path": identity.rom_path,
                "resolved_with_nonce": nonce,
            }
        )
        return candidate


def unique_id_to_title_id(unique_id: int) -> int:
    """Combine a 20-bit Unique ID into a full 64-bit application Title ID."""
    if not 0 <= unique_id <= MAX_UNIQUE_ID:
        raise ValueError(f"unique_id out of range: 0x{unique_id:X}")
    return (HIGH32_APPLICATION << 32) | (unique_id << 8) | VARIATION_BASE


def generate_title_id(
    identity: ForwarderIdentity,
    reserved_ids: set[int],
    registry: TitleIdRegistry,
) -> tuple[int, int]:
    """Resolve ``identity`` to a ``(unique_id, title_id)`` pair.

    This is the single entry point other tools should call: it hides the
    registry lookup/assignment/save dance behind one function.
    """
    unique_id = registry.resolve(identity, reserved_ids)
    registry.save()
    return unique_id, unique_id_to_title_id(unique_id)


def _self_check() -> None:
    """Small smoke test, run via ``python3 -m tools.title_id``."""
    sample = ForwarderIdentity(
        name="Super Mario World",
        short_name="SMW",
        long_name="Super Mario World (SNES)",
        manufacturer="Nintendo",
        core="snes9x",
        rom_path="roms/snes/Super Mario World.sfc",
    )
    registry = TitleIdRegistry(path=Path("/tmp/title_id_registry_selfcheck.json"))
    first_unique, first_title = generate_title_id(sample, set(), registry)
    second_unique, second_title = generate_title_id(sample, set(), registry)
    assert first_unique == second_unique, "same inputs must yield the same ID"
    assert first_title == second_title
    print(f"OK: 0x{first_unique:05X} -> 0x{first_title:016X}")


if __name__ == "__main__":
    sys.exit(_self_check())
