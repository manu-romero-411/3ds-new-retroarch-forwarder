"""Pick one SteamGridDB image: search the game, show a gallery, download.

:class:`SgdbPicker` runs the whole flow for one asset kind. The game found
for a query is remembered, so the icon, the hero and the logo of one
project are searched once. Requests run on
:class:`~forwarder3ds.gui.bridge.TaskThread`; failures go to the log.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from forwarder3ds.artwork.steamgriddb import (
    AssetKind,
    GameCandidate,
    ImageCandidate,
    SGDBClient,
    download_bytes,
    pick_game,
)
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.settings import SteamGridDBSettings
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.dialogs.game_picker_dialog import GamePickerDialog
from forwarder3ds.gui.dialogs.image_gallery_dialog import ImageGalleryDialog

_log = get_logger("gui")
#: Called with the image (``None``: cancelled or failed) and a source label.
Done = Callable[[bytes | None, str], None]


class SgdbPicker(QObject):
    """SteamGridDB search → game → gallery → download, for one widget."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._settings = SteamGridDBSettings()
        self._game: GameCandidate | None = None
        self._query = ""
        self._threads: list[TaskThread] = []

    def set_settings(self, settings: SteamGridDBSettings) -> None:
        """Use these API key and filters from now on."""
        self._settings = settings

    def _run(self, fn: Callable[[], Any], on_success: Callable[[Any], None], done: Done) -> None:
        thread = TaskThread(fn, parent=self)
        thread.succeeded.connect(on_success)

        def failed(message: str) -> None:
            _log.error("SteamGridDB: %s", message)
            done(None, "")

        thread.failed.connect(failed)
        self._threads.append(thread)
        thread.finished.connect(lambda: self._threads.remove(thread))
        thread.start()

    def pick(self, kind: AssetKind, query: str, done: Done) -> None:
        """Let the user choose a ``kind`` image for game ``query``; then call ``done``."""
        if not self._settings.api_key:
            QMessageBox.information(
                self._parent,
                self.tr("SteamGridDB"),
                self.tr("Add a SteamGridDB API key in Settings first."),
            )
            done(None, "")
            return
        query = query.strip()
        if not query:
            _log.warning("Fill in the long name before searching SteamGridDB")
            done(None, "")
            return
        client = SGDBClient(
            self._settings.api_key, nsfw=self._settings.nsfw, humor=self._settings.humor
        )
        if self._game is not None and self._query.casefold() == query.casefold():
            self._fetch(client, self._game, kind, done)
            return
        _log.info("Searching SteamGridDB for “%s”", query)
        self._run(
            lambda: client.search_games(query),
            lambda results: self._on_games(client, query, kind, results, done),
            done,
        )

    def _on_games(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        client: SGDBClient,
        query: str,
        kind: AssetKind,
        results: list[GameCandidate],
        done: Done,
    ) -> None:
        if not results:
            _log.warning("SteamGridDB has no game matching “%s”", query)
            done(None, "")
            return
        chosen = pick_game(query, results) or GamePickerDialog.choose(self._parent, query, results)
        if chosen is None:
            done(None, "")
            return
        self._game, self._query = chosen, query
        _log.info("Using SteamGridDB game “%s” (id %d)", chosen.name, chosen.id)
        self._fetch(client, chosen, kind, done)

    def _fetch(self, client: SGDBClient, game: GameCandidate, kind: AssetKind, done: Done) -> None:
        self._run(
            lambda: client.get_assets(game.id, kind),
            lambda candidates: self._on_assets(game, kind, candidates, done),
            done,
        )

    def _on_assets(
        self, game: GameCandidate, kind: AssetKind, candidates: list[ImageCandidate], done: Done
    ) -> None:
        if not candidates:
            _log.warning("SteamGridDB has no %s for “%s”", kind.label.lower(), game.name)
            done(None, "")
            return
        title = self.tr("Choose the {kind} — {game}").format(
            kind=kind.label.lower(), game=game.name
        )
        chosen = ImageGalleryDialog.choose(self._parent, title, candidates)
        if chosen is None:
            done(None, "")
            return
        source = "SteamGridDB" + (f" · {chosen.author}" if chosen.author else "")
        self._run(lambda: download_bytes(chosen.url), lambda data: done(data, source), done)
