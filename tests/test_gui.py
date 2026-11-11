"""The library, a project tab and the option dialogs, off-screen."""

# pylint: disable=missing-function-docstring,protected-access,no-member

from __future__ import annotations

import os
import time
import zlib
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# pylint: disable=wrong-import-position
import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forwarder3ds.core.game_config import ScreenMode, ScreenSettings  # noqa: E402
from forwarder3ds.core.romdb import GameDatabase  # noqa: E402
from forwarder3ds.gui.context import AppContext  # noqa: E402
from forwarder3ds.gui.dialogs.button_map_dialog import ButtonMapDialog  # noqa: E402
from forwarder3ds.gui.dialogs.injection_options_dialog import (  # noqa: E402
    GameContext,
    InjectionOptions,
    InjectionOptionsDialog,
)
from forwarder3ds.gui.main_window import MainWindow  # noqa: E402
from forwarder3ds.gui.project_editor import ProjectEditor  # noqa: E402
from forwarder3ds.gui.widgets import rom_info  # noqa: E402


@pytest.fixture(name="app", scope="module")
def fixture_app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    return instance


def _pump(app: QApplication, until, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_project_tab_follows_the_database(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rom = tmp_path / "Super Mario Wrld (hack).sfc"
    rom.write_bytes(b"\1" * 512)
    dat = (
        'game (\n name "Super Mario World (USA)"\n'
        f' rom ( name "x.sfc" size 512 crc {zlib.crc32(rom.read_bytes()):08X} )\n)\n'
    )
    monkeypatch.setattr(rom_info, "_DATABASES", {})
    monkeypatch.setattr(rom_info, "load_database", lambda *_a: GameDatabase.from_dats(dat))

    context = AppContext()
    project = context.store.create(
        rom, "snes", core="snes9x2005", long_name="Super Mario Wrld", folder="Super Mario Wrld"
    )
    window = MainWindow(context)
    window.show()
    assert window._library.chosen() == []
    window._open_projects([project])
    editor = window._tabs.currentWidget()
    assert isinstance(editor, ProjectEditor)
    _pump(app, lambda: editor.project.db_name)
    assert editor.project.db_name == "Super Mario World (USA)"
    assert editor.project.long_name == "Super Mario World"
    assert editor.project.folder == "Super Mario World"
    assert editor._title_id._title_id_edit.text().startswith("0x000400000F")
    editor.save()
    (stored,) = context.store.list()
    assert stored.long_name == "Super Mario World"
    assert context.problem(stored) is not None  # no base built here
    window._close_tab(1)
    window.close()
    shiboken6.delete(window)  # not at interpreter exit, where Qt may crash


def test_option_dialogs_round_trip(app: QApplication) -> None:
    del app
    remap = {"a": "b", "b": "a", "select": "none"}
    mapping = ButtonMapDialog(None, "snes", "Super Nintendo", remap)
    assert mapping.remap() == remap
    mapping.set_remap({})
    assert not mapping.remap()

    options = InjectionOptions(ScreenSettings(ScreenMode.CUSTOM, 360, 200, True), remap=remap)
    game = GameContext("snes", "Super Nintendo", "snes9x2005", None)
    dialog = InjectionOptionsDialog(None, game, options)
    assert dialog.options() == options
    shiboken6.delete(dialog)
    shiboken6.delete(mapping)
