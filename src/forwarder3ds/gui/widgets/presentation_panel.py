"""Presentation panel: how the forwarder looks and sounds on the HOME menu.

* **Icon**: from SteamGridDB or a file.
* **Banner**: a SteamGridDB *hero* (background) with the game's *logo* on
  top (see :mod:`forwarder3ds.artwork.compositor`), or a ready-made image;
  plus an optional platform frame drawn over it.
* **Jingle**: one of the catalog's WAVs or any file that follows the rules,
  with a play button.

SteamGridDB is the only artwork source. Its requests run on
:class:`~forwarder3ds.gui.bridge.TaskThread` so the window never blocks;
progress goes to the log like everything else.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.artwork.compositor import compose_banner_png_bytes, frame_png_bytes
from forwarder3ds.artwork.steamgriddb import (
    AssetKind,
    GameCandidate,
    ImageCandidate,
    SGDBClient,
    download_bytes,
    pick_game,
)
from forwarder3ds.core.catalog import (
    JINGLE_RULES,
    PLATFORM_LOGO_RULES,
    list_jingles,
    list_platform_logos,
    validate_jingle,
    validate_platform_logo,
)
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.settings import SteamGridDBSettings
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.dialogs.game_picker_dialog import GamePickerDialog
from forwarder3ds.gui.dialogs.image_gallery_dialog import ImageGalleryDialog
from forwarder3ds.gui.jingle_player import JinglePlayer
from forwarder3ds.gui.widgets.asset_choice import AssetChoice
from forwarder3ds.gui.widgets.asset_slot import AssetSlot

_log = get_logger("gui")
IMAGE_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"


class PresentationPanel(QWidget):
    """Icon, banner (hero + logo or a file, plus a frame) and jingle."""

    #: The user changed something (not emitted by ``reset()``/``load_*()``).
    changed = Signal()
    #: The icon and banner as they will be built (``bytes`` or ``None``), frame included.
    previews_changed = Signal(object, object)
    #: The user wants to configure SteamGridDB.
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._long_name = ""
        self._sgdb = SteamGridDBSettings()
        self._images: dict[AssetKind, bytes | None] = {kind: None for kind in AssetKind}
        self._banner_override: bytes | None = None
        self._banner_override_source = ""
        # The frame's pixels, for the preview only: the build gets its path.
        self._frame_bytes: bytes | None = None
        self._resolved_game: GameCandidate | None = None
        self._resolved_query = ""
        self._threads: list[TaskThread] = []

        self._slots = {
            AssetKind.ICON: AssetSlot(self.tr("Icon"), self.tr("Stretched to 48×48."), self),
            AssetKind.HERO: AssetSlot(
                self.tr("Hero"), self.tr("Banner background, cover-cropped to 256×128."), self
            ),
            AssetKind.LOGO: AssetSlot(
                self.tr("Logo"), self.tr("Pasted over the hero with a margin."), self
            ),
        }
        for kind, slot in self._slots.items():
            slot.search_requested.connect(lambda k=kind: self._start_search(k))
            slot.browse_requested.connect(lambda k=kind: self._browse_image(k))
            slot.clear_requested.connect(lambda k=kind: self._set_image(k, None, ""))

        self._sgdb_notice = QLabel(
            self.tr('No SteamGridDB API key yet. <a href="#">Open Settings</a> to add one.')
        )
        self._sgdb_notice.setWordWrap(True)
        self._sgdb_notice.linkActivated.connect(lambda _link: self.settings_requested.emit())

        self._frame_choice = AssetChoice(
            none_label=self.tr("None"),
            list_entries=list_platform_logos,
            validate=validate_platform_logo,
            dialog_title=self.tr("Choose a platform logo"),
            file_filter=self.tr("PNG images (*.png)"),
            rules=PLATFORM_LOGO_RULES,
        )
        self._frame_choice.changed.connect(self._on_frame_changed)
        self._reset_banner_button = QPushButton(self.tr("Use hero + logo"))
        self._reset_banner_button.setEnabled(False)
        self._reset_banner_button.clicked.connect(self._reset_banner_override)
        self._banner_source = QLabel()
        self._banner_source.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        self._jingle_choice = AssetChoice(
            none_label=self.tr("Silence"),
            list_entries=list_jingles,
            validate=validate_jingle,
            dialog_title=self.tr("Choose a banner jingle"),
            file_filter=self.tr("WAV files (*.wav)"),
            rules=JINGLE_RULES,
        )
        self._jingle_choice.changed.connect(self._on_jingle_changed)
        self._player = JinglePlayer(self)
        self._player.playing_changed.connect(self._update_play_button)
        self._player.failed.connect(lambda message: _log.warning("%s", message))
        self._play_button = QToolButton()
        self._play_button.clicked.connect(self._toggle_jingle)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._sgdb_notice)
        column.addWidget(self._build_icon_group())
        column.addWidget(self._build_banner_group())
        column.addWidget(self._build_jingle_group())
        column.addStretch(1)
        self._update_play_button(False)
        self.set_steamgriddb(self._sgdb)
        self._update_banner_source()

    # ── Construction ─────────────────────────────────────────────────────

    def _build_icon_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Icon"))
        column = QVBoxLayout(group)
        column.addWidget(self._slots[AssetKind.ICON])
        return group

    def _build_banner_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Banner"))
        column = QVBoxLayout(group)
        column.addWidget(self._slots[AssetKind.HERO])
        column.addWidget(self._slots[AssetKind.LOGO])

        override = QPushButton(self.tr("Ready-made banner…"))
        override.setToolTip(self.tr("Use one image file instead of the hero + logo composite."))
        override.clicked.connect(self._browse_banner_override)
        buttons = QHBoxLayout()
        buttons.addWidget(override)
        buttons.addWidget(self._reset_banner_button)
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addWidget(self._banner_source)

        form = QFormLayout()
        form.addRow(self.tr("Platform logo:"), self._frame_choice)
        column.addLayout(form)
        return group

    def _build_jingle_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Jingle"))
        row = QHBoxLayout(group)
        row.addWidget(self._jingle_choice, 1)
        row.addWidget(self._play_button)
        return group

    # ── Configuration ────────────────────────────────────────────────────

    def set_steamgriddb(self, settings: SteamGridDBSettings) -> None:
        """Use these SteamGridDB credentials and filters for the next searches."""
        if settings != self._sgdb:
            self._resolved_game, self._resolved_query = None, ""
        self._sgdb = settings
        self._sgdb_notice.setVisible(not settings.configured)
        for slot in self._slots.values():
            slot.set_search_enabled(settings.configured)

    def set_long_name(self, long_name: str) -> None:
        """The search term for SteamGridDB (the game's long name)."""
        self._long_name = long_name.strip()

    # ── SteamGridDB: search → resolve the game → pick an asset ───────────

    def _run(self, fn: Callable[[], Any], on_success: Callable[[Any], None]) -> None:
        thread = TaskThread(fn, parent=self)
        thread.succeeded.connect(on_success)
        thread.failed.connect(lambda message: _log.error("SteamGridDB: %s", message))
        self._threads.append(thread)
        thread.finished.connect(lambda: self._threads.remove(thread))
        thread.start()

    def _client(self) -> SGDBClient:
        return SGDBClient(self._sgdb.api_key, nsfw=self._sgdb.nsfw, humor=self._sgdb.humor)

    def _start_search(self, kind: AssetKind) -> None:
        query = self._long_name
        if not query:
            _log.warning("Fill in the long name before searching SteamGridDB")
            return
        client = self._client()
        if self._resolved_game and self._resolved_query.casefold() == query.casefold():
            self._fetch_assets(client, self._resolved_game, kind)
            return
        _log.info("Searching SteamGridDB for “%s”", query)
        self._run(
            lambda: client.search_games(query),
            lambda results: self._on_games_found(client, query, kind, results),
        )

    def _on_games_found(
        self, client: SGDBClient, query: str, kind: AssetKind, results: list[GameCandidate]
    ) -> None:
        if not results:
            _log.warning("SteamGridDB has no game matching “%s”", query)
            return
        chosen = pick_game(query, results)
        if chosen is None:
            chosen = GamePickerDialog.choose(self, query, results)
            if chosen is None:
                return
        self._resolved_game, self._resolved_query = chosen, query
        _log.info("Using SteamGridDB game “%s” (id %d)", chosen.name, chosen.id)
        self._fetch_assets(client, chosen, kind)

    def _fetch_assets(self, client: SGDBClient, game: GameCandidate, kind: AssetKind) -> None:
        self._run(
            lambda: client.get_assets(game.id, kind),
            lambda candidates: self._on_assets_found(game, kind, candidates),
        )

    def _on_assets_found(
        self, game: GameCandidate, kind: AssetKind, candidates: list[ImageCandidate]
    ) -> None:
        if not candidates:
            _log.warning("SteamGridDB has no %s for “%s”", kind.label.lower(), game.name)
            return
        title = self.tr("Choose the {kind} — {game}").format(
            kind=kind.label.lower(), game=game.name
        )
        chosen = ImageGalleryDialog.choose(self, title, candidates)
        if chosen is None:
            return
        source = "SteamGridDB" + (f" · {chosen.author}" if chosen.author else "")
        self._run(
            lambda: download_bytes(chosen.url),
            lambda data: self._apply_download(kind, data, source),
        )

    def _apply_download(self, kind: AssetKind, data: bytes | None, source: str) -> None:
        if not data:
            _log.error("The %s could not be downloaded", kind.label.lower())
            return
        self._set_image(kind, data, source)

    # ── Files ────────────────────────────────────────────────────────────

    def _read_image_file(self, title: str) -> tuple[bytes, str] | None:
        path_str, _filter = QFileDialog.getOpenFileName(self, title, "", IMAGE_FILE_FILTER)
        if not path_str:
            return None
        try:
            return Path(path_str).read_bytes(), Path(path_str).name
        except OSError as exc:
            _log.error("Cannot read %s: %s", path_str, exc)
            return None

    def _browse_image(self, kind: AssetKind) -> None:
        picked = self._read_image_file(self.tr("Choose an image"))
        if picked:
            self._set_image(kind, picked[0], self.tr("File · {name}").format(name=picked[1]))

    def _browse_banner_override(self) -> None:
        picked = self._read_image_file(self.tr("Choose a banner image"))
        if picked:
            self._set_banner_override(picked[0], self.tr("File · {name}").format(name=picked[1]))
            self.changed.emit()

    def _reset_banner_override(self) -> None:
        self._set_banner_override(None, "")
        self.changed.emit()

    # ── State ────────────────────────────────────────────────────────────

    def _set_image(self, kind: AssetKind, data: bytes | None, source: str) -> None:
        self._images[kind] = data
        self._slots[kind].set_source(source)
        self._refresh_previews()
        self.changed.emit()

    def _set_banner_override(self, data: bytes | None, source: str) -> None:
        self._banner_override = data
        self._banner_override_source = source
        self._reset_banner_button.setEnabled(data is not None)
        self._update_banner_source()
        self._refresh_previews()

    def _update_banner_source(self) -> None:
        if self._banner_override is not None:
            text = self.tr("Banner: ready-made image ({source}).").format(
                source=self._banner_override_source
            )
        else:
            text = self.tr("Banner: hero + logo.")
        self._banner_source.setText(text)

    def _on_frame_changed(self) -> None:
        path = self._frame_choice.selected_path()
        self._frame_bytes = None
        if path is not None:
            try:
                self._frame_bytes = path.read_bytes()
            except OSError as exc:
                _log.error("Cannot read %s: %s", path, exc)
        self._refresh_previews()
        self.changed.emit()

    def _on_jingle_changed(self) -> None:
        self._player.stop()
        self._update_play_button(False)
        self.changed.emit()

    def _update_play_button(self, playing: bool) -> None:
        icon = QStyle.StandardPixmap.SP_MediaStop if playing else QStyle.StandardPixmap.SP_MediaPlay
        self._play_button.setIcon(self.style().standardIcon(icon))
        self._play_button.setToolTip(self.tr("Stop") if playing else self.tr("Play the jingle"))
        can_play = self._player.available and self._jingle_choice.selected_path() is not None
        self._play_button.setEnabled(playing or can_play)

    def _toggle_jingle(self) -> None:
        path = self._jingle_choice.selected_path()
        if self._player.is_playing or path is None:
            self._player.stop()
        else:
            self._player.play(path)

    def _composite(self) -> bytes | None:
        hero, logo = self._images[AssetKind.HERO], self._images[AssetKind.LOGO]
        if self._banner_override is not None:
            return self._banner_override
        if hero is None and logo is None:
            return None
        return compose_banner_png_bytes(hero, logo)

    def current_previews(self) -> tuple[bytes | None, bytes]:
        """The icon (``None``: placeholder) and the banner, frame included, as built."""
        banner = self._composite() or compose_banner_png_bytes(None, None)
        if self._frame_bytes:
            banner = frame_png_bytes(banner, self._frame_bytes)
        return self._images[AssetKind.ICON], banner

    def _refresh_previews(self) -> None:
        self.previews_changed.emit(*self.current_previews())

    # ── Document (new / open) ────────────────────────────────────────────

    def reset(self) -> None:
        """Forget every picked asset, the frame, the jingle and the resolved game."""
        self._player.stop()
        self._images = {kind: None for kind in AssetKind}
        for slot in self._slots.values():
            slot.set_source()
        self._frame_choice.select_path(None)
        self._jingle_choice.select_path(None)
        self._resolved_game, self._resolved_query = None, ""
        self._set_banner_override(None, "")

    def load_from_cia(
        self, icon: bytes | None, banner: bytes | None, audio: Path | None, label: str
    ) -> None:
        """Show a loaded CIA's icon, banner (as a ready-made one) and jingle."""
        self.reset()
        if icon:
            self._images[AssetKind.ICON] = icon
            self._slots[AssetKind.ICON].set_source(label)
        if banner:
            # The original hero/logo composition cannot be recovered from it.
            self._set_banner_override(banner, label)
        self._jingle_choice.select_path(audio, self.tr("From the CIA"))
        self._refresh_previews()

    # ── Build inputs ─────────────────────────────────────────────────────

    def jingle_path(self) -> Path | None:
        """The selected jingle, or ``None`` for silence."""
        return self._jingle_choice.selected_path()

    def platform_logo_path(self) -> Path | None:
        """The chosen platform frame, or ``None``. The build draws it over the banner."""
        return self._frame_choice.selected_path()

    def write_build_images(self, directory: Path) -> tuple[Path | None, Path | None]:
        """Write the icon and the banner (without frame) to files for the build.

        Returns ``(icon, banner)``; ``None`` means "use the placeholder".
        """
        icon_path = banner_path = None
        icon = self._images[AssetKind.ICON]
        if icon:
            icon_path = directory / "icon_source.png"
            icon_path.write_bytes(icon)
        banner = self._composite()
        if banner:
            banner_path = directory / "banner_source.png"
            banner_path.write_bytes(banner)
        return icon_path, banner_path
