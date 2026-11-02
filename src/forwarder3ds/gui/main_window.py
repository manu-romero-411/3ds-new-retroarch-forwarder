"""Main window.

Layout, from general to specific::

    ┌ toolbar: New · Open… · Save · Save As… · Settings ─────── Title ID ┐
    │ Game (core, ROM, names) │ Presentation (icon, banner, jingle) │ Preview │
    ├ Activity: status · busy indicator · log ──────────────────────────┤
    └ status bar: file being edited · toolchain state ──────────────────┘

Everything that configures the program lives in the Settings window;
everything about one forwarder lives in the panels. The window owns the
document workflow (New / Open / Save / Save As, unsaved changes), the core
catalog and the Title ID registry used for the live Title ID preview.

Loading a CIA never patches it: its fields fill the panels and saving
rebuilds it from scratch under the Title ID it had.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds import __version__
from forwarder3ds.builder.forwarder import default_cia_filename, make_request
from forwarder3ds.builder.toolchain import Toolchain, find_toolchain
from forwarder3ds.core import paths
from forwarder3ds.core.cores import DEFAULT_CORES_JSON, CoreCatalogError, CoreRegistry
from forwarder3ds.core.logs import TagFormatter, get_logger
from forwarder3ds.core.settings import Settings, load_settings, save_settings
from forwarder3ds.core.title_id import (
    ForwarderIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    preview_unique_id,
)
from forwarder3ds.ctr.cia import CiaReadError, LoadedForwarder, read_forwarder_cia
from forwarder3ds.gui.bridge import BuildWorker, QtLogHandler
from forwarder3ds.gui.dialogs.cia_file_dialogs import choose_cia_to_open, choose_cia_to_save
from forwarder3ds.gui.dialogs.settings_dialog import (
    PAGE_STEAMGRIDDB,
    PAGE_TOOLCHAIN,
    SettingsDialog,
)
from forwarder3ds.gui.document import Document
from forwarder3ds.gui.widgets.activity import ActivityPanel
from forwarder3ds.gui.widgets.console_preview import ConsolePreview
from forwarder3ds.gui.widgets.elided_label import ElidedLabel
from forwarder3ds.gui.widgets.game_panel import GameFields, GamePanel
from forwarder3ds.gui.widgets.presentation_panel import PresentationPanel
from forwarder3ds.gui.widgets.title_id_bar import TitleIdBar

_log = get_logger("gui")
APP_TITLE = "3DS Forwarder"
_PREVIEW_MIN_WIDTH = 240


def _scrolling(widget: QWidget) -> QScrollArea:
    """``widget`` in a vertical-only scroll area that never squeezes it horizontally."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setMinimumWidth(
        widget.minimumSizeHint().width()
        + area.verticalScrollBar().sizeHint().width()
        + 2 * area.frameWidth()
    )
    return area


class MainWindow(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """Forwarder editor plus the file workflow and the build."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(1280, 820)
        self._settings = load_settings()
        self._document = Document()
        self._tools: Toolchain = find_toolchain(self._settings.toolchain)
        self._cores: CoreRegistry | None = None
        self._registry: TitleIdRegistry | None = None
        self._worker: BuildWorker | None = None
        self._build_dir: Path | None = None
        # Files extracted from a loaded CIA (its jingle) while it is the document.
        self._loaded_dir: Path | None = None

        self._game = GamePanel()
        self._presentation = PresentationPanel()
        self._preview = ConsolePreview()
        self._title_id = TitleIdBar()
        self._activity = ActivityPanel()
        self._document_label = ElidedLabel()
        self._toolchain_label = QLabel()
        self._toolchain_label.linkActivated.connect(
            lambda _link: self._open_settings(PAGE_TOOLCHAIN)
        )
        self._file_actions: list[QAction] = []

        self._log_handler = QtLogHandler()
        self._log_handler.setFormatter(TagFormatter(colour=False))
        self._log_handler.emitter.record.connect(self._activity.append_log)
        get_logger().addHandler(self._log_handler)

        self._build_toolbar()
        self._build_central()
        self._build_activity_dock()
        self.statusBar().addWidget(self._document_label, 1)
        self.statusBar().addPermanentWidget(self._toolchain_label)
        self._connect_signals()
        self._restore_layout()

        self._apply_settings_to_panels()
        self._load_catalogs()
        self._preview.show_artwork(*self._presentation.current_previews())
        self._refresh_title_id()
        self._update_title()

    # ── Construction ─────────────────────────────────────────────────────

    def _action(
        self,
        text: str,
        theme: str,
        fallback: QStyle.StandardPixmap,
        shortcut: QKeySequence | QKeySequence.StandardKey,
    ) -> QAction:
        icon = QIcon.fromTheme(theme, self.style().standardIcon(fallback))
        action = QAction(icon, text, self)
        action.setShortcut(shortcut)
        native = QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)
        action.setToolTip(f"{text.rstrip('…')} ({native})")
        return action

    def _build_toolbar(self) -> None:
        pixmap = QStyle.StandardPixmap
        new = self._action(
            self.tr("New"), "document-new", pixmap.SP_FileIcon, QKeySequence.StandardKey.New
        )
        open_ = self._action(
            self.tr("Open…"),
            "document-open",
            pixmap.SP_DialogOpenButton,
            QKeySequence.StandardKey.Open,
        )
        save = self._action(
            self.tr("Save"),
            "document-save",
            pixmap.SP_DialogSaveButton,
            QKeySequence.StandardKey.Save,
        )
        save_as = self._action(
            self.tr("Save As…"),
            "document-save-as",
            pixmap.SP_DriveFDIcon,
            QKeySequence.StandardKey.SaveAs,
        )
        settings = self._action(
            self.tr("Settings"),
            "configure",
            pixmap.SP_FileDialogDetailedView,
            QKeySequence.StandardKey.Preferences,
        )
        save.setToolTip(self.tr("Build the .cia (Ctrl+S)"))
        new.triggered.connect(self._on_new)
        open_.triggered.connect(self._on_open)
        save.triggered.connect(self._on_save)
        save_as.triggered.connect(self._on_save_as)
        settings.triggered.connect(self._open_settings_window)
        self._file_actions = [new, open_, save, save_as]

        toolbar = QToolBar(self.tr("Main"))
        toolbar.setObjectName("main-toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in self._file_actions:
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(settings)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self._title_id)
        self.addToolBar(toolbar)

    def _build_central(self) -> None:
        preview_pane = QWidget()
        preview_pane.setMinimumWidth(_PREVIEW_MIN_WIDTH)
        column = QVBoxLayout(preview_pane)
        column.addWidget(self._preview)
        column.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("editor-splitter")
        splitter.addWidget(_scrolling(self._game))
        splitter.addWidget(_scrolling(self._presentation))
        splitter.addWidget(preview_pane)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([400, 440, 440])
        self.setCentralWidget(splitter)

    def _build_activity_dock(self) -> None:
        dock = QDockWidget(self.tr("Activity"), self)
        dock.setObjectName("activity")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(self._activity)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [150], Qt.Orientation.Vertical)

    def _connect_signals(self) -> None:
        self._game.changed.connect(self._on_content_changed)
        self._presentation.changed.connect(self._mark_dirty)
        self._presentation.previews_changed.connect(self._preview.show_artwork)
        self._presentation.settings_requested.connect(lambda: self._open_settings(PAGE_STEAMGRIDDB))
        self._title_id.changed.connect(self._on_content_changed)

    # ── Settings and catalogs ────────────────────────────────────────────

    def _apply_settings_to_panels(self) -> None:
        general = self._settings.general
        self._game.set_sd_card(general.sd_card_path)
        self._game.set_default_manufacturer(general.manufacturer)
        self._presentation.set_steamgriddb(self._settings.steamgriddb)
        self._tools = find_toolchain(self._settings.toolchain)
        if self._tools.complete:
            self._toolchain_label.setText(self.tr("Toolchain ready"))
            self._toolchain_label.setToolTip(str(self._tools.makerom.parent))
        else:
            self._toolchain_label.setText(
                self.tr('<a href="#">Toolchain incomplete: {missing}</a>').format(
                    missing=", ".join(self._tools.missing)
                )
            )

    def _load_catalogs(self) -> None:
        try:
            self._cores = CoreRegistry.load(DEFAULT_CORES_JSON)
        except CoreCatalogError as exc:
            self._cores = None
            _log.error("%s", exc)
        self._game.set_cores(self._cores)
        self._reload_registry()

    def _reload_registry(self) -> None:
        path = self._settings.general.registry_path
        try:
            self._registry = TitleIdRegistry.load(path)
        except (OSError, ValueError) as exc:
            self._registry = None
            _log.error("Cannot read the Title ID registry %s: %s", path, exc)

    @Slot()
    def _open_settings_window(self) -> None:
        self._open_settings()

    def _open_settings(self, page: int = 0) -> None:
        dialog = SettingsDialog(self._settings, self, page=page)
        dialog.applied.connect(self._apply_settings)
        dialog.exec()

    @Slot(object)
    def _apply_settings(self, settings: Settings) -> None:
        registry_changed = settings.general.registry != self._settings.general.registry
        self._settings = settings
        try:
            save_settings(settings)
        except OSError as exc:
            _log.error("Cannot save the settings: %s", exc)
        self._apply_settings_to_panels()
        if registry_changed:
            self._reload_registry()
            self._refresh_title_id()

    # ── Document state ───────────────────────────────────────────────────

    def _update_title(self) -> None:
        self._document_label.setText(self._document.status_text)
        self._document_label.setToolTip(str(self._document.path or ""))
        # "[*]" is where Qt shows the "modified" marker.
        self.setWindowTitle(f"{self._document.display_name}[*] — {APP_TITLE} {__version__}")
        self.setWindowModified(self._document.dirty)

    def _mark_dirty(self) -> None:
        if not self._document.dirty:
            self._document.dirty = True
            self._update_title()

    def _on_content_changed(self) -> None:
        self._presentation.set_long_name(self._game.fields().long_name)
        self._refresh_title_id()
        self._mark_dirty()

    def _replaces_document_id(self, manual_unique_id: int | None) -> bool:
        """Whether ``manual_unique_id`` is the Title ID this document already has.

        Only then may the registry's entry for the document's previous
        contents be superseded (see ``ForwarderRequest.replace_existing_id``).
        """
        return manual_unique_id is not None and manual_unique_id == self._document.unique_id

    def _identity(self) -> ForwarderIdentity | None:
        fields = self._game.fields()
        if not (fields.core and fields.rom_path and fields.long_name):
            return None
        return make_request(
            core=fields.core,
            rom_path=fields.rom_path,
            long_name=fields.long_name,
            short_name=fields.short_name,
            manufacturer=fields.manufacturer,
            output=Path(),
        ).identity()

    def _unique_id_problem(self) -> tuple[int | None, str | None]:
        """``(unique_id, None)``, ``(None, error)`` or ``(None, None)`` if incomplete."""
        identity = self._identity()
        if identity is None or self._registry is None or self._cores is None:
            return None, None
        manual = self._title_id.manual_unique_id()
        try:
            unique_id = preview_unique_id(
                identity,
                self._cores.all_unique_ids(),
                self._registry,
                manual,
                self._replaces_document_id(manual),
            )
        except TitleIdCollisionError as exc:
            return None, str(exc)
        return unique_id, None

    def _refresh_title_id(self) -> None:
        unique_id, error = self._unique_id_problem()
        if error:
            self._title_id.show_error(error)
        elif unique_id is None:
            self._title_id.show_incomplete()
        else:
            self._title_id.show_unique_id(unique_id)

    def _confirm_discard(self, intent: str) -> bool:
        """Ask before throwing away unsaved edits; ``intent`` completes the question."""
        if not self._document.dirty:
            return True
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            self.tr("There are unsaved changes.\nDiscard them and {intent}?").format(intent=intent),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _discard_loaded_files(self) -> None:
        if self._loaded_dir is not None:
            shutil.rmtree(self._loaded_dir, ignore_errors=True)
            self._loaded_dir = None

    def _set_busy(self, busy: bool) -> None:
        for action in self._file_actions:
            action.setEnabled(not busy)
        self.centralWidget().setEnabled(not busy)
        self._title_id.setEnabled(not busy)
        self._activity.set_busy(busy, self.tr("Building…") if busy else "")

    # ── New / Open ───────────────────────────────────────────────────────

    def _on_new(self) -> None:
        if not self._confirm_discard(self.tr("start a new forwarder")):
            return
        self._discard_loaded_files()
        self._game.reset()
        self._presentation.reset()
        self._title_id.set_auto()
        self._document.reset()
        self._refresh_title_id()
        self._update_title()
        self._activity.set_status(self.tr("New forwarder"))

    def _start_dir(self) -> Path:
        if self._document.path is not None:
            return self._document.path.parent
        return self._settings.general.output_path

    def _on_open(self) -> None:
        path = choose_cia_to_open(self, self._start_dir())
        if path is None:
            return
        # Read before asking about unsaved changes, so a bad file costs nothing.
        try:
            loaded = read_forwarder_cia(path)
        except (CiaReadError, OSError) as exc:
            _log.error("%s: %s", path.name, exc)
            QMessageBox.critical(
                self,
                APP_TITLE,
                self.tr("Could not open '{name}':\n\n{error}").format(name=path.name, error=exc),
            )
            return
        if self._confirm_discard(self.tr("open '{name}'").format(name=path.name)):
            self._apply_loaded(loaded, path)

    def _apply_loaded(self, loaded: LoadedForwarder, path: Path) -> None:
        self._discard_loaded_files()
        self._loaded_dir = Path(tempfile.mkdtemp(prefix="3ds-forwarder-loaded-"))
        assets = loaded.write_assets(self._loaded_dir)
        self._game.set_fields(
            GameFields(
                core=loaded.core,
                rom_path=loaded.rom_path,
                short_name=loaded.short_name,
                long_name=loaded.long_name,
                manufacturer=loaded.manufacturer,
            )
        )
        self._presentation.load_from_cia(
            loaded.icon_png, loaded.banner_png, assets.audio, self.tr("From the CIA")
        )
        # The loaded Title ID is kept, not re-derived from the (editable) fields.
        self._title_id.set_manual_unique_id(loaded.unique_id)
        self._document.bind(path, loaded.unique_id)
        self._refresh_title_id()
        self._update_title()
        _log.info("Opened %s (Title ID 0x%016X)", path, loaded.title_id)
        for warning in loaded.warnings:
            _log.warning("%s", warning)

    # ── Save / Save As ───────────────────────────────────────────────────

    def _check_ready(self) -> bool:
        """Tell the user (and return ``False``) if a build cannot start."""
        problem = self._game.missing()
        if problem is None:
            problem = self._unique_id_problem()[1]
        if problem is None and not self._tools.complete:
            problem = self.tr(
                "The toolchain is incomplete (missing: {missing}). See Settings › Toolchain."
            ).format(missing=", ".join(self._tools.missing))
        if problem:
            _log.warning("%s", problem)
            QMessageBox.warning(self, APP_TITLE, problem)
            return False
        return True

    def _ask_save_path(self) -> Path | None:
        name = default_cia_filename(self._game.fields().rom_path)
        return choose_cia_to_save(self, self._start_dir(), name)

    def _on_save(self) -> None:
        """Replace the open CIA, or behave like *Save As* if there is no file yet."""
        if not self._check_ready():
            return
        path = self._document.path or self._ask_save_path()
        if path is not None:
            self._start_build(path)

    def _on_save_as(self) -> None:
        if not self._check_ready():
            return
        path = self._ask_save_path()
        if path is not None:
            self._start_build(path)

    def _start_build(self, output: Path) -> None:
        fields = self._game.fields()
        manual = self._title_id.manual_unique_id()
        self._build_dir = Path(tempfile.mkdtemp(prefix="3ds-forwarder-ui-"))
        icon, banner = self._presentation.write_build_images(self._build_dir)
        request = make_request(
            core=fields.core,
            rom_path=fields.rom_path,
            long_name=fields.long_name,
            short_name=fields.short_name,
            manufacturer=fields.manufacturer,
            output=output,
            icon=icon,
            banner=banner,
            audio=self._presentation.jingle_path(),
            platform_logo=self._presentation.platform_logo_path(),
            manual_unique_id=manual,
            replace_existing_id=self._replaces_document_id(manual),
        )
        _log.info("Building “%s” → %s", fields.long_name, output)
        self._set_busy(True)
        self._worker = BuildWorker(request, self._tools, self._settings.general.registry_path, self)
        self._worker.succeeded.connect(self._on_build_succeeded)
        self._worker.failed.connect(self._on_build_failed)
        self._worker.finished.connect(self._on_build_finished)
        self._worker.start()

    def _on_build_finished(self) -> None:
        if self._build_dir is not None:
            shutil.rmtree(self._build_dir, ignore_errors=True)
            self._build_dir = None
        self._set_busy(False)

    def _on_build_succeeded(self, unique_id: int, output: Path) -> None:
        self._document.bind(output, unique_id)
        # From now on this file *is* that Title ID: pin it, so that editing and
        # saving again replaces the CIA. Ticking "Auto" opts back out.
        self._title_id.set_manual_unique_id(unique_id)
        self._reload_registry()  # the build recorded the ID
        self._refresh_title_id()
        self._update_title()
        self._activity.set_status(self.tr("Saved {name}").format(name=output.name))

    def _on_build_failed(self, message: str) -> None:
        _log.error("%s", message)
        self._activity.set_status(self.tr("Build failed"))
        QMessageBox.critical(self, APP_TITLE, message)

    # ── Layout persistence and closing ───────────────────────────────────

    @staticmethod
    def _ui_state() -> QSettings:
        return QSettings(str(paths.ui_state_file()), QSettings.Format.IniFormat)

    def _restore_layout(self) -> None:
        state = self._ui_state()
        splitter = self.centralWidget()
        for key, restore in (
            ("window/geometry", self.restoreGeometry),
            ("window/state", self.restoreState),
            ("editor/splitter", splitter.restoreState),
        ):
            value = state.value(key)
            if isinstance(value, QByteArray):
                restore(value)

    def _save_layout(self) -> None:
        state = self._ui_state()
        state.setValue("window/geometry", self.saveGeometry())
        state.setValue("window/state", self.saveState())
        state.setValue("editor/splitter", self.centralWidget().saveState())
        state.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        """Refuse while building, confirm unsaved changes, remember the layout."""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, APP_TITLE, self.tr("A build is running. Wait for it to finish.")
            )
            event.ignore()
            return
        if not self._confirm_discard(self.tr("quit")):
            event.ignore()
            return
        self._save_layout()
        self._discard_loaded_files()
        get_logger().removeHandler(self._log_handler)
        super().closeEvent(event)
