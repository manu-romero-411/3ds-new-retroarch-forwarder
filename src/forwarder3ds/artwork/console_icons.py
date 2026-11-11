"""Pixel-art icons of each console, for the banner's tag.

The icons are plain PNGs in ``data/console_icons/`` named after the console
(``gb.png``, ``snes.png``…), with ``generic.png`` for the rest: replace or
add files there to change them for every game. A project can also use any
image of its own instead (see :func:`load_icon`).

Icons are drawn small (a few pixels per pixel of art): :func:`fit_icon`
scales pixel art up by whole steps, so it stays sharp, and big pictures
down smoothly.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from forwarder3ds.core.paths import bundled

GENERIC = "generic"


def icons_dir() -> Path:
    """The folder of the default console icons."""
    return bundled("console_icons")


def default_icon_path(console: str) -> Path:
    """The default icon of ``console`` (the generic one if it has none)."""
    own = icons_dir() / f"{console}.png"
    return own if own.is_file() else icons_dir() / f"{GENERIC}.png"


def load_icon(console: str, custom: Path | None = None) -> Image.Image:
    """``custom`` if it is a readable image, else the console's default icon."""
    for path in (custom, default_icon_path(console)):
        if path is None:
            continue
        try:
            with Image.open(path) as image:
                return image.convert("RGBA")
        except OSError:
            continue
    return Image.new("RGBA", (1, 1), (0, 0, 0, 0))


def fit_icon(icon: Image.Image, height: int) -> Image.Image:
    """``icon`` without its transparent margin, scaled to at most ``height`` pixels tall."""
    box = icon.getchannel("A").getbbox() if icon.mode == "RGBA" else None
    if box is not None:
        icon = icon.crop(box)
    if icon.height <= height:
        factor = max(1, height // icon.height)
        return icon.resize((icon.width * factor, icon.height * factor), Image.Resampling.NEAREST)
    ratio = height / icon.height
    return icon.resize((max(1, round(icon.width * ratio)), height), Image.Resampling.LANCZOS)
