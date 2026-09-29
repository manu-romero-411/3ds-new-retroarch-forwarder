"""title_id_bar.py — Compact Unique ID / Title ID controls for the top bar.

Purely presentational: it lets the user type a Unique ID (or leave it on
"Auto") and displays the Title ID the current fields would produce. It
knows nothing about registries or collisions -- ``MainWindow`` computes the
result with the backend (``tools.title_id.preview_unique_id``) and pushes it
in through ``show_unique_id()`` / ``show_error()`` / ``show_incomplete()``.

Sized to survive small windows: the Unique ID box and the Auto checkbox are
fixed and tiny, while the read-only Title ID field is the only part that is
allowed to shrink (its text is clipped, with the full value in a tooltip).
"""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QFontDatabase, QRegularExpressionValidator
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget

from tools.title_id import unique_id_to_title_id

UNIQUE_ID_DIGITS = 5
_TITLE_ID_TEXT_WIDTH = len("0x") + 16
_MIN_TITLE_ID_WIDTH = 72
_MUTED_STYLE = "color: palette(mid);"
_ERROR_STYLE = "color: #c0392b;"
_INCOMPLETE_HINT = "Fill in the core, the ROM path and the long name to see the Title ID."


class TitleIdBar(QWidget):
    """``Title ID: [F1234] [x] Auto  [0x00040000F1234500]``, in one compact row."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        char_width = self.fontMetrics().horizontalAdvance("0")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Title ID:"))

        self._unique_id_edit = QLineEdit()
        self._unique_id_edit.setFont(fixed_font)
        self._unique_id_edit.setPlaceholderText("F1234")
        self._unique_id_edit.setMaxLength(UNIQUE_ID_DIGITS)
        self._unique_id_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(f"[0-9A-Fa-f]{{0,{UNIQUE_ID_DIGITS}}}"))
        )
        self._unique_id_edit.setFixedWidth(char_width * (UNIQUE_ID_DIGITS + 3))
        self._unique_id_edit.setToolTip("Unique ID: the 20-bit part of the Title ID, in hex.")
        self._unique_id_edit.setEnabled(False)  # "Auto" starts checked
        self._unique_id_edit.textChanged.connect(self.changed)
        layout.addWidget(self._unique_id_edit)

        self._auto_check = QCheckBox("Auto")
        self._auto_check.setChecked(True)
        self._auto_check.setToolTip("Derive the Unique ID from the forwarder's fields.")
        self._auto_check.toggled.connect(self._on_auto_toggled)
        layout.addWidget(self._auto_check)

        self._title_id_edit = QLineEdit()
        self._title_id_edit.setFont(fixed_font)
        self._title_id_edit.setReadOnly(True)
        self._title_id_edit.setPlaceholderText("\u2014")
        self._title_id_edit.setMinimumWidth(_MIN_TITLE_ID_WIDTH)
        self._title_id_edit.setMaximumWidth(char_width * (_TITLE_ID_TEXT_WIDTH + 3))
        self._title_id_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._title_id_edit, 1)

        self.show_incomplete()

    # ── Input ────────────────────────────────────────────────────────────

    def _on_auto_toggled(self, checked: bool) -> None:
        self._unique_id_edit.setEnabled(not checked)
        self.changed.emit()

    def manual_unique_id(self) -> int | None:
        """The user-typed Unique ID, or ``None`` while "Auto" is on (or the box is empty)."""
        if self._auto_check.isChecked():
            return None
        text = self._unique_id_edit.text().strip()
        return int(text, 16) if text else None

    def set_manual_unique_id(self, unique_id: int) -> None:
        """Switch Auto off and pin the Unique ID, without emitting ``changed``."""
        self._set_silently(auto=False, text=f"{unique_id:0{UNIQUE_ID_DIGITS}X}")

    def set_auto(self) -> None:
        """Switch Auto back on, without emitting ``changed``."""
        self._set_silently(auto=True, text="")

    def _set_silently(self, auto: bool, text: str) -> None:
        for widget in (self._auto_check, self._unique_id_edit):
            widget.blockSignals(True)
        self._auto_check.setChecked(auto)
        self._unique_id_edit.setEnabled(not auto)
        self._unique_id_edit.setText(text)
        for widget in (self._auto_check, self._unique_id_edit):
            widget.blockSignals(False)

    # ── Output ───────────────────────────────────────────────────────────

    def _show(self, text: str, tooltip: str, style: str) -> None:
        self._title_id_edit.setText(text)
        self._title_id_edit.setCursorPosition(0)
        self._title_id_edit.setToolTip(tooltip)
        self._title_id_edit.setStyleSheet(style)

    def show_unique_id(self, unique_id: int) -> None:
        """Display the Title ID for ``unique_id`` (and mirror it into the box while on Auto)."""
        if self._auto_check.isChecked():
            self._unique_id_edit.blockSignals(True)
            self._unique_id_edit.setText(f"{unique_id:0{UNIQUE_ID_DIGITS}X}")
            self._unique_id_edit.blockSignals(False)
        title_id = f"0x{unique_id_to_title_id(unique_id):016X}"
        self._show(title_id, f"Title ID: {title_id}", "")

    def show_incomplete(self) -> None:
        """Nothing to show yet: the fields the Title ID derives from are not filled in."""
        self._show("", _INCOMPLETE_HINT, _MUTED_STYLE)

    def show_error(self, message: str) -> None:
        """Flag the current Unique ID as unusable; ``message`` explains why (tooltip)."""
        self._show("Invalid ID", message, _ERROR_STYLE)
