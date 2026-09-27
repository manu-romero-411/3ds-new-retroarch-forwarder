"""image_gallery_dialog.py — Thumbnail gallery to pick one SteamGridDB asset.

Every tile shows the asset's *thumbnail* (a smaller, lower-quality
rendition SteamGridDB serves alongside the full image — see
``ImageCandidate.thumb_url``), never the full-resolution file, and all
thumbnails are fetched in parallel via ``sgdb.downloader.download_many_bytes``
so opening the gallery doesn't feel like it hangs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..sgdb.downloader import download_many_bytes
from ..sgdb.models import ImageCandidate
from ..workers.task_thread import TaskThread

COLUMNS = 4
THUMB_MAX_SIZE = (170, 170)


class ImageGalleryDialog(QDialog):
    """Grid of low-quality thumbnails; clicking one selects it and closes the dialog."""

    def __init__(self, parent, title: str, candidates: list[ImageCandidate]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 640)
        self.setModal(True)

        self._candidates = candidates
        self._chosen: ImageCandidate | None = None
        self._preview_thread: TaskThread | None = None

        layout = QVBoxLayout(self)

        header = QLabel(title)
        header.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(header)

        self._loading_label = QLabel("Loading previews\u2026")
        layout.addWidget(self._loading_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.hide()
        layout.addWidget(self._scroll)

        button_row = QHBoxLayout()
        clear_button = QPushButton("Use no image")
        clear_button.clicked.connect(self._on_clear)
        button_row.addWidget(clear_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self._start_loading_previews()

    def _start_loading_previews(self) -> None:
        urls = [candidate.thumb_url for candidate in self._candidates]
        self._preview_thread = TaskThread(lambda: download_many_bytes(urls), parent=self)
        self._preview_thread.succeeded.connect(self._on_previews_ready)
        self._preview_thread.failed.connect(self._on_previews_failed)
        self._preview_thread.start()

    def _on_previews_failed(self, message: str) -> None:
        self._loading_label.setText(f"Could not load previews: {message}")

    def _on_previews_ready(self, previews: list) -> None:
        for candidate, preview in zip(self._candidates, previews):
            candidate.preview = preview
        self._loading_label.hide()
        self._scroll.setWidget(self._build_grid())
        self._scroll.show()

    def _build_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8)

        for index, candidate in enumerate(self._candidates):
            row, col = divmod(index, COLUMNS)
            grid.addWidget(self._build_tile(candidate), row, col)
        for col in range(COLUMNS):
            grid.setColumnStretch(col, 1)

        return container

    def _build_tile(self, candidate: ImageCandidate) -> QFrame:
        tile = QFrame()
        tile.setFrameShape(QFrame.Box)
        tile.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 4px; padding: 4px; }"
            "QFrame:hover { border: 1px solid palette(highlight); }"
        )
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(4, 4, 4, 4)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setCursor(Qt.PointingHandCursor)
        image_label.setFixedSize(*THUMB_MAX_SIZE)

        if candidate.preview:
            pixmap = QPixmap()
            pixmap.loadFromData(candidate.preview)
            pixmap = pixmap.scaled(
                THUMB_MAX_SIZE[0], THUMB_MAX_SIZE[1], Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("(preview unavailable)")
            image_label.setStyleSheet("border: 1px dashed palette(mid);")

        image_label.mousePressEvent = lambda _event, c=candidate: self._on_choose(c)
        tile_layout.addWidget(image_label, alignment=Qt.AlignCenter)

        has_dims = candidate.width and candidate.height
        dims = f"{candidate.width}\u00d7{candidate.height}" if has_dims else "size n/a"
        info = QLabel(f"{dims}\n{candidate.author}" if candidate.author else dims)
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("font-size: 8pt; color: palette(text);")
        tile_layout.addWidget(info)

        return tile

    def _on_choose(self, candidate: ImageCandidate) -> None:
        self._chosen = candidate
        self.accept()

    def _on_clear(self) -> None:
        self._chosen = None
        self.accept()

    @staticmethod
    def choose(parent, title: str, candidates: list[ImageCandidate]) -> ImageCandidate | None:
        """Run the dialog and return the chosen candidate, or ``None`` if none was picked."""
        dialog = ImageGalleryDialog(parent, title, candidates)
        if dialog.exec() == QDialog.Accepted:
            return dialog._chosen  # pylint: disable=protected-access
        return None
