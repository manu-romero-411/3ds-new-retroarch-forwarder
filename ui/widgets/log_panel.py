"""log_panel.py — Read-only scrolling log used for both SteamGridDB and build output."""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QPlainTextEdit, QVBoxLayout


class LogPanel(QGroupBox):
    """A simple append-only log box."""

    def __init__(self, parent=None) -> None:
        super().__init__("Log", parent)
        layout = QVBoxLayout(self)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setMaximumBlockCount(5000)
        layout.addWidget(self._text_edit)

    def append(self, message: str) -> None:
        self._text_edit.appendPlainText(message)

    def clear(self) -> None:
        self._text_edit.clear()
