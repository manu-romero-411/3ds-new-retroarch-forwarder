#!/usr/bin/env python3
"""Universal CIA forwarder generator for RetroArch on 3DS.

Builds a temporary RomFS (``core.txt`` + ``content.path``) and hands it to
``makerom`` via ``-DROMFS_DIR``, together with a deterministically-generated,
collision-checked Title ID (see ``tools/title_id.py``).

``make``, ``bannertool`` and ``makerom`` only exist inside the project's
Docker image (see ``tools/devkit_runtime.py``); nothing in this module
shells out to them on the host directly.

This module is the integration point for frontends: call
``build_forwarder()`` directly instead of shelling out to this file's CLI.
An existing forwarder CIA can be read back with
``tools.cia_reader.read_forwarder_cia()`` (or ``--from-cia`` on the CLI) and
rebuilt from scratch under its original Title ID.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.cia_reader import CiaReadError, LoadedForwarder, read_forwarder_cia
from tools.cores_registry import CoreRegistry, DEFAULT_CORES_JSON
from tools.devkit_runtime import (
    PROJECT_ROOT,
    devkit_tmp_dir,
    ensure_devkit_image_exists,
    run_devkit,
    to_container_path,
)
from tools.generate_placeholder_assets import ensure_placeholder_assets
from tools.media_catalog import (
    MediaCatalogError,
    list_jingles,
    list_platform_logos,
    resolve_jingle,
    resolve_platform_logo,
    validate_platform_logo,
)
from tools.media_prep import prepare_banner_audio, prepare_banner_image, prepare_icon
from tools.title_id import (
    DEFAULT_REGISTRY_PATH,
    ForwarderIdentity,
    TitleIdCollisionError,
    TitleIdRegistry,
    generate_title_id,
)

STUB_DIR = PROJECT_ROOT / "stub"
STUB_ELF = STUB_DIR / "3ds-forwarder-stub.elf"
RSF_TEMPLATE = STUB_DIR / "forwarder.rsf"

DEFAULT_MANUFACTURER = "Homebrew"


@dataclass
class ForwarderRequest:
    """Everything needed to produce one forwarder .cia."""

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
    # PNG (256x128, with transparency) drawn over the finished banner.
    platform_logo: Path | None = None
    manual_unique_id: int | None = None
    # Set when rebuilding a CIA loaded from disk under its original Title
    # ID: lets ``manual_unique_id`` take over an ID that the registry still
    # attributes to the identity the CIA had before it was edited.
    replace_existing_id: bool = False


CIA_EXTENSION = ".cia"
FALLBACK_CIA_STEM = "forwarder"


def default_save_dir() -> Path:
    """The user's home directory (``$HOME`` on Linux, ``%USERPROFILE%`` on Windows)."""
    return Path.home()


def default_cia_filename(rom_path: str) -> str:
    """Default ``.cia`` file name for a forwarder: the ROM's basename, minus its extension.

    ``rom_path`` is an SD-card path, so both ``/`` and ``\\`` separators
    are accepted regardless of the host OS.
    """
    stem = PurePosixPath(rom_path.strip().replace("\\", "/")).stem
    return f"{stem or FALLBACK_CIA_STEM}{CIA_EXTENSION}"


def ensure_cia_extension(path: Path) -> Path:
    """Return ``path`` ending in ``.cia``, appending it if missing.

    An existing, different suffix is kept (``game.v2`` -> ``game.v2.cia``).
    """
    if path.suffix.lower() == CIA_EXTENSION:
        return path
    return path.with_name(path.name + CIA_EXTENSION)


def normalize_sd_path(rom_path: str) -> str:
    """Strip an ``sdmc:/`` prefix and any leading slash from an SD path."""
    clean = rom_path
    if clean.startswith("sdmc:/"):
        clean = clean[len("sdmc:/"):]
    return clean.lstrip("/")


def require_valid_platform_logo(platform_logo: Path | None) -> None:
    """Exit with a clear message if ``platform_logo`` is set but breaks the frame rules."""
    problem = validate_platform_logo(platform_logo) if platform_logo else None
    if problem:
        print(f"ERROR: platform logo '{platform_logo.name}': {problem}", file=sys.stderr)
        sys.exit(1)


def build_stub_if_needed() -> None:
    """Compile the stub .elf via its own Makefile (inside Docker), unless already built."""
    if STUB_ELF.exists():
        print(f"[*] Stub already built: {STUB_ELF}")
        return
    print(f"[*] {STUB_ELF} not found. Building stub...")
    result = run_devkit(["make"], cwd=STUB_DIR)
    if result.returncode != 0 or not STUB_ELF.exists():
        print("ERROR: failed to build the stub.", file=sys.stderr)
        print(f"    stdout: {result.stdout.strip()}", file=sys.stderr)
        print(f"    stderr: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print("[+] Stub built successfully.")


def create_romfs(tmp_dir: Path, core: str, rom_path: str) -> Path:
    """Write the per-game RomFS (core.txt + content.path) under tmp_dir."""
    romfs_dir = tmp_dir / "romfs"
    romfs_dir.mkdir(parents=True, exist_ok=True)

    (romfs_dir / "core.txt").write_text(core, encoding="utf-8")

    clean_path = normalize_sd_path(rom_path)
    (romfs_dir / "content.path").write_text(clean_path, encoding="utf-8")

    print(f"[*] Temporary RomFS created at: {romfs_dir}")
    print(f"    core.txt: {core}")
    print(f"    content.path: {clean_path}  (no sdmc:/, the stub adds it)")

    return romfs_dir


def generate_smdh_banner(
    tmp_dir: Path,
    short_name: str,
    long_name: str,
    manufacturer: str,
    icon_path: Path,
    banner_path: Path,
    audio_path: Path,
) -> tuple[Path, Path]:
    """Run bannertool (inside Docker) to produce icon.icn and banner.bnr."""
    icon_icn = tmp_dir / "icon.icn"
    banner_bnr = tmp_dir / "banner.bnr"

    cmd_smdh = [
        "bannertool",
        "makesmdh",
        "-s",
        short_name,
        "-l",
        long_name,
        "-p",
        manufacturer,
        "-f",
        "visible,recordusage",
        "-i",
        to_container_path(icon_path),
        "-o",
        to_container_path(icon_icn),
    ]
    print(f"[*] Generating icon from: {icon_path}")
    result = run_devkit(cmd_smdh)
    if result.returncode != 0:
        print("ERROR: bannertool makesmdh failed.", file=sys.stderr)
        print(f"    stdout: {result.stdout.strip()}", file=sys.stderr)
        print(f"    stderr: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print("[+] Icon generated successfully.")

    cmd_banner = [
        "bannertool",
        "makebanner",
        "-i",
        to_container_path(banner_path),
        "-a",
        to_container_path(audio_path),
        "-o",
        to_container_path(banner_bnr),
    ]
    print(f"[*] Generating banner from: {banner_path}")
    result = run_devkit(cmd_banner)
    if result.returncode != 0:
        print("ERROR: bannertool makebanner failed.", file=sys.stderr)
        print(f"    stdout: {result.stdout.strip()}", file=sys.stderr)
        print(f"    stderr: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print("[+] Banner generated successfully.")

    return icon_icn, banner_bnr


def build_forwarder(
    request: ForwarderRequest,
    cores_json: Path = DEFAULT_CORES_JSON,
    title_id_registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> int:
    """Build one forwarder .cia end to end. Returns the assigned Unique ID."""
    ensure_devkit_image_exists()

    core_registry = CoreRegistry.load(cores_json)
    core_registry.require(request.core)  # validates and exits on failure

    clean_rom_path = normalize_sd_path(request.rom_path)

    identity = ForwarderIdentity(
        name=request.name,
        short_name=request.short_name,
        long_name=request.long_name,
        manufacturer=request.manufacturer,
        core=request.core,
        rom_path=clean_rom_path,
    )
    require_valid_platform_logo(request.platform_logo)

    title_registry = TitleIdRegistry.load(title_id_registry_path)
    try:
        unique_id, title_id = generate_title_id(
            identity,
            core_registry.all_unique_ids(),
            title_registry,
            manual_unique_id=request.manual_unique_id,
            replace_existing=request.replace_existing_id,
        )
    except TitleIdCollisionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Core: {request.core}")
    print(f"[*] ROM on SD: sdmc:/{clean_rom_path}")
    print(f"[*] Unique ID: 0x{unique_id:05X}")
    print(f"[*] Title ID: 0x{title_id:016X}")

    build_stub_if_needed()

    # Scratch space must live under the project (not the system /tmp) so
    # it is visible inside the Docker container that runs bannertool and
    # makerom -- see tools/devkit_runtime.py.
    with devkit_tmp_dir() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        print("[*] Preparing temporary RomFS...")
        romfs_dir = create_romfs(tmp_dir, request.core, clean_rom_path)

        print("[*] Preparing icon/banner/audio assets...")
        icon_source = request.icon
        banner_source = request.banner
        if icon_source is None or banner_source is None:
            placeholder_icon, placeholder_banner, _unused_audio = ensure_placeholder_assets(
                tmp_dir
            )
            icon_source = icon_source or placeholder_icon
            banner_source = banner_source or placeholder_banner

        # Always normalize to the exact spec bannertool needs, whether the
        # source is a user-supplied file or a placeholder: stretch (never
        # crop) the icon/banner to their fixed SMDH sizes, and re-encode
        # the audio to the 16-bit/44.1kHz/stereo WAV bannertool expects.
        # This step runs ffmpeg on the host, so icon_source/banner_source
        # may live anywhere -- only its *output* under tmp_dir needs to be
        # visible to the container.
        icon_png = tmp_dir / "icon_48x48.png"
        banner_png = tmp_dir / "banner_256x128.png"
        audio_wav = tmp_dir / "audio_prepared.wav"
        prepare_icon(icon_source, icon_png)
        prepare_banner_image(banner_source, banner_png, request.platform_logo)
        prepare_banner_audio(request.audio, audio_wav)

        icon_icn, banner_bnr = generate_smdh_banner(
            tmp_dir,
            request.short_name,
            request.long_name,
            request.manufacturer,
            icon_png,
            banner_png,
            audio_wav,
        )

        # makerom always writes inside the project (tmp_dir); the
        # user-requested --output may point anywhere on the host (e.g. a
        # mounted SD card), so it is copied there afterwards, on the host.
        local_cia = tmp_dir / "forwarder.cia"

        print(f"[*] Packaging CIA -> {request.output}")
        cmd_makerom = [
            "makerom",
            "-f",
            "cia",
            "-target",
            "t",
            "-exefslogo",
            "-o",
            to_container_path(local_cia),
            "-elf",
            to_container_path(STUB_ELF),
            "-rsf",
            to_container_path(RSF_TEMPLATE),
            "-icon",
            to_container_path(icon_icn),
            "-banner",
            to_container_path(banner_bnr),
            f"-DROMFS_DIR={to_container_path(romfs_dir)}",
            f"-DUNIQUE_ID=0x{unique_id:05X}",
        ]
        result = run_devkit(cmd_makerom)
        if result.returncode != 0:
            print("ERROR: makerom failed.", file=sys.stderr)
            print(f"    stdout: {result.stdout.strip()}", file=sys.stderr)
            print(f"    stderr: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)

        request.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_cia, request.output)

    print(f"\n[+] SUCCESS! CIA generated at: {request.output.resolve()}")
    print(f"[*] Unique Title ID: 0x{title_id:016X}")
    return unique_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for standalone use."""
    parser = argparse.ArgumentParser(description="Universal CIA forwarder generator")
    parser.add_argument(
        "--from-cia",
        type=Path,
        help="Load an existing forwarder .cia and rebuild it from scratch, keeping its "
        "Title ID. Its core, ROM path, names, manufacturer, icon, banner and audio become "
        "the defaults; any other flag overrides the corresponding value. Unless --output "
        "is given, the loaded file is replaced.",
    )
    parser.add_argument("--core", help="libretro core name, as in cores.json")
    parser.add_argument("--rom", help="ROM path on the SD card")
    parser.add_argument(
        "--name",
        help="Internal/display identifier for this forwarder "
        "(used as the registry key and default output filename; "
        "with --from-cia it defaults to the loaded long name)",
    )
    parser.add_argument(
        "--short-name", help="SMDH short description (default: --name)"
    )
    parser.add_argument(
        "--long-name", help="SMDH long description (default: --name)"
    )
    parser.add_argument(
        "--manufacturer",
        help=f"SMDH publisher field (default: {DEFAULT_MANUFACTURER!r})",
    )
    parser.add_argument(
        "--icon", type=Path, help="PNG icon, any size (default: placeholder; stretched to 48x48)"
    )
    parser.add_argument(
        "--banner",
        type=Path,
        help="PNG banner, any size (default: placeholder; stretched to 256x128)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        help="Audio for the banner jingle, any format ffmpeg reads "
        "(default: silence; re-encoded to 16-bit/44.1kHz/stereo WAV, max 3s)",
    )
    parser.add_argument(
        "--jingle",
        help="Banner jingle from the audio_jingles/ folder (by name) or any WAV file that "
        "meets the rules (16-bit PCM, mono/stereo, max 3 s). Unlike --audio, nothing is "
        "converted. Cannot be combined with --audio.",
    )
    parser.add_argument(
        "--platform-logo",
        help="Frame drawn over the banner: a name from the platform_logos/ folder or any PNG "
        "file of exactly 256x128 pixels (with transparency).",
    )
    parser.add_argument(
        "--list-jingles", action="store_true", help="List the audio_jingles/ folder and exit"
    )
    parser.add_argument(
        "--list-platform-logos",
        action="store_true",
        help="List the platform_logos/ folder and exit",
    )
    parser.add_argument("--output", type=Path, help="Output .cia path (default: output/<name>.cia)")
    parser.add_argument(
        "--unique-id",
        type=lambda value: int(value, 0),
        help="Manually pick the Unique ID (e.g. 0xF1234) instead of deriving "
        "one from the other fields; must not collide with a core CIA or "
        "another forwarder already in the registry",
    )
    parser.add_argument("--cores-json", type=Path, default=DEFAULT_CORES_JSON)
    parser.add_argument("--title-id-registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    args = parser.parse_args(argv)

    if args.list_jingles or args.list_platform_logos:
        return args
    if args.jingle is not None and args.audio is not None:
        parser.error("--jingle and --audio are mutually exclusive")
    if args.from_cia is None:
        for flag, value in (("--core", args.core), ("--rom", args.rom), ("--name", args.name)):
            if value is None:
                parser.error(f"{flag} is required unless --from-cia is given")
    return args


def load_source_cia(path: Path) -> LoadedForwarder:
    """Read the CIA given to ``--from-cia``, reporting problems like the other CLI errors."""
    try:
        loaded = read_forwarder_cia(path)
    except CiaReadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"[*] Loaded {path}")
    print(f"    Title ID: 0x{loaded.title_id:016X}")
    print(f"    Core: {loaded.core}")
    print(f"    ROM on SD: sdmc:/{loaded.rom_path}")
    for warning in loaded.warnings:
        print(f"[!] {warning}", file=sys.stderr)
    return loaded


def print_catalog(title: str, entries) -> None:
    """Print one catalog folder: usable entries by name, broken ones with the reason."""
    print(f"{title}:")
    for entry in entries:
        note = "" if entry.usable else f"  [unusable: {entry.problem}]"
        print(f"  {entry.name}{note}")
    if not entries:
        print("  (empty)")


def resolve_media_args(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """Resolve ``--jingle`` / ``--platform-logo`` to files, exiting on a bad value."""
    try:
        jingle = resolve_jingle(args.jingle) if args.jingle is not None else None
        platform_logo = (
            resolve_platform_logo(args.platform_logo) if args.platform_logo is not None else None
        )
    except MediaCatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    return jingle, platform_logo


def request_from_args(
    args: argparse.Namespace, loaded: LoadedForwarder | None, scratch_dir: Path
) -> ForwarderRequest:
    """Merge CLI flags over the loaded CIA (if any) into one :class:`ForwarderRequest`.

    Explicit flags always win; whatever they leave unset falls back to the
    loaded CIA and, failing that, to the usual defaults. ``scratch_dir``
    receives the loaded CIA's icon/banner/audio as files.
    """
    assets = loaded.write_assets(scratch_dir) if loaded else None

    def pick(flag_value, loaded_value):
        return flag_value if flag_value is not None else loaded_value

    jingle, platform_logo = resolve_media_args(args)
    name = pick(args.name, loaded.long_name if loaded else None)
    if not name:
        print(
            "ERROR: the loaded CIA has no name in its SMDH; pass --name.",
            file=sys.stderr,
        )
        sys.exit(1)
    unique_id = pick(args.unique_id, loaded.unique_id if loaded else None)
    if args.output is not None:
        output = args.output
    elif loaded:
        output = args.from_cia
    else:
        output = PROJECT_ROOT / "output" / f"{name}.cia"

    return ForwarderRequest(
        core=pick(args.core, loaded.core if loaded else None),
        rom_path=pick(args.rom, loaded.rom_path if loaded else None),
        name=name,
        short_name=args.short_name or (loaded.short_name if loaded else "") or name,
        long_name=args.long_name or (loaded.long_name if loaded else "") or name,
        manufacturer=args.manufacturer
        or (loaded.manufacturer if loaded else "")
        or DEFAULT_MANUFACTURER,
        output=output,
        icon=pick(args.icon, assets.icon if assets else None),
        banner=pick(args.banner, assets.banner if assets else None),
        audio=pick(jingle or args.audio, assets.audio if assets else None),
        platform_logo=platform_logo,
        manual_unique_id=unique_id,
        replace_existing_id=loaded is not None and unique_id == loaded.unique_id,
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = parse_args(argv)
    if args.list_jingles or args.list_platform_logos:
        if args.list_jingles:
            print_catalog("Jingles", list_jingles())
        if args.list_platform_logos:
            print_catalog("Platform logos", list_platform_logos())
        return
    loaded = load_source_cia(args.from_cia) if args.from_cia else None

    with tempfile.TemporaryDirectory(prefix="3ds_forwarder_cli_") as scratch_dir:
        request = request_from_args(args, loaded, Path(scratch_dir))
        if loaded and request.output == args.from_cia:
            print(f"[*] The loaded CIA will be replaced: {request.output}")
        build_forwarder(
            request,
            cores_json=args.cores_json,
            title_id_registry_path=args.title_id_registry,
        )


if __name__ == "__main__":
    main()
