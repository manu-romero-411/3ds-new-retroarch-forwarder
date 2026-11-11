"""The big 3DS, as a map of the game's controls.

Draws ``3ds_frame.png`` with a tag next to every button saying what the game
sees when it is pressed (highlighted when it is not the button itself).
Clicking a button selects it (``button_clicked``) so the dialog can focus
its row. Coordinates are the frame picture's own pixels, scaled when drawn.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from forwarder3ds.core.game_config import CONSOLE_BUTTONS, UNMAPPED
from forwarder3ds.core.paths import bundled

FRAME_PATH = bundled("3ds_frame.png")
# Where the screen holes are in the frame picture (native pixels).
TOP_SCREEN = QRect(151, 77, 400, 240)
BOTTOM_SCREEN = QRect(191, 408, 320, 240)

#: Button centres in the frame picture, and where their tag goes (offset).
BUTTONS: dict[str, tuple[QPoint, QPoint]] = {
    "a": (QPoint(649, 487), QPoint(38, 0)),
    "b": (QPoint(610, 524), QPoint(0, 36)),
    "x": (QPoint(610, 449), QPoint(0, -36)),
    "y": (QPoint(569, 487), QPoint(-38, 0)),
    "up": (QPoint(92, 578), QPoint(0, -34)),
    "down": (QPoint(92, 632), QPoint(0, 34)),
    "left": (QPoint(65, 605), QPoint(-40, 0)),
    "right": (QPoint(119, 605), QPoint(40, 0)),
    "select": (QPoint(241, 685), QPoint(0, -28)),
    "start": (QPoint(459, 685), QPoint(0, -28)),
    "l": (QPoint(48, 358), QPoint(0, 30)),
    "l2": (QPoint(120, 358), QPoint(0, 30)),
    "r": (QPoint(655, 358), QPoint(0, 30)),
    "r2": (QPoint(583, 358), QPoint(0, 30)),
}
_HIT_RADIUS = 22
_TAG_HEIGHT = 24
_ACCENT = QColor("#2d9cdb")
_MUTED = QColor("#5f6b7a")
_UNMAPPED = QColor("#8a8f98")
_SCREEN = QColor("#ffffff")
_TEXT = QColor("#2b2f36")


class ButtonMapView(QWidget):
    """A 3DS whose buttons show (and select) what they are mapped to."""

    button_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame = QImage(str(FRAME_PATH))
        self._frame = None if frame.isNull() else frame
        self._native = self._frame.size() if self._frame else QSize(703, 713)
        self._labels: dict[str, str] = {}
        self._mapping: dict[str, str] = {}
        self._selected = ""
        self._title = ""
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMouseTracking(True)

    # ── Public ───────────────────────────────────────────────────────────

    def set_state(self, mapping: dict[str, str], labels: dict[str, str], title: str) -> None:
        """Show ``mapping`` (3DS button → target) using ``labels`` for the targets."""
        self._mapping, self._labels, self._title = dict(mapping), labels, title
        self.update()

    def select(self, button: str) -> None:
        """Ring ``button`` (``""``: none)."""
        self._selected = button
        self.update()

    # ── Geometry ─────────────────────────────────────────────────────────

    def hasHeightForWidth(self) -> bool:  # pylint: disable=invalid-name
        """Keep the picture's aspect ratio."""
        return True

    def heightForWidth(self, width: int) -> int:  # pylint: disable=invalid-name
        """Height for ``width`` at the picture's aspect ratio."""
        return round(width * self._native.height() / self._native.width())

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Two thirds of the picture's native size."""
        return self._native * 2 // 3

    def _scale(self) -> tuple[float, QPointF]:
        scale = min(self.width() / self._native.width(), self.height() / self._native.height())
        offset = QPointF(
            (self.width() - self._native.width() * scale) / 2,
            (self.height() - self._native.height() * scale) / 2,
        )
        return scale, offset

    def _button_at(self, pos: QPointF) -> str:
        scale, offset = self._scale()
        native = (pos - offset) / scale
        for button, (centre, _offset) in BUTTONS.items():
            if (native - QPointF(centre)).manhattanLength() <= _HIT_RADIUS * 1.4:
                return button
        return ""

    # ── Events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # pylint: disable=invalid-name
        """Select the button under the pointer."""
        button = self._button_at(event.position())
        if button:
            self.select(button)
            self.button_clicked.emit(button)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # pylint: disable=invalid-name
        """Pointing hand over buttons."""
        over = bool(self._button_at(event.position()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:  # pylint: disable=invalid-name
        """Frame, screens, rings and tags."""
        scale, offset = self._scale()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(offset)
        painter.scale(scale, scale)
        painter.fillRect(TOP_SCREEN, _SCREEN)
        painter.fillRect(BOTTOM_SCREEN, _SCREEN)
        if self._frame is not None:
            painter.drawImage(QPoint(0, 0), self._frame)
        self._paint_screens(painter)
        for button, (centre, tag_offset) in BUTTONS.items():
            self._paint_button(painter, button, centre, centre + tag_offset)
        painter.end()

    def _paint_screens(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPixelSize(20)
        painter.setFont(font)
        painter.setPen(_TEXT)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        painter.drawText(TOP_SCREEN.adjusted(24, 24, -24, -24), int(flags), self._title)
        painter.setPen(_MUTED)
        painter.drawText(
            BOTTOM_SCREEN.adjusted(24, 24, -24, -24),
            int(flags),
            self.tr("Touch screen: RetroArch's menu\n(save and load states, options)"),
        )

    def _paint_button(self, painter: QPainter, button: str, centre: QPoint, at: QPoint) -> None:
        target = self._mapping.get(button, button)
        changed = target != button
        if button == self._selected:
            painter.setPen(QPen(_ACCENT, 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(centre), _HIT_RADIUS, _HIT_RADIUS)
        if target == UNMAPPED:
            text, colour = "—", _UNMAPPED
        else:
            text = self._labels.get(target, target.upper())
            colour = _ACCENT if changed else _MUTED
        if button in ("l", "r", "l2", "r2"):
            text = f"{CONSOLE_BUTTONS[button]}: {text}"
        font = QFont(self.font())
        font.setPixelSize(16)
        font.setBold(changed)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 14
        rect = QRectF(at.x() - width / 2, at.y() - _TAG_HEIGHT / 2, width, _TAG_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
