"""Game panel: which ROM goes in the CIA, for which console and core, and its names.

These are the fields the Title ID is derived from. The panel only collects
and (re)populates them; the window computes the Title ID preview and runs
the build.

Fields the user has not touched follow the ones they derive from: the
console follows the ROM's extension, the core follows the console, the
names follow the ROM's file name and the save folder follows the long name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.names import save_folder_name, suggest_title
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER
from forwarder3ds.core.systems import SystemCatalog
from forwarder3ds.gui.widgets.path_picker import PathPicker


@dataclass
class GameFields:
    """The panel's values, stripped."""

    rom: str
    console: str
    core: str
    folder: str
    short_name: str
    long_name: str
    manufacturer: str
    bezel: str = ""


class GamePanel(QWidget):  # pylint: disable=too-many-instance-attributes
    """ROM file, console, core, save folder, SMDH names and manufacturer."""

    #: Any edit to a field.
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._systems: SystemCatalog | None = None
        self._available_cores: set[str] = set()
        self._default_manufacturer = DEFAULT_MANUFACTURER
        self._last_dir = Path.home()
        # Last values derived automatically. A field still empty or equal to
        # its derived value has not been touched by the user, so it keeps
        # following; one that differs is the user's and is left alone.
        self._suggested_title = ""
        self._suggested_folder = ""
        self._suggested_core = ""

        self._rom_edit = QLineEdit()
        self._rom_edit.setPlaceholderText(self.tr("ROM file on this computer"))
        self._console_combo = QComboBox()
        self._core_combo = QComboBox()
        self._core_combo.setEditable(True)
        self._core_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText(self.tr("Same as the long name"))
        self._data_dir_label = QLabel()
        self._data_dir_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._data_dir_label.setWordWrap(True)
        self._long_name_edit = QLineEdit()
        self._long_name_edit.setPlaceholderText(self.tr("Filled from the ROM name"))
        self._long_name_edit.setToolTip(
            self.tr("Shown on the HOME menu; also the SteamGridDB search term.")
        )
        self._short_name_edit = QLineEdit()
        self._short_name_edit.setPlaceholderText(self.tr("Same as the long name"))
        self._manufacturer_edit = QLineEdit(DEFAULT_MANUFACTURER)
        self._bezel = PathPicker(
            select_dir=False,
            placeholder=self.tr("None"),
            file_filter=self.tr("Images (*.png *.webp *.jpg *.jpeg);;All files (*)"),
        )

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._build_game_group())
        column.addWidget(self._build_names_group())
        column.addWidget(self._build_ingame_group())
        column.addStretch(1)

        self._rom_edit.textChanged.connect(self._on_rom_changed)
        self._console_combo.currentIndexChanged.connect(self._on_console_changed)
        self._long_name_edit.textChanged.connect(self._follow_long_name)
        self._core_combo.currentTextChanged.connect(self.changed)
        self._folder_edit.textChanged.connect(self._show_data_dir)
        for edit in (
            self._rom_edit,
            self._folder_edit,
            self._short_name_edit,
            self._long_name_edit,
            self._manufacturer_edit,
            self._bezel.edit,
        ):
            edit.textChanged.connect(self.changed)

    # ── Construction ─────────────────────────────────────────────────────

    def _build_game_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Game"))
        form = QFormLayout(group)

        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse_rom)
        rom_row = QWidget()
        row = QHBoxLayout(rom_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._rom_edit, 1)
        row.addWidget(browse)
        form.addRow(self.tr("ROM:"), rom_row)
        form.addRow(self.tr("Console:"), self._console_combo)
        form.addRow(self.tr("RetroArch core:"), self._core_combo)
        form.addRow(self.tr("Save folder:"), self._folder_edit)
        form.addRow("", self._data_dir_label)

        hint = QLabel(
            self.tr(
                "The ROM is packed inside the CIA. Saves, states, core options and the "
                "game's RetroArch settings stay in its save folder; BIOS files go in "
                "sdmc:/saves/bios. CD games: a single .chd file."
            )
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        form.addRow("", hint)
        return group

    def _build_names_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("HOME menu"))
        form = QFormLayout(group)
        form.addRow(self.tr("Long name:"), self._long_name_edit)
        form.addRow(self.tr("Short name:"), self._short_name_edit)
        form.addRow(self.tr("Manufacturer:"), self._manufacturer_edit)
        return group

    def _build_ingame_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("In game"))
        form = QFormLayout(group)
        form.addRow(self.tr("Bezel:"), self._bezel)
        hint = QLabel(
            self.tr(
                "Drawn over the top screen (400x240); the game shows through its "
                "transparent part. A bezel.png in the save folder replaces it."
            )
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        form.addRow("", hint)
        return group

    # ── Configuration ────────────────────────────────────────────────────

    def set_catalogs(self, systems: SystemCatalog | None, available_cores: list[str]) -> None:
        """Fill the console and core lists (``systems`` ``None``: the catalog is unreadable)."""
        current = self.fields()
        self._systems = systems
        self._available_cores = set(available_cores)

        self._console_combo.blockSignals(True)
        self._console_combo.clear()
        self._console_combo.addItem(self.tr("Choose…"), "")
        for system in sorted(systems or [], key=lambda item: item.name.casefold()):
            self._console_combo.addItem(f"{system.name} ({system.console})", system.console)
        self._select_console(current.console)
        self._console_combo.blockSignals(False)

        cores = sorted({system.core for system in systems or []} | self._available_cores)
        self._core_combo.blockSignals(True)
        self._core_combo.clear()
        for core in cores:
            note = "" if core in self._available_cores else self.tr(" — no base built")
            self._core_combo.addItem(core + note, core)
        self._select_core(current.core)
        self._core_combo.blockSignals(False)

    def set_default_manufacturer(self, manufacturer: str) -> None:
        """Manufacturer used by :meth:`reset` and when the field is left empty."""
        self._default_manufacturer = manufacturer or DEFAULT_MANUFACTURER
        self._manufacturer_edit.setPlaceholderText(self._default_manufacturer)

    # ── Values ───────────────────────────────────────────────────────────

    def _selected_core(self) -> str:
        """The libretro name, whether picked from the list or typed."""
        index = self._core_combo.currentIndex()
        text = self._core_combo.currentText().strip()
        if index >= 0 and text == self._core_combo.itemText(index):
            return str(self._core_combo.itemData(index) or text)
        return text

    def _select_core(self, core: str) -> None:
        index = self._core_combo.findData(core) if core else -1
        if index >= 0:
            self._core_combo.setCurrentIndex(index)
        else:  # unknown (or empty): show it as typed, validation flags it
            self._core_combo.setCurrentIndex(-1)
            self._core_combo.setEditText(core)

    def _select_console(self, console: str) -> None:
        index = self._console_combo.findData(console)
        self._console_combo.setCurrentIndex(max(index, 0))

    def fields(self) -> GameFields:
        """Current values; empty names fall back like the CLI does."""
        long_name = self._long_name_edit.text().strip()
        return GameFields(
            rom=self._rom_edit.text().strip(),
            console=str(self._console_combo.currentData() or ""),
            core=self._selected_core(),
            folder=self._folder_edit.text().strip() or save_folder_name(long_name),
            short_name=self._short_name_edit.text().strip() or long_name,
            long_name=long_name,
            manufacturer=self._manufacturer_edit.text().strip() or self._default_manufacturer,
            bezel=self._bezel.text(),
        )

    def missing(self) -> str | None:  # pylint: disable=too-many-return-statements
        """What must still be filled in before building, or ``None``."""
        fields = self.fields()
        if not fields.rom:
            return self.tr("Choose the ROM.")
        if not Path(fields.rom).is_file():
            return self.tr("The ROM file does not exist.")
        if not fields.console:
            return self.tr("Choose the console.")
        if not fields.core:
            return self.tr("Pick a RetroArch core.")
        if fields.core not in self._available_cores:
            return self.tr(
                "There is no RetroArch base for '{core}'. See Settings › Toolchain."
            ).format(core=fields.core)
        if not fields.long_name:
            return self.tr("Enter the long name.")
        if save_folder_name(fields.folder) != fields.folder:
            return self.tr("The save folder name has characters an SD card cannot hold.")
        if fields.bezel and not Path(fields.bezel).is_file():
            return self.tr("The bezel file does not exist.")
        return None

    def set_fields(self, fields: GameFields) -> None:
        """Fill every field (e.g. from a loaded CIA). ``changed`` fires as usual."""
        self._rom_edit.setText(fields.rom)
        self._select_console(fields.console)
        self._select_core(fields.core)
        self._short_name_edit.setText(fields.short_name)
        self._long_name_edit.setText(fields.long_name)
        self._folder_edit.setText(fields.folder)
        self._manufacturer_edit.setText(fields.manufacturer)
        self._bezel.set_text(fields.bezel)

    def reset(self) -> None:
        """Back to an empty form."""
        self._suggested_title = self._suggested_folder = self._suggested_core = ""
        self.set_fields(GameFields("", "", "", "", "", "", self._default_manufacturer))

    # ── Behaviour ────────────────────────────────────────────────────────

    def _browse_rom(self) -> None:
        extensions = sorted({ext for system in self._systems or [] for ext in system.extensions})
        roms = " ".join(f"*.{ext}" for ext in extensions)
        path, _filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose the ROM"),
            str(self._last_dir),
            self.tr("ROMs ({patterns});;All files (*)").format(patterns=roms or "*"),
        )
        if path:
            self._last_dir = Path(path).parent
            self._rom_edit.setText(path)

    def _on_rom_changed(self, rom: str) -> None:
        """Follow the ROM: console from its extension, names from its file name."""
        previous, self._suggested_title = self._suggested_title, suggest_title(Path(rom).name)
        for edit in (self._long_name_edit, self._short_name_edit):
            if edit.text() in ("", previous):
                edit.setText(self._suggested_title)
        guessed = self._systems.guess(Path(rom)) if self._systems and rom else None
        if guessed is not None:
            self._select_console(guessed.console)

    def _on_console_changed(self) -> None:
        """Follow the console with its default core, unless the core was picked by hand."""
        console = str(self._console_combo.currentData() or "")
        system = self._systems.get(console) if self._systems else None
        default = system.core if system else ""
        previous, self._suggested_core = self._suggested_core, default
        if self._selected_core() in ("", previous):
            self._select_core(default)
        self._show_data_dir()
        self.changed.emit()

    def _follow_long_name(self, long_name: str) -> None:
        previous, self._suggested_folder = self._suggested_folder, save_folder_name(long_name)
        if self._folder_edit.text() in ("", previous):
            self._folder_edit.setText(self._suggested_folder if long_name.strip() else "")
        self._show_data_dir()

    def _show_data_dir(self) -> None:
        fields = self.fields()
        if fields.console and fields.long_name:
            self._data_dir_label.setText(f"sdmc:/saves/{fields.console}/{fields.folder}")
        else:
            self._data_dir_label.setText("")
