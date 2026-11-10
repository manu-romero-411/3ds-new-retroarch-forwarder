"""Command-line interface: ``3ds-forwarder <command>``.

Commands::

    3ds-forwarder build [options]     build (or rebuild) one game .cia
    3ds-forwarder inspect FILE.cia    show what a game .cia contains
    3ds-forwarder cores [FILTER]      list the consoles, their cores and the bases built
    3ds-forwarder media               list the banner jingles and platform logos
    3ds-forwarder doctor              check the toolchain and the SteamGridDB key
    3ds-forwarder config              show the settings file (secrets masked)
    3ds-forwarder gui                 open the graphical interface
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds import __version__
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
from forwarder3ds.core.logs import get_logger, log_success, setup_console_logging
from forwarder3ds.core.names import suggest_title
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


def _images(
    args: argparse.Namespace,
    settings: Settings,
    query: str,
    loaded_assets: _Images,
    scratch: Path,
) -> _Images:
    """Icon and banner files, by priority: flags, SteamGridDB, the loaded CIA, placeholder."""
    sgdb_icon, sgdb_hero, sgdb_logo = _steamgriddb_images(args, settings, query)
    images = _Images(icon=args.icon, banner=args.banner)
    if images.icon is None and sgdb_icon is not None:
        images.icon = scratch / "sgdb_icon.png"
        images.icon.write_bytes(sgdb_icon)
    images.icon = images.icon or loaded_assets.icon

    hero = _read(args.hero) or sgdb_hero
    logo = _read(args.logo) or sgdb_logo
    if images.banner is None and (hero or logo):
        images.banner = compose_banner_to_file(hero, logo, scratch / "composed_banner.png")
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


def _request_from_args(args: argparse.Namespace, settings: Settings, scratch: Path) -> GameRequest:
    """Merge the flags over the loaded CIA (if any) and the settings."""
    loaded = _load_source_cia(args.from_cia) if args.from_cia else None
    assets = loaded.write_assets(scratch / "loaded") if loaded else None

    def pick(flag: str | None, from_cia: str) -> str:
        return flag if flag is not None else (from_cia if loaded else "")

    rom = _rom_from_args(args, loaded, scratch)
    long_name = pick(args.long_name, loaded.long_name if loaded else "")
    long_name = long_name or suggest_title(rom.name)
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
    images = _images(args, settings, long_name, loaded_images, scratch)

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
        or settings.general.manufacturer,
        name=args.name or "",
        output=output,
        icon=images.icon,
        banner=images.banner,
        audio=jingle or args.audio or (assets.audio if assets else None),
        platform_logo=platform_logo,
        manual_unique_id=unique_id,
        replace_existing_id=loaded is not None and unique_id == loaded.unique_id,
    )


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
        for path in (written.icon, written.banner, written.audio, rom):
            if path:
                log_success(_log, "Wrote %s", path)
    return 0


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
    art.add_argument("--logo", type=Path, help="game logo pasted over the hero")
    art.add_argument("--banner", type=Path, help="ready-made banner (replaces hero + logo)")
    art.add_argument("--platform-logo", help="frame drawn over the banner: catalog name or PNG")

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
