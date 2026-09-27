"""app.py — Qt application entry point.

Run as a module from the project root so ``tools`` and ``ui`` resolve as
siblings importable packages::

    python3 -m ui.app

(``run_ui.py`` at the project root is a thin convenience wrapper around
this for people who'd rather double-click / run a single script.)
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("3DS Forwarder Builder")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
