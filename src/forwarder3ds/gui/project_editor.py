"""One project's tab, laid out like New Super Ultimate Injector's.

Left column:

* **Game information**: the ROM, its console and what the libretro
  database says about it.
* **CIA metadata**: names, publisher and icon.
* **Content options**: RetroArch core, save folder and the injection
  options (screen, bezel, button mapping, core options).

Right column:

* **CIA header**: the Title ID and the Activity Log flag.
* **CIA banner**: where the banner comes from, its preview and the jingle.

Every edit is saved to the project at once (after a short pause); artwork
is copied into the project folder when it is chosen. Fields the user has
not touched follow what they derive from: names and publisher follow the
database entry, the save folder follows the long name.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.artwork.console_icons import fit_icon, icons_dir, load_icon
from forwarder3ds.artwork.compositor import compose_banner_png_bytes
from forwarder3ds.artwork.libretro import ThumbnailKind, fetch_thumbnail
from forwarder3ds.artwork.steamgriddb import AssetKind
from forwarder3ds.core.catalog import JINGLE_RULES, list_jingles, validate_jingle
from forwarder3ds.core.game_config import ScreenMode, supports_alt_mode
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.names import database_title, save_folder_name, strip_tags, suggest_title
from forwarder3ds.core.projects import Asset, BannerStyle, Project
from forwarder3ds.core.romdb import DbGame
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER
from forwarder3ds.core.systems import System
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.context import AppContext
from forwarder3ds.gui.dialogs.injection_options_dialog import (
    GameContext,
    InjectionOptions,
    InjectionOptionsDialog,
    ScreenshotLoader,
)
from forwarder3ds.gui.jingle_player import JinglePlayer
from forwarder3ds.gui.sgdb_picker import SgdbPicker
from forwarder3ds.gui.widgets.asset_choice import AssetChoice
from forwarder3ds.gui.widgets.elided_label import ElidedLabel
from forwarder3ds.gui.widgets.rom_info import RomInfo
from forwarder3ds.gui.widgets.title_id_bar import TitleIdBar

_log = get_logger("gui")
_SAVE_DELAY_MS = 400
_ICON_PREVIEW = 96
_BANNER_PREVIEW = (384, 192)
IMAGE_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"
_THUMBNAILS = {
    BannerStyle.TITLE_SCREEN: ThumbnailKind.TITLE,
    BannerStyle.SNAPSHOT: ThumbnailKind.SNAP,
}


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return label


def _row(*widgets: QWidget, stretch_first: bool = True) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        row.addWidget(widget, 1 if index == 0 and stretch_first else 0)
    if not stretch_first:
        row.addStretch(1)
    return holder


class ProjectEditor(QScrollArea):  # pylint: disable=too-many-instance-attributes
    """Edits one :class:`Project` and keeps it saved."""

    #: The project was saved (its title may have changed).
    saved = Signal()

    def __init__(  # pylint: disable=too-many-statements
        self, context: AppContext, project: Project, parent=None
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._project = project
        self._loading = True
        self._threads: list[TaskThread] = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save)
        self._sgdb = SgdbPicker(self)
        self._player = JinglePlayer(self)

        self._rom_label = ElidedLabel()
        self._console_combo = QComboBox()
        self._rom_info = RomInfo()
        self._long_name = QLineEdit()
        self._short_name = QLineEdit()
        self._short_name.setPlaceholderText(self.tr("Same as the long name"))
        self._publisher = QLineEdit()
        self._icon = QLabel()
        self._icon.setFixedSize(_ICON_PREVIEW, _ICON_PREVIEW)
        self._icon.setFrameShape(QLabel.Shape.StyledPanel)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._core_combo = QComboBox()
        self._folder = QLineEdit()
        self._data_dir = _hint("")
        self._options_summary = _hint("")
        self._title_id = TitleIdBar()
        self._hide_log = QCheckBox(self.tr("Hide from the Activity Log"))
        self._banner_style = QComboBox()
        self._banner_download = QPushButton(self.tr("Download…"))
        self._banner = QLabel()
        self._banner.setFixedSize(*_BANNER_PREVIEW)
        self._banner.setFrameShape(QLabel.Shape.StyledPanel)
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner_source = _hint("")
        self._card_box = QWidget()
        self._card_name = QLineEdit()
        self._card_show_name = QCheckBox(self.tr("Show"))
        self._card_year = QLineEdit()
        self._tag_icon = QLabel()
        self._tag_icon.setFixedSize(56, 28)
        self._tag_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_year.setMaximumWidth(80)
        self._card_timer = QTimer(self)
        self._card_timer.setSingleShot(True)
        self._card_timer.setInterval(150)
        self._card_timer.timeout.connect(self._render_card)
        self._jingle = AssetChoice(
            none_label=self.tr("Silence"),
            list_entries=list_jingles,
            validate=validate_jingle,
            dialog_title=self.tr("Choose a banner jingle"),
            file_filter=self.tr("WAV files (*.wav)"),
            rules=JINGLE_RULES,
        )
        self._play = QToolButton()

        body = QWidget()
        columns = QHBoxLayout(body)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(self._build_game_group())
        left.addWidget(self._build_metadata_group())
        left.addWidget(self._build_content_group())
        left.addStretch(1)
        right.addWidget(self._build_header_group())
        right.addWidget(self._build_banner_group())
        right.addStretch(1)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        self.setWidget(body)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._connect()
        self.refresh_context()
        self._load()
        self._loading = False

    # ── Construction ─────────────────────────────────────────────────────

    def _build_game_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Game information"))
        form = QFormLayout(group)
        change = QPushButton(self.tr("Change…"))
        change.clicked.connect(self._change_rom)
        form.addRow(self.tr("Current ROM:"), _row(self._rom_label, change))
        form.addRow(self.tr("Console:"), self._console_combo)
        form.addRow(self._rom_info)
        return group

    def _build_metadata_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("CIA metadata"))
        form = QFormLayout(group)
        form.addRow(self.tr("Long name:"), self._long_name)
        form.addRow(self.tr("Short name:"), self._short_name)
        form.addRow(self.tr("Publisher:"), self._publisher)
        from_file = QPushButton(self.tr("Load image from file…"))
        from_file.clicked.connect(self._icon_from_file)
        download = QPushButton(self.tr("Download from SteamGridDB…"))
        download.clicked.connect(self._icon_from_sgdb)
        clear = QPushButton(self.tr("Clear"))
        clear.clicked.connect(lambda: self._set_asset(Asset.ICON, None))
        buttons = QVBoxLayout()
        for button in (from_file, download, clear):
            buttons.addWidget(button)
        buttons.addStretch(1)
        icon_row = QWidget()
        row = QHBoxLayout(icon_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(buttons)
        row.addStretch(1)
        form.addRow(self.tr("Icon:"), icon_row)
        return group

    def _build_content_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Content options"))
        form = QFormLayout(group)
        form.addRow(self.tr("RetroArch core:"), self._core_combo)
        form.addRow(self.tr("Save folder:"), self._folder)
        form.addRow("", self._data_dir)
        options = QPushButton(self.tr("Injection options…"))
        options.clicked.connect(self._edit_options)
        form.addRow(_row(options, self._options_summary, stretch_first=False))
        return group

    def _build_header_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("CIA header"))
        column = QVBoxLayout(group)
        randomize = QPushButton(self.tr("Random"))
        randomize.setToolTip(self.tr("Pick an unused Unique ID at random."))
        randomize.clicked.connect(self._randomize_id)
        column.addWidget(_row(self._title_id, randomize))
        column.addWidget(self._hide_log)
        return group

    def _build_banner_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("CIA banner"))
        form = QFormLayout(group)
        styles = {
            BannerStyle.CARD: self.tr("Logo + console and year"),
            BannerStyle.STEAMGRIDDB: self.tr("SteamGridDB: hero + logo"),
            BannerStyle.TITLE_SCREEN: self.tr("libretro: title screen"),
            BannerStyle.SNAPSHOT: self.tr("libretro: screenshot"),
            BannerStyle.FILE: self.tr("Image file"),
        }
        for style, text in styles.items():
            self._banner_style.addItem(text, style)
        from_file = QPushButton(self.tr("Load image from file…"))
        from_file.clicked.connect(self._banner_from_file)
        self._banner_download.clicked.connect(self._download_banner)
        form.addRow(self.tr("Style:"), self._banner_style)
        form.addRow(self._build_card_box())
        form.addRow("", _row(self._banner_download, from_file, stretch_first=False))
        form.addRow("", self._banner)
        form.addRow("", self._banner_source)
        form.addRow(self.tr("Jingle:"), _row(self._jingle, self._play))
        return group

    def _build_card_box(self) -> QWidget:
        """Logo, name and year of the default banner (shown for that style only)."""
        logo_sgdb = QPushButton(self.tr("Download from SteamGridDB…"))
        logo_sgdb.clicked.connect(self._logo_from_sgdb)
        logo_file = QPushButton(self.tr("From file…"))
        logo_file.clicked.connect(self._logo_from_file)
        logo_clear = QPushButton(self.tr("Clear"))
        logo_clear.clicked.connect(lambda: self._set_card_asset(Asset.LOGO, None))
        form = QFormLayout(self._card_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.tr("Logo:"), _row(logo_sgdb, logo_file, logo_clear, stretch_first=False))
        icon_change = QPushButton(self.tr("Change…"))
        icon_change.clicked.connect(self._tag_icon_from_file)
        icon_default = QPushButton(self.tr("Default"))
        icon_default.clicked.connect(lambda: self._set_card_asset(Asset.TAG_ICON, None))
        form.addRow(
            self.tr("Console icon:"),
            _row(self._tag_icon, icon_change, icon_default, stretch_first=False),
        )
        form.addRow(self.tr("Name:"), _row(self._card_name, self._card_show_name))
        form.addRow(self.tr("Year:"), self._card_year)
        form.addRow(
            "",
            _hint(
                self.tr(
                    "Without a logo the title is written instead. "
                    "Colours and font: Settings › Banner."
                )
            ),
        )
        return self._card_box

    def _connect(self) -> None:
        self._console_combo.currentIndexChanged.connect(self._on_console_changed)
        self._core_combo.currentIndexChanged.connect(self._on_edited)
        self._rom_info.identified.connect(self._on_identified)
        self._long_name.textChanged.connect(self._on_long_name)
        for edit in (self._short_name, self._publisher, self._folder):
            edit.textChanged.connect(self._on_edited)
        self._title_id.changed.connect(self._on_edited)
        self._hide_log.toggled.connect(self._on_edited)
        self._banner_style.currentIndexChanged.connect(self._on_banner_style)
        self._card_name.textChanged.connect(self._on_card_edited)
        self._card_show_name.toggled.connect(self._on_card_edited)
        self._card_year.textChanged.connect(self._on_card_edited)
        self._jingle.changed.connect(self._on_jingle)
        self._player.playing_changed.connect(self._update_play_button)
        self._player.failed.connect(lambda message: _log.warning("%s", message))
        self._play.clicked.connect(self._toggle_jingle)

    # ── Public ───────────────────────────────────────────────────────────

    @property
    def project(self) -> Project:
        """The project, with every edit applied."""
        return self._project

    def refresh_context(self) -> None:
        """Settings or catalogs changed: refill the lists, re-check the Title ID."""
        self._sgdb.set_settings(self._context.settings.steamgriddb)
        self._publisher.setPlaceholderText(self._context.settings.general.manufacturer)
        systems = self._context.systems
        self._console_combo.blockSignals(True)
        self._console_combo.clear()
        for system in sorted(systems or [], key=lambda item: item.name.casefold()):
            self._console_combo.addItem(f"{system.name} ({system.console})", system.console)
        self._select(self._console_combo, self._project.console)
        self._console_combo.blockSignals(False)

        self._fill_cores()
        self._refresh_title_id()
        self._card_timer.start()

    def save(self) -> None:
        """Write the project now."""
        self._save_timer.stop()
        try:
            self._context.store.save(self._project)
        except OSError as exc:
            _log.error("Cannot save the project “%s”: %s", self._project.title, exc)
            return
        self.saved.emit()

    def built(self, unique_id: int, output: Path) -> None:
        """A CIA was built from this project: pin its Title ID."""
        self._project.unique_id = self._project.built_id = unique_id
        self._project.output = str(output)
        self._title_id.set_manual_unique_id(unique_id)
        self.save()
        self._refresh_title_id()

    # ── Loading ──────────────────────────────────────────────────────────

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0 and value:
            combo.addItem(value, value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _system(self) -> System | None:
        systems = self._context.systems
        return systems.get(self._project.console) if systems else None

    def _load(self) -> None:
        project = self._project
        self._rom_label.setText(project.rom)
        self._rom_label.setToolTip(project.rom)
        self._long_name.setText(project.long_name)
        self._short_name.setText(project.short_name)
        self._publisher.setText(project.publisher)
        self._folder.setText(project.folder)
        self._hide_log.setChecked(project.hide_from_activity_log)
        if project.unique_id is None:
            self._title_id.set_auto()
        else:
            self._title_id.set_manual_unique_id(project.unique_id)
        self._select(self._banner_style, project.banner_style)
        self._card_name.setText(project.banner_name)
        self._card_show_name.setChecked(project.banner_show_name)
        self._card_year.setText(project.banner_year)
        self._show_card_box()
        audio = project.asset(Asset.AUDIO)
        self._jingle.select_path(audio, self.tr("Project jingle") if audio else None)
        self._update_play_button(False)
        self._show_icon()
        self._show_banner()
        self._show_data_dir()
        self._show_options_summary()
        self._rom_info.set_rom(project.rom_path, self._system(), project.db_name)

    # ── Edits ────────────────────────────────────────────────────────────

    def _on_edited(self) -> None:
        if self._loading:
            return
        project = self._project
        project.core = str(self._core_combo.currentData() or "")
        project.short_name = self._short_name.text().strip()
        project.publisher = self._publisher.text().strip()
        project.folder = self._folder.text().strip()
        project.hide_from_activity_log = self._hide_log.isChecked()
        project.unique_id = self._title_id.manual_unique_id()
        self._show_data_dir()
        self._refresh_title_id()
        self._card_timer.start()
        self._save_timer.start()

    def _on_long_name(self, text: str) -> None:
        if self._loading:
            return
        previous = self._project.long_name
        self._project.long_name = text.strip()
        self._follow(self._folder, {save_folder_name(previous)}, save_folder_name(text))
        self._on_edited()

    @staticmethod
    def _follow(edit: QLineEdit, old: set[str], new: str) -> None:
        """Set ``edit`` to ``new`` unless the user changed it from the ``old`` values."""
        if (edit.text().strip() in old or not edit.text().strip()) and new:
            edit.setText(new)

    def _fill_cores(self) -> None:
        """The emulators for the project's console (the default first)."""
        system = self._system()
        available = set(self._context.available_cores())
        cores = list(system.cores) if system else sorted(available)
        self._core_combo.blockSignals(True)
        self._core_combo.clear()
        for core in cores:
            note = "" if core in available else self.tr(" — no base built")
            if self._context.is_standalone(core):
                note = self.tr(" (standalone)") + note
            self._core_combo.addItem(core + note, core)
        self._select(self._core_combo, self._project.core)
        self._core_combo.blockSignals(False)

    def _on_console_changed(self) -> None:
        if self._loading:
            return
        self._project.console = str(self._console_combo.currentData() or "")
        system = self._system()
        if system is not None and self._project.core not in system.cores:
            self._project.core = system.core
        self._fill_cores()
        self._rom_info.set_rom(self._project.rom_path, system, self._project.db_name)
        self._on_edited()

    def _on_identified(self, game: DbGame | None, user: bool) -> None:
        project = self._project
        # What the names were set to automatically before (now or by older versions).
        previous = {suggest_title(project.rom_path.name)}
        if project.db_name:
            name = project.db_name
            previous |= {name, strip_tags(name), database_title(name)}
        project.db_name = game.name if game else ""
        project.developer = game.developer if game else ""
        project.year = game.year if game else ""
        if game is not None:
            # The database's full name, as No-Intro writes it; the short one without tags.
            self._follow(self._long_name, previous, game.name)
            self._follow(self._short_name, previous, strip_tags(game.name))
            current = self._publisher.text().strip()
            if game.publisher and current in ("", DEFAULT_MANUFACTURER):
                self._publisher.setText(game.publisher)
        self._show_card_box()
        self._card_timer.start()
        if user or game is not None:
            self._save_timer.start()

    def _change_rom(self) -> None:
        start = str(self._project.rom_path.parent)
        path, _filter = QFileDialog.getOpenFileName(self, self.tr("Choose the ROM"), start)
        if not path:
            return
        self._project.rom = path
        self._rom_label.setText(path)
        self._rom_label.setToolTip(path)
        self._rom_info.set_rom(Path(path), self._system(), "")
        self._on_edited()

    # ── Title ID ─────────────────────────────────────────────────────────

    def _refresh_title_id(self) -> None:
        unique_id, error = self._context.preview_unique_id(self._project)
        if error:
            self._title_id.show_error(error)
        elif unique_id is None:
            self._title_id.show_incomplete()
        else:
            self._title_id.show_unique_id(unique_id)

    def _randomize_id(self) -> None:
        self._title_id.set_manual_unique_id(self._context.random_unique_id())
        self._on_edited()

    # ── Artwork ──────────────────────────────────────────────────────────

    def _run(self, fn: Callable[[], Any], on_success: Callable[[Any], None]) -> None:
        thread = TaskThread(fn, parent=self)
        thread.succeeded.connect(on_success)
        thread.failed.connect(lambda message: _log.error("%s", message))
        self._threads.append(thread)
        thread.finished.connect(lambda: self._threads.remove(thread))
        thread.start()

    def _set_asset(self, kind: Asset, source: Path | bytes | None) -> None:
        try:
            self._context.store.set_asset(self._project, kind, source)
        except OSError as exc:
            _log.error("Cannot store the %s: %s", kind.value, exc)
            return
        if kind is Asset.ICON:
            self._show_icon()
        elif kind is Asset.BANNER:
            self._show_banner()
        self.save()

    def _pick_file(self, title: str) -> Path | None:
        path, _filter = QFileDialog.getOpenFileName(self, title, "", IMAGE_FILE_FILTER)
        return Path(path) if path else None

    def _icon_from_file(self) -> None:
        path = self._pick_file(self.tr("Choose the icon"))
        if path is not None:
            self._set_asset(Asset.ICON, path)

    def _icon_from_sgdb(self) -> None:
        self._sgdb.pick(
            AssetKind.ICON,
            self._project.plain_title,
            lambda data, _source: data and self._set_asset(Asset.ICON, data),
        )

    @staticmethod
    def _pixmap(path: Path | None, width: int, height: int) -> QPixmap | None:
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if pixmap.isNull():
            return None
        return pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _show_icon(self) -> None:
        pixmap = self._pixmap(self._project.asset(Asset.ICON), _ICON_PREVIEW, _ICON_PREVIEW)
        if pixmap is None:
            self._icon.clear()
            self._icon.setText(self.tr("Default"))
        else:
            self._icon.setPixmap(pixmap)

    def _show_banner(self) -> None:
        pixmap = self._pixmap(self._project.asset(Asset.BANNER), *_BANNER_PREVIEW)
        if pixmap is None:
            self._banner.clear()
            self._banner.setText(self.tr("Default banner"))
        else:
            self._banner.setPixmap(pixmap)

    def _on_banner_style(self) -> None:
        style = BannerStyle(self._banner_style.currentData())
        self._banner_download.setEnabled(style is not BannerStyle.FILE)
        self._show_card_box()
        if self._loading:
            return
        self._project.banner_style = style
        self.save()
        if style is BannerStyle.CARD:
            self._render_card()
        elif style in _THUMBNAILS:
            self._download_banner()

    # ── Default banner (logo + tag) ──────────────────────────────────────

    def _show_card_box(self) -> None:
        card = self._banner_style.currentData() == BannerStyle.CARD
        self._card_box.setVisible(card)
        self._banner_download.setVisible(not card)
        self._card_name.setPlaceholderText(self._project.plain_title)
        self._card_year.setPlaceholderText(self._project.year or self.tr("Year"))
        self._card_name.setEnabled(self._card_show_name.isChecked())

    def _on_card_edited(self) -> None:
        self._card_name.setEnabled(self._card_show_name.isChecked())
        if self._loading:
            return
        project = self._project
        project.banner_name = self._card_name.text().strip()
        project.banner_show_name = self._card_show_name.isChecked()
        project.banner_year = self._card_year.text().strip()
        self._card_timer.start()
        self._save_timer.start()

    def _render_card(self) -> None:
        if self._loading or self._project.banner_style is not BannerStyle.CARD:
            return
        try:
            self._context.refresh_card(self._project)
        except OSError as exc:
            _log.error("Cannot draw the banner: %s", exc)
            return
        self._banner_source.setText("")
        self._show_tag_icon()
        self._show_banner()

    def _set_card_asset(self, kind: Asset, source: Path | bytes | None) -> None:
        try:
            self._context.store.set_asset(self._project, kind, source)
        except OSError as exc:
            _log.error("Cannot store the %s: %s", kind.value, exc)
            return
        self._render_card()

    def _logo_from_file(self) -> None:
        path = self._pick_file(self.tr("Choose the logo"))
        if path is not None:
            self._set_card_asset(Asset.LOGO, path)

    def _tag_icon_from_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, self.tr("Choose the console icon"), str(icons_dir()), IMAGE_FILE_FILTER
        )
        if path:
            self._set_card_asset(Asset.TAG_ICON, Path(path))

    def _show_tag_icon(self) -> None:
        icon = load_icon(self._project.console, self._project.asset(Asset.TAG_ICON))
        buffer = BytesIO()
        fit_icon(icon, 26).save(buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self._tag_icon.setPixmap(pixmap)

    def _logo_from_sgdb(self) -> None:
        self._sgdb.pick(
            AssetKind.LOGO,
            self._project.plain_title,
            lambda data, _source: data and self._set_card_asset(Asset.LOGO, data),
        )

    def _banner_from_file(self) -> None:
        path = self._pick_file(self.tr("Choose the banner image"))
        if path is None:
            return
        self._banner_source.setText(self.tr("File · {name}").format(name=path.name))
        self._select(self._banner_style, BannerStyle.FILE)
        self._set_asset(Asset.BANNER, path)

    def _download_banner(self) -> None:
        style = self._project.banner_style
        if style is BannerStyle.STEAMGRIDDB:
            self._sgdb.pick(AssetKind.HERO, self._project.plain_title, self._on_hero)
            return
        kind = _THUMBNAILS.get(style)
        system = self._system()
        if kind is None or system is None:
            return
        if not self._project.db_name:
            QMessageBox.information(
                self,
                self.tr("Banner"),
                self.tr("The ROM is not matched to a libretro database entry."),
            )
            return
        name = self._project.db_name
        self._banner_source.setText(self.tr("Downloading the {kind}…").format(kind=kind.label))

        def done(data: bytes | None) -> None:
            if not data:
                self._banner_source.setText(
                    self.tr("libretro has no {kind} for this game.").format(kind=kind.label)
                )
                return
            self._banner_source.setText(f"libretro · {kind.label}")
            self._set_asset(Asset.BANNER, compose_banner_png_bytes(data, None))

        self._run(lambda: fetch_thumbnail(system, name, kind), done)

    def _on_hero(self, hero: bytes | None, source: str) -> None:
        if not hero:
            return

        def on_logo(logo: bytes | None, _logo_source: str) -> None:
            self._banner_source.setText(source)
            self._set_asset(Asset.BANNER, compose_banner_png_bytes(hero, logo))

        self._sgdb.pick(AssetKind.LOGO, self._project.plain_title, on_logo)

    # ── Jingle ───────────────────────────────────────────────────────────

    def _on_jingle(self) -> None:
        self._player.stop()
        path = self._jingle.selected_path()
        current = self._project.asset(Asset.AUDIO)
        if path != current:
            self._set_asset(Asset.AUDIO, path)
        self._update_play_button(False)

    def _update_play_button(self, playing: bool) -> None:
        icon = QStyle.StandardPixmap.SP_MediaStop if playing else QStyle.StandardPixmap.SP_MediaPlay
        self._play.setIcon(self.style().standardIcon(icon))
        self._play.setToolTip(self.tr("Stop") if playing else self.tr("Play the jingle"))
        can_play = self._player.available and self._jingle.selected_path() is not None
        self._play.setEnabled(playing or can_play)

    def _toggle_jingle(self) -> None:
        path = self._jingle.selected_path()
        if self._player.is_playing or path is None:
            self._player.stop()
        else:
            self._player.play(path)

    # ── Injection options ────────────────────────────────────────────────

    def _show_data_dir(self) -> None:
        project = self._project
        folder = project.folder or save_folder_name(project.long_name)
        self._data_dir.setText(f"sdmc:/saves/{project.console}/{folder}")

    def _show_options_summary(self) -> None:
        project = self._project
        modes = {
            ScreenMode.PIXEL_PERFECT: self.tr("pixel perfect"),
            ScreenMode.RECOMMENDED: self.tr("recommended"),
            ScreenMode.FULL: self.tr("full screen"),
            ScreenMode.CUSTOM: f"{project.screen.width}×{project.screen.height}",
        }
        parts = [modes[project.screen.mode]]
        if project.screen.smooth:
            parts.append(self.tr("bilinear"))
        if project.asset(Asset.BEZEL):
            parts.append(self.tr("bezel"))
        if project.bottom_screen:
            parts.append(self.tr("own touch screen"))
        if (
            project.alt_mode
            and supports_alt_mode(project.console)
            and not self._context.is_standalone(project.core)
        ):
            parts.append(self.tr("alternate mode"))
        if project.remap:
            parts.append(self.tr("custom buttons"))
        if project.core_options:
            parts.append(self.tr("{n} core option(s)").format(n=len(project.core_options)))
        self._options_summary.setText(", ".join(parts))

    def _screenshot_loader(self) -> ScreenshotLoader | None:
        """Fetches libretro's screenshot of the game, for the screen preview."""
        system, name = self._system(), self._project.db_name
        if system is None or not name:
            return None
        return lambda done: self._run(
            lambda: fetch_thumbnail(system, name, ThumbnailKind.SNAP), done
        )

    def _edit_options(self) -> None:
        project = self._project
        system = self._system()
        game = GameContext(
            console=project.console,
            console_name=system.name if system else project.console,
            core=project.core,
            core_options=self._context.core_options(project.core),
            standalone=self._context.is_standalone(project.core),
            menu_name=self._context.menu_name(project.core),
            default_touch=self._context.bottom_screen_style(),
            touch_font=self._context.touch_font(),
            load_screenshot=self._screenshot_loader(),
        )
        bezel = project.asset(Asset.BEZEL)
        alt_bezel = project.asset(Asset.ALT_BEZEL)
        touch_image = project.asset(Asset.BOTTOM_SCREEN)
        current = InjectionOptions(
            screen=project.screen,
            core_options=dict(project.core_options),
            remap=dict(project.remap),
            bezel=bezel,
            bottom_screen=project.bottom_screen,
            bottom_image=touch_image,
            alt_mode=project.alt_mode,
            alt_bezel=alt_bezel,
        )
        edited = InjectionOptionsDialog.edit(self, game, current)
        if edited is None:
            return
        project.screen = edited.screen
        project.core_options = edited.core_options
        project.remap = edited.remap
        project.bottom_screen = edited.bottom_screen
        project.alt_mode = edited.alt_mode
        if edited.bezel != bezel:
            self._set_asset(Asset.BEZEL, edited.bezel)
        if edited.alt_bezel != alt_bezel:
            self._set_asset(Asset.ALT_BEZEL, edited.alt_bezel)
        if edited.bottom_image != touch_image:
            self._set_asset(Asset.BOTTOM_SCREEN, edited.bottom_image)
        self._show_options_summary()
        self.save()
