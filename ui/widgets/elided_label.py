"""elided_label.py — A one-line label that shortens itself instead of widening the window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """Shows its text on one line, cutting the middle with an ellipsis if it doesn't fit.

    A plain ``QLabel`` reports its full text width as its minimum, so a long
    file name would stop the window from shrinking. This one ignores its
    text when negotiating size and elides to whatever width it is given.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:  # pylint: disable=invalid-name
        """Set the (unelided) text; what is displayed is fitted to the current width."""
        self._full_text = text
        self._elide()

    def resizeEvent(self, event) -> None:  # pylint: disable=invalid-name
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, self.width())
        super().setText(shown)
