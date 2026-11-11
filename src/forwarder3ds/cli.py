"""Command-line interface: ``3ds-forwarder <command>``.

Commands::

    3ds-forwarder build [options]     build (or rebuild) one game .cia
    3ds-forwarder inspect FILE.cia    show what a game .cia contains
    3ds-forwarder identify ROM        look a ROM up in the libretro database
    3ds-forwarder cores [FILTER]      list the consoles, their cores and the bases built
    3ds-forwarder media               list the banner jingles and platform logos
    3ds-forwarder doctor              check the toolchain and the SteamGridDB key
    3ds-forwarder config              show the settings file (secrets masked)
    3ds-forwarder gui                 open the graphical interface
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds import __version__
from forwarder3ds.artwork.banner_card import CardStyle, render_card_to_file
from forwarder3ds.artwork.compositor import compose_banner_to_file
from forwarder3ds.artwork.steamgriddb import SGDBClient, SGDBError, fetch_best_artwork
from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.injector import (
    GameRequest,
    build_game,
    default_cia_filename,
    ensure_cia_extension,
    load_systems,
    make_request,
    preview_title_id,
)
from forwarder3ds.builder.toolchain import find_toolchain
from forwarder3ds.core import catalog, paths
from forwarder3ds.core.game_config import ScreenMode, ScreenSettings
from forwarder3ds.core.logs import get_logger, log_success, setup_console_logging
from forwarder3ds.artwork.libretro import (
    DatabaseUnavailableError,
    ThumbnailKind,
    load_database,
    thumbnail_url,
)
from forwarder3ds.core.names import suggest_title
from forwarder3ds.core.romdb import Identification, MatchKind, identify
from forwarder3ds.core.systems import System
from forwarder3ds.core.settings import Settings, load_settings, masked
from forwarder3ds.core.title_id import unique_id_to_title_id
from forwarder3ds.ctr.cia import CiaReadError, LoadedGame, read_game_cia

_log = get_logger("cli")


# ── build ────────────────────────────────────────────────────────────────


@dataclass
class _Images:
    icon: Path | None = None
    banner: Path | None = None


def _load_source_cia(path: Path) -> LoadedGame:
    try:
        loaded = read_game_cia(path)
    except (CiaReadError, OSError) as exc:
        raise BuildError(f"{path}: {exc}") from exc
    _log.info("Loaded %s (Title ID 0x%016X)", path, loaded.title_id)
    for warning in loaded.warnings:
        _log.warning("%s", warning)
    return loaded


def _steamgriddb_images(
    args: argparse.Namespace, settings: Settings, query: str
) -> tuple[bytes | None, bytes | None, bytes | None]:
    """``(icon, hero, logo)`` from SteamGridDB when asked to, else ``(None,)*3``."""
    if not (args.steamgriddb or args.sgdb_game):
        return None, None, None
    sgdb = settings.steamgriddb
    client = SGDBClient(args.sgdb_key or sgdb.api_key, nsfw=sgdb.nsfw, humor=sgdb.humor)
    try:
        artwork = fetch_best_artwork(client, query, args.sgdb_game)
    except SGDBError as exc:
        raise BuildError(str(exc)) from exc
    _log.info("SteamGridDB game “%s” (id %d)", artwork.game.name, artwork.game.id)
    for kind in ("icon", "hero", "logo"):
        if getattr(artwork, kind) is None:
            _log.warning("SteamGridDB has no %s for this game", kind)
    return artwork.icon, artwork.hero, artwork.logo


def _read(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BuildError(f"Cannot read {path}: {exc}") from exc


@dataclass(frozen=True)
class _Card:
    """What the default banner's tag says."""

    console: str
    title: str
    year: str


def _images(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    args: argparse.Namespace,
    settings: Settings,
    query: str,
    loaded_assets: _Images,
    scratch: Path,
    card: _Card,
) -> _Images:
    """Icon and banner files, by priority: flags, SteamGridDB, the loaded CIA, default.

    The default banner is the logo (or the title) over a tag with the
    console and the year; ``--hero`` makes the older hero + logo banner.
    """
    sgdb_icon, sgdb_hero, sgdb_logo = _steamgriddb_images(args, settings, query)
    images = _Images(icon=args.icon, banner=args.banner)
    if images.icon is None and sgdb_icon is not None:
        images.icon = scratch / "sgdb_icon.png"
        images.icon.write_bytes(sgdb_icon)
    images.icon = images.icon or loaded_assets.icon

    hero = _read(args.hero) or sgdb_hero
    logo = _read(args.logo) or sgdb_logo
    if images.banner is None and hero:
        images.banner = compose_banner_to_file(hero, logo, scratch / "composed_banner.png")
    elif images.banner is None and (logo or loaded_assets.banner is None):
        banner = settings.banner
        images.banner = render_card_to_file(
            scratch / "card_banner.png",
            console=card.console,
            title=card.title,
            name=args.banner_name or "",
            year=card.year,
            logo=logo,
            style=CardStyle(banner.background, banner.text, banner.font),
        )
    images.banner = images.banner or loaded_assets.banner
    return images


def _rom_from_args(args: argparse.Namespace, loaded: LoadedGame | None, scratch: Path) -> Path:
    """The ROM given with ``--rom``, or the one inside the loaded CIA."""
    if args.rom is not None:
        return args.rom
    assert loaded is not None  # main() requires --rom without --from-cia
    try:
        return loaded.extract_rom(scratch / "rom")
    except CiaReadError as exc:
        raise BuildError(str(exc)) from exc


def _system_for(rom: Path, console: str | None) -> System | None:
    """The console given, or the one ``rom``'s extension points to."""
    systems = load_systems()
    return systems.get(console) if console else systems.guess(rom)


def _identify(rom: Path, system: System, refresh: bool = False) -> Identification | None:
    """Look ``rom`` up; ``None`` (with a warning) when the database is unavailable."""
    try:
        database = load_database(system, refresh)
    except DatabaseUnavailableError as exc:
        _log.warning("%s", exc)
        return None
    found = identify(rom, system, database)
    if found.kind is MatchKind.NONE:
        _log.warning(
            "%s is not in the %s database (a hack, a translation or a bad dump?)",
            rom.name,
            system.name,
        )
    elif found.kind is MatchKind.NAME:
        _log.warning("Matched “%s” by file name only: check it", found.game.name)
    else:
        _log.info("Identified as “%s”", found.game.name)
    return found


def _request_from_args(args: argparse.Namespace, settings: Settings, scratch: Path) -> GameRequest:
    """Merge the flags over the loaded CIA (if any) and the settings."""
    loaded = _load_source_cia(args.from_cia) if args.from_cia else None
    assets = loaded.write_assets(scratch / "loaded") if loaded else None

    def pick(flag: str | None, from_cia: str) -> str:
        return flag if flag is not None else (from_cia if loaded else "")

    rom = _rom_from_args(args, loaded, scratch)
    found = None
    if args.identify:
        system = _system_for(rom, pick(args.console, loaded.console if loaded else ""))
        found = _identify(rom, system) if system else None
    db_game = found.game if found else None
    long_name = pick(args.long_name, loaded.long_name if loaded else "")
    long_name = long_name or (db_game.title if db_game else suggest_title(rom.name))
    if not long_name:
        raise BuildError("--long-name is required (no name could be derived).")

    jingle, platform_logo = None, None
    try:
        if args.jingle:
            jingle = catalog.resolve_jingle(args.jingle)
        if args.platform_logo:
            platform_logo = catalog.resolve_platform_logo(args.platform_logo)
    except catalog.MediaCatalogError as exc:
        raise BuildError(str(exc)) from exc

    loaded_images = _Images(assets.icon, assets.banner) if assets else _Images()
    system = _system_for(rom, pick(args.console, loaded.console if loaded else ""))
    card = _Card(
        console=system.console if system else "",
        title=long_name,
        year=args.year if args.year is not None else (db_game.year if db_game else ""),
    )
    images = _images(args, settings, long_name, loaded_images, scratch, card)

    if args.output is not None:
        output = ensure_cia_extension(args.output)
    elif args.from_cia is not None:
        output = args.from_cia
    else:
        output = settings.general.output_path / default_cia_filename(long_name)

    unique_id = args.unique_id
    if unique_id is None and loaded is not None:
        unique_id = loaded.unique_id
    return make_request(
        rom=rom,
        console=pick(args.console, loaded.console if loaded else ""),
        core=pick(args.core, loaded.core if loaded else ""),
        folder=pick(args.folder, loaded.folder if loaded else ""),
        long_name=long_name,
        short_name=pick(args.short_name, loaded.short_name if loaded else ""),
        manufacturer=pick(args.manufacturer, loaded.manufacturer if loaded else "")
        or (db_game.publisher if db_game else "")
        or settings.general.manufacturer,
        name=args.name or "",
        output=output,
        icon=images.icon,
        banner=images.banner,
        audio=jingle or args.audio or (assets.audio if assets else None),
        platform_logo=platform_logo,
        bezel=None if args.no_bezel else (args.bezel or (assets.bezel if assets else None)),
        screen=_screen(args, loaded.screen if loaded else None),
        core_options=dict(loaded.core_options) if loaded else {},
        remap=dict(loaded.remap) if loaded else {},
        manual_unique_id=unique_id,
        replace_existing_id=loaded is not None and unique_id == loaded.unique_id,
    )


def _describe_screen(screen: ScreenSettings | None) -> str:
    if screen is None:
        return "RetroArch defaults"
    text = screen.mode.value
    if screen.mode is ScreenMode.CUSTOM:
        text += f" {screen.width}x{screen.height}"
    return text + (", bilinear" if screen.smooth else "")


def _screen(args: argparse.Namespace, loaded: ScreenSettings | None) -> ScreenSettings | None:
    """``--screen``/``--smooth`` over the loaded CIA's screen settings."""
    if args.screen is None and args.smooth is None:
        return loaded
    screen = ScreenSettings(**vars(loaded)) if loaded else ScreenSettings()
    if args.screen is not None:
        mode, _sep, size = args.screen.partition(":")
        screen.mode = ScreenMode(mode)
        if size:
            screen.width, screen.height = (int(part) for part in size.lower().split("x"))
    if args.smooth is not None:
        screen.smooth = args.smooth
    return screen


def _screen_arg(text: str) -> str:
    """Validate ``--screen``: a mode, or ``custom:WxH``."""
    mode, _sep, size = text.partition(":")
    try:
        ScreenMode(mode)
    except ValueError as exc:
        modes = ", ".join(item.value for item in ScreenMode)
        raise argparse.ArgumentTypeError(f"unknown mode '{mode}' (one of {modes})") from exc
    if (mode == ScreenMode.CUSTOM.value) != bool(size) or (
        size and not re.fullmatch(r"\d{1,3}[xX]\d{1,3}", size)
    ):
        raise argparse.ArgumentTypeError("custom needs a size, e.g. custom:360x240")
    return text


def _cmd_build(args: argparse.Namespace, settings: Settings) -> int:
    registry = args.title_id_registry or settings.general.registry_path
    with tempfile.TemporaryDirectory(prefix="3ds-forwarder-cli-") as scratch_name:
        try:
            request = _request_from_args(args, settings, Path(scratch_name))
            if args.dry_run:
                unique_id = preview_title_id(request, registry)
                print(f"Title ID:  0x{unique_id_to_title_id(unique_id):016X}")
                print(f"Unique ID: 0x{unique_id:05X}")
                print(f"Core:      {request.core} ({request.console})")
                print(f"Saves:     {request.data_dir}")
                print(f"Output:    {request.output}")
                return 0
            if args.from_cia and request.output == args.from_cia:
                _log.info("The loaded CIA will be replaced: %s", request.output)
            build_game(request, find_toolchain(settings.toolchain), registry)
        except BuildError as exc:
            _log.error("%s", exc)
            return 1
    return 0


# ── other commands ───────────────────────────────────────────────────────


def _cmd_inspect(args: argparse.Namespace, _settings: Settings) -> int:
    try:
        loaded = read_game_cia(args.cia)
    except (CiaReadError, OSError) as exc:
        _log.error("%s: %s", args.cia, exc)
        return 1
    rows = (
        ("Title ID", f"0x{loaded.title_id:016X}"),
        ("Unique ID", f"0x{loaded.unique_id:05X}"),
        ("Core", loaded.core),
        ("Console", loaded.console),
        ("Saves", f"sdmc:/saves/{loaded.console}/{loaded.folder}"),
        ("ROM", f"{loaded.rom_name} ({loaded.rom_size} bytes)"),
        ("Bezel", "yes" if loaded.bezel_png else "no"),
        ("Screen", _describe_screen(loaded.screen)),
        ("Core options", f"{len(loaded.core_options)} set" if loaded.core_options else "defaults"),
        ("Controls", ", ".join(f"{k}->{v}" for k, v in loaded.remap.items()) or "default"),
        ("Short name", loaded.short_name),
        ("Long name", loaded.long_name),
        ("Manufacturer", loaded.manufacturer),
        ("Icon", "yes" if loaded.icon_png else "no"),
        ("Banner", "yes" if loaded.banner_png else "no"),
        ("Jingle", "yes" if loaded.audio_wav else "silent"),
    )
    for label, value in rows:
        print(f"{label + ':':<14}{value}")
    for warning in loaded.warnings:
        _log.warning("%s", warning)
    if args.extract:
        written = loaded.write_assets(args.extract)
        try:
            rom = loaded.extract_rom(args.extract)
        except CiaReadError as exc:
            _log.error("%s", exc)
            return 1
        for path in (written.icon, written.banner, written.audio, written.bezel, rom):
            if path:
                log_success(_log, "Wrote %s", path)
    return 0


def _cmd_identify(args: argparse.Namespace, _settings: Settings) -> int:
    if not args.rom.is_file():
        _log.error("The ROM does not exist: %s", args.rom)
        return 1
    try:
        system = _system_for(args.rom, args.console)
    except BuildError as exc:
        _log.error("%s", exc)
        return 1
    if system is None:
        _log.error("Cannot tell the console of %s; give --console", args.rom.name)
        return 1
    found = _identify(args.rom, system, args.refresh)
    if found is None:
        return 1
    rows = [("Console", f"{system.console} ({system.libretro})")]
    if found.crc is not None:
        rows.append(("CRC32", f"{found.crc:08X}"))
    rows.append(("Match", found.kind.value))
    if found.game is not None:
        game = found.game
        rows += [
            ("Name", game.name),
            ("Title", game.title),
            ("Publisher", game.publisher or "?"),
            ("Developer", game.developer or "?"),
            ("Year", game.year or "?"),
        ]
        rows += [(kind.label, thumbnail_url(system, game.name, kind)) for kind in ThumbnailKind]
    for label, value in rows:
        print(f"{label + ':':<14}{value}")
    for other in found.candidates[1:]:
        print(f"{'Also like:':<14}{other.name}")
    return 0 if found.game is not None else 3


def _cmd_cores(args: argparse.Namespace, settings: Settings) -> int:
    try:
        systems = load_systems()
    except BuildError as exc:
        _log.error("%s", exc)
        return 1
    built = set(find_toolchain(settings.toolchain).available_cores())
    wanted = (args.filter or "").casefold()
    for system in sorted(systems, key=lambda s: s.console):
        text = f"{system.console} {system.name} {system.core}".casefold()
        if wanted and wanted not in text:
            continue
        status = "base ready" if system.core in built else "no base"
        extensions = ", ".join(f".{ext}" for ext in system.extensions)
        print(f"{system.console:<14} {system.core:<20} {status:<11} {system.name} ({extensions})")
    return 0


def _print_catalog(title: str, folders: tuple[Path, ...], entries: list) -> None:
    print(f"{title} ({', '.join(str(folder) for folder in folders)}):")
    for entry in entries:
        note = "" if entry.usable else f"  [unusable: {entry.problem}]"
        print(f"  {entry.name:<24} {entry.path}{note}")
    if not entries:
        print("  (none)")


def _cmd_media(_args: argparse.Namespace, _settings: Settings) -> int:
    _print_catalog("Jingles", catalog.jingle_dirs(), catalog.list_jingles())
    _print_catalog("Platform logos", catalog.platform_logo_dirs(), catalog.list_platform_logos())
    print(f"\nJingle rules: {catalog.JINGLE_RULES}")
    print(f"Platform logo rules: {catalog.PLATFORM_LOGO_RULES}")
    return 0


def _cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    tools = find_toolchain(settings.toolchain)
    print("Toolchain directories found:")
    for directory in paths.toolchain_dirs() or []:
        print(f"  {directory}")
    if not paths.toolchain_dirs():
        print("  (none found)")
    for name in ("makerom", "bannertool", "bases", "ffmpeg"):
        path = getattr(tools, name)
        optional = " (optional: only for non-WAV audio)" if name == "ffmpeg" else ""
        print(f"  {name:<11} {path if path else 'NOT FOUND' + optional}")
    print(f"  {'cores':<11} {', '.join(tools.available_cores()) or '(no base built)'}")
    for key, value in tools.versions().items():
        print(f"  {key:<11} {value}")
    status = 0 if tools.complete else 1
    if not args.offline:
        status = max(status, _check_steamgriddb(settings))
    return status


def _check_steamgriddb(settings: Settings) -> int:
    if not settings.steamgriddb.configured:
        print("SteamGridDB: no API key (artwork search disabled)")
        return 0
    try:
        SGDBClient(settings.steamgriddb.api_key).check()
    except SGDBError as exc:
        print(f"SteamGridDB: {exc}")
        return 1
    print("SteamGridDB: API key OK")
    return 0


def _cmd_config(_args: argparse.Namespace, settings: Settings) -> int:
    print(f"# {paths.config_file()}")
    for section, values in masked(settings).items():
        print(f"[{section}]")
        for key, value in values.items():
            print(f"{key} = {value}")
        print()
    print(f"# Title ID registry: {settings.general.registry_path}")
    return 0


def _cmd_gui(_args: argparse.Namespace, _settings: Settings) -> int:
    try:
        from forwarder3ds.gui.app import main as gui_main  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        _log.error("The graphical interface needs PySide6: %s", exc)
        return 1
    return gui_main()


# ── parser ───────────────────────────────────────────────────────────────


def _hex(value: str) -> int:
    return int(value, 16) if not value.lower().startswith("0x") else int(value, 0)


def _add_build_parser(sub: argparse._SubParsersAction) -> None:
    build = sub.add_parser("build", help="build one game .cia")
    build.add_argument(
        "--from-cia",
        type=Path,
        help="rebuild an existing game CIA, keeping its Title ID; its fields (and ROM) become "
        "the defaults and it is replaced unless --output is given",
    )
    game = build.add_argument_group("game")
    game.add_argument("--rom", type=Path, help="ROM file to pack (CD games: a single .chd)")
    game.add_argument(
        "--console",
        help="Batocera console name, e.g. snes (default: from the ROM's extension)",
    )
    game.add_argument("--core", help="libretro core (default: the console's, see 'cores')")
    game.add_argument(
        "--folder",
        help="save folder name: sdmc:/saves/<console>/<folder> (default: the long name)",
    )
    game.add_argument(
        "--long-name",
        help="SMDH long name; also the SteamGridDB search term (default: from the ROM name)",
    )
    game.add_argument(
        "--identify",
        action="store_true",
        help="look the ROM up in the libretro database: its title and publisher become "
        "the default names",
    )
    game.add_argument("--short-name", help="SMDH short name (default: the long name)")
    game.add_argument("--manufacturer", help="SMDH publisher (default: from the settings)")
    game.add_argument("--name", help=argparse.SUPPRESS)  # legacy: internal name in the hash

    art = build.add_argument_group("artwork (SteamGridDB or local files)")
    art.add_argument(
        "--steamgriddb",
        action="store_true",
        help="fetch the first icon, hero and logo of the matching SteamGridDB game",
    )
    art.add_argument("--sgdb-game", type=int, metavar="ID", help="SteamGridDB game id to use")
    art.add_argument("--sgdb-key", help="SteamGridDB API key (default: from the settings)")
    art.add_argument("--icon", type=Path, help="icon image, any size (stretched to 48x48)")
    art.add_argument("--hero", type=Path, help="banner background (cover-cropped)")
    art.add_argument(
        "--logo", type=Path, help="game logo, on the default banner (or over the hero)"
    )
    art.add_argument("--year", help="year on the default banner (default: from --identify)")
    art.add_argument("--banner-name", help="name on the default banner's tag (default: none)")
    art.add_argument("--banner", type=Path, help="ready-made banner (replaces hero + logo)")
    art.add_argument("--platform-logo", help="frame drawn over the banner: catalog name or PNG")
    bezel = art.add_mutually_exclusive_group()
    bezel.add_argument(
        "--bezel",
        type=Path,
        help="top screen bezel, any size (stretched to 400x240; transparent where the game shows)",
    )
    bezel.add_argument("--no-bezel", action="store_true", help="drop the loaded CIA's bezel")

    screen = build.add_argument_group("screen")
    screen.add_argument(
        "--screen",
        type=_screen_arg,
        metavar="MODE",
        help="pixel_perfect, recommended (core aspect), full (400x240) or custom:WxH",
    )
    screen.add_argument(
        "--smooth",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="bilinear filtering",
    )

    sound = build.add_argument_group("jingle").add_mutually_exclusive_group()
    sound.add_argument("--jingle", help="catalog name or 16-bit PCM WAV (≤ 3 s)")
    sound.add_argument("--audio", type=Path, help="any audio file (needs ffmpeg unless WAV)")

    out = build.add_argument_group("output")
    out.add_argument("-o", "--output", type=Path, help="output .cia (default: settings folder)")
    out.add_argument("--unique-id", type=_hex, help="force the Unique ID (hex, e.g. F1234)")
    out.add_argument("--title-id-registry", type=Path, help="registry file (default: settings)")
    out.add_argument("--dry-run", action="store_true", help="print the Title ID and stop")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="3ds-forwarder",
        description="Build standalone 3DS CIAs of one game, each with its own RetroArch core.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug output")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_build_parser(sub)
    inspect = sub.add_parser("inspect", help="show what a game .cia contains")
    inspect.add_argument("cia", type=Path)
    inspect.add_argument(
        "--extract", type=Path, metavar="DIR", help="write icon/banner/jingle and the ROM"
    )
    ident = sub.add_parser("identify", help="look a ROM up in the libretro database")
    ident.add_argument("rom", type=Path)
    ident.add_argument("--console", help="Batocera console name (default: from the extension)")
    ident.add_argument("--refresh", action="store_true", help="download the database again")
    cores = sub.add_parser("cores", help="list the consoles and their RetroArch cores")
    cores.add_argument("filter", nargs="?", help="substring of the console or core name")
    sub.add_parser("media", help="list banner jingles and platform logos")
    doctor = sub.add_parser("doctor", help="check the toolchain and SteamGridDB")
    doctor.add_argument("--offline", action="store_true", help="do not contact SteamGridDB")
    sub.add_parser("config", help="show the settings")
    sub.add_parser("gui", help="open the graphical interface")
    return parser


_COMMANDS = {
    "build": _cmd_build,
    "inspect": _cmd_inspect,
    "identify": _cmd_identify,
    "cores": _cmd_cores,
    "media": _cmd_media,
    "doctor": _cmd_doctor,
    "config": _cmd_config,
    "gui": _cmd_gui,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``3ds-forwarder`` command."""
    args = _build_parser().parse_args(argv)
    setup_console_logging(args.verbose)
    if args.command == "build" and not args.from_cia and args.rom is None:
        _log.error("--rom is required unless --from-cia is given")
        return 2
    try:
        return _COMMANDS[args.command](args, load_settings())
    except KeyboardInterrupt:
        _log.warning("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
