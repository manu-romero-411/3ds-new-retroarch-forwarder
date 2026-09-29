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

Manual overrides
----------------
A user may instead pick the Unique ID by hand (e.g. from the UI's live
preview field). ``TitleIdRegistry.resolve_manual`` records that choice
through the same registry -- so later automatic builds steer clear of it
too -- but rejects it outright if it collides with a core CIA or a
*different* forwarder, via ``TitleIdCollisionError``.

Rebuilding an existing CIA
--------------------------
When an existing forwarder CIA is loaded, edited and rebuilt, it must keep
its Title ID even though the edit changes the fields that identify it. The
registry still remembers the *previous* identity as the owner of that ID,
which a plain manual override would reject as "used by another forwarder".
Passing ``replace_existing=True`` declares that the caller is deliberately
superseding that entry: the old identity no longer describes any CIA, so it
is dropped when the new one is recorded. Core CIA IDs stay off limits.
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


class TitleIdCollisionError(ValueError):
    """A manually-chosen Unique ID is already taken by something else."""


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

    def preview(self, identity: ForwarderIdentity, reserved_ids: set[int]) -> int:
        """Return the Unique ID ``identity`` would get, without assigning it.

        Read-only counterpart to :meth:`resolve`: same lookup and
        collision-search logic, but never writes to ``by_key``/``entries``
        and never saves. Meant for a live UI preview, where the identity
        may still be incomplete or changing on every keystroke.
        """
        exact_key = identity.canonical_key(nonce=0)
        if exact_key in self.by_key:
            return self.by_key[exact_key]

        taken = reserved_ids | self.assigned_ids()
        nonce = 0
        while True:
            candidate = FORWARDER_NAMESPACE | identity.digest_offset(nonce)
            if candidate not in taken:
                return candidate
            nonce += 1

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

        candidate = self.preview(identity, reserved_ids)
        self._record(exact_key, candidate, identity, nonce=None, manual=False)
        return candidate

    def validate_manual(
        self,
        identity: ForwarderIdentity,
        unique_id: int,
        reserved_ids: set[int],
        replace_existing: bool = False,
    ) -> None:
        """Raise ``TitleIdCollisionError`` if ``unique_id`` is unusable for ``identity``.

        Read-only counterpart to :meth:`resolve_manual`: runs the exact same
        checks but never records anything. Meant for live UI validation of
        a manually-typed ID, which may be incomplete or mid-edit.

        With ``replace_existing`` an ID owned by a *different* forwarder in
        this registry is accepted (see the module docstring); one reserved
        for a core CIA is still rejected.
        """
        if not 0 <= unique_id <= MAX_UNIQUE_ID:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:X} is out of range "
                f"(0x00000-0x{MAX_UNIQUE_ID:05X})."
            )

        exact_key = identity.canonical_key(nonce=0)
        owner_key = next(
            (key for key, value in self.by_key.items() if value == unique_id), None
        )
        if owner_key is not None and owner_key != exact_key and not replace_existing:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:05X} is already used by another forwarder "
                "in the registry. Pick a different one."
            )
        if owner_key is None and unique_id in reserved_ids:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:05X} is already used by a RetroArch "
                "core CIA (see data/cores.json). Pick a different one."
            )

    def resolve_manual(
        self,
        identity: ForwarderIdentity,
        unique_id: int,
        reserved_ids: set[int],
        replace_existing: bool = False,
    ) -> int:
        """Register a user-chosen Unique ID for ``identity``.

        Unlike :meth:`resolve`, ``unique_id`` comes from the caller (e.g. a
        UI override) instead of being derived from ``identity``'s hash.
        Still goes through the same registry, so later automatic builds
        steer clear of it -- but raises ``TitleIdCollisionError`` (see
        :meth:`validate_manual`) if it is already used by a RetroArch core
        CIA or a *different* forwarder identity. Re-submitting the same
        identity with the same ID is a no-op (idempotent), same as
        :meth:`resolve`.

        ``replace_existing`` lets ``identity`` take over an ID currently
        owned by another forwarder in this registry; that owner's entry is
        removed, since the CIA it described is being replaced.
        """
        self.validate_manual(identity, unique_id, reserved_ids, replace_existing)
        exact_key = identity.canonical_key(nonce=0)
        if replace_existing:
            self._release_other_owners(unique_id, keep_key=exact_key)
        self._record(exact_key, unique_id, identity, nonce=None, manual=True)
        return unique_id

    def _release_other_owners(self, unique_id: int, keep_key: str) -> None:
        """Drop every entry that owns ``unique_id`` except the one under ``keep_key``."""
        self.by_key = {
            key: value
            for key, value in self.by_key.items()
            if value != unique_id or key == keep_key
        }
        self.entries = [
            entry
            for entry in self.entries
            if entry["unique_id"] != unique_id or entry["key"] == keep_key
        ]

    def _record(
        self,
        key: str,
        unique_id: int,
        identity: ForwarderIdentity,
        nonce: int | None,
        manual: bool,
    ) -> None:
        """Write one key -> unique_id assignment into by_key/entries (no save)."""
        self.by_key[key] = unique_id
        self.entries = [entry for entry in self.entries if entry["key"] != key]
        self.entries.append(
            {
                "key": key,
                "unique_id": unique_id,
                "name": identity.name,
                "core": identity.core,
                "rom_path": identity.rom_path,
                "resolved_with_nonce": nonce,
                "manual": manual,
            }
        )


def unique_id_to_title_id(unique_id: int) -> int:
    """Combine a 20-bit Unique ID into a full 64-bit application Title ID."""
    if not 0 <= unique_id <= MAX_UNIQUE_ID:
        raise ValueError(f"unique_id out of range: 0x{unique_id:X}")
    return (HIGH32_APPLICATION << 32) | (unique_id << 8) | VARIATION_BASE


def title_id_to_unique_id(title_id: int) -> int:
    """Extract the 20-bit Unique ID from a 64-bit application Title ID.

    Inverse of :func:`unique_id_to_title_id`. Raises ``ValueError`` for a
    Title ID that is not an application title (wrong ``High32``).
    """
    if title_id >> 32 != HIGH32_APPLICATION:
        raise ValueError(f"not an application Title ID: 0x{title_id:016X}")
    return (title_id >> 8) & MAX_UNIQUE_ID


def preview_unique_id(
    identity: ForwarderIdentity,
    reserved_ids: set[int],
    registry: TitleIdRegistry,
    manual_unique_id: int | None = None,
    replace_existing: bool = False,
) -> int:
    """Return the Unique ID :func:`generate_title_id` would pick, changing nothing.

    Read-only counterpart to :func:`generate_title_id` (same arguments, same
    result, but never writes to ``registry`` or saves it). Raises
    ``TitleIdCollisionError`` if ``manual_unique_id`` is unusable. Meant for
    live previews in a frontend.
    """
    if manual_unique_id is None:
        return registry.preview(identity, reserved_ids)
    registry.validate_manual(identity, manual_unique_id, reserved_ids, replace_existing)
    return manual_unique_id


def generate_title_id(
    identity: ForwarderIdentity,
    reserved_ids: set[int],
    registry: TitleIdRegistry,
    manual_unique_id: int | None = None,
    replace_existing: bool = False,
) -> tuple[int, int]:
    """Resolve ``identity`` to a ``(unique_id, title_id)`` pair.

    This is the single entry point other tools should call: it hides the
    registry lookup/assignment/save dance behind one function. Pass
    ``manual_unique_id`` to register a user-chosen ID instead of deriving
    one automatically; see :meth:`TitleIdRegistry.resolve_manual` for the
    collision rules that applies, and ``replace_existing`` for rebuilding a
    CIA under changed metadata while keeping its ID.
    """
    if manual_unique_id is not None:
        unique_id = registry.resolve_manual(
            identity, manual_unique_id, reserved_ids, replace_existing
        )
    else:
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

    preview_only = registry.preview(sample, set())
    assert preview_only == first_unique, "preview() must match the already-resolved ID"

    other = ForwarderIdentity(
        name="Other Game",
        short_name="OG",
        long_name="Other Game",
        manufacturer="Someone",
        core="snes9x",
        rom_path="roms/snes/Other Game.sfc",
    )
    try:
        registry.resolve_manual(other, first_unique, set())
    except TitleIdCollisionError:
        pass
    else:
        raise AssertionError("resolve_manual() must reject an ID taken by another forwarder")

    assert title_id_to_unique_id(first_title) == first_unique, "inverse conversion must round-trip"
    assert preview_unique_id(sample, set(), registry) == first_unique

    edited = ForwarderIdentity(
        name=sample.name,
        short_name="SMW2",  # a metadata edit changes the identity...
        long_name=sample.long_name,
        manufacturer=sample.manufacturer,
        core=sample.core,
        rom_path=sample.rom_path,
    )
    try:
        preview_unique_id(edited, set(), registry, first_unique)
    except TitleIdCollisionError:
        pass
    else:
        raise AssertionError("the old owner must block the ID unless it is being replaced")
    kept, _title = generate_title_id(
        edited, set(), registry, manual_unique_id=first_unique, replace_existing=True
    )
    assert kept == first_unique, "replacing must keep the Title ID"
    assert registry.assigned_ids() == {first_unique}
    assert len(registry.entries) == 1, "the superseded identity must be dropped"

    try:
        registry.validate_manual(edited, 0xBAC01, {0xBAC01}, replace_existing=True)
    except TitleIdCollisionError:
        pass
    else:
        raise AssertionError("core CIA IDs must stay reserved even when replacing")

    print(f"OK: 0x{first_unique:05X} -> 0x{first_title:016X}")


if __name__ == "__main__":
    sys.exit(_self_check())
