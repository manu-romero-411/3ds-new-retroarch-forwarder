"""Injection options: how the game is shown and set up on first boot.

* **Screen**: pixel perfect, the core's aspect ratio, the whole 400x240
  screen or a custom size; bilinear filtering.
* **RetroArch**: the top screen bezel, the button mapping and the initial
  core options.

Everything here seeds the game's save folder the first time it boots; from
then on the files there (``retroarch.cfg``, ``game.opt``, the remap,
``bezel.png``) are the ones in use and can be edited by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.core_options import CoreOptions
from forwarder3ds.core.game_config import SCREEN_HEIGHT, SCREEN_WIDTH, ScreenMode, ScreenSettings
from forwarder3ds.gui.dialogs.button_map_dialog import ButtonMapDialog
from forwarder3ds.gui.dialogs.core_options_dialog import CoreOptionsDialog
from forwarder3ds.gui.widgets.path_picker import PathPicker

_IMAGE_FILTER = "Images (*.png *.webp *.jpg *.jpeg);;All files (*)"


@dataclass
class InjectionOptions:
    """What the dialog edits."""

    screen: ScreenSettings
    core_options: dict[str, str] = field(default_factory=dict)
    remap: dict[str, str] = field(default_factory=dict)
    #: The bezel image to use (``None``: no bezel).
    bezel: Path | None = None


@dataclass(frozen=True)
class GameContext:
    """What the dialog needs to know about the game."""

    console: str
    console_name: str
    core: str
    core_options: CoreOptions | None
    #: A standalone emulator: it has its own settings menu, none of these apply.
    standalone: bool = False


class InjectionOptionsDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """NSUI's *Injection method options*, for RetroArch."""

    def __init__(
        self, parent: QWidget | None, game: GameContext, options: InjectionOptions
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Injection options"))
        self._game = game
        self._core_options = dict(options.core_options)
        self._remap = dict(options.remap)

        self._modes = QButtonGroup(self)
        self._radios: dict[ScreenMode, QRadioButton] = {}
        texts = {
            ScreenMode.PIXEL_PERFECT: self.tr("Pixel perfect (square pixels, integer scale)"),
            ScreenMode.RECOMMENDED: self.tr("Recommended (as large as fits, core aspect ratio)"),
            ScreenMode.FULL: self.tr("Full screen (stretched to 400×240)"),
            ScreenMode.CUSTOM: self.tr("Custom:"),
        }
        for mode, text in texts.items():
            radio = QRadioButton(text)
            self._radios[mode] = radio
            self._modes.addButton(radio)
        self._width = QSpinBox()
        self._width.setRange(1, SCREEN_WIDTH)
        self._height = QSpinBox()
        self._height.setRange(1, SCREEN_HEIGHT)
        self._smooth = QCheckBox(self.tr("Bilinear filter"))
        self._bezel = PathPicker(
            select_dir=False, placeholder=self.tr("None"), file_filter=_IMAGE_FILTER
        )
        self._remap_label = QLabel()
        self._options_label = QLabel()

        screen = options.screen
        self._radios[screen.mode].setChecked(True)
        self._width.setValue(screen.width)
        self._height.setValue(screen.height)
        self._smooth.setChecked(screen.smooth)
        self._bezel.set_text(str(options.bezel) if options.bezel else "")
        self._radios[ScreenMode.CUSTOM].toggled.connect(self._update_custom)
        self._update_custom()
        self._update_summaries()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        screen_group = self._build_screen_group()
        retroarch_group = self._build_retroarch_group()
        if game.standalone:
            note = QLabel(
                self.tr(
                    "{core} is a standalone emulator with its own settings (screen, controls, "
                    "bezels…): set them in its menu on the console. The options below only "
                    "apply to RetroArch."
                ).format(core=game.core)
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            screen_group.setEnabled(False)
            retroarch_group.setEnabled(False)
        layout.addWidget(screen_group)
        layout.addWidget(retroarch_group)
        layout.addWidget(buttons)

    def _build_screen_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Screen"))
        column = QVBoxLayout(group)
        for mode in (ScreenMode.PIXEL_PERFECT, ScreenMode.RECOMMENDED, ScreenMode.FULL):
            column.addWidget(self._radios[mode])
        custom = QHBoxLayout()
        custom.addWidget(self._radios[ScreenMode.CUSTOM])
        custom.addWidget(self._width)
        custom.addWidget(QLabel("×"))
        custom.addWidget(self._height)
        custom.addStretch(1)
        column.addLayout(custom)
        column.addWidget(self._smooth)
        return group

    def _build_retroarch_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("RetroArch"))
        form = QFormLayout(group)
        form.addRow(self.tr("Bezel:"), self._bezel)
        hint = QLabel(
            self.tr(
                "Drawn over the top screen (400×240); the game shows through its transparent "
                "part. A bezel.png in the save folder replaces it."
            )
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        form.addRow("", hint)

        mapping = QPushButton(self.tr("Edit button mapping…"))
        mapping.clicked.connect(self._edit_mapping)
        form.addRow(mapping, self._remap_label)
        core = QPushButton(self.tr("Edit core options…"))
        core.clicked.connect(self._edit_core_options)
        if self._game.core_options is None:
            core.setEnabled(False)
            core.setToolTip(
                self.tr("The {core} base has no option list (rebuild it).").format(
                    core=self._game.core
                )
            )
        form.addRow(core, self._options_label)
        return group

    def _update_custom(self) -> None:
        custom = self._radios[ScreenMode.CUSTOM].isChecked()
        self._width.setEnabled(custom)
        self._height.setEnabled(custom)

    def _update_summaries(self) -> None:
        count = len(self._remap)
        self._remap_label.setText(
            self.tr("{n} button(s) changed").format(n=count) if count else self.tr("Default")
        )
        count = len(self._core_options)
        self._options_label.setText(
            self.tr("{n} option(s) changed").format(n=count) if count else self.tr("Defaults")
        )

    def _edit_mapping(self) -> None:
        remap = ButtonMapDialog.edit(self, self._game.console, self._game.console_name, self._remap)
        if remap is not None:
            self._remap = remap
            self._update_summaries()

    def _edit_core_options(self) -> None:
        if self._game.core_options is None:
            return
        values = CoreOptionsDialog.edit(
            self, self._game.core, self._game.core_options, self._core_options
        )
        if values is not None:
            self._core_options = values
            self._update_summaries()

    def options(self) -> InjectionOptions:
        """The edited options."""
        mode = next(mode for mode, radio in self._radios.items() if radio.isChecked())
        bezel = self._bezel.text()
        return InjectionOptions(
            screen=ScreenSettings(
                mode=mode,
                width=self._width.value(),
                height=self._height.value(),
                smooth=self._smooth.isChecked(),
            ),
            core_options=dict(self._core_options),
            remap=dict(self._remap),
            bezel=Path(bezel) if bezel else None,
        )

    @staticmethod
    def edit(
        parent: QWidget | None, game: GameContext, options: InjectionOptions
    ) -> InjectionOptions | None:
        """Show the dialog; the new options, or ``None`` if cancelled."""
        dialog = InjectionOptionsDialog(parent, game, options)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.options()
