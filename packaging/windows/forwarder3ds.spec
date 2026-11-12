# PyInstaller spec of the Windows build: two folders, "3DS Forwarder" with
# "3DS Forwarder.exe" (the GUI, no console) and "3ds-forwarder-cli" with
# 3ds-forwarder.exe (the command line tool, without Qt). build-windows.sh
# moves the second into the first as cli/ and adds the toolchain (makerom,
# bannertool, the RetroArch bases), so the GUI is the one program at the top.
# pylint: skip-file
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

HERE = Path(SPECPATH)
DATAS = collect_data_files("forwarder3ds")
# Imported only when present (the jingle preview).
HIDDEN = ["PySide6.QtMultimedia", "PySide6.QtSvg"]
EXCLUDES = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick"]

gui = Analysis(
    [str(HERE / "launch_gui.py")], datas=DATAS, hiddenimports=HIDDEN, excludes=EXCLUDES
)
cli = Analysis([str(HERE / "launch_cli.py")], datas=DATAS, excludes=EXCLUDES + ["PySide6"])

gui_exe = EXE(
    PYZ(gui.pure),
    gui.scripts,
    exclude_binaries=True,
    name="3DS Forwarder",
    icon=str(HERE / "forwarder3ds.ico"),
    console=False,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    exclude_binaries=True,
    name="3ds-forwarder",
    icon=str(HERE / "forwarder3ds.ico"),
    console=True,
)
COLLECT(gui_exe, gui.binaries, gui.datas, name="3DS Forwarder")
COLLECT(cli_exe, cli.binaries, cli.datas, name="3ds-forwarder-cli")
