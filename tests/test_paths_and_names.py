"""Small pure helpers: ROM titles, save folders, output names, settings, toolchain lookup."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from PIL import Image

from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.injector import (
    default_cia_filename,
    ensure_cia_extension,
    make_request,
    manifest_text,
    seed_config_text,
    write_romfs,
)
from forwarder3ds.builder.toolchain import Base, find_toolchain
from forwarder3ds.core import paths
from forwarder3ds.core.names import save_folder_name, suggest_title
from forwarder3ds.core.settings import Settings, load_settings, masked, save_settings


@pytest.mark.parametrize(
    ("rom", "title"),
    [
        ("roms/snes/Super Mario World (USA) (Rev 1) [!].sfc", "Super Mario World"),
        ("roms\\psx\\Bust-a-Move 4 (Europe).chd", "Bust-a-Move 4"),
        ("roms/snes/", ""),
        ("(Only Tags).zip", "(Only Tags)"),
    ],
)
def test_suggest_title(rom: str, title: str) -> None:
    assert suggest_title(rom) == title


def test_output_names() -> None:
    assert default_cia_filename("Zelda: Link's Awakening") == "Zelda Link's Awakening.cia"
    assert default_cia_filename("") == "game.cia"
    assert ensure_cia_extension(Path("x.v2")) == Path("x.v2.cia")
    assert ensure_cia_extension(Path("x.CIA")) == Path("x.CIA")


@pytest.mark.parametrize(
    ("title", "folder"),
    [("Super Mario World", "Super Mario World"), ('A/B: "C"?', "A B C"), (" . ", "game")],
)
def test_save_folder_name(title: str, folder: str) -> None:
    assert save_folder_name(title) == folder


def test_request_defaults_and_romfs_files(tmp_path: Path) -> None:
    rom = tmp_path / "Tetris (World) (Rev 1).GB"
    rom.write_bytes(b"\0")
    request = make_request(rom=rom, long_name="Tetris", output=tmp_path / "t.cia")
    assert (request.console, request.core, request.folder) == ("gb", "gambatte", "Tetris")
    assert request.content_name == "game.gb"
    assert request.data_dir == "sdmc:/saves/gb/Tetris"
    manifest = manifest_text(request)
    assert 'content = "game.gb"' in manifest
    assert 'data_dir = "sdmc:/saves/gb/Tetris"' in manifest
    assert 'rom_name = "Tetris (World) (Rev 1).GB"' in manifest
    assert 'core_options_path = "sdmc:/saves/gb/Tetris/game.opt"' in seed_config_text(request)


def test_bezel_goes_in_the_romfs(tmp_path: Path) -> None:
    rom = tmp_path / "Tetris.gb"
    rom.write_bytes(b"\0")
    image = tmp_path / "frame.png"
    Image.new("RGBA", (800, 480), (0, 0, 0, 0)).save(image)
    request = make_request(rom=rom, long_name="Tetris", output=tmp_path / "t.cia", bezel=image)
    base = Base("gambatte", tmp_path / "x.elf", "64MB", "Legacy", False, None, {})
    romfs = write_romfs(tmp_path / "scratch", request, base)
    with Image.open(romfs / "bezel.png") as bezel:
        assert bezel.size == (400, 240) and bezel.mode == "RGBA"
    assert 'overlay0_overlay = "bezel.png"' in (romfs / "bezel.cfg").read_text(encoding="utf-8")
    assert (romfs / "game.gb").read_bytes() == b"\0"
    with pytest.raises(BuildError):
        make_request(rom=tmp_path / "disc.chd", long_name="Disc", output=tmp_path / "d.cia")


def test_settings_round_trip() -> None:
    settings = Settings()
    settings.steamgriddb.api_key = "0123456789abcdef"
    settings.general.manufacturer = "Me"
    settings.steamgriddb.nsfw = True
    path = save_settings(settings)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_settings() == settings
    assert masked(settings)["steamgriddb"]["api_key"] == "0123…"


def test_settings_import_from_old_ui() -> None:
    legacy = paths.config_dir().parent / "3ds-new-forwarder-generator" / "ForwarderBuilderUI.conf"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[sgdb]\napi_key=abc\n[paths]\nlast_output_dir=/tmp/out\n", "utf-8")
    settings = load_settings()
    assert settings.steamgriddb.api_key == "abc"
    assert settings.general.output_dir == "/tmp/out"
    assert paths.config_file().is_file()  # imported once, then read from the new file
    legacy.unlink()
    assert load_settings().steamgriddb.api_key == "abc"


def test_toolchain_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toolchain = tmp_path / "toolchain"
    for relative in ("bin/makerom", "bin/bannertool", "bases/gambatte/retroarch.elf"):
        (toolchain / relative).parent.mkdir(parents=True, exist_ok=True)
        (toolchain / relative).write_bytes(b"")
    (toolchain / "bases/gambatte/base.env").write_text(
        "CORE_NAME=gambatte\nAPP_SYSTEM_MODE=64MB\nAPP_SYSTEM_MODE_EXT=124MB\n", encoding="utf-8"
    )
    (toolchain / "VERSIONS").write_text("makerom=v1\nbase-gambatte=abc\n", encoding="utf-8")
    monkeypatch.setenv(paths.TOOLCHAIN_ENV, str(toolchain))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    tools = find_toolchain()
    assert tools.complete
    assert tools.makerom == toolchain / "bin" / "makerom"
    assert tools.versions() == {"makerom": "v1", "base-gambatte": "abc"}
    assert tools.rsf.is_file()
    assert tools.available_cores() == ["gambatte"]
    base = tools.base("gambatte")
    assert (base.system_mode, base.system_mode_ext, base.bottom_menu) == ("64MB", "124MB", None)
    with pytest.raises(BuildError):
        tools.base("snes9x2005")
