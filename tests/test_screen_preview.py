"""Previews of the top and touch screens."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from PIL import Image

from forwarder3ds.artwork.bottom_screen import choice_language, vc_choice
from forwarder3ds.artwork.screen_preview import (
    console_screen,
    fit_bottom,
    game_size,
    render_top_preview,
)
from forwarder3ds.core.game_config import ScreenMode, ScreenSettings


def test_game_sizes() -> None:
    gba, snes = console_screen("gba"), console_screen("snes")
    assert game_size(ScreenSettings(ScreenMode.RECOMMENDED), gba) == (360, 240)
    assert game_size(ScreenSettings(ScreenMode.RECOMMENDED), snes) == (320, 240)
    assert game_size(ScreenSettings(ScreenMode.PIXEL_PERFECT), console_screen("gb")) == (160, 144)
    assert game_size(ScreenSettings(ScreenMode.PIXEL_PERFECT), snes) == (256, 224)
    assert game_size(ScreenSettings(ScreenMode.FULL), snes) == (400, 240)
    assert game_size(ScreenSettings(ScreenMode.CUSTOM, 999, 100), snes) == (400, 100)


def test_top_preview_layers() -> None:
    shot = Image.new("RGBA", (512, 448), (0, 255, 0, 255))  # libretro's 2x snaps
    bezel = Image.new("RGBA", (400, 240), (255, 0, 0, 255))
    screen = ScreenSettings(ScreenMode.PIXEL_PERFECT)
    over = render_top_preview(console="snes", screen=screen, screenshot=shot, bezel=bezel)
    assert over.size == (400, 240) and over.getpixel((200, 120))[:3] == (255, 0, 0)
    behind = render_top_preview(
        console="snes", screen=screen, screenshot=shot, bezel=bezel, bezel_behind=True
    )
    assert behind.getpixel((200, 120))[:3] == (0, 255, 0)
    assert behind.getpixel((10, 120))[:3] == (255, 0, 0)
    plain = render_top_preview(console="snes", screen=screen)
    assert plain.getpixel((10, 120))[:3] == (0, 0, 0)


def test_bottom_choices() -> None:
    assert choice_language(vc_choice("ja")) == "ja"
    assert choice_language("image") is None
    assert fit_bottom(Image.new("RGB", (10, 10))).size == (320, 240)
