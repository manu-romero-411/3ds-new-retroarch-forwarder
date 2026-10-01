"""asset_slot.py — One artwork slot: a title, Search/Browse/Clear and where it came from.

Purely a UI element: it emits signals when the user wants to search
SteamGridDB, browse a local file, or clear the slot, and shows a one-line
caption of the current source. It deliberately has no image preview of its
own: what the artwork looks like is shown, in context, by ``ConsolePreview``.
All SteamGridDB/network/composition logic lives in ``ArtworkPanel``, which
owns and wires up these slots.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

NO_SOURCE_TEXT = "(none selected)"
_TITLE_MIN_WIDTH = 44


class AssetSlot(QWidget):
    """A labeled artwork slot with Search/Browse/Clear actions and a source caption."""

    search_requested = Signal()
    browse_requested = Signal()
    clear_requested = Signal()

    def __init__(self, title: str, hint: str, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        row = QHBoxLayout()
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setMinimumWidth(_TITLE_MIN_WIDTH)
        title_label.setToolTip(hint)
        row.addWidget(title_label)
        row.addStretch(1)

        search_button = QPushButton("Search\u2026")
        search_button.setToolTip(f"Search SteamGridDB. {hint}")
        search_button.clicked.connect(self.search_requested)
        row.addWidget(search_button)

        browse_button = QPushButton("Browse\u2026")
        browse_button.setToolTip(f"Use a local image file. {hint}")
        browse_button.clicked.connect(self.browse_requested)
        row.addWidget(browse_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_requested)
        row.addWidget(clear_button)
        layout.addLayout(row)

        self._source_label = QLabel(NO_SOURCE_TEXT)
        self._source_label.setStyleSheet("font-size: 8pt; font-style: italic; color: palette(mid);")
        layout.addWidget(self._source_label)

    def set_source(self, source_text: str = "") -> None:
        """Caption where the current image came from (empty: nothing selected)."""
        self._source_label.setText(source_text or NO_SOURCE_TEXT)
