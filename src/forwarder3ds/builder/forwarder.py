"""Build one forwarder ``.cia``.

Per game nothing is compiled: the stub ``.elf`` built once with devkitARM
is repackaged by ``makerom`` together with

* a RomFS holding ``core.txt`` (libretro core name) and ``content.path``
  (ROM path on the SD card, without ``sdmc:/``);
* an SMDH icon and a banner made by ``bannertool``;
* a Title ID that is deterministic and collision-checked
  (:mod:`forwarder3ds.core.title_id`).

:func:`build_forwarder` is the single entry point for the CLI and the GUI.
It reports progress through the ``forwarder3ds.build`` logger and raises
:class:`~forwarder3ds.builder.errors.BuildError` on failure. An existing
forwarder can be read back with :func:`forwarder3ds.ctr.cia.read_forwarder_cia`
and rebuilt under its original Title ID (``replace_existing_id``).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.media import prepare_banner_audio, prepare_banner_image, prepare_icon
from forwarder3ds.builder.placeholders import ensure_placeholder_assets
from forwarder3ds.builder.toolchain import Toolchain, run_tool
from forwarder3ds.core.catalog import validate_platform_logo
from forwarder3ds.core.cores import DEFAULT_CORES_JSON, CoreCatalogError, CoreRegistry
from forwarder3ds.core.logs import get_logger, log_success
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER
from forwarder3ds.core.title_id import (
    ForwarderIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    generate_title_id,
    preview_unique_id,
    unique_id_to_title_id,
)

_log = get_logger("build")

CIA_EXTENSION = ".cia"
FALLBACK_CIA_STEM = "forwarder"
SMDH_FLAGS = "visible,recordusage"  # without "visible" the HOME menu hides the title


@dataclass
class ForwarderRequest:
    """Everything needed to produce one forwarder ``.cia``."""

    core: str
    rom_path: str
    name: str
    short_name: str
    long_name: str
    manufacturer: str
    output: Path
    icon: Path | None = None
    banner: Path | None = None
    audio: Path | None = None
    #: PNG (256x128, with transparency) drawn over the finished banner.
    platform_logo: Path | None = None
    manual_unique_id: int | None = None
    #: Set when rebuilding a CIA loaded from disk under its original Title
    #: ID: lets ``manual_unique_id`` take over an ID that the registry still
    #: attributes to the identity the CIA had before it was edited.
    replace_existing_id: bool = False

    @property
    def sd_rom_path(self) -> str:
        """The ROM path as stored in the RomFS (no ``sdmc:/``, no leading slash)."""
        return normalize_sd_path(self.rom_path)

    def identity(self) -> ForwarderIdentity:
        """The fields the Title ID is derived from."""
        return ForwarderIdentity(
            name=self.name,
            short_name=self.short_name,
            long_name=self.long_name,
            manufacturer=self.manufacturer,
            core=self.core,
            rom_path=self.sd_rom_path,
        )


@dataclass(frozen=True)
class BuildResult:
    """What a successful build produced."""

    unique_id: int
    output: Path

    @property
    def title_id(self) -> int:
        """Full 64-bit Title ID."""
        return unique_id_to_title_id(self.unique_id)


# ── Path helpers ─────────────────────────────────────────────────────────


def default_cia_filename(rom_path: str) -> str:
    """Default ``.cia`` file name: the ROM's basename without its extension.

    ``rom_path`` is an SD card path, so ``/`` and ``\\`` both separate
    directories whatever the host OS.
    """
    stem = PurePosixPath(rom_path.strip().replace("\\", "/")).stem
    return f"{stem or FALLBACK_CIA_STEM}{CIA_EXTENSION}"


def ensure_cia_extension(path: Path) -> Path:
    """``path`` ending in ``.cia`` (``game.v2`` becomes ``game.v2.cia``)."""
    if path.suffix.lower() == CIA_EXTENSION:
        return path
    return path.with_name(path.name + CIA_EXTENSION)


def normalize_sd_path(rom_path: str) -> str:
    """Strip an ``sdmc:/`` prefix and leading slashes; use ``/`` separators."""
    clean = rom_path.strip().replace("\\", "/")
    if clean.lower().startswith("sdmc:/"):
        clean = clean[len("sdmc:/") :]
    return clean.lstrip("/")


# ── Validation ───────────────────────────────────────────────────────────


def validate_request(request: ForwarderRequest, cores: CoreRegistry) -> None:
    """Raise :class:`BuildError` if ``request`` cannot be built."""
    if not request.core:
        raise BuildError("No RetroArch core given.")
    try:
        cores.require(request.core)
    except CoreCatalogError as exc:
        raise BuildError(str(exc)) from exc
    if not request.sd_rom_path:
        raise BuildError("No ROM path on the SD card given.")
    if not request.long_name:
        raise BuildError("No long name given.")
    for label, path in (
        ("icon", request.icon),
        ("banner", request.banner),
        ("audio", request.audio),
        ("platform logo", request.platform_logo),
    ):
        if path is not None and not path.is_file():
            raise BuildError(f"The {label} file does not exist: {path}")
    if request.platform_logo is not None:
        problem = validate_platform_logo(request.platform_logo)
        if problem:
            raise BuildError(f"Platform logo '{request.platform_logo.name}': {problem}")


def load_cores(cores_json: Path = DEFAULT_CORES_JSON) -> CoreRegistry:
    """The core catalog, with read errors turned into :class:`BuildError`."""
    try:
        return CoreRegistry.load(cores_json)
    except CoreCatalogError as exc:
        raise BuildError(str(exc)) from exc


def load_registry(path: Path) -> TitleIdRegistry:
    """The Title ID registry, with read errors turned into :class:`BuildError`."""
    try:
        return TitleIdRegistry.load(path)
    except (OSError, ValueError) as exc:
        raise BuildError(f"Cannot read the Title ID registry {path}: {exc}") from exc


def preview_title_id(
    request: ForwarderRequest, registry_path: Path, cores_json: Path = DEFAULT_CORES_JSON
) -> int:
    """The Unique ID a build of ``request`` would get, without writing anything."""
    cores = load_cores(cores_json)
    validate_request(request, cores)
    try:
        return preview_unique_id(
            request.identity(),
            cores.all_unique_ids(),
            load_registry(registry_path),
            request.manual_unique_id,
            request.replace_existing_id,
        )
    except TitleIdCollisionError as exc:
        raise BuildError(str(exc)) from exc


# ── Build steps ──────────────────────────────────────────────────────────


def _write_romfs(directory: Path, core: str, sd_rom_path: str) -> Path:
    romfs = directory / "romfs"
    romfs.mkdir(parents=True, exist_ok=True)
    (romfs / "core.txt").write_text(core, encoding="utf-8")
    (romfs / "content.path").write_text(sd_rom_path, encoding="utf-8")
    return romfs


def _make_smdh_and_banner(
    tools: Toolchain, request: ForwarderRequest, icon: Path, banner: Path, audio: Path
) -> tuple[Path, Path]:
    assert tools.bannertool is not None
    icon_icn = icon.with_name("icon.icn")
    banner_bnr = banner.with_name("banner.bnr")
    run_tool(
        [
            str(tools.bannertool), "makesmdh",
            "-s", request.short_name, "-l", request.long_name, "-p", request.manufacturer,
            "-f", SMDH_FLAGS, "-i", str(icon), "-o", str(icon_icn),
        ],
        "creating the icon",
    )  # fmt: skip
    run_tool(
        [str(tools.bannertool), "makebanner", "-i", str(banner), "-a", str(audio),
         "-o", str(banner_bnr)],
        "creating the banner",
    )  # fmt: skip
    return icon_icn, banner_bnr


def _make_cia(
    tools: Toolchain, romfs: Path, icon_icn: Path, banner_bnr: Path, unique_id: int, out: Path
) -> None:
    assert tools.makerom is not None and tools.stub is not None
    run_tool(
        [
            str(tools.makerom), "-f", "cia", "-target", "t", "-exefslogo",
            "-o", str(out), "-elf", str(tools.stub), "-rsf", str(tools.rsf),
            "-icon", str(icon_icn), "-banner", str(banner_bnr),
            f"-DROMFS_DIR={romfs}", f"-DUNIQUE_ID=0x{unique_id:05X}",
        ],
        "packaging the CIA",
    )  # fmt: skip


def build_forwarder(
    request: ForwarderRequest,
    tools: Toolchain,
    registry_path: Path,
    cores_json: Path = DEFAULT_CORES_JSON,
) -> BuildResult:
    """Build ``request`` into ``request.output``; raise :class:`BuildError` on failure.

    The Title ID is recorded in the registry at ``registry_path`` once it is
    assigned, before the tools run, exactly like an earlier build would have.
    """
    tools.require()
    cores = load_cores(cores_json)
    validate_request(request, cores)
    registry = load_registry(registry_path)
    try:
        unique_id, title_id = generate_title_id(
            request.identity(),
            cores.all_unique_ids(),
            registry,
            manual_unique_id=request.manual_unique_id,
            replace_existing=request.replace_existing_id,
        )
    except TitleIdCollisionError as exc:
        raise BuildError(str(exc)) from exc
    except OSError as exc:
        raise BuildError(f"Cannot write the Title ID registry {registry_path}: {exc}") from exc

    _log.info("Core %s, ROM sdmc:/%s", request.core, request.sd_rom_path)
    _log.info("Title ID 0x%016X (Unique ID 0x%05X)", title_id, unique_id)

    with tempfile.TemporaryDirectory(prefix="3ds-forwarder-") as scratch_name:
        scratch = Path(scratch_name)
        romfs = _write_romfs(scratch, request.core, request.sd_rom_path)

        placeholder_icon, placeholder_banner, _audio = ensure_placeholder_assets(
            scratch / "placeholders"
        )
        icon_png = scratch / "icon_48x48.png"
        banner_png = scratch / "banner_256x128.png"
        audio_wav = scratch / "audio.wav"
        _log.info("Preparing icon, banner and jingle")
        prepare_icon(request.icon or placeholder_icon, icon_png)
        prepare_banner_image(
            request.banner or placeholder_banner, banner_png, request.platform_logo
        )
        prepare_banner_audio(request.audio, audio_wav, tools.ffmpeg)

        _log.info("Running bannertool")
        icon_icn, banner_bnr = _make_smdh_and_banner(
            tools, request, icon_png, banner_png, audio_wav
        )

        _log.info("Running makerom")
        local_cia = scratch / "forwarder.cia"
        _make_cia(tools, romfs, icon_icn, banner_bnr, unique_id, local_cia)

        try:
            request.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_cia, request.output)
        except OSError as exc:
            raise BuildError(f"Cannot write {request.output}: {exc}") from exc

    log_success(_log, "Saved %s", request.output)
    return BuildResult(unique_id=unique_id, output=request.output)


def make_request(
    *,
    core: str,
    rom_path: str,
    long_name: str,
    output: Path,
    short_name: str = "",
    manufacturer: str = "",
    name: str = "",
    **extra: Any,
) -> ForwarderRequest:
    """A :class:`ForwarderRequest` with the usual defaults filled in.

    The internal name (part of the Title ID hash) and the short name default
    to the long name; the manufacturer to :data:`DEFAULT_MANUFACTURER`.
    """
    long_name = long_name.strip()
    return ForwarderRequest(
        core=core.strip(),
        rom_path=rom_path.strip(),
        name=name.strip() or long_name,
        short_name=short_name.strip() or long_name,
        long_name=long_name,
        manufacturer=manufacturer.strip() or DEFAULT_MANUFACTURER,
        output=output,
        **extra,
    )
