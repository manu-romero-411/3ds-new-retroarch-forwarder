"""Find and run the native tools a build needs.

A build calls two programs from the 3DS homebrew toolchain, ``bannertool``
(SMDH icon and banner) and ``makerom`` (the ``.cia``), and packs one of the
*bases*, compiled once with devkitARM by ``packaging/toolchain/build-base.sh``:
RetroArch + one core, or a standalone emulator (e.g. ``snes9x_3ds``) that
brings its own RSF and RomFS files. The release packages and
``install.sh`` ship them, built for the user's system and architecture, in
a ``toolchain/`` directory::

    toolchain/
    ├── bin/makerom
    ├── bin/bannertool
    ├── bases/<core>/retroarch.elf     RetroArch + core, patched
    ├── bases/<core>/base.env          memory mode and source revisions
    ├── bases/<core>/assets/bottom_menu.png
    ├── bases/<emulator>/app.elf       a standalone emulator, patched
    ├── bases/<emulator>/app.rsf       its makerom settings
    ├── bases/<emulator>/romfs/        its own RomFS files
    └── VERSIONS                       what was built, from which revision

Each item is resolved on its own, first match wins:

1. an explicit path from the settings (``[toolchain]`` in ``config.ini``);
2. the toolchain directories of :func:`forwarder3ds.core.paths.toolchain_dirs`;
3. for the two programs, ``PATH``; for the bases, ``toolchain/bases`` of a
   git checkout (where ``build-base.sh toolchain ...`` leaves them).

``ffmpeg`` is optional and only searched for in the settings and ``PATH``.
Nothing here uses Docker.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds.builder.errors import BuildError
from forwarder3ds.core import paths
from forwarder3ds.core.logs import get_logger
from forwarder3ds.core.settings import ToolchainSettings

_log = get_logger("toolchain")

BASES_DIR = "bases"
BASE_ELF = "retroarch.elf"
STANDALONE_ELF = "app.elf"
STANDALONE_RSF = "app.rsf"
STANDALONE_ROMFS = "romfs"
BASE_ENV = "base.env"
BOTTOM_MENU_ASSET = "assets/bottom_menu.png"
VERSIONS_FILE = "VERSIONS"
_CHECKOUT_BASES = Path(__file__).resolve().parents[3] / "toolchain" / BASES_DIR


def _base_elf(directory: Path) -> Path | None:
    for name in (BASE_ELF, STANDALONE_ELF):
        if (directory / name).is_file():
            return directory / name
    return None


@dataclass(frozen=True)
class Base:  # pylint: disable=too-many-instance-attributes
    """One compiled base: RetroArch linked with ``core``, or a standalone emulator."""

    core: str
    elf: Path
    system_mode: str
    system_mode_ext: str
    big_text_section: bool
    bottom_menu: Path | None
    info: dict[str, str]
    #: A standalone emulator's own RSF and RomFS files (``None`` for RetroArch).
    rsf: Path | None = None
    romfs: Path | None = None

    @property
    def standalone(self) -> bool:
        """True for a standalone emulator (no RetroArch settings apply)."""
        return self.info.get("KIND") == "standalone"

    @property
    def menu_name(self) -> str:
        """What the emulator's menu is called, for the touch screen's message."""
        if not self.standalone:
            return self.info.get("MENU_NAME") or "RetroArch"
        return self._standalone_info("MENU_NAME") or self.core

    def _standalone_info(self, key: str) -> str:
        """``key`` from ``base.env``; for a base built before it had it, the known value."""
        value = self.info.get(key, "").strip()
        if not value and self.standalone:
            value = _STANDALONE_DEFAULTS.get(self.core, {}).get(key, "")
        return value

    def _romfs_files(self, key: str) -> list[str]:
        return [item.strip() for item in self._standalone_info(key).split(",") if item.strip()]

    @property
    def bottom_screen_files(self) -> list[str]:
        """RomFS paths a standalone emulator reads its touch screen picture from."""
        return self._romfs_files("BOTTOM_SCREEN_FILES")

    @property
    def top_background_files(self) -> list[str]:
        """RomFS paths a standalone emulator reads its picture behind the game from."""
        return self._romfs_files("TOP_BACKGROUND_FILES")

    @classmethod
    def load(cls, directory: Path) -> "Base":
        """Read ``directory`` (``bases/<core>``); raise :class:`BuildError` if broken."""
        elf, env = _base_elf(directory), directory / BASE_ENV
        if elf is None or not env.is_file():
            raise BuildError(f"Incomplete base in {directory} (rebuild it).")
        info = _parse_versions(env)
        bottom_menu = directory / BOTTOM_MENU_ASSET
        rsf, romfs = directory / STANDALONE_RSF, directory / STANDALONE_ROMFS
        if info.get("KIND") == "standalone" and not rsf.is_file():
            raise BuildError(f"The base in {directory} has no {STANDALONE_RSF} (rebuild it).")
        return cls(
            core=info.get("CORE_NAME", directory.name),
            elf=elf,
            system_mode=info.get("APP_SYSTEM_MODE") or "64MB",
            system_mode_ext=info.get("APP_SYSTEM_MODE_EXT") or "Legacy",
            big_text_section=info.get("APP_BIG_TEXT_SECTION", "0") == "1",
            bottom_menu=bottom_menu if bottom_menu.is_file() else None,
            info=info,
            rsf=rsf if rsf.is_file() else None,
            romfs=romfs if romfs.is_dir() else None,
        )


#: What ``emulators/<name>/recipe.env`` puts in ``base.env``, for bases built
#: before those keys existed.
_STANDALONE_DEFAULTS: dict[str, dict[str, str]] = {
    "snes9x_3ds": {
        "MENU_NAME": "snes9x",
        "BOTTOM_SCREEN_FILES": "gfx/background_second_screen_us.png,"
        "gfx/background_second_screen_pal.png",
        "TOP_BACKGROUND_FILES": "gfx/background_game_screen.png",
    },
}


@dataclass(frozen=True)
class Toolchain:
    """Resolved locations; ``None`` for whatever could not be found."""

    makerom: Path | None
    bannertool: Path | None
    bases: Path | None
    ffmpeg: Path | None
    rsf: Path

    @property
    def missing(self) -> list[str]:
        """Names of the required items that were not found."""
        required = {"makerom": self.makerom, "bannertool": self.bannertool, "bases": self.bases}
        return [name for name, path in required.items() if path is None]

    @property
    def complete(self) -> bool:
        """True when a game can be built (given a base for its core)."""
        return not self.missing

    def available_cores(self) -> list[str]:
        """Cores with a compiled base, sorted."""
        if self.bases is None:
            return []
        return sorted(entry.name for entry in self.bases.iterdir() if _base_elf(entry))

    def base(self, core: str) -> Base:
        """The base for ``core``; raise :class:`BuildError` if there is none."""
        if self.bases is None or _base_elf(self.bases / core) is None:
            available = ", ".join(self.available_cores()) or "none"
            raise BuildError(
                f"No base for '{core}' (available: {available}). Build it with "
                f"packaging/toolchain/build-base.sh TOOLCHAIN_DIR {core}."
            )
        return Base.load(self.bases / core)

    def require(self) -> None:
        """Raise :class:`BuildError` naming what is missing, if anything."""
        if self.missing:
            raise BuildError(
                "Toolchain incomplete, missing: "
                + ", ".join(self.missing)
                + ". Install the release package or run install.sh, or set the paths in "
                "Settings › Toolchain (3ds-forwarder doctor shows what was searched)."
            )

    def versions(self) -> dict[str, str]:
        """Contents of the ``VERSIONS`` file next to the tools, if there is one."""
        for tool in (self.makerom, self.bannertool):
            if tool is None:
                continue
            for candidate in (tool.parent.parent / VERSIONS_FILE, tool.parent / VERSIONS_FILE):
                if candidate.is_file():
                    return _parse_versions(candidate)
        return {}


def _parse_versions(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            table[key.strip()] = value.strip()
    return table


def _explicit(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        return path
    _log.warning("Configured tool not found: %s", path)
    return None


def _explicit_dir(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_dir():
        return path
    _log.warning("Configured folder not found: %s", path)
    return None


def _in_toolchain_dirs(relative: str) -> Path | None:
    for directory in paths.toolchain_dirs():
        candidate = directory / relative
        if candidate.is_file():
            return candidate
    return None


def _bases_in_toolchain_dirs() -> Path | None:
    for directory in paths.toolchain_dirs():
        candidate = directory / BASES_DIR
        if candidate.is_dir():
            return candidate
    return None


def _on_path(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def find_toolchain(settings: ToolchainSettings | None = None) -> Toolchain:
    """Resolve every tool (see the module docstring for the order)."""
    settings = settings or ToolchainSettings()
    makerom = (
        _explicit(settings.makerom)
        or _in_toolchain_dirs(f"bin/{paths.executable('makerom')}")
        or _on_path("makerom")
    )
    bannertool = (
        _explicit(settings.bannertool)
        or _in_toolchain_dirs(f"bin/{paths.executable('bannertool')}")
        or _on_path("bannertool")
    )
    bases = (
        _explicit_dir(settings.bases)
        or _bases_in_toolchain_dirs()
        or (_CHECKOUT_BASES if _CHECKOUT_BASES.is_dir() else None)
    )
    ffmpeg = _explicit(settings.ffmpeg) or _on_path("ffmpeg")
    return Toolchain(
        makerom=makerom,
        bannertool=bannertool,
        bases=bases,
        ffmpeg=ffmpeg,
        rsf=paths.bundled("injected.rsf"),
    )


def run_tool(cmd: list[str], what: str, cwd: Path | None = None) -> str:
    """Run ``cmd``; return its output, or raise :class:`BuildError` with it on failure."""
    _log.debug("Running %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            errors="replace",
            creationflags=paths.NO_WINDOW,
        )
    except OSError as exc:
        raise BuildError(f"Cannot run {cmd[0]} ({what}): {exc}") from exc
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise BuildError(f"{Path(cmd[0]).name} failed while {what}:\n{output or '(no output)'}")
    return output
