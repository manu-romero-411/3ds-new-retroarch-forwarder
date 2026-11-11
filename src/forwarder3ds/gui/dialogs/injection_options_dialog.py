"""Injection options: how the game is shown and set up on first boot.

Like NSUI's *Injection method options*, with live previews of both screens:

* **Screen**: pixel perfect, the core's aspect ratio, the whole 400x240
  screen or a custom size; bilinear filtering (RetroArch only). The preview
  uses libretro's screenshot of the game when there is one.
* **Screens**: the touch screen picture (the settings' choice, the
  Virtual Console style message in any language, an image of your own or
  the emulator's own) and the top screen bezel. Both apply to every
  emulator: RetroArch draws the bezel over the game, a standalone emulator
  behind it.
* **RetroArch**: the button mapping and the initial core options.

Everything here seeds the game's save folder the first time it boots; from
then on the files there (``retroarch.cfg``, ``game.opt``, the remap,
``bezel.png``) are the ones in use and can be edited by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.artwork.bottom_screen import (
    CHOICE_DEFAULT,
    CHOICE_IMAGE,
    CHOICE_NONE,
    LANGUAGE_NAMES,
    BottomScreenStyle,
    choice_language,
    render_bottom_screen,
    vc_choice,
)
from forwarder3ds.artwork.screen_preview import (
    BOTTOM_HEIGHT,
    BOTTOM_WIDTH,
    console_screen,
    fit_bottom,
    game_size,
    open_image,
    render_top_preview,
    to_png,
)
from forwarder3ds.core.core_options import CoreOptions
from forwarder3ds.core.game_config import SCREEN_HEIGHT, SCREEN_WIDTH, ScreenMode, ScreenSettings
from forwarder3ds.gui.dialogs.button_map_dialog import ButtonMapDialog
from forwarder3ds.gui.dialogs.core_options_dialog import CoreOptionsDialog
from forwarder3ds.gui.widgets.path_picker import PathPicker

_IMAGE_FILTER = "Images (*.png *.webp *.jpg *.jpeg);;All files (*)"
_BOTTOM_PREVIEW_SCALE = 0.75

#: Asks for the game's screenshot and calls back with it (``None``: there is none).
ScreenshotLoader = Callable[[Callable[[bytes | None], None]], None]


@dataclass
class InjectionOptions:
    """What the dialog edits."""

    screen: ScreenSettings
    core_options: dict[str, str] = field(default_factory=dict)
    remap: dict[str, str] = field(default_factory=dict)
    #: The bezel image to use (``None``: no bezel).
    bezel: Path | None = None
    #: The touch screen choice (see ``Project.bottom_screen``).
    bottom_screen: str = CHOICE_DEFAULT
    #: The picture for :data:`CHOICE_IMAGE`.
    bottom_image: Path | None = None


@dataclass(frozen=True)
class GameContext:  # pylint: disable=too-many-instance-attributes
    """What the dialog needs to know about the game."""

    console: str
    console_name: str
    core: str
    core_options: CoreOptions | None
    #: A standalone emulator: its own menu sets the screen, controls and options.
    standalone: bool = False
    #: The emulator's menu, as the touch screen message names it.
    menu_name: str = "RetroArch"
    #: The touch screen the settings give (``None``: the emulator's own).
    default_touch: BottomScreenStyle | None = None
    #: The font of the touch screen message (the settings').
    touch_font: str = ""
    load_screenshot: ScreenshotLoader | None = None


class InjectionOptionsDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """NSUI's *Injection method options*: screen, touch screen, bezel, RetroArch."""

    def __init__(
        self, parent: QWidget | None, game: GameContext, options: InjectionOptions
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Injection options"))
        self._game = game
        self._core_options = dict(options.core_options)
        self._remap = dict(options.remap)
        self._screenshot: Image.Image | None = None
        self._images: dict[str, Image.Image | None] = {}

        self._top_preview = QLabel()
        self._top_preview.setFixedSize(SCREEN_WIDTH, SCREEN_HEIGHT)
        self._bottom_preview = QLabel()
        self._bottom_preview.setFixedSize(
            round(BOTTOM_WIDTH * _BOTTOM_PREVIEW_SCALE),
            round(BOTTOM_HEIGHT * _BOTTOM_PREVIEW_SCALE),
        )
        self._bottom_preview.setScaledContents(True)
        self._bottom_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._modes = QButtonGroup(self)
        self._radios = {mode: QRadioButton() for mode in ScreenMode}
        for radio in self._radios.values():
            self._modes.addButton(radio)
        self._width = QSpinBox()
        self._width.setRange(1, SCREEN_WIDTH)
        self._height = QSpinBox()
        self._height.setRange(1, SCREEN_HEIGHT)
        self._smooth = QCheckBox(self.tr("Bilinear filter"))
        self._bezel = PathPicker(
            select_dir=False, placeholder=self.tr("None"), file_filter=_IMAGE_FILTER
        )
        self._touch = QComboBox()
        self._fill_touch_choices()
        self._touch_image = PathPicker(
            select_dir=False, placeholder=self.tr("None"), file_filter=_IMAGE_FILTER
        )
        self._remap_label = QLabel()
        self._options_label = QLabel()

        self._load(options)
        self._label_modes()
        self._connect_previews()

        self._build_layout()
        self._update_custom()
        self._update_summaries()
        self._refresh_top()
        self._refresh_bottom()
        if game.load_screenshot is not None:
            game.load_screenshot(self._on_screenshot)

    # ── Building ─────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        if self._game.standalone:
            layout.addWidget(self._standalone_note())
        columns = QHBoxLayout()
        columns.addWidget(self._build_screen_group())
        right = QVBoxLayout()
        right.addWidget(self._build_screens_group())
        right.addWidget(self._build_retroarch_group())
        right.addStretch(1)
        columns.addLayout(right)
        layout.addLayout(columns)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill_touch_choices(self) -> None:
        default = self._game.default_touch
        if default is None:
            summary = self.tr("the emulator's own")
        else:
            summary = self.tr("VC message, {language}").format(
                language=LANGUAGE_NAMES.get(default.language, default.language)
            )
        self._touch.addItem(self.tr("Settings ({choice})").format(choice=summary), CHOICE_DEFAULT)
        for code, name in LANGUAGE_NAMES.items():
            self._touch.addItem(self.tr("VC message in {language}").format(language=name),
                                vc_choice(code))  # fmt: skip
        self._touch.addItem(self.tr("My image (below)"), CHOICE_IMAGE)
        self._touch.addItem(self.tr("The emulator's own"), CHOICE_NONE)

    def _load(self, options: InjectionOptions) -> None:
        screen = options.screen
        self._radios[screen.mode].setChecked(True)
        self._width.setValue(screen.width)
        self._height.setValue(screen.height)
        self._smooth.setChecked(screen.smooth)
        self._bezel.set_text(str(options.bezel) if options.bezel else "")
        index = self._touch.findData(options.bottom_screen)
        self._touch.setCurrentIndex(max(index, 0))
        self._touch_image.set_text(str(options.bottom_image) if options.bottom_image else "")

    def _connect_previews(self) -> None:
        for radio in self._radios.values():
            radio.toggled.connect(self._refresh_top)
        self._radios[ScreenMode.CUSTOM].toggled.connect(self._update_custom)
        self._width.valueChanged.connect(self._refresh_top)
        self._height.valueChanged.connect(self._refresh_top)
        self._smooth.toggled.connect(self._refresh_top)
        self._bezel.edit.textChanged.connect(self._refresh_top)
        self._touch.currentIndexChanged.connect(self._refresh_bottom)
        self._touch_image.edit.textChanged.connect(self._on_touch_image)

    def _label_modes(self) -> None:
        native = console_screen(self._game.console)

        def sized(text: str, mode: ScreenMode) -> str:
            width, height = game_size(ScreenSettings(mode=mode), native)
            return f"{text} ({width}×{height})"

        self._radios[ScreenMode.PIXEL_PERFECT].setText(
            sized(self.tr("Pixel perfect"), ScreenMode.PIXEL_PERFECT)
        )
        self._radios[ScreenMode.RECOMMENDED].setText(
            sized(self.tr("Recommended"), ScreenMode.RECOMMENDED)
        )
        self._radios[ScreenMode.FULL].setText(sized(self.tr("Full screen"), ScreenMode.FULL))
        self._radios[ScreenMode.CUSTOM].setText(self.tr("Custom:"))
        self._radios[ScreenMode.PIXEL_PERFECT].setToolTip(
            self.tr("Square pixels at a whole scale: the console's pixels, never resampled.")
        )
        self._radios[ScreenMode.RECOMMENDED].setToolTip(
            self.tr("As large as it fits, at the core's aspect ratio.")
        )

    def _standalone_note(self) -> QLabel:
        note = QLabel(
            self.tr(
                "{core} is a standalone emulator: its own menu on the console sets the screen "
                "size, controls and options. The touch screen and the bezel (drawn behind the "
                "game) do apply."
            ).format(core=self._game.core)
        )
        note.setWordWrap(True)
        return note

    def _build_screen_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Screen"))
        column = QVBoxLayout(group)
        column.addWidget(self._top_preview, 0, Qt.AlignmentFlag.AlignHCenter)
        modes = QWidget()
        grid = QGridLayout(modes)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self._radios[ScreenMode.PIXEL_PERFECT], 0, 0)
        grid.addWidget(self._radios[ScreenMode.RECOMMENDED], 0, 1)
        grid.addWidget(self._radios[ScreenMode.FULL], 1, 0)
        custom = QHBoxLayout()
        custom.addWidget(self._radios[ScreenMode.CUSTOM])
        custom.addWidget(self._width)
        custom.addWidget(QLabel("×"))
        custom.addWidget(self._height)
        custom.addStretch(1)
        grid.addLayout(custom, 1, 1)
        column.addWidget(modes)
        column.addWidget(self._smooth)
        bezel = QFormLayout()
        bezel.addRow(self.tr("Bezel:"), self._bezel)
        hint = QLabel(
            self.tr(
                "Top screen picture (stretched to 400×240); the game shows through its "
                "transparent part. A bezel.png in the save folder replaces it."
            )
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        bezel.addRow("", hint)
        column.addLayout(bezel)
        column.addStretch(1)
        if self._game.standalone:
            modes.setEnabled(False)
            self._smooth.setEnabled(False)
        return group

    def _build_screens_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("Touch screen"))
        form = QFormLayout(group)
        form.addRow(self._bottom_preview)
        form.setAlignment(self._bottom_preview, Qt.AlignmentFlag.AlignHCenter)
        form.addRow(self.tr("Picture:"), self._touch)
        form.addRow(self.tr("Image:"), self._touch_image)
        hint = QLabel(
            self.tr(
                "Any image of yours (stretched to 320×240), or one of the Virtual Console "
                "style messages. Shown while the game runs."
            )
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        form.addRow("", hint)
        return group

    def _build_retroarch_group(self) -> QGroupBox:
        group = QGroupBox(self.tr("RetroArch"))
        form = QFormLayout(group)
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
        group.setEnabled(not self._game.standalone)
        return group

    # ── Previews ─────────────────────────────────────────────────────────

    def _image(self, path: str) -> Image.Image | None:
        """The picture at ``path``, read once."""
        if not path:
            return None
        if path not in self._images:
            self._images[path] = open_image(Path(path))
        return self._images[path]

    def _on_screenshot(self, data: bytes | None) -> None:
        self._screenshot = open_image(data) if data else None
        self._refresh_top()

    def _screen(self) -> ScreenSettings:
        mode = next(mode for mode, radio in self._radios.items() if radio.isChecked())
        if self._game.standalone:
            mode = ScreenMode.RECOMMENDED
        return ScreenSettings(
            mode=mode,
            width=self._width.value(),
            height=self._height.value(),
            smooth=self._smooth.isChecked() and not self._game.standalone,
        )

    def _refresh_top(self) -> None:
        image = render_top_preview(
            console=self._game.console,
            screen=self._screen(),
            screenshot=self._screenshot,
            bezel=self._image(self._bezel.text()),
            bezel_behind=self._game.standalone,
        )
        self._top_preview.setPixmap(_pixmap(to_png(image)))

    def _touch_style(self, choice: str) -> BottomScreenStyle | None:
        language = choice_language(choice)
        if language is not None:
            return BottomScreenStyle(language, self._game.touch_font)
        return self._game.default_touch if choice == CHOICE_DEFAULT else None

    def _on_touch_image(self, path: str) -> None:
        """Picking an image selects it as the touch screen."""
        if path.strip() and self._touch.currentData() != CHOICE_IMAGE:
            self._touch.setCurrentIndex(self._touch.findData(CHOICE_IMAGE))
        else:
            self._refresh_bottom()

    def _refresh_bottom(self) -> None:
        choice = self._touch.currentData()
        picture = None
        if choice == CHOICE_IMAGE:
            own = self._image(self._touch_image.text())
            picture = fit_bottom(own) if own is not None else None
        else:
            style = self._touch_style(choice)
            if style is not None:
                picture = render_bottom_screen(self._game.menu_name, style)
        if picture is None:
            self._bottom_preview.setPixmap(QPixmap())
            self._bottom_preview.setText(self.tr("The emulator's own"))
            return
        self._bottom_preview.setPixmap(_pixmap(to_png(picture)))

    # ── RetroArch ────────────────────────────────────────────────────────

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

    # ── Result ───────────────────────────────────────────────────────────

    def options(self) -> InjectionOptions:
        """The edited options."""
        mode = next(mode for mode, radio in self._radios.items() if radio.isChecked())
        bezel = self._bezel.text()
        touch_image = self._touch_image.text()
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
            bottom_screen=self._touch.currentData() or CHOICE_DEFAULT,
            bottom_image=Path(touch_image) if touch_image else None,
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


def _pixmap(png: bytes) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(png)
    return pixmap
