"""asset_slot.py — One artwork slot (preview + Search/Browse/Clear buttons).

Purely a UI element: it shows whatever preview bytes it is given and emits
signals when the user wants to search SteamGridDB, browse a local file, or
clear the slot. All SteamGridDB/network/composition logic lives in
``ArtworkPanel``, which owns and wires up these slots — this class has no
opinion on where the image data comes from.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

PREVIEW_SIZE = (180, 100)


class AssetSlot(QGroupBox):
    """A labeled artwork slot with a preview and Search/Browse/Clear actions."""

    search_requested = Signal()
    browse_requested = Signal()
    clear_requested = Signal()

    def __init__(self, title: str, hint: str, parent=None) -> None:
        super().__init__(title, parent)

        layout = QVBoxLayout(self)

        self._preview_label = QLabel("(none selected)")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setFixedSize(*PREVIEW_SIZE)
        self._preview_label.setStyleSheet("border: 1px dashed palette(mid); color: palette(mid);")
        layout.addWidget(self._preview_label, alignment=Qt.AlignHCenter)

        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("font-size: 8pt; color: palette(mid);")
        layout.addWidget(hint_label)

        self._source_label = QLabel("")
        self._source_label.setWordWrap(True)
        self._source_label.setStyleSheet("font-size: 8pt; font-style: italic;")
        layout.addWidget(self._source_label)

        # Search gets its own full-width row (its label is the longest);
        # Browse/Clear share a second row. Two short rows instead of one
        # wide one keeps the whole slot narrow.
        search_button = QPushButton("Search SteamGridDB\u2026")
        search_button.clicked.connect(self.search_requested)
        layout.addWidget(search_button)

        second_row = QHBoxLayout()
        browse_button = QPushButton("Browse\u2026")
        browse_button.clicked.connect(self.browse_requested)
        second_row.addWidget(browse_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_requested)
        second_row.addWidget(clear_button)
        layout.addLayout(second_row)

    def set_preview(self, image_bytes: bytes | None, source_text: str = "") -> None:
        """Update the thumbnail preview and the small caption below it."""
        if image_bytes:
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes)
            pixmap = pixmap.scaled(
                PREVIEW_SIZE[0], PREVIEW_SIZE[1], Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._preview_label.setPixmap(pixmap)
        else:
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText("(none selected)")
        self._source_label.setText(source_text)
