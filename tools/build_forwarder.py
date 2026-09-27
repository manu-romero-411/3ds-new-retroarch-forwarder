#!/usr/bin/env python3
"""Universal CIA forwarder generator for RetroArch on 3DS.

Builds a temporary RomFS (``core.txt`` + ``content.path``) and hands it to
``makerom`` via ``-DROMFS_DIR``, together with a deterministically-generated,
collision-checked Title ID (see ``tools/title_id.py``).

``make``, ``bannertool`` and ``makerom`` only exist inside the project's
Docker image (see ``tools/devkit_runtime.py``); nothing in this module
shells out to them on the host directly.

This module is the intended integration point for a future frontend: call
``build_forwarder()`` directly instead of shelling out to this file's CLI.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.cores_registry import CoreRegistry, DEFAULT_CORES_JSON
from tools.devkit_runtime import (
    PROJECT_ROOT,
    devkit_tmp_dir,
    ensure_devkit_image_exists,
    run_devkit,
    to_container_path,
)
from tools.generate_placeholder_assets import ensure_placeholder_assets
from tools.media_prep import prepare_banner_audio, prepare_banner_image, prepare_icon
from tools.title_id import (
    DEFAULT_REGISTRY_PATH,
    ForwarderIdentity,
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


def normalize_sd_path(rom_path: str) -> str:
    """Strip an ``sdmc:/`` prefix and any leading slash from an SD path."""
    clean = rom_path
    if clean.startswith("sdmc:/"):
        clean = clean[len("sdmc:/"):]
    return clean.lstrip("/")


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
    title_registry = TitleIdRegistry.load(title_id_registry_path)
    unique_id, title_id = generate_title_id(
        identity, core_registry.all_unique_ids(), title_registry
    )

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
        prepare_banner_image(banner_source, banner_png)
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
    parser.add_argument("--core", required=True, help="libretro core name, as in cores.json")
    parser.add_argument("--rom", required=True, help="ROM path on the SD card")
    parser.add_argument(
        "--name",
        required=True,
        help="Internal/display identifier for this forwarder "
        "(used as the registry key and default output filename)",
    )
    parser.add_argument(
        "--short-name", help="SMDH short description (default: --name)"
    )
    parser.add_argument(
        "--long-name", help="SMDH long description (default: --name)"
    )
    parser.add_argument(
        "--manufacturer",
        default=DEFAULT_MANUFACTURER,
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
    parser.add_argument("--output", type=Path, help="Output .cia path (default: output/<name>.cia)")
    parser.add_argument("--cores-json", type=Path, default=DEFAULT_CORES_JSON)
    parser.add_argument("--title-id-registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = parse_args(argv)
    output = args.output or (PROJECT_ROOT / "output" / f"{args.name}.cia")

    request = ForwarderRequest(
        core=args.core,
        rom_path=args.rom,
        name=args.name,
        short_name=args.short_name or args.name,
        long_name=args.long_name or args.name,
        manufacturer=args.manufacturer,
        output=output,
        icon=args.icon,
        banner=args.banner,
        audio=args.audio,
    )
    build_forwarder(
        request,
        cores_json=args.cores_json,
        title_id_registry_path=args.title_id_registry,
    )


if __name__ == "__main__":
    main()
