"""One artwork slot: a title, *SteamGridDB… / File… / Clear* and where it came from.

Purely a view: it emits signals and shows a caption of the current source.
It has no image preview of its own; the console preview shows the artwork
in context. All SteamGridDB, file and composition logic lives in
:class:`~forwarder3ds.gui.widgets.presentation_panel.PresentationPanel`.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

_TITLE_MIN_WIDTH = 44


class AssetSlot(QWidget):
    """A labelled artwork slot with SteamGridDB/File/Clear actions and a source caption."""

    search_requested = Signal()
    browse_requested = Signal()
    clear_requested = Signal()

    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hint = hint

        title_label = QLabel(f"<b>{title}</b>")
        title_label.setMinimumWidth(_TITLE_MIN_WIDTH)
        title_label.setToolTip(hint)

        self._search_button = QPushButton(self.tr("SteamGridDB…"))
        self._search_button.clicked.connect(self.search_requested)
        browse_button = QPushButton(self.tr("File…"))
        browse_button.setToolTip(self.tr("Use an image file. {hint}").format(hint=hint))
        browse_button.clicked.connect(self.browse_requested)
        clear_button = QPushButton(self.tr("Clear"))
        clear_button.clicked.connect(self.clear_requested)

        self._source_label = QLabel()
        self._source_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        font = self._source_label.font()
        font.setItalic(True)
        font.setPointSizeF(font.pointSizeF() * 0.9)
        self._source_label.setFont(font)

        row = QHBoxLayout()
        row.addWidget(title_label)
        row.addStretch(1)
        row.addWidget(self._search_button)
        row.addWidget(browse_button)
        row.addWidget(clear_button)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addLayout(row)
        column.addWidget(self._source_label)
        self.set_source()
        self.set_search_enabled(True)

    def set_source(self, source_text: str = "") -> None:
        """Caption where the current image came from (empty: nothing selected)."""
        self._source_label.setText(source_text or self.tr("(none selected)"))

    def set_search_enabled(self, enabled: bool) -> None:
        """Enable SteamGridDB search; when disabled the tooltip says why."""
        self._search_button.setEnabled(enabled)
        self._search_button.setToolTip(
            self.tr("Search SteamGridDB by the long name. {hint}").format(hint=self._hint)
            if enabled
            else self.tr("Set a SteamGridDB API key in Settings first.")
        )
