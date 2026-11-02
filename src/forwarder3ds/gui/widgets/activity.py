"""Activity panel: what is going on right now, and the log."""

from __future__ import annotations

import logging
from html import escape

from PySide6.QtCore import Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.logs import SUCCESS

_LOG_COLOURS = {logging.WARNING: "#b26a00", logging.ERROR: "#c62828", SUCCESS: "#2e7d32"}
_MAX_LOG_LINES = 5000


class ActivityPanel(QWidget):
    """A one-line status with a busy indicator, above the log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = QLabel(self.tr("Ready"))
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setTextVisible(False)
        self._progress.setMaximumWidth(220)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_MAX_LOG_LINES)
        self._log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        row = QHBoxLayout()
        row.addWidget(self._status, 1)
        row.addWidget(self._progress)
        column = QVBoxLayout(self)
        column.setContentsMargins(4, 4, 4, 4)
        column.addLayout(row)
        column.addWidget(self._log, 1)

    def set_busy(self, busy: bool, status: str = "") -> None:
        """Show an indeterminate progress bar while ``busy``."""
        self._progress.setRange(0, 0 if busy else 1)
        self._progress.setValue(0)
        if status:
            self._status.setText(status)

    def set_status(self, text: str) -> None:
        """Show a one-line status."""
        self._status.setText(text)

    @Slot(int, str)
    def append_log(self, level: int, text: str) -> None:
        """Add a log line, coloured by level."""
        colour = _LOG_COLOURS.get(level)
        style = f' style="color:{colour}"' if colour else ""
        self._log.appendHtml(f"<span{style}>{escape(text)}</span>")
