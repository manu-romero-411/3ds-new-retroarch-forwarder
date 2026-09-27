"""build_form.py — All the fields the CLI/interactive builders ask for.

Mirrors ``tools/build_forwarder.parse_args`` and
``tools/interactive_build.main`` field-for-field: core, ROM path, name,
short/long name, manufacturer, optional audio, output path, and (tucked
under "Advanced") the catalog/registry path overrides. This widget only
collects and validates those fields; it never talks to SteamGridDB or
starts a build itself.
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
    QVBoxLayout,
    QWidget,
)

from tools.build_forwarder import DEFAULT_MANUFACTURER, PROJECT_ROOT
from tools.cores_registry import DEFAULT_CORES_JSON, CoreRegistry
from tools.title_id import DEFAULT_REGISTRY_PATH


class BuildForm(QGroupBox):
    """Collects every field ``build_forwarder()`` needs, with the same defaults as the CLI."""

    long_name_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Forwarder details", parent)

        self._core_registry: CoreRegistry | None = None
        self._cores_json_path = DEFAULT_CORES_JSON

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
        self._reload_core_registry()
        form.addRow("Core (libretro name):", self._core_combo)

        self._core_status_label = QLabel()
        self._core_status_label.setStyleSheet("font-size: 8pt; color: palette(mid);")
        form.addRow("", self._core_status_label)

        self._rom_edit = QLineEdit()
        self._rom_edit.setPlaceholderText("roms/snes/Super Mario World.sfc")
        form.addRow("ROM path (on the SD card):", self._rom_edit)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Internal identifier, also the default output filename")
        self._name_edit.textChanged.connect(self._on_name_changed)
        form.addRow("Name:", self._name_edit)

        self._short_name_edit = QLineEdit()
        self._short_name_edit.setPlaceholderText("Defaults to Name")
        form.addRow("Short name (SMDH):", self._short_name_edit)

        self._long_name_edit = QLineEdit()
        self._long_name_edit.setPlaceholderText(
            "Defaults to Name \u2014 also used as the SteamGridDB search term"
        )
        self._long_name_edit.textChanged.connect(self.long_name_changed)
        form.addRow("Long name (SMDH):", self._long_name_edit)

        self._manufacturer_edit = QLineEdit(DEFAULT_MANUFACTURER)
        form.addRow("Manufacturer (SMDH):", self._manufacturer_edit)

        self._audio_edit, audio_row = self._build_path_row(
            "Any ffmpeg-readable format; re-encoded and trimmed to 3s (default: silence)",
            self._browse_audio,
        )
        form.addRow("Banner audio (optional):", audio_row)

        self._output_edit, output_row = self._build_path_row(
            "Defaults to output/<name>.cia",
            self._browse_output,
        )
        form.addRow("Output .cia path:", output_row)

        return form

    def _build_path_row(
        self, hint: str, browse_slot, initial_text: str = ""
    ) -> tuple[QLineEdit, QWidget]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(initial_text)
        edit.setPlaceholderText(hint)
        row.addWidget(edit, 1)

        browse_button = QPushButton("Browse\u2026")
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

    # ── Browsing ─────────────────────────────────────────────────────────

    def _browse_audio(self, edit: QLineEdit) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "Choose banner audio", "", "Audio files (*)"
        )
        if path_str:
            edit.setText(path_str)

    def _browse_output(self, edit: QLineEdit) -> None:
        default_name = f"{self._name_edit.text().strip() or 'forwarder'}.cia"
        path_str, _filter = QFileDialog.getSaveFileName(
            self, "Choose output .cia", default_name, "CIA files (*.cia)"
        )
        if path_str:
            edit.setText(path_str)

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

    # ── Reactivity ───────────────────────────────────────────────────────

    def _on_name_changed(self, text: str) -> None:
        if not self._output_edit.text().strip():
            # Cosmetic only: the real default is applied by resolve_output_path()
            # if the field is still empty at build time.
            self._output_edit.setPlaceholderText(f"output/{text or '<name>'}.cia")

    # ── Public API ───────────────────────────────────────────────────────

    def long_name_text(self) -> str:
        """Current long-name value, resolved the same way the CLI resolves it."""
        return self._long_name_edit.text().strip() or self._name_edit.text().strip()

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

    def resolve_output_path(self) -> Path:
        text = self._output_edit.text().strip()
        if text:
            return Path(text)
        name = self._name_edit.text().strip() or "forwarder"
        return PROJECT_ROOT / "output" / f"{name}.cia"

    def collect_fields(self) -> dict:
        """Return every field as plain strings/paths, same shape as ``ForwarderRequest``."""
        name = self._name_edit.text().strip()
        audio_text = self._audio_edit.text().strip()
        return {
            "core": self.selected_core(),
            "rom_path": self._rom_edit.text().strip(),
            "name": name,
            "short_name": self._short_name_edit.text().strip() or name,
            "long_name": self.long_name_text(),
            "manufacturer": self._manufacturer_edit.text().strip() or DEFAULT_MANUFACTURER,
            "audio": Path(audio_text) if audio_text else None,
            "output": self.resolve_output_path(),
        }

    def set_core_status(self, message: str) -> None:
        self._core_status_label.setText(message)
