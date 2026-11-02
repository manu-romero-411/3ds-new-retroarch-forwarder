"""Entry point of ``3ds-forwarder-gui``."""

from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from forwarder3ds import __version__
from forwarder3ds.core.logs import setup_console_logging
from forwarder3ds.core.paths import bundled
from forwarder3ds.gui.main_window import APP_TITLE, MainWindow

APP_ID = "io.github.manu_romero_411.forwarder3ds"
ICON_SIZES = (16, 32, 48, 64, 128, 256)


def _install_qt_translations(app: QApplication) -> None:
    """Translate Qt's own strings (standard buttons...) to the system language."""
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale.system(), "qtbase", "_", path):
        app.installTranslator(translator)


def app_icon() -> QIcon:
    """Theme icon when installed, otherwise rendered from the bundled SVG."""
    svg = bundled(f"icons/{APP_ID}.svg")
    fallback = QIcon()
    renderer = QSvgRenderer(QByteArray(svg.read_bytes())) if svg.is_file() else None
    if renderer is not None and renderer.isValid():
        for size in ICON_SIZES:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            fallback.addPixmap(pixmap)
    return QIcon.fromTheme(APP_ID, fallback)


def main() -> int:
    """Start the graphical interface."""
    setup_console_logging()
    # argv[0] becomes the X11 WM_CLASS; match the desktop file id.
    app = QApplication.instance() or QApplication([APP_ID, *sys.argv[1:]])
    assert isinstance(app, QApplication)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    _install_qt_translations(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
