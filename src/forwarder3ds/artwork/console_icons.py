"""Small pixel-art icons of each console, for the banner's tag.

Each icon is a grid of characters (one per pixel) drawn with a palette;
``.`` is transparent. A few generic shapes (a rounded pad, a flat pad,
upright and landscape handhelds) are recoloured per console, so the icons
suggest the machine without copying anyone's artwork.

A PNG named after the console (``gb.png``, ``snes.png``…) in
:func:`custom_icons_dir` replaces the built-in icon.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from forwarder3ds.core import paths

_PAD = (
    "...KKKK....KKKK...",
    "..KBBBBKKKKBBBBK..",
    ".KBBDBBBBBBBBBaBBK",
    ".KBDDDBBSBSBBbBcBK",
    ".KBBDBBBBBBBBBdBBK",
    ".KBBBBBBKKKBBBBBBK",
    "..KBBBBK...KBBBBK.",
    "...KKKK.....KKKK..",
)  # fmt: skip
_PAD_HANDLES = (
    "..KKKKK....KKKKK..",
    ".KBBBBBKKKKBBBBBK.",
    "KBBDBBBBBBBBBBaBBK",
    "KBDDDBBSBBSBBbBcBK",
    "KBBDBBBBBBBBBBdBBK",
    "KBBBBBBKKKKBBBBBBK",
    "KBBBBBK....KBBBBBK",
    ".KBBBK......KBBBK.",
    "..KKK........KKK..",
)  # fmt: skip
_FLAT_PAD = (
    "KKKKKKKKKKKKKKKKK",
    "KLLLLLLLLLLLLLLLK",
    "KLBBBBBBBBBBBBBLK",
    "KLBDBBBBBBBBBBBLK",
    "KLDDDBBSBSBBcBaLK",
    "KLBDBBBBBBBBBBBLK",
    "KLBBBBBBBBBBBBBLK",
    "KKKKKKKKKKKKKKKKK",
)  # fmt: skip
_UPRIGHT = (
    ".KKKKKKKKK.",
    "KBBBBBBBBBK",
    "KBFFFFFFFBK",
    "KBFGGGGGFBK",
    "KBFGGGGGFBK",
    "KBFGGGGGFBK",
    "KBFFFFFFFBK",
    "KBBBBBBBBBK",
    "KBDBBBBBBBK",
    "KDDDBBBBaBK",
    "KBDBBBBaBBK",
    "KBBBSSBBBBK",
    ".KKKKKKKKK.",
)  # fmt: skip
_LANDSCAPE = (
    "..KKKKKKKKKKKKKK..",
    ".KBBBBBBBBBBBBBBK.",
    "KBBBBFFFFFFFFBBBBK",
    "KBDBBFGGGGGGFBBaBK",
    "KDDDBFGGGGGGFBaBBK",
    "KBDBBFGGGGGGFBBBBK",
    "KBBBBFFFFFFFFBBBBK",
    ".KBBBBBBBBBBBBBBK.",
    "..KKKKKKKKKKKKKK..",
)  # fmt: skip

_OUTLINE = "#101010"
_SCREEN = "#7c9c3c"


def _palette(body: str, dpad: str, *buttons: str, **extra: str) -> dict[str, str]:
    a, b, c, d = (buttons + (buttons[-1],) * 4)[:4]
    colours = {"K": _OUTLINE, "B": body, "D": dpad, "a": a, "b": b, "c": c, "d": d}
    colours |= {"S": extra.get("select", dpad), "L": extra.get("frame", body)}
    colours |= {"F": extra.get("bezel", "#3a3a44"), "G": extra.get("screen", _SCREEN)}
    return colours


_ICONS: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    "gb": (_UPRIGHT, _palette("#c8c4bc", "#2a2a2a", "#9a2050", bezel="#5a5a68")),
    "gbc": (
        _UPRIGHT,
        _palette("#7a3cb8", "#2a2a2a", "#d0d0d0", bezel="#2a2a2a", screen="#88b8e0"),
    ),
    "gba": (
        _LANDSCAPE,
        _palette("#5048a8", "#2a2a2a", "#c8c8d0", bezel="#2a2a2a", screen="#88b8e0"),
    ),
    "gamegear": (
        _LANDSCAPE,
        _palette("#2a2a2a", "#4a4a4a", "#3060c0", bezel="#1a1a1a", screen="#5aa0d8"),
    ),
    "nes": (_FLAT_PAD, _palette("#1e1e1e", "#4a4a4a", "#c02020", frame="#b8b8b8")),
    "fds": (_FLAT_PAD, _palette("#1e1e1e", "#4a4a4a", "#c02020", frame="#b8b8b8")),
    "snes": (
        _PAD,
        _palette("#c4c4cc", "#3a3a3a", "#3050c8", "#30a050", "#c02828", "#e0c020"),
    ),
    "megadrive": (_PAD, _palette("#1e1e1e", "#3c3c3c", "#4a4a4a", select="#808080")),
    "segacd": (_PAD, _palette("#1e1e1e", "#3c3c3c", "#4a4a4a", select="#808080")),
    "mastersystem": (
        _FLAT_PAD,
        _palette("#1e1e1e", "#3a3a3a", "#c02020", "#c02020", frame="#2a2a2a"),
    ),
    "sg1000": (_FLAT_PAD, _palette("#1e1e1e", "#3a3a3a", "#c02020", frame="#7a7a7a")),
    "pcengine": (_FLAT_PAD, _palette("#e8e8e8", "#2a2a2a", "#2a2a2a", frame="#2a2a2a")),
    "pcenginecd": (_FLAT_PAD, _palette("#e8e8e8", "#2a2a2a", "#2a2a2a", frame="#2a2a2a")),
    "psx": (
        _PAD_HANDLES,
        _palette("#b8b8c0", "#4a4a4a", "#30a060", "#d05090", "#c03030", "#3060c0"),
    ),
}
_GENERIC = (_PAD, _palette("#8a8a92", "#2a2a2a", "#c03030"))


def custom_icons_dir() -> Path:
    """Where the user's own console icons go (``<console>.png``)."""
    return paths.data_dir() / "console_icons"


def console_icon(console: str, scale: int = 2) -> Image.Image:
    """The icon of ``console`` (the user's own if there is one), scaled by ``scale``."""
    custom = custom_icons_dir() / f"{console}.png"
    if custom.is_file():
        try:
            return Image.open(custom).convert("RGBA")
        except OSError:
            pass
    grid, palette = _ICONS.get(console, _GENERIC)
    width = max(len(row) for row in grid)
    image = Image.new("RGBA", (width, len(grid)), (0, 0, 0, 0))
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell != ".":
                image.putpixel((x, y), _rgba(palette.get(cell, _OUTLINE)))
    return image.resize((width * scale, len(grid) * scale), Image.Resampling.NEAREST)


def _rgba(colour: str) -> tuple[int, int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255
