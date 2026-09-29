"""top_bar.py — The window's top strip: file actions on the left, Title ID on the right.

Renders whatever ``QAction`` objects it is given as tool buttons (the
actions, with their shortcuts and handlers, are owned by ``MainWindow``)
next to a ``TitleIdBar``.

It adapts to the window width: while everything fits it is a single row;
when the window gets too narrow the Title ID controls drop onto a second row
instead of forcing the window wider or getting squeezed.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QToolButton, QWidget

from .title_id_bar import TitleIdBar

_MIN_GAP = 6


class TopBar(QWidget):
    """Action buttons plus the Title ID controls, reflowing on narrow windows."""

    def __init__(
        self, actions: Sequence[QAction], title_id_bar: TitleIdBar, parent=None
    ) -> None:
        super().__init__(parent)

        self._buttons = QWidget(self)
        buttons_layout = QHBoxLayout(self._buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        for action in actions:
            button = QToolButton(self._buttons)
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setAutoRaise(True)
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)

        self._title_id_bar = title_id_bar
        self._title_id_bar.setParent(self)

        self._wide: bool | None = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._apply_layout(wide=True)

    def _apply_layout(self, wide: bool) -> None:
        """Place the two groups side by side (``wide``) or stacked."""
        if wide == self._wide:
            return
        self._wide = wide
        self._grid.removeWidget(self._buttons)
        self._grid.removeWidget(self._title_id_bar)
        if wide:
            self._grid.addWidget(self._buttons, 0, 0)
            self._grid.addWidget(self._title_id_bar, 0, 1)
            self._grid.setColumnStretch(0, 0)
            self._grid.setColumnStretch(1, 1)
        else:
            self._grid.addWidget(self._buttons, 0, 0)
            self._grid.addWidget(self._title_id_bar, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
        self.updateGeometry()

    def _side_by_side_width(self) -> int:
        """Width needed to show both groups on one row."""
        return (
            self._buttons.sizeHint().width()
            + max(self._grid.horizontalSpacing(), _MIN_GAP)  # -1 means "style default"
            + self._title_id_bar.sizeHint().width()
        )

    def resizeEvent(self, event) -> None:  # pylint: disable=invalid-name
        # Decided from the children's size hints, never from this widget's
        # own layout, so switching rows can't feed back into the decision.
        self._apply_layout(wide=event.size().width() >= self._side_by_side_width())
        super().resizeEvent(event)

    def minimumSizeHint(self) -> QSize:  # pylint: disable=invalid-name
        # Always report the *stacked* width as the minimum. Otherwise the
        # single-row layout's larger minimum would stop the window from
        # ever becoming narrow enough to trigger the stacked one.
        stacked_width = max(
            self._buttons.minimumSizeHint().width(),
            self._title_id_bar.minimumSizeHint().width(),
        )
        return QSize(stacked_width, self._grid.minimumSize().height())
