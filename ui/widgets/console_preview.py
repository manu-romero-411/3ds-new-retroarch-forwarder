"""console_preview.py — The forwarder as it will look on a 3DS's HOME menu.

Draws the icon and the banner *behind* a picture of a 3DS whose two screens
are transparent holes (``ui/assets/3ds_frame.png``), so they show through:

* top screen: the banner (256x128, platform frame included) centred on a
  plain white background;
* bottom screen: a made-up icon grid, two rows high, with the forwarder's icon
  in it among empty placeholder tiles.

The picture is composed at its native size, where the screen holes are exactly
400x240 and 320x240 pixels (see ``TOP_SCREEN``/``BOTTOM_SCREEN``), and only
scaled down when shown, so the layout stays pixel-accurate. This widget is a
pure view: it is handed PNG bytes and draws them; it knows nothing about where
they come from.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..sgdb.compositor import BANNER_HEIGHT, BANNER_WIDTH, PLACEHOLDER_BACKGROUND

FRAME_PATH = Path(__file__).resolve().parent.parent / "assets" / "3ds_frame.png"

# Where the screen holes are in the frame picture (native pixels).
TOP_SCREEN = QRect(151, 77, 400, 240)
BOTTOM_SCREEN = QRect(191, 408, 320, 240)
_FALLBACK_FRAME_SIZE = QSize(703, 713)

ICON_SIZE = 48
GRID_ROWS = 2
GRID_COLUMNS = 5
GRID_GAP_X = 14
GRID_GAP_Y = 18
# The forwarder's cell: first row, middle column.
ICON_CELL = (0, GRID_COLUMNS // 2)
TILE_RADIUS = 6

_SCREEN_BACKGROUND = QColor("#ffffff")
_BOTTOM_BACKGROUND = QColor("#f4f5f7")
_EMPTY_TILE = QColor("#dfe2e7")
_SELECTION = QColor("#2d9cdb")
_SELECTION_PADDING = 3
_SELECTION_WIDTH = 2


def _load_image(data: bytes | None) -> QImage | None:
    """Decode PNG/JPEG bytes, or ``None`` if there are none or they are unreadable."""
    if not data:
        return None
    image = QImage()
    return image if image.loadFromData(data) else None


class ConsolePreview(QWidget):
    """Shows the banner and the icon inside a 3DS, scaled to the available width."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        frame = QImage(str(FRAME_PATH))
        # A missing frame picture degrades to the bare screens, never to a crash.
        self._frame: QImage | None = None if frame.isNull() else frame
        self._native_size = self._frame.size() if self._frame else _FALLBACK_FRAME_SIZE

        self._icon: QImage | None = None
        self._banner: QImage | None = None
        self._native = QImage()
        self._shown = QPixmap()

        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setToolTip("How the forwarder will look on the 3DS HOME menu.")

        self._compose()

    # ── Public API ───────────────────────────────────────────────────────

    def show_artwork(self, icon_png: bytes | None, banner_png: bytes | None) -> None:
        """Show the given icon and banner (``None`` draws the default placeholder)."""
        self._icon = _load_image(icon_png)
        self._banner = _load_image(banner_png)
        self._compose()

    # ── Size handling ────────────────────────────────────────────────────

    def hasHeightForWidth(self) -> bool:  # pylint: disable=invalid-name
        return True

    def heightForWidth(self, width: int) -> int:  # pylint: disable=invalid-name
        # Never taller than the picture's own size: it is not scaled up.
        shown_width = min(width, self._native_size.width())
        return round(shown_width * self._native_size.height() / self._native_size.width())

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name
        width = self._native_size.width() // 2
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # pylint: disable=invalid-name
        return QSize(220, self.heightForWidth(220))

    def resizeEvent(self, event) -> None:  # pylint: disable=invalid-name
        super().resizeEvent(event)
        self._rescale()

    # ── Composition ──────────────────────────────────────────────────────

    def _compose(self) -> None:
        """Draw the screens, then the frame over them, at the picture's native size."""
        canvas = QImage(self._native_size, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_top_screen(painter)
        self._paint_bottom_screen(painter)
        if self._frame:
            painter.drawImage(0, 0, self._frame)
        painter.end()
        self._native = canvas
        self._rescale()

    def _paint_top_screen(self, painter: QPainter) -> None:
        painter.save()
        painter.setClipRect(TOP_SCREEN)
        painter.fillRect(TOP_SCREEN, _SCREEN_BACKGROUND)
        target = QRect(
            TOP_SCREEN.x() + (TOP_SCREEN.width() - BANNER_WIDTH) // 2,
            TOP_SCREEN.y() + (TOP_SCREEN.height() - BANNER_HEIGHT) // 2,
            BANNER_WIDTH,
            BANNER_HEIGHT,
        )
        if self._banner:
            painter.drawImage(target, self._banner)  # stretched, like the build does
        else:
            painter.fillRect(target, QColor(*PLACEHOLDER_BACKGROUND))
        painter.restore()

    def _paint_bottom_screen(self, painter: QPainter) -> None:
        painter.save()
        painter.setClipRect(BOTTOM_SCREEN)
        painter.fillRect(BOTTOM_SCREEN, _BOTTOM_BACKGROUND)

        grid_width = GRID_COLUMNS * ICON_SIZE + (GRID_COLUMNS - 1) * GRID_GAP_X
        grid_height = GRID_ROWS * ICON_SIZE + (GRID_ROWS - 1) * GRID_GAP_Y
        origin = QPoint(
            BOTTOM_SCREEN.x() + (BOTTOM_SCREEN.width() - grid_width) // 2,
            BOTTOM_SCREEN.y() + (BOTTOM_SCREEN.height() - grid_height) // 2,
        )
        for row in range(GRID_ROWS):
            for column in range(GRID_COLUMNS):
                tile = QRect(
                    origin.x() + column * (ICON_SIZE + GRID_GAP_X),
                    origin.y() + row * (ICON_SIZE + GRID_GAP_Y),
                    ICON_SIZE,
                    ICON_SIZE,
                )
                if (row, column) == ICON_CELL:
                    self._paint_icon(painter, tile)
                else:
                    self._fill_tile(painter, tile, _EMPTY_TILE)
        painter.restore()

    def _fill_tile(self, painter: QPainter, tile: QRect, color: QColor) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(tile), TILE_RADIUS, TILE_RADIUS)
        painter.fillPath(path, color)

    def _paint_icon(self, painter: QPainter, tile: QRect) -> None:
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(tile), TILE_RADIUS, TILE_RADIUS)
        painter.setClipPath(clip, Qt.IntersectClip)
        if self._icon:
            painter.drawImage(tile, self._icon)  # stretched to 48x48, like the build does
        else:
            painter.fillRect(tile, QColor(*PLACEHOLDER_BACKGROUND))
        painter.restore()

        selection = tile.adjusted(
            -_SELECTION_PADDING, -_SELECTION_PADDING, _SELECTION_PADDING, _SELECTION_PADDING
        )
        painter.setPen(QPen(_SELECTION, _SELECTION_WIDTH))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(selection), TILE_RADIUS + 2, TILE_RADIUS + 2)

    # ── Display ──────────────────────────────────────────────────────────

    def _rescale(self) -> None:
        """Scale the native picture to the widget (high quality, HiDPI-aware)."""
        ratio = self.devicePixelRatioF()
        width = max(1, round(min(self.width(), self._native_size.width()) * ratio))
        scaled = self._native.scaled(
            QSize(width, round(width * self._native_size.height() / self._native_size.width())),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._shown = QPixmap.fromImage(scaled)
        self._shown.setDevicePixelRatio(ratio)
        self.update()

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name
        painter = QPainter(self)
        shown_width = round(self._shown.width() / self._shown.devicePixelRatio())
        painter.drawPixmap((self.width() - shown_width) // 2, 0, self._shown)
        painter.end()
        event.accept()
