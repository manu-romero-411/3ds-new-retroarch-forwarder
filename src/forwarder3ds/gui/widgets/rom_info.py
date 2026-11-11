"""What the libretro database knows about the chosen ROM.

When the ROM (or its console) changes, the system's dat is loaded (once per
session, downloaded the first time) and the ROM is matched against it on a
worker thread (see :mod:`forwarder3ds.core.romdb`). The widget shows how
sure the match is, the entry's name, publisher and year, and its libretro
title screen and snapshot, each of which can become the banner background.
A missing or doubtful match is flagged, and *Change match…* lets the user
pick the entry by hand (or none).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.artwork.libretro import ThumbnailKind, fetch_thumbnail, load_database
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.names import suggest_title
from forwarder3ds.core.romdb import DbGame, GameDatabase, Identification, MatchKind, identify
from forwarder3ds.core.systems import System
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.dialogs.match_dialog import MatchDialog

_log = get_logger("gui")
_THUMBNAILS = (ThumbnailKind.TITLE, ThumbnailKind.SNAP)
_THUMBNAIL_WIDTH = 150
_THUMBNAIL_HEIGHT = 112


class RomInfo(QWidget):  # pylint: disable=too-many-instance-attributes
    """Match status, database entry and libretro thumbnails of one ROM."""

    #: The entry now in use (``DbGame``), or ``None``; after a lookup or a manual pick.
    identified = Signal(object)
    #: A thumbnail the user wants as the banner background: PNG bytes, source label.
    hero_offered = Signal(bytes, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._databases: dict[str, GameDatabase] = {}
        self._threads: list[TaskThread] = []
        self._generation = 0  # results of older lookups are dropped
        self._rom: Path | None = None
        self._system: System | None = None
        self._game: DbGame | None = None
        self._kind: MatchKind | None = None
        self._crc: int | None = None
        self._thumbnails: dict[ThumbnailKind, bytes | None] = {}

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._name = QLabel()
        self._name.setWordWrap(True)
        self._name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._details = QLabel()
        self._details.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._change = QPushButton(self.tr("Change match…"))
        self._change.clicked.connect(self._change_match)

        self._images: dict[ThumbnailKind, QLabel] = {}
        self._use_buttons: dict[ThumbnailKind, QPushButton] = {}
        self._thumbnail_area = QWidget()
        thumbnails = QGridLayout(self._thumbnail_area)
        thumbnails.setContentsMargins(0, 0, 0, 0)
        for column, kind in enumerate(_THUMBNAILS):
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setFixedSize(_THUMBNAIL_WIDTH, _THUMBNAIL_HEIGHT)
            image.setFrameShape(QLabel.Shape.StyledPanel)
            image.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            use = QPushButton(self.tr("Use as banner"))
            use.setToolTip(self.tr("Make this the banner background (instead of the hero)."))
            use.clicked.connect(lambda _checked=False, k=kind: self._offer(k))
            thumbnails.addWidget(image, 0, column)
            thumbnails.addWidget(use, 1, column)
            self._images[kind], self._use_buttons[kind] = image, use

        buttons = QHBoxLayout()
        buttons.addWidget(self._change)
        buttons.addStretch(1)

        column_layout = QVBoxLayout(self)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(self._status)
        column_layout.addWidget(self._name)
        column_layout.addWidget(self._details)
        column_layout.addWidget(self._thumbnail_area)
        column_layout.addLayout(buttons)
        self._show(None, None)

    # ── Public ───────────────────────────────────────────────────────────

    @property
    def game(self) -> DbGame | None:
        """The database entry in use, if any."""
        return self._game

    def set_rom(self, rom: Path | None, system: System | None) -> None:
        """Look ``rom`` up in ``system``'s database (in the background)."""
        if rom == self._rom and system == self._system:
            return
        self._rom, self._system = rom, system
        self._generation += 1
        self._game, self._kind, self._crc = None, None, None
        self._clear_thumbnails()
        if rom is None or system is None or not rom.is_file():
            self._show(None, None)
            return
        self._set_status(self.tr("Looking the ROM up in the libretro database…"))
        generation = self._generation

        def lookup() -> tuple[GameDatabase, Identification]:
            database = self._databases.get(system.console) or load_database(system)
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
        self._set_status(
            self.tr("⚠ The libretro database is not available: {message}").format(message=message)
        )

    def _on_identified(
        self, generation: int, system: System, database: GameDatabase, found: Identification
    ) -> None:
        self._databases[system.console] = database
        if generation != self._generation:
            return
        if found.kind is MatchKind.NONE and self._rom is not None:
            _log.warning("%s is not in the %s database", self._rom.name, system.name)
        self._apply(found.game, found.kind, found.crc)

    def _apply(self, game: DbGame | None, kind: MatchKind, crc: int | None = None) -> None:
        self._game, self._kind = game, kind
        if crc is not None:
            self._crc = crc
        self._show(game, kind, self._crc)
        self.identified.emit(game)
        self._clear_thumbnails()
        if game is not None and self._system is not None:
            system, generation = self._system, self._generation
            for kind_ in _THUMBNAILS:
                self._run(
                    lambda k=kind_: fetch_thumbnail(system, game.name, k),
                    lambda data, k=kind_: self._on_thumbnail(generation, k, data),
                )

    def _on_thumbnail(self, generation: int, kind: ThumbnailKind, data: bytes | None) -> None:
        if generation != self._generation:
            return
        self._thumbnails[kind] = data
        label = self._images[kind]
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            label.setPixmap(
                pixmap.scaled(
                    label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._use_buttons[kind].setEnabled(True)
        else:
            label.setText(self.tr("No {kind}").format(kind=kind.label.lower()))

    # ── Display ──────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

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
        self._set_status(statuses.get(kind, "") if kind else self.tr("Choose a ROM."))
        self._name.setText(game.name if game else "")
        details = [game.publisher, game.developer, game.year] if game else []
        self._details.setText(" · ".join(part for part in details if part))
        self._thumbnail_area.setVisible(game is not None)
        self._change.setEnabled(self._rom is not None and self._system is not None)

    def _clear_thumbnails(self) -> None:
        self._thumbnails = {}
        for image in self._images.values():
            image.clear()
        for button in self._use_buttons.values():
            button.setEnabled(False)

    # ── Actions ──────────────────────────────────────────────────────────

    def _offer(self, kind: ThumbnailKind) -> None:
        data = self._thumbnails.get(kind)
        if data:
            self.hero_offered.emit(data, f"libretro · {kind.label}")

    def _change_match(self) -> None:
        system, rom = self._system, self._rom
        if system is None or rom is None:
            return
        database = self._databases.get(system.console)
        if database is None:
            self._set_status(self.tr("Loading the libretro database…"))
            self._run(
                lambda: load_database(system),
                lambda loaded: self._open_match_dialog(system, rom, loaded),
            )
            return
        self._open_match_dialog(system, rom, database)

    def _open_match_dialog(self, system: System, rom: Path, database: GameDatabase) -> None:
        self._databases[system.console] = database
        query = self._game.title if self._game else suggest_title(rom.name)
        choice = MatchDialog.choose(self, database, system.name, query)
        if choice is None:  # cancelled: keep the current match
            self._show(self._game, self._kind, self._crc)
            return
        self._generation += 1
        self._apply(choice.game, MatchKind.MANUAL if choice.game else MatchKind.NONE)
