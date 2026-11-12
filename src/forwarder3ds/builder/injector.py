"""Build one standalone game ``.cia``.

Nothing is compiled per game: a RetroArch *base* (RetroArch statically
linked with one core and patched for single-game mode, see
``retroarch/patches/``) is repackaged by ``makerom`` together with

* a flat RomFS holding the ROM as ``game.<ext>``, ``manifest.cfg`` (where
  the game keeps its data on the SD card, plus the fields needed to read
  the CIA back), the seed ``retroarch.cfg`` (with the game's screen
  settings), the menu's colour theme, the touch screen asset and, optionally, a top screen bezel
  (``bezel.png`` + its overlay ``bezel.cfg``), initial core options
  (``game.opt``) and a control remap (``game.rmp``);
* an SMDH icon and a banner made by ``bannertool``;
* a Title ID that is deterministic and collision-checked
  (:mod:`forwarder3ds.core.title_id`).

On the console the game keeps everything in one flat folder,
``sdmc:/saves/<console>/<game>/``: ``retroarch.cfg``, ``game.srm``,
``game.state*``, ``game.opt``... BIOS files go in ``sdmc:/emu_bios/``.
An arcade romset keeps its own name instead of ``game`` (``sf2.zip``, so
``sf2.srm``...): the emulator recognizes the game by it.
A ``bezel.png`` dropped in that folder replaces the CIA's own bezel.

:func:`build_game` is the single entry point for the CLI and the GUI. It
reports progress through the ``forwarder3ds.build`` logger and raises
:class:`~forwarder3ds.builder.errors.BuildError` on failure. An existing
game CIA can be read back with :func:`forwarder3ds.ctr.cia.read_game_cia`
and rebuilt under its original Title ID (``replace_existing_id``).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forwarder3ds.artwork.bottom_screen import BottomScreenStyle, render_bottom_screen_to_file
from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.media import (
    prepare_banner_audio,
    prepare_banner_image,
    prepare_bezel,
    prepare_bottom_image,
    prepare_flat_bezel,
    prepare_icon,
)
from forwarder3ds.builder.placeholders import ensure_placeholder_assets
from forwarder3ds.builder.toolchain import Base, Toolchain, run_tool
from forwarder3ds.core.archives import ArchiveError, extract, inner_name, is_archive
from forwarder3ds.core.catalog import validate_platform_logo
from forwarder3ds.core.core_options import options_file_text
from forwarder3ds.core.cores import DEFAULT_CORES_JSON, CoreCatalogError, CoreRegistry
from forwarder3ds.core.game_config import ScreenSettings, remap_text
from forwarder3ds.core.logs import get_logger, log_success
from forwarder3ds.core.names import save_folder_name
from forwarder3ds.core.paths import bundled
from forwarder3ds.core.projects import Asset, Project
from forwarder3ds.core.settings import DEFAULT_MANUFACTURER
from forwarder3ds.core.systems import DEFAULT_SYSTEMS_JSON, SystemCatalog, SystemCatalogError
from forwarder3ds.core.title_id import (
    GameIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    generate_title_id,
    preview_unique_id,
    unique_id_to_title_id,
)

_log = get_logger("build")

CIA_EXTENSION = ".cia"
FALLBACK_CIA_STEM = "game"
SMDH_FLAGS = "visible,recordusage"  # without "visible" the HOME menu hides the title
#: SMDH flags of a title kept out of the Activity Log.
SMDH_FLAGS_UNRECORDED = "visible"

#: Root of every game's data folder on the SD card.
SAVES_ROOT = "sdmc:/saves"
#: Shared BIOS folder (RetroArch's "system" directory) of every game.
BIOS_DIR = "sdmc:/emu_bios"
#: Base name of the ROM inside the RomFS, hence of its saves (game.srm...).
CONTENT_STEM = "game"
MANIFEST_FILE = "manifest.cfg"
SEED_CONFIG_FILE = "retroarch.cfg"
#: The menu's colour theme, referenced by the seed config.
MENU_THEME_FILE = "rgui_theme.cfg"
#: Drawn by RetroArch on the touch screen while the game runs (patch 0004).
BOTTOM_IDLE_FILE = "bottom_idle.png"
BEZEL_FILE = "bezel.png"
BEZEL_OVERLAY_FILE = "bezel.cfg"
#: RetroArch overlay showing ``bezel.png`` over the whole top screen (the same
#: text the patched RetroArch writes next to a bezel.png on the SD card).
BEZEL_OVERLAY = (
    "overlays = 1\n"
    f'overlay0_overlay = "{BEZEL_FILE}"\n'
    "overlay0_full_screen = true\n"
    "overlay0_descs = 0\n"
)
CORE_OPTIONS_FILE = "game.opt"
REMAP_FILE = "game.rmp"
#: makerom's BasicInfo Title is limited to 64 bytes.
_RSF_TITLE_MAX = 64


@dataclass
class GameRequest:  # pylint: disable=too-many-instance-attributes
    """Everything needed to produce one game ``.cia``."""

    core: str
    rom: Path
    console: str
    folder: str
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
    #: Top screen bezel (any image; scaled to 400x240, transparency kept).
    bezel: Path | None = None
    #: The ROM's own file name; for a ``.zip``, the name of the ROM inside it.
    rom_name: str = ""
    #: An arcade romset: packed as it is, under its own name.
    arcade: bool = False
    #: Screen scaling and filtering (``None``: RetroArch's defaults).
    screen: ScreenSettings | None = None
    #: Initial core options (key -> value), written as ``game.opt``.
    core_options: dict[str, str] = field(default_factory=dict)
    #: Game controls: 3DS button -> RetroPad button (see :mod:`~forwarder3ds.core.game_config`).
    remap: dict[str, str] = field(default_factory=dict)
    manual_unique_id: int | None = None
    #: The Virtual Console style touch screen (``None``: the emulator's own).
    bottom_screen: BottomScreenStyle | None = None
    #: A touch screen picture of the user's (any size, stretched to 320x240);
    #: wins over ``bottom_screen``.
    bottom_image: Path | None = None
    #: Keep the game out of the HOME menu's Activity Log.
    hide_from_activity_log: bool = False
    #: Set when rebuilding a CIA loaded from disk under its original Title
    #: ID: lets ``manual_unique_id`` take over an ID that the registry still
    #: attributes to the identity the CIA had before it was edited.
    replace_existing_id: bool = False

    @property
    def data_dir(self) -> str:
        """The game's folder on the SD card, e.g. ``sdmc:/saves/snes/Super Mario World``."""
        return f"{SAVES_ROOT}/{self.console}/{self.folder}"

    @property
    def content_name(self) -> str:
        """The ROM's name inside the RomFS: ``game`` plus its extension, lowercase.

        An arcade romset keeps its own (lowercase) name: it is the game's identity.
        """
        name = self.rom_name or self.rom.name
        if self.arcade:
            return name.lower()
        return CONTENT_STEM + Path(name).suffix.lower()

    def identity(self) -> GameIdentity:
        """The fields the Title ID is derived from."""
        return GameIdentity(
            name=self.name,
            short_name=self.short_name,
            long_name=self.long_name,
            manufacturer=self.manufacturer,
            core=self.core,
            data_dir=self.data_dir,
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


def default_cia_filename(long_name: str) -> str:
    """Default ``.cia`` file name: the game's title, made safe for any file system."""
    stem = save_folder_name(long_name) if long_name.strip() else FALLBACK_CIA_STEM
    return f"{stem}{CIA_EXTENSION}"


def ensure_cia_extension(path: Path) -> Path:
    """``path`` ending in ``.cia`` (``game.v2`` becomes ``game.v2.cia``)."""
    if path.suffix.lower() == CIA_EXTENSION:
        return path
    return path.with_name(path.name + CIA_EXTENSION)


# ── Catalogs ─────────────────────────────────────────────────────────────


def load_cores(cores_json: Path = DEFAULT_CORES_JSON) -> CoreRegistry:
    """The core catalog, with read errors turned into :class:`BuildError`."""
    try:
        return CoreRegistry.load(cores_json)
    except CoreCatalogError as exc:
        raise BuildError(str(exc)) from exc


def load_systems(systems_json: Path = DEFAULT_SYSTEMS_JSON) -> SystemCatalog:
    """The console catalog, with read errors turned into :class:`BuildError`."""
    try:
        return SystemCatalog.load(systems_json)
    except SystemCatalogError as exc:
        raise BuildError(str(exc)) from exc


def load_registry(path: Path) -> TitleIdRegistry:
    """The Title ID registry, with read errors turned into :class:`BuildError`."""
    try:
        return TitleIdRegistry.load(path)
    except (OSError, ValueError) as exc:
        raise BuildError(f"Cannot read the Title ID registry {path}: {exc}") from exc


# ── Validation ───────────────────────────────────────────────────────────


def validate_request(request: GameRequest, cores: CoreRegistry, systems: SystemCatalog) -> None:
    """Raise :class:`BuildError` if ``request`` cannot be built."""
    if not request.core:
        raise BuildError("No core given.")
    try:
        system = systems.require(request.console)
        if request.core not in system.cores:  # e.g. a standalone emulator for it
            cores.require(request.core)
    except (CoreCatalogError, SystemCatalogError) as exc:
        raise BuildError(str(exc)) from exc
    if not request.rom.is_file():
        raise BuildError(f"The ROM does not exist: {request.rom}")
    if is_archive(request.rom):
        try:
            inner_name(request.rom, systems.require(request.console).extensions)
        except ArchiveError as exc:
            raise BuildError(str(exc)) from exc
    if not request.folder or save_folder_name(request.folder) != request.folder:
        raise BuildError(f"Invalid save folder name: '{request.folder}'.")
    if not request.long_name:
        raise BuildError("No long name given.")
    for label, path in (
        ("icon", request.icon),
        ("banner", request.banner),
        ("audio", request.audio),
        ("platform logo", request.platform_logo),
        ("bezel", request.bezel),
    ):
        if path is not None and not path.is_file():
            raise BuildError(f"The {label} file does not exist: {path}")
    if request.platform_logo is not None:
        problem = validate_platform_logo(request.platform_logo)
        if problem:
            raise BuildError(f"Platform logo '{request.platform_logo.name}': {problem}")


def preview_title_id(
    request: GameRequest, registry_path: Path, cores_json: Path = DEFAULT_CORES_JSON
) -> int:
    """The Unique ID a build of ``request`` would get, without writing anything."""
    cores = load_cores(cores_json)
    validate_request(request, cores, load_systems())
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


def _quote(value: str) -> str:
    """A RetroArch config value; the format has no escapes, so ``"`` cannot appear."""
    if '"' in value or "\n" in value:
        raise BuildError(f"Value not allowed in a RetroArch config file: {value!r}")
    return f'"{value}"'


def manifest_text(request: GameRequest) -> str:
    """``manifest.cfg``: read by the patched RetroArch and by :mod:`forwarder3ds.ctr.cia`."""
    entries = {
        "content": request.content_name,
        "data_dir": request.data_dir,
        "system_dir": BIOS_DIR,
        "core": request.core,
        "console": request.console,
        "game": request.folder,
        "rom_name": request.rom_name or request.rom.name,
    }
    lines = ["# Single-game CIA (retroarch/patches/0001-ctr-single-game-mode.patch)."]
    lines += [f"{key} = {_quote(value)}" for key, value in entries.items()]
    return "\n".join(lines) + "\n"


def seed_config_text(request: GameRequest) -> str:
    """The bundled seed ``retroarch.cfg`` plus the lines that depend on this game."""
    base = bundled(SEED_CONFIG_FILE).read_text(encoding="utf-8")
    entries = {"core_options_path": f"{request.data_dir}/{CORE_OPTIONS_FILE}"}
    if request.screen is not None:
        entries.update(request.screen.config_lines())
    lines = [f"{key} = {_quote(value)}" for key, value in entries.items()]
    return f"{base.rstrip()}\n\n# --- This game ---\n" + "\n".join(lines) + "\n"


def write_romfs(directory: Path, request: GameRequest, base: Base) -> Path:
    """Lay out the CIA's RomFS in ``directory/romfs`` and return that folder.

    A standalone emulator gets its own RomFS files, the ROM, the manifest and
    the pictures it can take (touch screen; bezel, as its game background):
    RetroArch's settings (screen, controls, core options) do not apply to it.
    """
    romfs = directory / "romfs"
    if base.standalone and base.romfs is not None:
        shutil.copytree(base.romfs, romfs, dirs_exist_ok=True)
    romfs.mkdir(parents=True, exist_ok=True)
    try:
        if is_archive(request.rom) and not request.arcade:  # nothing to extract on the console
            extensions = load_systems().require(request.console).extensions
            extract(request.rom, extensions, romfs / request.content_name)
        else:
            shutil.copyfile(request.rom, romfs / request.content_name)
    except (OSError, ArchiveError, SystemCatalogError) as exc:
        raise BuildError(f"Cannot read {request.rom}: {exc}") from exc
    (romfs / MANIFEST_FILE).write_text(manifest_text(request), encoding="utf-8")
    if base.standalone:
        _write_standalone_pictures(romfs, request, base)
        if request.core_options or request.remap:
            _log.info("%s has its own settings: controls and core options skipped", base.core)
        return romfs
    (romfs / SEED_CONFIG_FILE).write_text(seed_config_text(request), encoding="utf-8")
    shutil.copyfile(bundled(MENU_THEME_FILE), romfs / MENU_THEME_FILE)
    _write_retroarch_pictures(romfs, request, base)
    if request.core_options:
        for value in request.core_options.values():
            _quote(value)
        (romfs / CORE_OPTIONS_FILE).write_text(
            options_file_text(request.core_options), encoding="utf-8"
        )
    (romfs / REMAP_FILE).write_text(remap_text(request.remap, request.console), encoding="utf-8")
    return romfs


def _write_bottom_picture(target: Path, request: GameRequest, base: Base) -> None:
    """The touch screen picture at ``target``: the user's image, the VC style one, or none."""
    if request.bottom_image is not None:
        prepare_bottom_image(request.bottom_image, target)
    elif request.bottom_screen is not None:
        render_bottom_screen_to_file(target, base.menu_name, request.bottom_screen)


def _write_retroarch_pictures(romfs: Path, request: GameRequest, base: Base) -> None:
    """The touch screen picture and the bezel overlay, for RetroArch.

    No ``bottom_menu.png``: without it the touch screen stays black while the
    menu is open (``retroarch/patches/0005``), as on the Virtual Console.
    """
    _write_bottom_picture(romfs / BOTTOM_IDLE_FILE, request, base)
    if request.bezel is not None:
        prepare_bezel(request.bezel, romfs / BEZEL_FILE)
        (romfs / BEZEL_OVERLAY_FILE).write_text(BEZEL_OVERLAY, encoding="utf-8")


def _write_standalone_pictures(romfs: Path, request: GameRequest, base: Base) -> None:
    """Replace a standalone emulator's own backgrounds with the project's.

    The base lists which of its RomFS pictures are the touch screen and the
    picture behind the game (``base.env``); the bezel is flattened on black,
    as the emulator draws it under the game, without transparency.
    """
    touch = request.bottom_image is not None or request.bottom_screen is not None
    if touch and not base.bottom_screen_files:
        _log.warning("The %s base names no touch screen picture: kept its own", base.core)
    for name in base.bottom_screen_files if touch else ():
        target = romfs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_bottom_picture(target, request, base)
        _log.info("Touch screen picture: romfs:/%s", name)
    if request.bezel is not None and not base.top_background_files:
        _log.warning("The %s base names no game background: bezel skipped", base.core)
    for name in base.top_background_files:
        target = romfs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        prepare_flat_bezel(request.bezel, target)
        _log.info("Game background (%s): romfs:/%s", "bezel" if request.bezel else "black", name)


def _make_smdh_and_banner(
    tools: Toolchain, request: GameRequest, icon: Path, banner: Path, audio: Path
) -> tuple[Path, Path]:
    assert tools.bannertool is not None
    icon_icn = icon.with_name("icon.icn")
    banner_bnr = banner.with_name("banner.bnr")
    run_tool(
        [
            str(tools.bannertool), "makesmdh",
            "-s", request.short_name, "-l", request.long_name, "-p", request.manufacturer,
            "-f", SMDH_FLAGS_UNRECORDED if request.hide_from_activity_log else SMDH_FLAGS,
            "-i", str(icon), "-o", str(icon_icn),
        ],
        "creating the icon",
    )  # fmt: skip
    run_tool(
        [str(tools.bannertool), "makebanner", "-i", str(banner), "-a", str(audio),
         "-o", str(banner_bnr)],
        "creating the banner",
    )  # fmt: skip
    return icon_icn, banner_bnr


def _make_cia(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    tools: Toolchain,
    base: Base,
    request: GameRequest,
    romfs: Path,
    assets: tuple[Path, Path],
    unique_id: int,
    out: Path,
) -> None:
    assert tools.makerom is not None
    icon_icn, banner_bnr = assets
    title = request.short_name.encode("utf-8")[:_RSF_TITLE_MAX].decode("utf-8", "ignore")
    run_tool(
        [
            str(tools.makerom), "-f", "cia", "-target", "t", "-exefslogo",
            "-o", str(out), "-elf", str(base.elf), "-rsf", str(base.rsf or tools.rsf),
            "-icon", str(icon_icn), "-banner", str(banner_bnr),
            f"-DAPP_TITLE={title}",
            f"-DAPP_PRODUCT_CODE=CTR-I-{unique_id & 0xFFFF:04X}",
            f"-DAPP_UNIQUE_ID=0x{unique_id:05X}",
            f"-DAPP_SYSTEM_MODE={base.system_mode}",
            f"-DAPP_SYSTEM_MODE_EXT={base.system_mode_ext}",
            "-DAPP_ENCRYPTED=false",
            f"-DROMFS_DIR={romfs}",
            f"-DAPP_ROMFS={romfs}",  # the name standalone emulators' RSFs use
        ],
        "packaging the CIA",
    )  # fmt: skip


def _assign_title_id(request: GameRequest, cores: CoreRegistry, registry_path: Path) -> int:
    registry = load_registry(registry_path)
    try:
        unique_id, _title_id = generate_title_id(
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
    return unique_id


def build_game(
    request: GameRequest,
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
    validate_request(request, cores, load_systems())
    base = tools.base(request.core)
    if base.big_text_section:
        # The MAME and FB Alpha 2012 bases: RetroArch takes kernel access
        # (svchax) at boot, which Luma3DS grants through the backdoor SVC.
        _log.info("The %s base uses svchax (big text section)", request.core)
    unique_id = _assign_title_id(request, cores, registry_path)

    _log.info("Core %s, console %s, ROM %s", request.core, request.console, request.rom.name)
    _log.info("Data folder %s", request.data_dir)
    _log.info("Title ID 0x%016X (Unique ID 0x%05X)", unique_id_to_title_id(unique_id), unique_id)

    with tempfile.TemporaryDirectory(prefix="3ds-injector-") as scratch_name:
        scratch = Path(scratch_name)
        romfs = write_romfs(scratch, request, base)

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
        assets = _make_smdh_and_banner(tools, request, icon_png, banner_png, audio_wav)

        _log.info("Running makerom")
        local_cia = scratch / "game.cia"
        _make_cia(tools, base, request, romfs, assets, unique_id, local_cia)

        try:
            request.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_cia, request.output)
        except OSError as exc:
            raise BuildError(f"Cannot write {request.output}: {exc}") from exc

    log_success(_log, "Saved %s", request.output)
    return BuildResult(unique_id=unique_id, output=request.output)


def make_request(  # pylint: disable=too-many-arguments
    *,
    rom: Path,
    long_name: str,
    output: Path,
    console: str = "",
    core: str = "",
    folder: str = "",
    short_name: str = "",
    manufacturer: str = "",
    name: str = "",
    systems: SystemCatalog | None = None,
    **extra: Any,
) -> GameRequest:
    """A :class:`GameRequest` with the usual defaults filled in.

    * ``console``: guessed from the ROM's extension (for a ``.zip``, from the
      ROM inside) when it points to one console only (``.chd`` does not: CD
      systems need it given);
    * ``core``: the console's default core;
    * ``folder``: the long name, made safe for the SD card;
    * the internal name (part of the Title ID hash) and the short name
      default to the long name; the manufacturer to :data:`DEFAULT_MANUFACTURER`.

    Raises :class:`BuildError` if the console cannot be worked out.
    """
    systems = systems or load_systems()
    long_name = long_name.strip()
    console = console.strip()
    if not console:
        guessed = systems.guess(rom)
        if guessed is None:
            options = ", ".join(system.console for system in systems.candidates(rom))
            raise BuildError(
                f"Cannot tell the console of '{rom.name}' from its extension; "
                f"give it explicitly{f' ({options})' if options else ''}."
            )
        console = guessed.console
    system = systems.get(console)
    if not core.strip():
        core = system.core if system else ""
    rom_name = rom.name
    if system is not None and system.arcade:
        extra.setdefault("arcade", True)
    elif system is not None and is_archive(rom):
        try:
            rom_name = inner_name(rom, system.extensions)
        except ArchiveError as exc:
            raise BuildError(str(exc)) from exc
    extra.setdefault("rom_name", rom_name)
    return GameRequest(
        core=core.strip(),
        rom=rom,
        console=console,
        folder=folder.strip() or save_folder_name(long_name),
        name=name.strip() or long_name,
        short_name=short_name.strip() or long_name,
        long_name=long_name,
        manufacturer=manufacturer.strip() or DEFAULT_MANUFACTURER,
        output=output,
        **extra,
    )


def request_from_project(
    project: Project, output: Path, systems: SystemCatalog | None = None
) -> GameRequest:
    """The :class:`GameRequest` for a saved project, building into ``output``."""
    long_name = project.long_name.strip() or project.rom_path.stem
    return make_request(
        rom=project.rom_path,
        console=project.console,
        core=project.core,
        folder=project.folder,
        long_name=long_name,
        short_name=project.short_name,
        manufacturer=project.publisher,
        output=output,
        systems=systems,
        icon=project.asset(Asset.ICON),
        banner=project.asset(Asset.BANNER),
        audio=project.asset(Asset.AUDIO),
        bezel=project.asset(Asset.BEZEL),
        screen=project.screen,
        core_options=dict(project.core_options),
        remap=dict(project.remap),
        manual_unique_id=project.unique_id,
        replace_existing_id=project.unique_id is not None and project.unique_id == project.built_id,
        hide_from_activity_log=project.hide_from_activity_log,
    )
