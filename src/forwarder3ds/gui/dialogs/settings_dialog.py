"""Settings window: one page per concern, navigated from a side list.

Pages edit a private copy of :class:`~forwarder3ds.core.settings.Settings`;
nothing is applied until *Apply* or *OK* is pressed.
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.artwork.banner_card import CardStyle, render_card_png
from forwarder3ds.artwork.bottom_screen import (
    LANGUAGE_NAMES,
    BottomScreenStyle,
    render_bottom_screen_png,
)
from forwarder3ds.artwork.console_icons import icons_dir
from forwarder3ds.artwork.steamgriddb import API_KEY_HELP_URL, SGDBClient
from forwarder3ds.builder.toolchain import find_toolchain
from forwarder3ds.core import catalog, paths
from forwarder3ds.core.fonts import font_path
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER, Settings, ToolchainSettings
from forwarder3ds.ctr.formats import BANNER_HEIGHT, BANNER_WIDTH
from forwarder3ds.gui.bridge import TaskThread
from forwarder3ds.gui.widgets.font_picker import FontPicker
from forwarder3ds.gui.widgets.path_picker import PathPicker


class _Page(QWidget):
    """A settings page: copies values in and out of a :class:`Settings`."""

    title = ""

    def load(self, settings: Settings) -> None:
        """Fill the widgets from ``settings``."""

    def store(self, settings: Settings) -> None:
        """Write the widgets back into ``settings``."""


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    return label


class GeneralPage(_Page):
    """Defaults for new games and where files go."""

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("General")
        self._manufacturer = QLineEdit()
        self._manufacturer.setPlaceholderText(DEFAULT_MANUFACTURER)
        self._output = PathPicker(select_dir=True, placeholder=str(Path.home()))
        self._registry = PathPicker(
            select_dir=False,
            placeholder=str(paths.default_registry_file()),
            file_filter=self.tr("JSON files (*.json)"),
        )
        form = QFormLayout(self)
        form.addRow(self.tr("Default manufacturer:"), self._manufacturer)
        form.addRow(self.tr("Save new CIAs in:"), self._output)
        form.addRow(self.tr("Title ID registry:"), self._registry)
        form.addRow(
            "",
            _hint(
                self.tr(
                    "Every Title ID handed out is recorded here, so two games never "
                    "share one. Point several computers at the same (synced) file to keep "
                    "that true across them."
                )
            ),
        )

    def load(self, settings: Settings) -> None:
        general = settings.general
        self._manufacturer.setText(
            "" if general.manufacturer == DEFAULT_MANUFACTURER else general.manufacturer
        )
        self._output.set_text(general.output_dir)
        self._registry.set_text(general.registry)

    def store(self, settings: Settings) -> None:
        general = settings.general
        general.manufacturer = self._manufacturer.text().strip() or DEFAULT_MANUFACTURER
        general.output_dir = self._output.text()
        general.registry = self._registry.text()


class _CheckSignals(QObject):
    done = Signal(bool, str)


class SteamGridDBPage(_Page):
    """API key, a *Test* button and the search filters."""

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("SteamGridDB")
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self._nsfw = QCheckBox(self.tr("Include artwork marked as adult content"))
        self._humor = QCheckBox(self.tr("Include humorous artwork"))
        self._status = QLabel()
        self._thread: TaskThread | None = None
        test = QPushButton(self.tr("Test"))
        test.clicked.connect(self._test)

        key_row = QHBoxLayout()
        key_row.addWidget(self._key, 1)
        key_row.addWidget(test)
        form = QFormLayout(self)
        form.addRow(self.tr("API key:"), key_row)
        form.addRow("", self._status)
        form.addRow(
            "",
            _hint(
                self.tr(
                    "SteamGridDB is where icons, heroes and logos come from. Get a key in "
                    '<a href="{url}">your SteamGridDB preferences</a>.'
                ).format(url=API_KEY_HELP_URL)
            ),
        )
        form.addRow(self._nsfw)
        form.addRow(self._humor)

    def load(self, settings: Settings) -> None:
        self._key.setText(settings.steamgriddb.api_key)
        self._nsfw.setChecked(settings.steamgriddb.nsfw)
        self._humor.setChecked(settings.steamgriddb.humor)

    def store(self, settings: Settings) -> None:
        settings.steamgriddb.api_key = self._key.text().strip()
        settings.steamgriddb.nsfw = self._nsfw.isChecked()
        settings.steamgriddb.humor = self._humor.isChecked()

    def _test(self) -> None:
        if self._thread is not None:
            return
        client = SGDBClient(self._key.text())
        self._status.setText(self.tr("Testing…"))
        self._thread = TaskThread(client.check, parent=self)
        self._thread.succeeded.connect(lambda _r: self._status.setText(self.tr("✔ The key works.")))
        self._thread.failed.connect(lambda message: self._status.setText(f"✘ {message}"))
        self._thread.finished.connect(self._on_test_finished)
        self._thread.start()

    def _on_test_finished(self) -> None:
        self._thread = None


class ToolchainPage(_Page):
    """Where makerom, bannertool, the RetroArch bases and ffmpeg are; overrides if needed."""

    # (settings key, label, is a folder)
    _ITEMS = (
        ("makerom", "makerom:", False),
        ("bannertool", "bannertool:", False),
        ("bases", "RetroArch bases:", True),
        ("ffmpeg", "ffmpeg (optional):", False),
    )

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("Toolchain")
        self._pickers: dict[str, PathPicker] = {}
        form = QFormLayout(self)
        form.addRow(
            _hint(
                self.tr(
                    "The packages and install.sh ship these tools built for this system. "
                    "Leave a field empty to use what is found automatically (shown in grey). "
                    "The bases folder holds one RetroArch build per core "
                    "(packaging/toolchain/build-base.sh)."
                )
            )
        )
        for key, label, is_dir in self._ITEMS:
            picker = PathPicker(select_dir=is_dir)
            picker.edit.textChanged.connect(self._refresh_status)
            self._pickers[key] = picker
            form.addRow(self.tr(label), picker)
        self._status = QLabel()
        self._status.setWordWrap(True)
        form.addRow("", self._status)
        self._detected = find_toolchain()
        self._show_detected()

    def _current(self) -> ToolchainSettings:
        return ToolchainSettings(**{key: picker.text() for key, picker in self._pickers.items()})

    def _show_detected(self) -> None:
        for key, picker in self._pickers.items():
            found = getattr(self._detected, key)
            picker.set_placeholder(str(found) if found else self.tr("Not found"))

    def _refresh_status(self) -> None:
        tools = find_toolchain(self._current())
        if tools.complete:
            self._status.setText(
                self.tr("✔ Ready. Cores with a base: {cores}").format(
                    cores=", ".join(tools.available_cores()) or self.tr("none")
                )
            )
        else:
            self._status.setText(
                self.tr("✘ Missing: {items}").format(items=", ".join(tools.missing))
            )

    def load(self, settings: Settings) -> None:
        self._detected = find_toolchain()
        self._show_detected()
        for key, picker in self._pickers.items():
            picker.set_text(getattr(settings.toolchain, key))
        self._refresh_status()

    def store(self, settings: Settings) -> None:
        settings.toolchain = self._current()


class MediaPage(_Page):
    """Where the user's own jingles and platform logos go."""

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("Jingles and logos")
        form = QFormLayout(self)
        form.addRow(
            _hint(
                self.tr(
                    "Drop your own files in these folders; they are listed after the bundled "
                    "ones.<br><b>Jingles:</b> {jingles}<br><b>Platform logos:</b> {logos}"
                ).format(jingles=catalog.JINGLE_RULES, logos=catalog.PLATFORM_LOGO_RULES)
            )
        )
        for label, folder in (
            (self.tr("Jingles:"), paths.user_jingles_dir()),
            (self.tr("Platform logos:"), paths.user_platform_logos_dir()),
        ):
            button = QPushButton(self.tr("Open"))
            button.clicked.connect(lambda _=False, f=folder: self.open_folder(f))
            row = QHBoxLayout()
            path_label = QLabel(str(folder))
            path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(path_label, 1)
            row.addWidget(button)
            form.addRow(label, row)

    @staticmethod
    def open_folder(folder: Path) -> None:
        """Create ``folder`` if needed and show it in the file manager."""
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class _ColourButton(QPushButton):
    """A button showing a colour; clicking it opens a colour picker."""

    changed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self._colour = "#000000"
        self.setFixedWidth(90)
        self.clicked.connect(self._pick)

    def colour(self) -> str:
        """The colour as ``#rrggbb``."""
        return self._colour

    def set_colour(self, colour: str) -> None:
        """Show ``colour`` (``#rrggbb``)."""
        if QColor(colour).isValid():
            self._colour = QColor(colour).name()
        self.setText(self._colour)
        text = "#000000" if QColor(self._colour).lightness() > 128 else "#ffffff"
        self.setStyleSheet(f"background: {self._colour}; color: {text};")

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._colour), self, self._title)
        if chosen.isValid():
            self.set_colour(chosen.name())
            self.changed.emit()


class BannerPage(_Page):
    """Colours and font of the default banner (logo + console tag)."""

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("Banner")
        self._background = _ColourButton(self.tr("Tag colour"))
        self._text = _ColourButton(self.tr("Banner text"))
        self._font = FontPicker()
        self._preview = QLabel()
        self._preview.setFixedSize(BANNER_WIDTH * 2, BANNER_HEIGHT * 2)
        self._background.changed.connect(self._refresh)
        self._text.changed.connect(self._refresh)
        self._font.changed.connect(self._refresh)

        icons = QPushButton(self.tr("Open"))
        icons.clicked.connect(lambda: MediaPage.open_folder(icons_dir()))
        icons_path = QLabel(str(icons_dir()))
        icons_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        icons_row = QHBoxLayout()
        icons_row.addWidget(icons_path, 1)
        icons_row.addWidget(icons)
        form = QFormLayout(self)
        form.addRow(self.tr("Tag colour:"), self._background)
        form.addRow(self.tr("Text:"), self._text)
        form.addRow(self.tr("Font:"), self._font)
        form.addRow(self.tr("Console icons:"), icons_row)
        form.addRow(
            "",
            _hint(
                self.tr(
                    "The default icon of each console: a PNG named after it (gb.png, "
                    "snes.png…; generic.png for the rest). Each project can pick another "
                    "image."
                )
            ),
        )
        form.addRow(self._preview)

    def _style(self) -> CardStyle:
        return CardStyle(
            self._background.colour(), self._text.colour(), font_path(self._font.choice())
        )

    def _refresh(self) -> None:
        png = render_card_png(
            console="snes", title="Super Mario World", year="1990", style=self._style()
        )
        pixmap = QPixmap()
        pixmap.loadFromData(png)
        self._preview.setPixmap(pixmap.scaled(self._preview.size()))

    def load(self, settings: Settings) -> None:
        self._background.set_colour(settings.banner.background)
        self._text.set_colour(settings.banner.text)
        self._font.set_choice(settings.banner.font_choice)
        self._refresh()

    def store(self, settings: Settings) -> None:
        style = self._style()
        settings.banner.background = style.background
        settings.banner.text = style.text
        settings.banner.font_choice = self._font.choice()


class BottomScreenPage(_Page):
    """The Virtual Console style touch screen shown while a game runs."""

    def __init__(self) -> None:
        super().__init__()
        self.title = self.tr("Touch screen")
        self._enabled = QCheckBox(self.tr("Virtual Console style touch screen"))
        self._language = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self._language.addItem(name, code)
        self._font = FontPicker()
        self._preview = QLabel()
        self._preview.setFixedSize(320, 240)
        self._enabled.toggled.connect(self._refresh)
        self._language.currentIndexChanged.connect(self._refresh)
        self._font.changed.connect(self._refresh)

        form = QFormLayout(self)
        form.addRow(self._enabled)
        form.addRow(self.tr("Language:"), self._language)
        form.addRow(self.tr("Font:"), self._font)
        form.addRow(
            "",
            _hint(
                self.tr(
                    "Shown on the touch screen while the game runs, instead of the "
                    "emulator's own. Nintendo's font is FOT-Rodin (not included)."
                )
            ),
        )
        form.addRow(self._preview)

    def _style(self) -> BottomScreenStyle:
        return BottomScreenStyle(
            self._language.currentData() or "en", font_path(self._font.choice())
        )

    def _refresh(self) -> None:
        enabled = self._enabled.isChecked()
        self._language.setEnabled(enabled)
        self._font.setEnabled(enabled)
        pixmap = QPixmap()
        if enabled:
            pixmap.loadFromData(render_bottom_screen_png("RetroArch", self._style()))
        self._preview.setPixmap(pixmap)

    def load(self, settings: Settings) -> None:
        touch = settings.bottom_screen
        self._enabled.setChecked(touch.enabled)
        index = self._language.findData(touch.language)
        self._language.setCurrentIndex(max(index, 0))
        self._font.set_choice(touch.font_choice)
        self._refresh()

    def store(self, settings: Settings) -> None:
        style = self._style()
        settings.bottom_screen.enabled = self._enabled.isChecked()
        settings.bottom_screen.language = style.language
        settings.bottom_screen.font_choice = self._font.choice()


class SettingsDialog(QDialog):
    """Side list of pages plus OK / Apply / Cancel."""

    applied = Signal(object)  # a new Settings

    def __init__(self, settings: Settings, parent: QWidget | None = None, page: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.resize(760, 460)
        self._settings = copy.deepcopy(settings)
        self._pages: list[_Page] = [
            GeneralPage(),
            SteamGridDBPage(),
            ToolchainPage(),
            MediaPage(),
            BannerPage(),
            BottomScreenPage(),
        ]

        self._list = QListWidget()
        self._list.setMaximumWidth(180)
        self._stack = QStackedWidget()
        for page_widget in self._pages:
            self._list.addItem(page_widget.title)
            self._stack.addWidget(page_widget)
            page_widget.load(self._settings)
        self._list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._list.setCurrentRow(max(0, min(page, len(self._pages) - 1)))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.clicked.connect(self._apply)

        body = QHBoxLayout()
        body.addWidget(self._list)
        body.addWidget(self._stack, 1)
        column = QVBoxLayout(self)
        column.addLayout(body, 1)
        column.addWidget(buttons)

    def _apply(self) -> None:
        for page_widget in self._pages:
            page_widget.store(self._settings)
        self.applied.emit(copy.deepcopy(self._settings))

    def accept(self) -> None:
        """Apply, then close."""
        self._apply()
        super().accept()


#: Page indexes, for opening the dialog on a given page.
PAGE_GENERAL, PAGE_STEAMGRIDDB, PAGE_TOOLCHAIN, PAGE_MEDIA, PAGE_BANNER = range(5)
