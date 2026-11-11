"""What the libretro database knows about a project's ROM.

When the ROM (or its console) changes, the system's dat is loaded (once per
session, downloaded the first time) and the ROM is matched against it on a
worker thread (see :mod:`forwarder3ds.core.romdb`). The widget shows how
sure the match is and the entry's name, publisher, developer and year. A
missing or doubtful match is flagged, and *Change match…* lets the user
pick the entry by hand (or none). A project remembers its entry by name,
so a hand-picked match survives reopening it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from forwarder3ds.artwork.libretro import load_database
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.names import suggest_title
from forwarder3ds.core.romdb import DbGame, GameDatabase, Identification, MatchKind, identify
from forwarder3ds.core.systems import System
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.dialogs.match_dialog import MatchDialog

_log = get_logger("gui")
#: Databases already loaded this session, by console (shared by every tab).
_DATABASES: dict[str, GameDatabase] = {}


class RomInfo(QWidget):  # pylint: disable=too-many-instance-attributes
    """Match status and database entry of one ROM, as form rows."""

    #: The entry now in use (``DbGame``) or ``None``, and whether the user picked it.
    identified = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._threads: list[TaskThread] = []
        self._generation = 0  # results of older lookups are dropped
        self._rom: Path | None = None
        self._system: System | None = None
        self._preferred = ""
        self._game: DbGame | None = None
        self._kind: MatchKind | None = None
        self._crc: int | None = None

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._name = QLabel()
        self._name.setWordWrap(True)
        self._name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._companies = QLabel()
        self._companies.setWordWrap(True)
        self._year = QLabel()
        self._change = QPushButton(self.tr("Change match…"))
        self._change.clicked.connect(self._change_match)

        status_row = QWidget()
        row = QHBoxLayout(status_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._status, 1)
        row.addWidget(self._change, 0, Qt.AlignmentFlag.AlignTop)

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.tr("Database:"), status_row)
        form.addRow(self.tr("Name:"), self._name)
        form.addRow(self.tr("Developer / Publisher:"), self._companies)
        form.addRow(self.tr("Year:"), self._year)
        self._show(None, None)

    # ── Public ───────────────────────────────────────────────────────────

    @property
    def game(self) -> DbGame | None:
        """The database entry in use, if any."""
        return self._game

    def set_rom(self, rom: Path | None, system: System | None, preferred: str = "") -> None:
        """Look ``rom`` up in ``system``'s database (in the background).

        ``preferred`` is the entry the project was matched to before: when
        the lookup finds another one (or none), that one wins.
        """
        if rom == self._rom and system == self._system:
            return
        self._rom, self._system, self._preferred = rom, system, preferred
        self._generation += 1
        self._game, self._kind, self._crc = None, None, None
        if rom is None or system is None or not rom.is_file():
            self._show(None, None)
            if rom is not None and not rom.is_file():
                self._status.setText(self.tr("⚠ The ROM file is missing."))
            return
        self._status.setText(self.tr("Looking the ROM up in the libretro database…"))
        generation = self._generation

        def lookup() -> tuple[GameDatabase, Identification]:
            database = _DATABASES.get(system.console) or load_database(system)
            return database, identify(rom, system, database)

        self._run(lookup, lambda result: self._on_identified(generation, system, *result))

    # ── Lookup ───────────────────────────────────────────────────────────

    def _run(self, fn: Callable[[], Any], on_success: Callable[[Any], None]) -> None:
        thread = TaskThread(fn, parent=self)
        thread.succeeded.connect(on_success)
        thread.failed.connect(self._on_failed)
        self._threads.append(thread)
        thread.finished.connect(lambda: self._threads.remove(thread))
        thread.start()

    def _on_failed(self, message: str) -> None:
        _log.warning("libretro database: %s", message)
        self._status.setText(
            self.tr("⚠ The libretro database is not available: {message}").format(message=message)
        )

    def _on_identified(
        self, generation: int, system: System, database: GameDatabase, found: Identification
    ) -> None:
        _DATABASES[system.console] = database
        if generation != self._generation:
            return
        preferred = database.by_name(self._preferred) if self._preferred else None
        if preferred is not None and (found.game is None or found.game.name != preferred.name):
            self._apply(preferred, MatchKind.MANUAL, found.crc, user=False)
            return
        if found.kind is MatchKind.NONE and self._rom is not None:
            _log.warning("%s is not in the %s database", self._rom.name, system.name)
        self._apply(found.game, found.kind, found.crc, user=False)

    def _apply(
        self, game: DbGame | None, kind: MatchKind, crc: int | None = None, *, user: bool
    ) -> None:
        self._game, self._kind = game, kind
        if crc is not None:
            self._crc = crc
        self._show(game, kind, self._crc)
        self.identified.emit(game, user)

    # ── Display ──────────────────────────────────────────────────────────

    def _show(self, game: DbGame | None, kind: MatchKind | None, crc: int | None = None) -> None:
        crc_text = f" (CRC32 {crc:08X})" if crc is not None else ""
        statuses = {
            MatchKind.CRC: self.tr("✔ Verified dump{crc}").format(crc=crc_text),
            MatchKind.NAME: self.tr("⚠ Matched by file name only: check it"),
            MatchKind.MANUAL: self.tr("✔ Chosen by hand"),
            MatchKind.NONE: self.tr(
                "⚠ Not in the database{crc}: a hack, a translation or another revision? "
                "Use <i>Change match…</i> to pick its entry."
            ).format(crc=crc_text),
        }
        self._status.setText(statuses.get(kind, "") if kind else "")
        self._name.setText(game.name if game else "—")
        companies = [game.developer, game.publisher] if game else []
        self._companies.setText(" / ".join(part for part in companies if part) or "—")
        self._year.setText(game.year if game and game.year else "—")
        self._change.setEnabled(self._rom is not None and self._system is not None)

    # ── Actions ──────────────────────────────────────────────────────────

    def _change_match(self) -> None:
        system, rom = self._system, self._rom
        if system is None or rom is None:
            return
        database = _DATABASES.get(system.console)
        if database is None:
            self._status.setText(self.tr("Loading the libretro database…"))
            self._run(
                lambda: load_database(system),
                lambda loaded: self._open_match_dialog(system, rom, loaded),
            )
            return
        self._open_match_dialog(system, rom, database)

    def _open_match_dialog(self, system: System, rom: Path, database: GameDatabase) -> None:
        _DATABASES[system.console] = database
        query = self._game.title if self._game else suggest_title(rom.name)
        choice = MatchDialog.choose(self, database, system.name, query)
        if choice is None:  # cancelled: keep the current match
            self._show(self._game, self._kind, self._crc)
            return
        self._generation += 1
        kind = MatchKind.MANUAL if choice.game else MatchKind.NONE
        self._apply(choice.game, kind, user=True)
