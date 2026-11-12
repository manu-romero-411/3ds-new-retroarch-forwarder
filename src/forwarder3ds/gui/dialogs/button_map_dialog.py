"""Edit the game's controls on a picture of the 3DS.

Each 3DS button gets a list of what the game sees when it is pressed: one
of the console's buttons, or nothing. The Circle Pad drives the D-Pad; on a
console with an analog controller (the PlayStation's DualShock) it can be
its stick instead. This is a RetroArch *remap*
(``game.rmp``): RetroArch's menu keeps the 3DS layout, and the menu itself
opens from the touch screen. Click a button on the picture or use the list.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.game_config import (
    ANALOG_DEVICES,
    CIRCLE_PAD,
    CIRCLE_PAD_DPAD,
    CIRCLE_PAD_STICK,
    CONSOLE_BUTTONS,
    UNMAPPED,
    console_targets,
    normalize_remap,
    target_labels,
)
from forwarder3ds.gui.widgets.button_map_view import ButtonMapView

#: The order of the rows: face buttons, shoulders, START/SELECT, d-pad.
_ROWS = ("a", "b", "x", "y", "l", "r", "l2", "r2", "start", "select", "up", "down", "left", "right")


class ButtonMapDialog(QDialog):
    """3DS picture on the left, one list per button on the right."""

    def __init__(
        self, parent: QWidget | None, console: str, console_name: str, remap: dict[str, str]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Button mapping — {console}").format(console=console_name))
        self._labels = target_labels(console)
        self._view = ButtonMapView()
        self._view.button_clicked.connect(self._focus_row)
        self._title = self.tr("{console}\nWhat each 3DS button does in the game").format(
            console=console_name
        )
        self._combos: dict[str, QComboBox] = {}

        form = QFormLayout()
        for button in _ROWS:
            combo = QComboBox()
            for target in console_targets(console):
                combo.addItem(self._labels[target], target)
            combo.addItem(self.tr("Nothing"), UNMAPPED)
            combo.currentIndexChanged.connect(self._refresh)
            combo.installEventFilter(self)
            self._combos[button] = combo
            form.addRow(f"{CONSOLE_BUTTONS[button]}:", combo)
        self._circle_pad = QComboBox()
        self._circle_pad.addItem(self.tr("D-Pad"), CIRCLE_PAD_DPAD)
        self._circle_pad.addItem(self.tr("Left stick (DualShock)"), CIRCLE_PAD_STICK)
        if console in ANALOG_DEVICES:
            form.addRow(self.tr("Circle Pad:"), self._circle_pad)
        self.set_remap(remap)

        defaults = QPushButton(self.tr("Restore defaults"))
        defaults.clicked.connect(lambda: self.set_remap({}))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        side = QVBoxLayout()
        side.addLayout(form)
        side.addStretch(1)
        side.addWidget(defaults)
        body = QHBoxLayout()
        body.addWidget(self._view, 1)
        body.addLayout(side)

        note = QLabel(
            self.tr(
                "Only the game's controls change; RetroArch's menu keeps the 3DS layout "
                "(A confirms, B goes back). Edited later, the remap in the game's save folder "
                "wins."
            )
        )
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(note)
        layout.addWidget(buttons, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(980, 640)

    def eventFilter(self, watched, event) -> bool:  # pylint: disable=invalid-name
        """Ring the button whose list has the focus."""
        if event.type() == event.Type.FocusIn:
            for button, combo in self._combos.items():
                if combo is watched:
                    self._view.select(button)
        return super().eventFilter(watched, event)

    def _focus_row(self, button: str) -> None:
        combo = self._combos.get(button)
        if combo is not None:
            combo.setFocus()
            combo.showPopup()

    def set_remap(self, remap: dict[str, str]) -> None:
        """Show ``remap`` (buttons not in it do what they do by default)."""
        for button, combo in self._combos.items():
            target = remap.get(button, button)
            index = combo.findData(target)
            if index < 0:  # a button this console lacks: list it anyway
                combo.addItem(self._labels.get(target, target), target)
                index = combo.count() - 1
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        stick = remap.get(CIRCLE_PAD) == CIRCLE_PAD_STICK
        self._circle_pad.setCurrentIndex(self._circle_pad.findData(
            CIRCLE_PAD_STICK if stick else CIRCLE_PAD_DPAD
        ))  # fmt: skip
        self._refresh()

    def remap(self) -> dict[str, str]:
        """The buttons that no longer do what they do by default."""
        remap = {button: str(combo.currentData()) for button, combo in self._combos.items()}
        if self._circle_pad.isVisibleTo(self):
            remap[CIRCLE_PAD] = str(self._circle_pad.currentData())
        return normalize_remap(remap)

    def _refresh(self) -> None:
        mapping = {button: str(combo.currentData()) for button, combo in self._combos.items()}
        self._view.set_state(mapping, self._labels, self._title)

    @staticmethod
    def edit(
        parent: QWidget | None, console: str, console_name: str, remap: dict[str, str]
    ) -> dict[str, str] | None:
        """Show the dialog; the new remap, or ``None`` if cancelled."""
        dialog = ButtonMapDialog(parent, console, console_name, remap)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.remap()
