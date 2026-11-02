"""The main window opens and reacts to input (off-screen)."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# pylint: disable=wrong-import-position
from PySide6.QtWidgets import QApplication  # noqa: E402

from forwarder3ds.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(name="app", scope="module")
def fixture_app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    return instance


def test_title_id_follows_the_fields(app: QApplication) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    # pylint: disable=protected-access
    window._game._select_core("snes9x2005")
    window._game._rom_edit.setText("roms/snes/Super Mario World (USA).sfc")
    assert window._game.fields().long_name == "Super Mario World"
    assert window._title_id._title_id_edit.text().startswith("0x000400000F")
    assert window._document.dirty
    window._document.dirty = False
    window.close()
