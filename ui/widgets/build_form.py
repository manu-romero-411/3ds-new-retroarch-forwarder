"""build_form.py — The forwarder fields the CLI asks for.

Mirrors ``tools/build_forwarder.parse_args`` field-for-field, minus the ones
that now live elsewhere: core, ROM path, short/long name, manufacturer, the
banner jingle and (tucked under "Advanced") the catalog/registry path
overrides.
The output file is chosen through the window's Save / Save As actions, and
the Unique ID / Title ID controls live in the top bar. There is no separate
"Name" field: the forwarder's internal identifier is its long name.

This widget only collects, validates and (re)populates those fields; it
never talks to SteamGridDB or starts a build itself. It does own the core
catalog and the Title ID registry, so it is what can answer "which Unique
ID would these fields get?" -- see :meth:`BuildForm.preview_unique_id`,
which goes through the backend's read-only ``preview_unique_id()`` and so
never writes to the registry.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.build_forwarder import DEFAULT_MANUFACTURER, normalize_sd_path
from tools.cores_registry import DEFAULT_CORES_JSON, CoreRegistry
from tools.media_catalog import JINGLE_RULES, list_jingles, validate_jingle
from tools.rom_names import suggest_title
from tools.title_id import (
    DEFAULT_REGISTRY_PATH,
    ForwarderIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    preview_unique_id,
)

from ..dialogs.rom_picker import choose_rom_on_sd
from ..jingle_player import JinglePlayer
from .asset_choice import AssetChoice


class BuildForm(QGroupBox):
    """Collects every field ``build_forwarder()`` needs, with the same defaults as the CLI."""

    long_name_changed = Signal(str)
    # Something worth telling the user, for the window's log.
    log_message = Signal(str)
    # Any edit to the document's content (core, ROM, names, manufacturer, audio).
    fields_changed = Signal()
    # The core catalog or Title ID registry was swapped/reloaded, so anything
    # derived from them (the Title ID preview) must be recomputed.
    catalogs_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Forwarder details", parent)

        self._core_registry: CoreRegistry | None = None
        self._cores_json_path = DEFAULT_CORES_JSON

        self._title_id_registry: TitleIdRegistry | None = None
        self._title_id_registry_path = DEFAULT_REGISTRY_PATH
        self._reload_title_id_registry()

        # The title last derived from the ROM path. A name field that is still
        # empty or equal to it has not been touched by the user, so it keeps
        # following the ROM; one that differs is the user's and is left alone.
        self._suggested_title = ""

        # Created by _build_jingle_row(); declared here so they exist from construction.
        self._jingle_player: JinglePlayer
        self._play_button: QToolButton

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_main_form())
        layout.addWidget(self._build_advanced_group())

    # ── Main fields ──────────────────────────────────────────────────────

    def _build_main_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self._core_combo = QComboBox()
        self._core_combo.setEditable(True)
        self._core_combo.setInsertPolicy(QComboBox.NoInsert)
        # Size to a few characters, not to the longest core name in the
        # catalog: otherwise the combo's width alone would push the form
        # (and the Browse buttons under it) past the edge of the column.
        self._core_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._core_combo.setMinimumContentsLength(12)
        self._reload_core_registry()
        form.addRow("Core (libretro name):", self._core_combo)

        self._core_status_label = QLabel()
        self._core_status_label.setStyleSheet("font-size: 8pt; color: palette(mid);")
        form.addRow("", self._core_status_label)

        self._rom_edit, rom_row = self._build_path_row(
            "roms/snes/Super Mario World.sfc",
            self._browse_rom,
            button_text="Browse SD\u2026",
            button_tooltip="Pick the ROM on the 3DS SD card (it must be inserted).",
        )
        self._rom_edit.textChanged.connect(self._autofill_names)
        form.addRow("ROM path (on the SD card):", rom_row)

        self._short_name_edit = QLineEdit()
        self._short_name_edit.setPlaceholderText("Filled from the ROM name (empty: long name)")
        form.addRow("Short name (SMDH):", self._short_name_edit)

        self._long_name_edit = QLineEdit()
        self._long_name_edit.setPlaceholderText(
            "Filled from the ROM name \u2014 also the SteamGridDB search term"
        )
        self._long_name_edit.textChanged.connect(self.long_name_changed)
        form.addRow("Long name (SMDH):", self._long_name_edit)

        self._manufacturer_edit = QLineEdit(DEFAULT_MANUFACTURER)
        form.addRow("Manufacturer (SMDH):", self._manufacturer_edit)

        self._jingle_choice = AssetChoice(
            none_label="Silence (default)",
            list_entries=list_jingles,
            validate=validate_jingle,
            dialog_title="Choose a banner jingle",
            file_filter="WAV files (*.wav)",
            rules=JINGLE_RULES,
        )
        form.addRow("Banner jingle:", self._build_jingle_row())

        self._connect_change_signals()
        return form

    def _build_jingle_row(self) -> QWidget:
        """The jingle drop-down with a play/stop button next to it."""
        self._jingle_player = JinglePlayer(self)
        self._jingle_player.playing_changed.connect(self._update_play_button)
        self._jingle_player.failed.connect(self.log_message)

        self._play_button = QToolButton()
        self._play_button.clicked.connect(self._toggle_jingle)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._jingle_choice, 1)
        layout.addWidget(self._play_button)
        self._update_play_button(False)
        return row

    def _update_play_button(self, playing: bool) -> None:
        """Show stop while a jingle sounds, play otherwise; only usable with a jingle chosen."""
        icon = QStyle.SP_MediaStop if playing else QStyle.SP_MediaPlay
        self._play_button.setIcon(self.style().standardIcon(icon))
        self._play_button.setToolTip("Stop the jingle" if playing else "Play the jingle")
        self._play_button.setEnabled(playing or self._jingle_choice.selected_path() is not None)

    def _toggle_jingle(self) -> None:
        path = self._jingle_choice.selected_path()
        if self._jingle_player.is_playing or path is None:
            self._jingle_player.stop()
        else:
            self._jingle_player.play(path)

    def _on_jingle_changed(self) -> None:
        """A different jingle (or none) was chosen: silence the old one and tell the form."""
        self._jingle_player.stop()
        self._update_play_button(False)
        self.fields_changed.emit()

    def _connect_change_signals(self) -> None:
        """Forward every content-bearing widget's edits as ``fields_changed``."""
        self._core_combo.currentTextChanged.connect(self.fields_changed)
        for edit in (
            self._rom_edit,
            self._short_name_edit,
            self._long_name_edit,
            self._manufacturer_edit,
        ):
            edit.textChanged.connect(self.fields_changed)
        self._jingle_choice.changed.connect(self._on_jingle_changed)

    def _build_path_row(
        self,
        hint: str,
        browse_slot,
        initial_text: str = "",
        button_text: str = "Browse\u2026",
        button_tooltip: str = "",
    ) -> tuple[QLineEdit, QWidget]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(initial_text)
        edit.setPlaceholderText(hint)
        row.addWidget(edit, 1)

        browse_button = QPushButton(button_text)
        browse_button.setToolTip(button_tooltip)
        browse_button.clicked.connect(lambda: browse_slot(edit))
        row.addWidget(browse_button)

        return edit, container

    # ── Advanced (catalog/registry overrides) ───────────────────────────

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

        self._cores_json_edit, cores_json_row = self._build_path_row(
            "", self._browse_cores_json, initial_text=str(DEFAULT_CORES_JSON)
        )
        self._cores_json_edit.editingFinished.connect(self._on_cores_json_path_changed)
        form.addRow("Core catalog (cores.json):", cores_json_row)

        self._title_id_registry_edit, registry_row = self._build_path_row(
            "", self._browse_title_id_registry, initial_text=str(DEFAULT_REGISTRY_PATH)
        )
        self._title_id_registry_edit.editingFinished.connect(
            self._on_title_id_registry_path_changed
        )
        form.addRow("Title ID registry:", registry_row)

        return group

    # ── Core registry loading ───────────────────────────────────────────

    def _reload_core_registry(self) -> None:
        self._core_combo.clear()
        try:
            self._core_registry = CoreRegistry.load(self._cores_json_path)
        except SystemExit:
            self._core_registry = None
            return

        entries = sorted(self._core_registry, key=lambda entry: entry.title.lower())
        for entry in entries:
            self._core_combo.addItem(f"{entry.title} ({entry.libretro_name})", entry.libretro_name)

        completer = QCompleter([entry.libretro_name for entry in entries], self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._core_combo.setCompleter(completer)
        self._core_combo.setCurrentIndex(-1)
        self._core_combo.setEditText("")

    def _on_cores_json_path_changed(self) -> None:
        self._cores_json_path = Path(self._cores_json_edit.text().strip() or DEFAULT_CORES_JSON)
        self._reload_core_registry()
        self.catalogs_changed.emit()

    # ── Title ID registry loading ───────────────────────────────────────

    def _reload_title_id_registry(self) -> None:
        try:
            self._title_id_registry = TitleIdRegistry.load(self._title_id_registry_path)
        except (OSError, ValueError):
            # Malformed/unreadable registry: keep going with no live preview
            # rather than crashing the form; the CLI/build path surfaces the
            # same error properly when it actually tries to build.
            self._title_id_registry = None

    def _on_title_id_registry_path_changed(self) -> None:
        self._title_id_registry_path = Path(
            self._title_id_registry_edit.text().strip() or str(DEFAULT_REGISTRY_PATH)
        )
        self._reload_title_id_registry()
        self.catalogs_changed.emit()

    # ── Browsing ─────────────────────────────────────────────────────────

    def _browse_rom(self, edit: QLineEdit) -> None:
        rom_path = choose_rom_on_sd(self)
        if rom_path:
            edit.setText(rom_path)

    def _autofill_names(self, rom_path: str) -> None:
        """Keep the name fields the user has not edited in sync with the ROM's file name."""
        previous, self._suggested_title = self._suggested_title, suggest_title(rom_path)
        for edit in (self._short_name_edit, self._long_name_edit):
            if edit.text() in ("", previous):
                edit.setText(self._suggested_title)

    def _browse_cores_json(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "Choose cores.json", "", "JSON files (*.json)"
        )
        if path_str:
            self._cores_json_edit.setText(path_str)
            self._on_cores_json_path_changed()

    def _browse_title_id_registry(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "Choose title_id_registry.json", "", "JSON files (*.json)"
        )
        if path_str:
            self._title_id_registry_edit.setText(path_str)
            self._on_title_id_registry_path_changed()

    # ── Identity ─────────────────────────────────────────────────────────

    def _current_identity(self) -> ForwarderIdentity | None:
        """Build a ForwarderIdentity from the current fields, or None if incomplete.

        Mirrors exactly what ``build_forwarder()`` hashes -- same field
        set, same ``normalize_sd_path()`` -- so the preview always matches
        what an actual build would produce.
        """
        core = self.selected_core()
        rom_path = self._rom_edit.text().strip()
        name = self.long_name_text()
        if not core or not rom_path or not name:
            return None
        return ForwarderIdentity(
            name=name,
            short_name=self._short_name_edit.text().strip() or name,
            long_name=name,
            manufacturer=self._manufacturer_edit.text().strip() or DEFAULT_MANUFACTURER,
            core=core,
            rom_path=normalize_sd_path(rom_path),
        )

    # ── Public API ───────────────────────────────────────────────────────

    def long_name_text(self) -> str:
        """Current long name, which doubles as the forwarder's internal name."""
        return self._long_name_edit.text().strip()

    def selected_core(self) -> str:
        """The raw libretro core name, whether picked from the dropdown or typed.

        Dropdown entries display ``"Title (libretro_name)"`` but carry the
        raw ``libretro_name`` as item data; free-typed text (matched against
        the completer, which only suggests raw names) is used verbatim.
        """
        index = self._core_combo.currentIndex()
        if index >= 0:
            data = self._core_combo.itemData(index)
            if data:
                return str(data)
        return self._core_combo.currentText().strip()

    def core_registry_valid(self) -> bool:
        return self._core_registry is not None

    def core_exists(self, core_name: str) -> bool:
        return self._core_registry is not None and self._core_registry.get(core_name) is not None

    def cores_json_path(self) -> Path:
        return self._cores_json_path

    def title_id_registry_path(self) -> Path:
        return Path(self._title_id_registry_edit.text().strip() or str(DEFAULT_REGISTRY_PATH))

    def preview_unique_id(
        self, manual_unique_id: int | None, replace_existing: bool = False
    ) -> int | None:
        """The Unique ID a build of the current fields would use, or ``None`` if unknown.

        ``None`` means the fields are incomplete or a catalog/registry could
        not be loaded. Raises ``TitleIdCollisionError`` if ``manual_unique_id``
        is unusable. Never writes to the registry.
        """
        identity = self._current_identity()
        if identity is None or self._title_id_registry is None or self._core_registry is None:
            return None
        return preview_unique_id(
            identity,
            self._core_registry.all_unique_ids(),
            self._title_id_registry,
            manual_unique_id,
            replace_existing,
        )

    def unique_id_error(
        self, manual_unique_id: int | None, replace_existing: bool = False
    ) -> str | None:
        """Why ``manual_unique_id`` can't be used for the current fields, or ``None`` if it can."""
        try:
            self.preview_unique_id(manual_unique_id, replace_existing)
        except TitleIdCollisionError as exc:
            return str(exc)
        return None

    def refresh_title_id_registry(self) -> None:
        """Re-read the registry from disk (a build just wrote to it)."""
        self._reload_title_id_registry()
        self.catalogs_changed.emit()

    def collect_fields(self) -> dict:
        """Return every field as plain strings/paths, same shape as ``ForwarderRequest``."""
        long_name = self.long_name_text()
        return {
            "core": self.selected_core(),
            "rom_path": self._rom_edit.text().strip(),
            "name": long_name,
            "short_name": self._short_name_edit.text().strip() or long_name,
            "long_name": long_name,
            "manufacturer": self._manufacturer_edit.text().strip() or DEFAULT_MANUFACTURER,
            "audio": self._jingle_choice.selected_path(),
        }

    def set_fields(
        self,
        core: str,
        rom_path: str,
        short_name: str,
        long_name: str,
        manufacturer: str,
        audio: Path | None,
        audio_label: str | None = None,
    ) -> None:
        """Fill every field, e.g. from a loaded CIA. ``fields_changed`` fires as usual.

        ``audio`` is taken as is (it is not checked against the jingle rules);
        ``audio_label`` is how it is named in the list when it is not one of
        the catalog's files.
        """
        index = self._core_combo.findData(core)
        if index >= 0:
            self._core_combo.setCurrentIndex(index)
        else:  # not in the catalog: show it anyway, validation will flag it
            self._core_combo.setCurrentIndex(-1)
            self._core_combo.setEditText(core)
        self._rom_edit.setText(rom_path)
        self._short_name_edit.setText(short_name)
        self._long_name_edit.setText(long_name)
        self._manufacturer_edit.setText(manufacturer)
        self._jingle_choice.select_path(audio, audio_label)

    def reset(self) -> None:
        """Back to an empty form, with the same defaults as at startup."""
        self.set_fields("", "", "", "", DEFAULT_MANUFACTURER, None)
        self._core_combo.setCurrentIndex(-1)
        self._core_combo.setEditText("")

    def set_core_status(self, message: str) -> None:
        self._core_status_label.setText(message)
