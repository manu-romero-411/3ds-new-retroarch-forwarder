"""Deterministic 3DS Title ID generation for injected games.

Background on the format
-------------------------
A 3DS Title ID is a 64-bit value::

    TitleID = (High32 << 32) | (UniqueID << 8) | Variation

``High32`` is ``0x00040000`` for a normal application (this project never
changes it). ``Variation`` is a single byte, ``0x00`` for the base title;
this project also never changes it. That leaves ``UniqueID``, a 20-bit
value (``0x00000``-``0xFFFFF``), as the only part a game CIA can pick.

Reserved namespace
------------------
The pre-built RetroArch core CIAs already occupy the ``0xBAC00``-``0xBACFF``
block (see ``forwarder3ds/data/cores.json``); this project must never generate a
game ID inside that block. Nintendo does not publish the ranges it has
assigned to retail/eShop titles, so no unofficial generator can *guarantee*
zero collision with a real title. This module manages the risk instead of
ignoring it:

* Game IDs are drawn from ``GAME_NAMESPACE`` (``0xF0000``-
  ``0xFFFFF``), a block conventionally used by homebrew/scene tools for
  exactly this purpose, kept well away from the RetroArch core block above.
* Every ID handed out is written to a persistent registry
  (``~/.local/share/3ds-forwarder/title_id_registry.json`` by default) together with the exact
  inputs that produced it, so a second run with the same inputs always
  reproduces the same ID (idempotent), and a genuine collision against
  anything already known (a core CIA or an earlier game) is detected
  and resolved deterministically rather than silently overwritten.

Determinism
-----------
The ID is derived from a SHA-256 hash of the game's own identifying
fields -- name, short name, long name, manufacturer, emulator core and save
folder -- so the same game always gets the same ID across machines and
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
*different* game, via ``TitleIdCollisionError``.

Rebuilding an existing CIA
--------------------------
When an existing game CIA is loaded, edited and rebuilt, it must keep
its Title ID even though the edit changes the fields that identify it. The
registry still remembers the *previous* identity as the owner of that ID,
which a plain manual override would reject as "used by another game".
Passing ``replace_existing=True`` declares that the caller is deliberately
superseding that entry: the old identity no longer describes any CIA, so it
is dropped when the new one is recorded. Core CIA IDs stay off limits.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HIGH32_APPLICATION = 0x00040000
VARIATION_BASE = 0x00

# Reserved block for this project's game CIAs: 0xF0000-0xFFFFF (2**16 slots).
# Kept clear of the RetroArch core CIAs (0xBAC00-0xBACFF) and outside the
# lower ranges Nintendo is known to have used for retail/eShop titles.
GAME_NAMESPACE = 0xF0000
GAME_NAMESPACE_SIZE = 0x10000
MAX_UNIQUE_ID = 0xFFFFF


class TitleIdCollisionError(ValueError):
    """A manually-chosen Unique ID is already taken by something else."""


@dataclass(frozen=True)
class GameIdentity:
    """The fields that make a game CIA unique, in generation order.

    ``name`` is the internal/display identifier (also used as the default
    output filename); ``short_name``/``long_name``/``manufacturer`` map
    straight onto the SMDH fields bannertool needs (``-s``/``-l``/``-p``).
    """

    name: str
    short_name: str
    long_name: str
    manufacturer: str
    core: str
    data_dir: str

    def canonical_key(self, nonce: int = 0) -> str:
        """A stable string uniquely identifying this exact combination."""
        parts = [
            self.name,
            self.short_name,
            self.long_name,
            self.manufacturer,
            self.core,
            self.data_dir,
        ]
        key = "\x1f".join(parts)  # unit separator: safe even if fields contain '|'
        if nonce:
            key = f"{key}\x1f#{nonce}"
        return key

    def digest_offset(self, nonce: int = 0) -> int:
        """A value in ``[0, GAME_NAMESPACE_SIZE)`` derived from SHA-256."""
        digest = hashlib.sha256(self.canonical_key(nonce).encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % GAME_NAMESPACE_SIZE


@dataclass
class TitleIdRegistry:
    """Persistent map of game identity -> assigned Unique ID.

    Two lookup paths are kept in sync: ``by_key`` (canonical identity
    string -> unique_id) makes regenerating the same game idempotent;
    ``assigned_ids`` (the set of ids already handed out) is what new
    lookups are checked against to avoid collisions.
    """

    path: Path
    by_key: dict[str, int] = field(default_factory=dict)
    entries: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "TitleIdRegistry":
        """Load the registry from disk, or start an empty one if it does not exist.

        Raises ``ValueError`` if the file exists but is not a registry.
        """
        if not path.exists():
            return cls(path=path)
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        try:
            by_key = {entry["key"]: int(entry["unique_id"]) for entry in raw}
        except (TypeError, KeyError) as exc:
            raise ValueError(f"{path} is not a Title ID registry") from exc
        return cls(path=path, by_key=by_key, entries=raw)

    def save(self) -> None:
        """Persist the registry atomically, creating parent directories."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".registry-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.entries, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def assigned_ids(self) -> set[int]:
        """Every Unique ID this registry has already handed out."""
        return set(self.by_key.values())

    def preview(self, identity: GameIdentity, reserved_ids: set[int]) -> int:
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
            candidate = GAME_NAMESPACE | identity.digest_offset(nonce)
            if candidate not in taken:
                return candidate
            nonce += 1

    def resolve(self, identity: GameIdentity, reserved_ids: set[int]) -> int:
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
        identity: GameIdentity,
        unique_id: int,
        reserved_ids: set[int],
        replace_existing: bool = False,
    ) -> None:
        """Raise ``TitleIdCollisionError`` if ``unique_id`` is unusable for ``identity``.

        Read-only counterpart to :meth:`resolve_manual`: runs the exact same
        checks but never records anything. Meant for live UI validation of
        a manually-typed ID, which may be incomplete or mid-edit.

        With ``replace_existing`` an ID owned by a *different* game in
        this registry is accepted (see the module docstring); one reserved
        for a core CIA is still rejected.
        """
        if not 0 <= unique_id <= MAX_UNIQUE_ID:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:X} is out of range " f"(0x00000-0x{MAX_UNIQUE_ID:05X})."
            )

        exact_key = identity.canonical_key(nonce=0)
        owner_key = next((key for key, value in self.by_key.items() if value == unique_id), None)
        if owner_key is not None and owner_key != exact_key and not replace_existing:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:05X} is already used by another game "
                "in the registry. Pick a different one."
            )
        if owner_key is None and unique_id in reserved_ids:
            raise TitleIdCollisionError(
                f"Unique ID 0x{unique_id:05X} is already used by a RetroArch "
                "core CIA. Pick a different one."
            )

    def resolve_manual(
        self,
        identity: GameIdentity,
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
        CIA or a *different* game identity. Re-submitting the same
        identity with the same ID is a no-op (idempotent), same as
        :meth:`resolve`.

        ``replace_existing`` lets ``identity`` take over an ID currently
        owned by another game in this registry; that owner's entry is
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
        identity: GameIdentity,
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
                "data_dir": identity.data_dir,
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
    identity: GameIdentity,
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
    identity: GameIdentity,
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
