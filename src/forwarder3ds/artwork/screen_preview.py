"""Previews of the 3DS screens, as the injection options will leave them.

The top screen shows a picture of the game (libretro's screenshot, or a
placeholder) scaled and placed as the chosen :class:`ScreenSettings` make
RetroArch do it, with the bezel over it; a standalone emulator draws the
bezel behind the game instead. The touch screen preview is the picture the
CIA will carry (see :mod:`forwarder3ds.artwork.bottom_screen`).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from forwarder3ds.core.game_config import SCREEN_HEIGHT, SCREEN_WIDTH, ScreenMode, ScreenSettings

BOTTOM_WIDTH, BOTTOM_HEIGHT = 320, 240


@dataclass(frozen=True)
class ConsoleScreen:
    """A console's native picture size and the aspect ratio its core shows it at."""

    width: int
    height: int
    aspect: float


_FOUR_THIRDS = 4 / 3
_HANDHELD = ConsoleScreen(160, 144, 10 / 9)
#: Console -> its screen; the rest use :data:`DEFAULT_SCREEN`.
CONSOLE_SCREENS: dict[str, ConsoleScreen] = {
    "gb": _HANDHELD,
    "gbc": _HANDHELD,
    "gamegear": _HANDHELD,
    "gba": ConsoleScreen(240, 160, 3 / 2),
    "nes": ConsoleScreen(256, 240, _FOUR_THIRDS),
    "fds": ConsoleScreen(256, 240, _FOUR_THIRDS),
    "snes": ConsoleScreen(256, 224, _FOUR_THIRDS),
    "mastersystem": ConsoleScreen(256, 192, _FOUR_THIRDS),
    "sg1000": ConsoleScreen(256, 192, _FOUR_THIRDS),
    "megadrive": ConsoleScreen(320, 224, _FOUR_THIRDS),
    "segacd": ConsoleScreen(320, 224, _FOUR_THIRDS),
    "pcengine": ConsoleScreen(256, 232, _FOUR_THIRDS),
    "pcenginecd": ConsoleScreen(256, 232, _FOUR_THIRDS),
    "psx": ConsoleScreen(320, 240, _FOUR_THIRDS),
    "atari2600": ConsoleScreen(160, 210, _FOUR_THIRDS),
    "atari7800": ConsoleScreen(320, 223, _FOUR_THIRDS),
    "lynx": ConsoleScreen(160, 102, 160 / 102),
    "pokemini": ConsoleScreen(96, 64, 3 / 2),
    "sega32x": ConsoleScreen(320, 224, _FOUR_THIRDS),
    "mame": ConsoleScreen(320, 224, _FOUR_THIRDS),
    "fbneo": ConsoleScreen(320, 224, _FOUR_THIRDS),
}
DEFAULT_SCREEN = ConsoleScreen(256, 224, _FOUR_THIRDS)

_PLACEHOLDER_CELL = 16
_PLACEHOLDER_COLOURS = ((58, 62, 74), (48, 52, 62))


def console_screen(console: str) -> ConsoleScreen:
    """The screen of ``console`` (a typical 4:3 one if unknown)."""
    return CONSOLE_SCREENS.get(console, DEFAULT_SCREEN)


def game_size(screen: ScreenSettings, console: ConsoleScreen) -> tuple[int, int]:
    """Width and height of the game's picture on the 400x240 top screen."""
    if screen.mode is ScreenMode.PIXEL_PERFECT:
        scale = max(1, min(SCREEN_WIDTH // console.width, SCREEN_HEIGHT // console.height))
        return min(console.width * scale, SCREEN_WIDTH), min(console.height * scale, SCREEN_HEIGHT)
    if screen.mode is ScreenMode.FULL:
        return SCREEN_WIDTH, SCREEN_HEIGHT
    if screen.mode is ScreenMode.CUSTOM:
        return max(1, min(screen.width, SCREEN_WIDTH)), max(1, min(screen.height, SCREEN_HEIGHT))
    width = round(SCREEN_HEIGHT * console.aspect)
    if width <= SCREEN_WIDTH:
        return width, SCREEN_HEIGHT
    return SCREEN_WIDTH, round(SCREEN_WIDTH / console.aspect)


def open_image(source: bytes | Path | None) -> Image.Image | None:
    """``source`` as an RGBA image, or ``None`` if there is none or it cannot be read."""
    if source is None:
        return None
    try:
        with Image.open(BytesIO(source) if isinstance(source, bytes) else source) as image:
            return image.convert("RGBA")
    except (OSError, UnidentifiedImageError):
        return None


def placeholder(console: ConsoleScreen) -> Image.Image:
    """A checkered stand-in for the game, at its native size."""
    image = Image.new("RGBA", (console.width, console.height), _PLACEHOLDER_COLOURS[0])
    draw = ImageDraw.Draw(image)
    for top in range(0, console.height, _PLACEHOLDER_CELL):
        for left in range(0, console.width, _PLACEHOLDER_CELL):
            if (top // _PLACEHOLDER_CELL + left // _PLACEHOLDER_CELL) % 2:
                right, bottom = left + _PLACEHOLDER_CELL - 1, top + _PLACEHOLDER_CELL - 1
                draw.rectangle((left, top, right, bottom), fill=_PLACEHOLDER_COLOURS[1])
    return image


def _native(shot: Image.Image, console: ConsoleScreen) -> Image.Image:
    """``shot`` at the console's own size (libretro keeps some at 2x)."""
    if shot.size == (console.width, console.height):
        return shot
    whole = shot.width % console.width == 0 and shot.height % console.height == 0
    resample = Image.Resampling.NEAREST if whole else Image.Resampling.LANCZOS
    return shot.resize((console.width, console.height), resample)


def render_top_preview(  # pylint: disable=too-many-arguments
    *,
    console: str,
    screen: ScreenSettings,
    screenshot: Image.Image | None = None,
    bezel: Image.Image | None = None,
    bezel_behind: bool = False,
) -> Image.Image:
    """The top screen: the game placed as ``screen`` says, with the bezel.

    ``bezel_behind`` draws the bezel under the game (standalone emulators).
    """
    native_screen = console_screen(console)
    game = _native(screenshot, native_screen) if screenshot else placeholder(native_screen)
    resample = Image.Resampling.BILINEAR if screen.smooth else Image.Resampling.NEAREST
    size = game_size(screen, native_screen)
    game = game.resize(size, resample)

    image = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0, 255))
    frame = bezel.resize(image.size, Image.Resampling.LANCZOS) if bezel else None
    if frame is not None and bezel_behind:
        image.alpha_composite(frame)
    image.alpha_composite(game, ((SCREEN_WIDTH - size[0]) // 2, (SCREEN_HEIGHT - size[1]) // 2))
    if frame is not None and not bezel_behind:
        image.alpha_composite(frame)
    return image


def fit_bottom(picture: Image.Image) -> Image.Image:
    """A touch screen picture of any size, stretched to 320x240."""
    return picture.convert("RGBA").resize((BOTTOM_WIDTH, BOTTOM_HEIGHT), Image.Resampling.LANCZOS)


def to_png(image: Image.Image) -> bytes:
    """``image`` as PNG data."""
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
