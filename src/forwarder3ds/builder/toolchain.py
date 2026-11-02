"""Find and run the native tools a build needs.

A forwarder build calls two programs from the 3DS homebrew toolchain,
``bannertool`` (SMDH icon and banner) and ``makerom`` (the ``.cia``), and
repackages a stub ``.elf`` compiled once with devkitARM. The release
packages and ``install.sh`` ship all three, built for the user's system and
architecture, in a ``toolchain/`` directory::

    toolchain/
    ├── bin/makerom
    ├── bin/bannertool
    ├── stub/3ds-forwarder-stub.elf
    └── VERSIONS            # what was built, from which source revision

Each item is resolved on its own, first match wins:

1. an explicit path from the settings (``[toolchain]`` in ``config.ini``);
2. the toolchain directories of :func:`forwarder3ds.core.paths.toolchain_dirs`;
3. for the two programs, ``PATH``; for the stub, ``stub/`` of a git checkout
   (where ``make -C stub`` leaves it).

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

STUB_NAME = "3ds-forwarder-stub.elf"
VERSIONS_FILE = "VERSIONS"
_CHECKOUT_STUB = Path(__file__).resolve().parents[3] / "stub" / STUB_NAME


@dataclass(frozen=True)
class Toolchain:
    """Resolved locations; ``None`` for whatever could not be found."""

    makerom: Path | None
    bannertool: Path | None
    stub: Path | None
    ffmpeg: Path | None
    rsf: Path

    @property
    def missing(self) -> list[str]:
        """Names of the required items that were not found."""
        required = {"makerom": self.makerom, "bannertool": self.bannertool, "stub": self.stub}
        return [name for name, path in required.items() if path is None]

    @property
    def complete(self) -> bool:
        """True when a forwarder can be built."""
        return not self.missing

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


def _in_toolchain_dirs(relative: str) -> Path | None:
    for directory in paths.toolchain_dirs():
        candidate = directory / relative
        if candidate.is_file():
            return candidate
    return None


def _on_path(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def find_toolchain(settings: ToolchainSettings | None = None) -> Toolchain:
    """Resolve every tool (see the module docstring for the order)."""
    settings = settings or ToolchainSettings()
    makerom = (
        _explicit(settings.makerom) or _in_toolchain_dirs("bin/makerom") or _on_path("makerom")
    )
    bannertool = (
        _explicit(settings.bannertool)
        or _in_toolchain_dirs("bin/bannertool")
        or _on_path("bannertool")
    )
    stub = (
        _explicit(settings.stub)
        or _in_toolchain_dirs(f"stub/{STUB_NAME}")
        or (_CHECKOUT_STUB if _CHECKOUT_STUB.is_file() else None)
    )
    ffmpeg = _explicit(settings.ffmpeg) or _on_path("ffmpeg")
    return Toolchain(
        makerom=makerom,
        bannertool=bannertool,
        stub=stub,
        ffmpeg=ffmpeg,
        rsf=paths.bundled("forwarder.rsf"),
    )


def run_tool(cmd: list[str], what: str, cwd: Path | None = None) -> str:
    """Run ``cmd``; return its output, or raise :class:`BuildError` with it on failure."""
    _log.debug("Running %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=cwd, errors="replace"
        )
    except OSError as exc:
        raise BuildError(f"Cannot run {cmd[0]} ({what}): {exc}") from exc
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise BuildError(f"{Path(cmd[0]).name} failed while {what}:\n{output or '(no output)'}")
    return output
