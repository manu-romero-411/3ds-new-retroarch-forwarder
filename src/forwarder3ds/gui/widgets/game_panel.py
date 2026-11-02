"""Game panel: which core launches which ROM, and the names on the HOME menu.

These are the fields the Title ID is derived from. The panel only collects
and (re)populates them; the window computes the Title ID preview and runs
the build.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.cores import CoreRegistry
from forwarder3ds.core.names import suggest_title
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER
from forwarder3ds.gui.dialogs.rom_picker import choose_rom_on_sd


@dataclass
class GameFields:
    """The panel's values, stripped."""

    core: str
    rom_path: str
    short_name: str
    long_name: str
    manufacturer: str


class GamePanel(QWidget):
    """Core, ROM path on the SD card, SMDH names and manufacturer."""

    #: Any edit to a field.
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cores: CoreRegistry | None = None
        self._sd_card: Path | None = None
        self._default_manufacturer = DEFAULT_MANUFACTURER
        # The title last derived from the ROM path. A name field that is still
        # empty or equal to it has not been touched by the user, so it keeps
        # following the ROM; one that differs is the user's and is left alone.
        self._suggested_title = ""

        self._core_combo = QComboBox()
        self._core_combo.setEditable(True)
        self._core_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Size to a few characters, not to the longest core title.
        self._core_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._core_combo.setMinimumContentsLength(12)
        self._core_combo.lineEdit().setPlaceholderText(self.tr("e.g. snes9x2005"))

        self._rom_edit = QLineEdit()
        self._rom_edit.setPlaceholderText("roms/snes/Super Mario World.sfc")
        self._rom_edit.setToolTip(self.tr("Path relative to the root of the 3DS SD card."))
        self._long_name_edit = QLineEdit()
        self._long_name_edit.setPlaceholderText(self.tr("Filled from the ROM name"))
        self._long_name_edit.setToolTip(
            self.tr("Shown on the HOME menu; also the SteamGridDB search term.")
        )
        self._short_name_edit = QLineEdit()
        self._short_name_edit.setPlaceholderText(self.tr("Same as the long name"))
        self._manufacturer_edit = QLineEdit(DEFAULT_MANUFACTURER)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._build_game_group())
        column.addWidget(self._build_names_group())
        column.addStretch(1)

        self._rom_edit.textChanged.connect(self._autofill_names)
        self._core_combo.currentTextChanged.connect(self.changed)
        for edit in (
            self._rom_edit,
            self._short_name_edit,
            self._long_name_edit,
            self._manufacturer_edit,
        ):
            edit.textChanged.connect(self.changed)

    # ── Construction ─────────────────────────────────────────────────────

    def _build_game_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Game"))
        form = QFormLayout(group)
        form.addRow(self.tr("RetroArch core:"), self._core_combo)

        browse = QPushButton(self.tr("Browse SD…"))
        browse.setToolTip(self.tr("Pick the ROM on the 3DS SD card (it must be mounted)."))
        browse.clicked.connect(self._browse_rom)
        rom_row = QWidget()
        row = QHBoxLayout(rom_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._rom_edit, 1)
        row.addWidget(browse)
        form.addRow(self.tr("ROM on the SD card:"), rom_row)

        hint = QLabel(
            self.tr(
                "The forwarder installs the core from sdmc:/retroarch/cores/ on first "
                "launch if it is not installed yet."
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

    # ── Configuration ────────────────────────────────────────────────────

    def set_cores(self, cores: CoreRegistry | None) -> None:
        """Fill the core list (``None``: the catalog could not be read)."""
        current = self.fields().core
        self._cores = cores
        self._core_combo.blockSignals(True)
        self._core_combo.clear()
        entries = sorted(cores or [], key=lambda entry: entry.title.casefold())
        for entry in entries:
            self._core_combo.addItem(f"{entry.title} ({entry.libretro_name})", entry.libretro_name)
        completer = QCompleter([entry.libretro_name for entry in entries], self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._core_combo.setCompleter(completer)
        self._select_core(current)
        self._core_combo.blockSignals(False)

    def set_sd_card(self, sd_card: Path | None) -> None:
        """Use this SD card root for *Browse SD…* (``None``: detect mounted cards)."""
        self._sd_card = sd_card

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

    def fields(self) -> GameFields:
        """Current values; empty names fall back like the CLI does."""
        long_name = self._long_name_edit.text().strip()
        return GameFields(
            core=self._selected_core(),
            rom_path=self._rom_edit.text().strip(),
            short_name=self._short_name_edit.text().strip() or long_name,
            long_name=long_name,
            manufacturer=self._manufacturer_edit.text().strip() or self._default_manufacturer,
        )

    def missing(self) -> str | None:
        """What must still be filled in before building, or ``None``."""
        fields = self.fields()
        if not fields.core:
            return self.tr("Pick a RetroArch core.")
        if self._cores is not None and self._cores.get(fields.core) is None:
            return self.tr("Core '{core}' is not in the core catalog.").format(core=fields.core)
        if not fields.rom_path:
            return self.tr("Enter the ROM path on the SD card.")
        if not fields.long_name:
            return self.tr("Enter the long name.")
        return None

    def set_fields(self, fields: GameFields) -> None:
        """Fill every field (e.g. from a loaded CIA). ``changed`` fires as usual."""
        self._select_core(fields.core)
        self._rom_edit.setText(fields.rom_path)
        self._short_name_edit.setText(fields.short_name)
        self._long_name_edit.setText(fields.long_name)
        self._manufacturer_edit.setText(fields.manufacturer)

    def reset(self) -> None:
        """Back to an empty form."""
        self._suggested_title = ""
        self.set_fields(GameFields("", "", "", "", self._default_manufacturer))

    # ── Behaviour ────────────────────────────────────────────────────────

    def _browse_rom(self) -> None:
        rom_path = choose_rom_on_sd(self, self._sd_card)
        if rom_path:
            self._rom_edit.setText(rom_path)

    def _autofill_names(self, rom_path: str) -> None:
        """Keep the name fields the user has not edited in sync with the ROM's file name."""
        previous, self._suggested_title = self._suggested_title, suggest_title(rom_path)
        for edit in (self._long_name_edit, self._short_name_edit):
            if edit.text() in ("", previous):
                edit.setText(self._suggested_title)
