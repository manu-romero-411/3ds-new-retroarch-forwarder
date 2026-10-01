"""main_window.py — Top-level window: top bar + form + artwork panel + log.

Owns the document workflow -- New / Open / Save / Save As, the "unsaved
changes" confirmation and the window title -- and is the only place that
calls into the backend to read a CIA (``tools.cia_reader``) or write one
(``tools.build_forwarder``, via ``BuildWorker``). Everything else is
delegated: field handling to ``BuildForm``, artwork to ``ArtworkPanel``,
the file actions and the Title ID strip to ``TopBar``, path rules and CIA
parsing to the backend.

Loading a CIA never patches it: its fields are recovered into the form and
saving rebuilds it from scratch, keeping the Title ID it had (see
``ForwarderRequest.replace_existing_id``).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from tools.build_forwarder import ForwarderRequest, default_cia_filename, default_save_dir
from tools.cia_reader import CiaReadError, LoadedForwarder, read_forwarder_cia
from tools.title_id import TitleIdCollisionError

from .dialogs.cia_file_dialogs import choose_cia_to_open, choose_cia_to_save
from .document import Document
from .settings import AppSettings
from .widgets.artwork_panel import ArtworkPanel
from .widgets.build_form import BuildForm
from .widgets.console_preview import ConsolePreview
from .widgets.elided_label import ElidedLabel
from .widgets.log_panel import LogPanel
from .widgets.title_id_bar import TitleIdBar
from .widgets.top_bar import TopBar
from .workers.build_worker import BuildWorker

WINDOW_TITLE = "3DS Forwarder Builder"
DEFAULT_WINDOW_SIZE = QSize(920, 800)
# The right-hand pane holds the console preview, which only reads well when wide.
PREVIEW_PANE_MIN_WIDTH = 240
SPLITTER_SIZES = [470, 430]
# The document label is set a little smaller than the rest of the UI.
DOCUMENT_LABEL_SCALE = 0.85
ELLIPSIS = "\u2026"


class MainWindow(QWidget):
    """Assembles the top bar, form, artwork panel and log, and runs the file workflow."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(DEFAULT_WINDOW_SIZE)

        self._settings = AppSettings()
        self._document = Document()
        self._build_worker: BuildWorker | None = None
        self._build_tmp_dir: Path | None = None
        # Holds files extracted from a loaded CIA that the form points at
        # (the banner audio); lives as long as that CIA is the open document.
        self._loaded_assets_dir: Path | None = None

        self._build_form = BuildForm(self)
        self._artwork_panel = ArtworkPanel(self._settings, self._build_form.long_name_text, self)
        self._console_preview = ConsolePreview(self)
        self._title_id_bar = TitleIdBar(self)
        self._log_panel = LogPanel(self)
        self._actions = self._create_actions()
        self._top_bar = TopBar(self._actions, self._title_id_bar, self)
        self._document_label = self._create_document_label()
        self._editor_area = self._build_editor_area()

        self._connect_signals()
        self._assemble_layout()

        self._console_preview.show_artwork(*self._artwork_panel.current_previews())
        self._refresh_title_id()
        self._update_window_title()

    # ── Construction ─────────────────────────────────────────────────────

    def _create_actions(self) -> list[QAction]:
        """The file actions, in toolbar order. Shortcuts work anywhere in the window."""
        style = self.style()
        specs = (
            ("New", "document-new", QStyle.SP_FileIcon, QKeySequence.New, self._on_new),
            (
                "Open\u2026",
                "document-open",
                QStyle.SP_DialogOpenButton,
                QKeySequence.Open,
                self._on_open,
            ),
            (
                "Save",
                "document-save",
                QStyle.SP_DialogSaveButton,
                QKeySequence.Save,
                self._on_save,
            ),
            (
                "Save As\u2026",
                "document-save-as",
                QStyle.SP_DriveFDIcon,
                QKeySequence.SaveAs,
                self._on_save_as,
            ),
        )
        actions = []
        for text, theme_name, fallback_icon, shortcut, handler in specs:
            icon = QIcon.fromTheme(theme_name, style.standardIcon(fallback_icon))
            action = QAction(icon, text, self)
            action.setShortcut(shortcut)
            key_text = QKeySequence(shortcut).toString(QKeySequence.NativeText)
            action.setToolTip(f"{text.rstrip(ELLIPSIS)} ({key_text})")
            action.triggered.connect(handler)
            self.addAction(action)
            actions.append(action)
        return actions

    def _create_document_label(self) -> ElidedLabel:
        """The small line under the top bar naming the file being edited."""
        label = ElidedLabel(parent=self)
        font = label.font()
        font.setPointSizeF(font.pointSizeF() * DOCUMENT_LABEL_SCALE)
        label.setFont(font)
        label.setForegroundRole(QPalette.PlaceholderText)
        label.setContentsMargins(6, 0, 6, 0)
        return label

    def _build_editor_area(self) -> QSplitter:
        """Left: the fields and artwork controls (scrolls). Right: the live preview (stays put)."""
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self._build_form)
        controls_layout.addWidget(self._artwork_panel)
        controls_layout.addStretch(1)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls)
        # No horizontal scrollbar: the controls must shrink to fit the column
        # instead of the column growing/scrolling to fit them.
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # ...and the window must not shrink past what they need, or the preview
        # pane would squeeze them into an unusable sliver.
        controls_scroll.setMinimumWidth(
            controls.minimumSizeHint().width()
            + controls_scroll.verticalScrollBar().sizeHint().width()
            + 2 * controls_scroll.frameWidth()
        )

        # The preview is not inside a scroll area on purpose: while the artwork
        # is being edited it has to stay in view to show the effect.
        preview_pane = QWidget()
        preview_pane.setMinimumWidth(PREVIEW_PANE_MIN_WIDTH)
        preview_layout = QVBoxLayout(preview_pane)
        preview_layout.addWidget(self._console_preview)
        preview_layout.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(preview_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes(SPLITTER_SIZES)
        return splitter

    def _connect_signals(self) -> None:
        self._artwork_panel.log_message.connect(self._append_log)
        self._artwork_panel.changed.connect(self._mark_dirty)
        self._artwork_panel.previews_changed.connect(self._console_preview.show_artwork)
        self._build_form.log_message.connect(self._append_log)
        self._build_form.fields_changed.connect(self._on_content_changed)
        self._build_form.catalogs_changed.connect(self._refresh_title_id)
        self._title_id_bar.changed.connect(self._on_content_changed)

    def _assemble_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(self._top_bar)
        outer.addWidget(self._document_label)
        outer.addWidget(self._editor_area, 3)
        outer.addWidget(self._log_panel, 1)

    # ── Document state ───────────────────────────────────────────────────

    def _append_log(self, message: str) -> None:
        self._log_panel.append(message)

    def _update_window_title(self) -> None:
        """Refresh everything that names the current document (title bar and label)."""
        self._document_label.setText(self._document.status_text)
        self._document_label.setToolTip(str(self._document.path or ""))
        # "[*]" is Qt's placeholder for the "modified" marker.
        self.setWindowTitle(f"{self._document.display_name}[*] \u2014 {WINDOW_TITLE}")
        self.setWindowModified(self._document.dirty)

    def _mark_dirty(self) -> None:
        if not self._document.dirty:
            self._document.dirty = True
            self._update_window_title()

    def _on_content_changed(self) -> None:
        self._refresh_title_id()
        self._mark_dirty()

    def _replaces_document_id(self, manual_unique_id: int | None) -> bool:
        """Whether ``manual_unique_id`` is the Title ID this document already has.

        Only then may the registry's stale entry for the document's previous
        contents be superseded (see ``ForwarderRequest.replace_existing_id``).
        """
        return manual_unique_id is not None and manual_unique_id == self._document.unique_id

    def _refresh_title_id(self) -> None:
        """Recompute the Title ID for the current fields and show it in the top bar."""
        manual = self._title_id_bar.manual_unique_id()
        try:
            unique_id = self._build_form.preview_unique_id(
                manual, self._replaces_document_id(manual)
            )
        except TitleIdCollisionError as exc:
            self._title_id_bar.show_error(str(exc))
            return
        if unique_id is None:
            self._title_id_bar.show_incomplete()
        else:
            self._title_id_bar.show_unique_id(unique_id)

    def _confirm_discard(self, intent: str) -> bool:
        """Ask before throwing away unsaved edits; ``intent`` completes "Discard them and ...?"."""
        if not self._document.dirty:
            return True
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            f"There are unsaved changes.\nDiscard them and {intent}?",
            QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Discard

    def _discard_loaded_assets(self) -> None:
        if self._loaded_assets_dir is not None:
            shutil.rmtree(self._loaded_assets_dir, ignore_errors=True)
            self._loaded_assets_dir = None

    def _set_busy(self, busy: bool) -> None:
        """Lock the editing surface (and file actions) while a build is running."""
        for action in self._actions:
            action.setEnabled(not busy)
        self._top_bar.setEnabled(not busy)
        self._editor_area.setEnabled(not busy)

    # ── New ──────────────────────────────────────────────────────────────

    def _on_new(self) -> None:
        if not self._confirm_discard("start a new forwarder"):
            return
        self._discard_loaded_assets()
        self._build_form.reset()
        self._artwork_panel.reset()
        self._title_id_bar.set_auto()
        self._document.reset()
        self._refresh_title_id()
        self._update_window_title()
        self._append_log("\u25b8 New forwarder.")

    # ── Open ─────────────────────────────────────────────────────────────

    def _on_open(self) -> None:
        start_dir = self._document.path.parent if self._document.path else default_save_dir()
        path = choose_cia_to_open(self, start_dir)
        if path is None:
            return

        # Read before asking about unsaved changes, so a bad file costs nothing.
        try:
            loaded = read_forwarder_cia(path)
        except CiaReadError as exc:
            self._append_log(f"\u2717 {path.name}: {exc}")
            QMessageBox.critical(self, WINDOW_TITLE, f"Could not open '{path.name}':\n\n{exc}")
            return

        if self._confirm_discard(f"open '{path.name}'"):
            self._apply_loaded(loaded, path)

    def _apply_loaded(self, loaded: LoadedForwarder, path: Path) -> None:
        """Populate the whole window from ``loaded`` and bind the document to ``path``."""
        self._discard_loaded_assets()
        self._loaded_assets_dir = Path(tempfile.mkdtemp(prefix="3ds_forwarder_ui_loaded_"))
        assets = loaded.write_assets(self._loaded_assets_dir)

        self._build_form.set_fields(
            core=loaded.core,
            rom_path=loaded.rom_path,
            short_name=loaded.short_name,
            long_name=loaded.long_name,
            manufacturer=loaded.manufacturer,
            audio=assets.audio,
            audio_label="From the CIA",
        )
        self._artwork_panel.reset()
        if loaded.icon_png:
            self._artwork_panel.load_icon(loaded.icon_png, f"From CIA \u00b7 {path.name}")
        if loaded.banner_png:
            self._artwork_panel.load_banner(loaded.banner_png)
        # The loaded Title ID is kept, not re-derived from the (editable) fields.
        self._title_id_bar.set_manual_unique_id(loaded.unique_id)

        self._document.bind(path, loaded.unique_id)
        self._refresh_title_id()
        self._update_window_title()

        self._append_log(f"\u25b8 Opened {path} \u2014 Title ID 0x{loaded.title_id:016X}")
        for warning in loaded.warnings:
            self._append_log(f"! {warning}")

    # ── Save / Save As ───────────────────────────────────────────────────

    def _validate_fields(self, fields: dict, manual_unique_id: int | None) -> str | None:
        """Return an error message if something required is missing/invalid, else ``None``."""
        if not self._build_form.core_registry_valid():
            return (
                f"The core catalog could not be loaded from "
                f"'{self._build_form.cores_json_path()}'. Check the path under Advanced."
            )
        if not fields["core"]:
            return "Pick a RetroArch core."
        if not self._build_form.core_exists(fields["core"]):
            return f"Core '{fields['core']}' is not in the core catalog."
        if not fields["rom_path"]:
            return "Enter the ROM path on the SD card."
        if not fields["long_name"]:
            return "Enter the long name of this forwarder."
        return self._build_form.unique_id_error(
            manual_unique_id, self._replaces_document_id(manual_unique_id)
        )

    def _collect_valid_fields(self) -> dict | None:
        """The form's fields, or ``None`` (after telling the user why) if they can't be built."""
        fields = self._build_form.collect_fields()
        error = self._validate_fields(fields, self._title_id_bar.manual_unique_id())
        if error:
            self._append_log(f"\u2717 {error}")
            QMessageBox.warning(self, WINDOW_TITLE, error)
            return None
        return fields

    def _ask_save_path(self, fields: dict) -> Path | None:
        start_dir = self._document.path.parent if self._document.path else default_save_dir()
        return choose_cia_to_save(self, start_dir, default_cia_filename(fields["rom_path"]))

    def _on_save(self) -> None:
        """Replace the open CIA, or behave like Save As if the document has no file yet."""
        fields = self._collect_valid_fields()
        if fields is None:
            return
        path = self._document.path or self._ask_save_path(fields)
        if path is not None:
            self._start_build(path, fields)

    def _on_save_as(self) -> None:
        fields = self._collect_valid_fields()
        if fields is None:
            return
        path = self._ask_save_path(fields)
        if path is not None:
            self._start_build(path, fields)

    def _start_build(self, output: Path, fields: dict) -> None:
        manual_unique_id = self._title_id_bar.manual_unique_id()
        self._build_tmp_dir = Path(tempfile.mkdtemp(prefix="3ds_forwarder_ui_"))
        icon_path, banner_path = self._artwork_panel.write_temp_assets(self._build_tmp_dir)

        request = ForwarderRequest(
            core=fields["core"],
            rom_path=fields["rom_path"],
            name=fields["name"],
            short_name=fields["short_name"],
            long_name=fields["long_name"],
            manufacturer=fields["manufacturer"],
            output=output,
            icon=icon_path,
            banner=banner_path,
            audio=fields["audio"],
            platform_logo=self._artwork_panel.platform_logo_path(),
            manual_unique_id=manual_unique_id,
            replace_existing_id=self._replaces_document_id(manual_unique_id),
        )

        self._append_log(f"\u25b8 Saving '{fields['long_name']}' \u2192 {output}\u2026")
        self._set_busy(True)

        self._build_worker = BuildWorker(
            request,
            cores_json=self._build_form.cores_json_path(),
            title_id_registry_path=self._build_form.title_id_registry_path(),
            parent=self,
        )
        self._build_worker.log_line.connect(self._append_log)
        self._build_worker.succeeded.connect(self._on_build_succeeded)
        self._build_worker.failed.connect(self._on_build_failed)
        self._build_worker.finished.connect(self._on_build_finished)
        self._build_worker.start()

    def _on_build_finished(self) -> None:
        if self._build_tmp_dir and self._build_tmp_dir.exists():
            shutil.rmtree(self._build_tmp_dir, ignore_errors=True)
        self._build_tmp_dir = None
        self._set_busy(False)

    def _on_build_succeeded(self, unique_id: int, output: Path) -> None:
        self._document.bind(output, unique_id)
        # From now on this file *is* that Title ID: pin it, so that editing
        # the fields and saving again replaces the CIA instead of silently
        # re-deriving a different ID. Ticking "Auto" opts back out.
        self._title_id_bar.set_manual_unique_id(unique_id)
        # The build just wrote this forwarder into the registry file.
        self._build_form.refresh_title_id_registry()
        self._update_window_title()
        self._append_log(f"\u2713 Saved. Unique ID 0x{unique_id:05X} \u2192 {output}")
        QMessageBox.information(self, WINDOW_TITLE, f"Forwarder saved successfully:\n{output}")

    def _on_build_failed(self, message: str) -> None:
        self._append_log(f"\u2717 {message}")
        QMessageBox.critical(self, WINDOW_TITLE, message)

    # ── Closing ──────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        if self._build_worker is not None and self._build_worker.isRunning():
            QMessageBox.information(
                self, WINDOW_TITLE, "A save is in progress. Wait for it to finish before closing."
            )
            event.ignore()
            return
        if not self._confirm_discard("quit"):
            event.ignore()
            return
        self._discard_loaded_assets()
        event.accept()
