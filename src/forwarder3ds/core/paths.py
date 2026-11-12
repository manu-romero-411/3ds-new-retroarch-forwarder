"""Where things live: per-user directories, bundled data and the toolchain.

User files follow the XDG base directory spec (``~/.config``,
``~/.local/share``, ``~/.cache``); on Windows they go to ``%APPDATA%`` and
``%LOCALAPPDATA%``. Nothing is ever written next to the installed code, so
the package can live in a read-only prefix such as
``/opt/3ds-new-retroarch-forwarder`` (or an AppImage).

The native toolchain (``makerom``, ``bannertool`` and the pre-built
RetroArch bases) is looked up in a ``toolchain/`` directory, see
:func:`toolchain_dirs` for the search order.
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

#: Name of the per-user directories (``~/.config/3ds-forwarder``...).
USER_DIR_NAME = "3ds-forwarder"
#: Environment variable that points at a toolchain directory, first in the search.
TOOLCHAIN_ENV = "FORWARDER3DS_TOOLCHAIN"
#: Name of the toolchain directory looked up next to the installation.
TOOLCHAIN_DIR_NAME = "toolchain"

_PACKAGE_DIR = Path(__file__).resolve().parent.parent


_WINDOWS = sys.platform == "win32"


def _xdg(variable: str, fallback: str, windows: str) -> Path:
    """``$variable`` (XDG), or ``%windows%`` on Windows, else ``~/fallback``; plus our folder."""
    value = os.environ.get(variable, "").strip()
    if not value and _WINDOWS:
        value = os.environ.get(windows, "").strip()
    return (Path(value) if value else Path.home() / fallback) / USER_DIR_NAME


def config_dir() -> Path:
    """Directory holding ``config.ini``."""
    return _xdg("XDG_CONFIG_HOME", ".config", "APPDATA")


def data_dir() -> Path:
    """Directory for user data: the Title ID registry, extra jingles and logos."""
    return _xdg("XDG_DATA_HOME", ".local/share", "APPDATA")


def bios_dir(core: str = "") -> Path:
    """The BIOS files to pack with every game of ``core`` (``<data>/bios/<core>``).

    Laid out as in the console's system folder (``fbneo/neogeo.zip``); the
    CIA carries them and RetroArch reads them as part of the game's system
    folder.
    """
    root = data_dir() / "bios"
    return root / core if core else root


def cache_dir() -> Path:
    """Directory for disposable files (build scratch space)."""
    return _xdg("XDG_CACHE_HOME", ".cache", "LOCALAPPDATA")


#: ``subprocess`` flags for console programs: on Windows, no console window
#: flashing up from the graphical program.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def executable(name: str) -> str:
    """``name`` as an executable file name on this system (``makerom.exe`` on Windows)."""
    return f"{name}.exe" if _WINDOWS else name


def config_file() -> Path:
    """Main settings file."""
    return config_dir() / "config.ini"


def ui_state_file() -> Path:
    """Window layout (sizes, splitter); safe to delete."""
    return config_dir() / "ui.ini"


def default_registry_file() -> Path:
    """Default location of the Title ID registry."""
    return data_dir() / "title_id_registry.json"


def user_jingles_dir() -> Path:
    """Folder for the user's own banner jingles (listed after the bundled ones)."""
    return data_dir() / "jingles"


def user_platform_logos_dir() -> Path:
    """Folder for the user's own platform logos (listed after the bundled ones)."""
    return data_dir() / "platform_logos"


def bundled(name: str) -> Path:
    """Path of a file or folder shipped in ``forwarder3ds/data``."""
    return Path(str(resources.files("forwarder3ds.data").joinpath(name)))


def toolchain_dirs() -> list[Path]:
    """Candidate toolchain directories, most specific first.

    1. ``$FORWARDER3DS_TOOLCHAIN`` (the AppImage sets it);
    2. ``toolchain`` beside the program, or beside its folder (the command
       line tool in ``cli/``), for the Windows build (PyInstaller);
    3. ``<prefix>/toolchain`` where the package sits in ``<prefix>/lib`` (the
       .deb/.rpm layout) or ``<prefix>/src`` (a git checkout);
    4. ``<venv>/../toolchain`` (``install.sh`` puts the venv next to it);
    5. ``~/.local/share/3ds-forwarder/toolchain``.

    Missing directories are kept out of the list.
    """
    candidates: list[Path] = []
    override = os.environ.get(TOOLCHAIN_ENV, "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    if getattr(sys, "frozen", False):  # a PyInstaller build: the toolchain sits beside it
        program_dir = Path(sys.executable).resolve().parent
        candidates.append(program_dir / TOOLCHAIN_DIR_NAME)
        candidates.append(program_dir.parent / TOOLCHAIN_DIR_NAME)  # cli/ of the Windows build
    candidates.append(_PACKAGE_DIR.parent.parent / TOOLCHAIN_DIR_NAME)
    candidates.append(Path(sys.prefix).parent / TOOLCHAIN_DIR_NAME)
    candidates.append(data_dir() / TOOLCHAIN_DIR_NAME)
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in unique:
            unique.append(candidate)
    return unique
