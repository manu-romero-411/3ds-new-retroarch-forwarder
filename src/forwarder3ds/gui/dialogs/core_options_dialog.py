"""Edit a game's initial core options: options on the left, values on the right.

The options come from the core's own definitions (the base's
``core_options.h``, see :mod:`forwarder3ds.core.core_options`). Only values
that differ from the core's defaults are kept; they become the CIA's
``game.opt``, copied to the game's save folder on first boot, where they
can still be changed from RetroArch's menu or by hand.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.core_options import CoreOption, CoreOptions

_KEY_ROLE = Qt.ItemDataRole.UserRole


class CoreOptionsDialog(QDialog):
    """Two lists, like NSUI's: option → value."""

    def __init__(
        self, parent: QWidget | None, core: str, options: CoreOptions, values: dict[str, str]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Core options — {core}").format(core=core))
        self.resize(760, 480)
        self._options = options
        self._values = options.defaults() | options.clean(values)

        self._option_list = QListWidget()
        self._value_list = QListWidget()
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._info.setMinimumHeight(self.fontMetrics().lineSpacing() * 3)
        self._info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        for option in options.options:
            item = QListWidgetItem(self._option_text(option))
            item.setData(_KEY_ROLE, option.key)
            item.setToolTip(option.key)
            self._option_list.addItem(item)
            self._refresh_item(item)
        self._option_list.currentItemChanged.connect(self._show_values)
        self._value_list.currentItemChanged.connect(self._pick_value)

        reset = QPushButton(self.tr("Reset all to defaults"))
        reset.clicked.connect(self._reset)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(reset)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._option_list)
        splitter.addWidget(self._value_list)
        splitter.setSizes([460, 300])

        layout = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "Initial values: the game's game.opt in its save folder takes over once it "
                "exists. Bold options differ from the core's default."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._info)
        layout.addLayout(bottom)
        if self._option_list.count():
            self._option_list.setCurrentRow(0)

    def _option_text(self, option: CoreOption) -> str:
        category = self._options.category_label(option.category)
        label = f"{category} › {option.label}" if category else option.label
        return f"{label}: {option.label_of(self._values.get(option.key, option.default))}"

    def _current_option(self) -> CoreOption | None:
        item = self._option_list.currentItem()
        return self._options.get(str(item.data(_KEY_ROLE))) if item else None

    def _refresh_item(self, item: QListWidgetItem) -> None:
        option = self._options.get(str(item.data(_KEY_ROLE)))
        if option is None:
            return
        item.setText(self._option_text(option))
        font = QFont(item.font())
        font.setBold(self._values.get(option.key) != option.default)
        item.setFont(font)

    def _show_values(self) -> None:
        option = self._current_option()
        self._value_list.blockSignals(True)
        self._value_list.clear()
        if option is not None:
            current = self._values.get(option.key, option.default)
            for value, label in option.values:
                text = label + (self.tr("  (default)") if value == option.default else "")
                item = QListWidgetItem(text)
                item.setData(_KEY_ROLE, value)
                self._value_list.addItem(item)
                if value == current:
                    self._value_list.setCurrentItem(item)
            self._info.setText(option.info)
        self._value_list.blockSignals(False)

    def _pick_value(self, item: QListWidgetItem | None) -> None:
        option = self._current_option()
        if option is None or item is None:
            return
        self._values[option.key] = str(item.data(_KEY_ROLE))
        self._refresh_item(self._option_list.currentItem())

    def _reset(self) -> None:
        self._values = self._options.defaults()
        for row in range(self._option_list.count()):
            self._refresh_item(self._option_list.item(row))
        self._show_values()

    def values(self) -> dict[str, str]:
        """The options that differ from their defaults."""
        return self._options.clean(self._values)

    @staticmethod
    def edit(
        parent: QWidget | None, core: str, options: CoreOptions, values: dict[str, str]
    ) -> dict[str, str] | None:
        """Show the dialog; the new values, or ``None`` if cancelled."""
        dialog = CoreOptionsDialog(parent, core, options, values)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.values()
