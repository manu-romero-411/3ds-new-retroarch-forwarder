"""Where things live: per-user directories, bundled data and the toolchain.

User files follow the XDG base directory spec (``~/.config``,
``~/.local/share``, ``~/.cache``). Nothing is ever written next to the
installed code, so the package can live in a read-only prefix such as
``/opt/3ds-new-retroarch-forwarder``.

The native toolchain (``makerom``, ``bannertool`` and the pre-built stub
``.elf``) is looked up in a ``toolchain/`` directory, see
:func:`toolchain_dirs` for the search order.
"""

from __future__ import annotations

import os
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


def _xdg(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "").strip()
    return (Path(value) if value else Path.home() / fallback) / USER_DIR_NAME


def config_dir() -> Path:
    """Directory holding ``config.ini``."""
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    """Directory for user data: the Title ID registry, extra jingles and logos."""
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    """Directory for disposable files (build scratch space)."""
    return _xdg("XDG_CACHE_HOME", ".cache")


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

    1. ``$FORWARDER3DS_TOOLCHAIN``;
    2. ``<prefix>/toolchain`` where the package sits in ``<prefix>/lib`` (the
       .deb/.rpm layout) or ``<prefix>/src`` (a git checkout);
    3. ``<venv>/../toolchain`` (``install.sh`` puts the venv next to it);
    4. ``~/.local/share/3ds-forwarder/toolchain``.

    Missing directories are kept out of the list.
    """
    candidates: list[Path] = []
    override = os.environ.get(TOOLCHAIN_ENV, "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(_PACKAGE_DIR.parent.parent / TOOLCHAIN_DIR_NAME)
    candidates.append(Path(sys.prefix).parent / TOOLCHAIN_DIR_NAME)
    candidates.append(data_dir() / TOOLCHAIN_DIR_NAME)
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in unique:
            unique.append(candidate)
    return unique
