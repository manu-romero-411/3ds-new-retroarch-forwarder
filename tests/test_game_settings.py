"""Per-game settings: core options, screen, remaps and projects."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from pathlib import Path

import pytest

from forwarder3ds.builder.injector import (
    make_request,
    request_from_project,
    validate_request,
    write_romfs,
)
from forwarder3ds.builder.toolchain import Base
from forwarder3ds.core.core_options import (
    CoreOptionsError,
    options_file_text,
    parse_core_options,
)
from forwarder3ds.core.game_config import (
    ScreenMode,
    ScreenSettings,
    console_targets,
    parse_remap,
    remap_text,
)
from forwarder3ds.core.cores import DEFAULT_CORES_JSON, CoreRegistry
from forwarder3ds.core.projects import Asset, BannerStyle, ProjectStore
from forwarder3ds.core.systems import SystemCatalog

HEADER = r"""
#include <libretro.h>
/* A comment with { braces } */
struct retro_core_option_v2_category option_cats_us[] = {
   { "video", "Video", "Picture settings." },
   { NULL, NULL, NULL },
};
#define V(x) { #x, NULL }
struct retro_core_option_v2_definition option_defs_us[] = {
   {
      "demo_palette", "Palette", NULL,
      "Colours " "used.", NULL, "video",
      { { "rgb", "RGB" }, { "composite", "Composite" }, { NULL, NULL } },
      "rgb"
   },
#ifdef _3DS
   { "demo_frameskip", "Frameskip", NULL, "Skips.", NULL, NULL,
      { V(0), V(1), V(2), { NULL, NULL } }, "1" },
#else
   { "demo_desktop_only", "Desktop", NULL, NULL, NULL, NULL,
      { { "on", NULL }, { NULL, NULL } }, "on" },
#endif
#if !defined(_3DS) && !defined(VITA)
   { "demo_threads", "Threads", NULL, NULL, NULL, NULL, { { "2", NULL }, { NULL, NULL } }, NULL },
#endif
   { NULL, NULL, NULL, NULL, NULL, NULL, {{0}}, NULL },
};
"""


def test_core_options_parse_the_3ds_branches() -> None:
    options = parse_core_options(HEADER)
    assert [option.key for option in options.options] == ["demo_palette", "demo_frameskip"]
    palette = options.get("demo_palette")
    assert palette is not None
    assert palette.info == "Colours used."
    assert palette.values == (("rgb", "RGB"), ("composite", "Composite"))
    assert options.category_label(palette.category) == "Video"
    frameskip = options.get("demo_frameskip")
    assert frameskip is not None and frameskip.default == "1"
    assert [value for value, _label in frameskip.values] == ["0", "1", "2"]
    assert options.clean({"demo_palette": "rgb", "demo_frameskip": "2", "bogus": "x"}) == {
        "demo_frameskip": "2"
    }
    assert options_file_text({"b": "2", "a": "1"}) == 'a = "1"\nb = "2"\n'
    with pytest.raises(CoreOptionsError):
        parse_core_options("int x;")


def test_core_options_v1() -> None:
    header = """
    struct retro_core_option_definition option_defs_us[] = {
       { "gpsp_bios", "BIOS", "Which one.", { { "auto", "Auto" }, { "builtin", NULL },
         { NULL, NULL } }, "auto" },
       { NULL, NULL, NULL, {{0}}, NULL },
    };
    """
    option = parse_core_options(header).options[0]
    assert (option.key, option.label, option.default) == ("gpsp_bios", "BIOS", "auto")
    assert option.values[1] == ("builtin", "builtin")


@pytest.mark.parametrize(
    ("screen", "expected"),
    [
        (
            ScreenSettings(ScreenMode.PIXEL_PERFECT),
            {"video_scale_integer": "true", "aspect_ratio_index": "21"},
        ),
        (ScreenSettings(ScreenMode.FULL, smooth=True), {"aspect_ratio_index": "24"}),
        (
            ScreenSettings(ScreenMode.CUSTOM, 360, 240),
            {"aspect_ratio_index": "23", "custom_viewport_x": "20", "custom_viewport_y": "0"},
        ),
        (ScreenSettings(), {"aspect_ratio_index": "22", "video_smooth": "false"}),
    ],
)
def test_screen_settings(screen: ScreenSettings, expected: dict[str, str]) -> None:
    lines = screen.config_lines()
    assert expected.items() <= lines.items()
    assert ScreenSettings.from_config(lines) == screen
    assert ScreenSettings.from_json(screen.to_json()) == screen


def test_remap_round_trip() -> None:
    remap = {"a": "b", "b": "a", "select": "none", "x": "x", "zz": "a"}
    text = remap_text(remap)
    assert 'input_player1_btn_a = "0"' in text
    assert 'input_player1_btn_b = "8"' in text
    assert 'input_player1_btn_select = "-1"' in text
    assert "_x " not in text
    entries = dict(line.replace('"', "").split(" = ") for line in text.splitlines())
    assert parse_remap(entries) == {"a": "b", "b": "a", "select": "none"}
    assert remap_text({}) == ""
    assert "x" not in console_targets("gb") and "x" in console_targets("snes")


def test_romfs_seeds_settings(tmp_path: Path) -> None:
    rom = tmp_path / "Tetris.gb"
    rom.write_bytes(b"\0")
    request = make_request(
        rom=rom,
        long_name="Tetris",
        output=tmp_path / "t.cia",
        screen=ScreenSettings(ScreenMode.FULL),
        core_options={"gambatte_gb_colorization": "auto"},
        remap={"a": "b"},
    )
    base = Base("gambatte", tmp_path / "x.elf", "64MB", "Legacy", False, None, {})
    romfs = write_romfs(tmp_path / "scratch", request, base)
    config = (romfs / "retroarch.cfg").read_text(encoding="utf-8")
    assert 'aspect_ratio_index = "24"' in config
    assert 'menu_swap_ok_cancel_buttons = "false"' in config
    assert 'rgui_menu_theme_preset = "romfs:/rgui_theme.cfg"' in config
    assert "rgui_bg_dark_color" in (romfs / "rgui_theme.cfg").read_text(encoding="utf-8")
    options = (romfs / "game.opt").read_text(encoding="utf-8")
    assert options == 'gambatte_gb_colorization = "auto"\n'
    assert (romfs / "game.rmp").read_text(encoding="utf-8") == 'input_player1_btn_a = "0"\n'


def test_projects_store(tmp_path: Path) -> None:
    rom = tmp_path / "Tetris (World).gb"
    rom.write_bytes(b"\0")
    store = ProjectStore(tmp_path / "projects")
    project = store.create(rom, "gb", core="gambatte", long_name="Tetris", folder="Tetris")
    project.remap = {"a": "b"}
    project.screen = ScreenSettings(ScreenMode.PIXEL_PERFECT)
    project.banner_style = BannerStyle.SNAPSHOT
    store.save(project)
    icon = tmp_path / "icon.PNG"
    icon.write_bytes(b"png")
    store.set_asset(project, Asset.ICON, icon)
    assert project.asset(Asset.ICON) == project.directory / "icon.png"

    (listed,) = store.list()
    assert listed.remap == {"a": "b"} and listed.banner_style is BannerStyle.SNAPSHOT
    request = request_from_project(listed, tmp_path / "out.cia")
    assert (request.console, request.core, request.folder) == ("gb", "gambatte", "Tetris")
    assert request.icon == listed.asset(Asset.ICON)
    assert request.screen == ScreenSettings(ScreenMode.PIXEL_PERFECT)
    assert not request.replace_existing_id

    exported = tmp_path / "export.zip"
    store.export([listed], exported)
    other = ProjectStore(tmp_path / "other")
    imported = other.import_archive(exported)[0]
    assert imported.id != listed.id and imported.long_name == "Tetris"
    assert imported.asset(Asset.ICON) is not None

    store.delete(listed)
    assert not store.list() and rom.exists()


def test_standalone_base_romfs(tmp_path: Path) -> None:
    base_dir = tmp_path / "bases" / "snes9x_3ds"
    (base_dir / "romfs" / "gfx").mkdir(parents=True)
    (base_dir / "romfs" / "gfx" / "splash.t3x").write_bytes(b"t3x")
    (base_dir / "app.elf").write_bytes(b"\x7fELF")
    (base_dir / "app.rsf").write_text("RomFs:\n  RootPath: $(APP_ROMFS)\n", encoding="utf-8")
    (base_dir / "base.env").write_text(
        "KIND=standalone\nCORE_NAME=snes9x_3ds\nAPP_SYSTEM_MODE=64MB\n", encoding="utf-8"
    )
    base = Base.load(base_dir)
    assert base.standalone and base.rsf == base_dir / "app.rsf"

    rom = tmp_path / "Super Mario World (USA).sfc"
    rom.write_bytes(b"\0" * 16)
    request = make_request(rom=rom, core="snes9x_3ds", long_name="Super Mario World",
                           output=tmp_path / "o.cia", remap={"a": "b"})  # fmt: skip
    romfs = write_romfs(tmp_path / "scratch", request, base)
    names = sorted(str(path.relative_to(romfs)) for path in romfs.rglob("*") if path.is_file())
    assert names == ["game.sfc", "gfx/splash.t3x", "manifest.cfg"]
    manifest = (romfs / "manifest.cfg").read_text(encoding="utf-8")
    assert 'content = "game.sfc"' in manifest
    assert 'data_dir = "sdmc:/saves/snes/Super Mario World"' in manifest


def test_snes_alternatives() -> None:
    snes = SystemCatalog.load().require("snes")
    assert snes.cores == ("snes9x2005", "snes9x_3ds")


def test_standalone_core_validates() -> None:
    validate_request(make_request(
        rom=Path(__file__),
        console="snes",
        core="snes9x_3ds",
        long_name="X",
        output=Path("x.cia")),  # fmt: skip
        CoreRegistry.load(DEFAULT_CORES_JSON),
        SystemCatalog.load(),
    )
