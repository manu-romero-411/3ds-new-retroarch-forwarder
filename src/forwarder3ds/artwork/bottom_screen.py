"""The touch screen shown while a game runs, in the style of the Virtual Console.

The 320x240 picture replaces the emulator's own idle screen: RetroArch
draws it instead of its "Tap the Touch Screen…" text (``bottom_idle.png``,
see ``retroarch/patches/0004``) and snes9x_3ds uses it as its second screen
background. Layout, as on Nintendo's Virtual Console::

    ┌────────────────────────────────┐
    │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  dark grey band, blurred edges
    │ ░░  Tap the Touch Screen to go ░░ │
    │ ░░  to the RetroArch menu.     ░░ │  message, centred and wrapped
    │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
    │      ⌂: Return to HOME Menu      │  footer
    └────────────────────────────────┘

The background is ``data/bottom_screen/background.png`` (drawn from
``background.svg``). The font is a setting: Nintendo's is FOT-Rodin, which
cannot be shipped; without one the built-in font is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from forwarder3ds.core.paths import bundled

WIDTH, HEIGHT = 320, 240

#: Language code -> (message with a ``{menu}`` placeholder, footer after the icon).
MESSAGES: dict[str, tuple[str, str]] = {
    "en": ("Tap the Touch Screen to go to the {menu} menu.", ": Return to HOME Menu"),
    "ja": ("タッチスクリーンにタッチすると{menu}メニューに移ります。", "：HOMEメニューにもどる"),
    "fr": ("Touchez l'écran tactile pour accéder au menu {menu}.", " : Retour au menu HOME"),
    "de": ("Berühre den Touchscreen, um zum {menu}-Menü zu gelangen.", ": Zurück zum HOME-Menü"),
    "it": ("Tocca il touch screen per accedere al menu di {menu}.", ": Torna al menu HOME"),
    "es": ("Toca la pantalla táctil para ir al menú de {menu}.", ": Volver al menú HOME"),
    "nl": (
        "Tik op het aanraakscherm om naar het {menu}-menu te gaan.",
        ": Terug naar het HOME-menu",
    ),
    "pt": ("Toca no ecrã tátil para ir para o menu do {menu}.", ": Voltar ao Menu HOME"),
    "ru": ("Коснитесь сенсорного экрана, чтобы открыть меню {menu}.", ": Вернуться в меню HOME"),
}

#: Language code -> its name in that language, for the settings.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ja": "日本語",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "es": "Español",
    "nl": "Nederlands",
    "pt": "Português",
    "ru": "Русский",
}

DEFAULT_LANGUAGE = "en"

_FONT_SIZE = 16
_LINE_HEIGHT = 19
_TEXT_WIDTH = 236
_MESSAGE_CENTRE = 108  # middle of the message block's capitals
_FOOTER_CAP_TOP = 215
_ICON_GAP = -1
_MESSAGE_COLOUR = (88, 88, 88, 255)
_FOOTER_COLOUR = (80, 80, 80, 255)
_SUPERSAMPLE = 4

# The HOME icon (data/bottom_screen/home_icon.svg, 16 units square), as on
# the Virtual Console: a wide roof over a house with a window under it. Both
# outlines are stroked with round joins, which rounds the corners.
_HOUSE_UNITS = 16
_HOUSE_STROKE = 1.2
_HOUSE = (
    (8, 2), (1.5, 8), (1.5, 9), (3, 9), (3, 14), (13, 14), (13, 9), (14.5, 9), (14.5, 8),
)  # fmt: skip
_WINDOW = ((5.5, 9), (5.5, 13), (10.5, 13), (10.5, 9))

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@dataclass(frozen=True)
class BottomScreenStyle:
    """Language of the message (a key of :data:`MESSAGES`) and font (TTF/OTF; empty: built-in)."""

    language: str = DEFAULT_LANGUAGE
    font: str = ""


def _font(path: str, size: int) -> Font:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _tokens(text: str) -> list[str]:
    """Wrapping units: words (with their space) or, for text without spaces, characters.

    Latin words inside text without spaces (a menu name in Japanese) stay whole.
    """
    if " " not in text:
        return re.findall(r"[A-Za-z0-9]+|.", text)
    words = text.split(" ")
    return [word + " " for word in words[:-1]] + [words[-1]]


def wrap(text: str, font: Font, width: int) -> list[str]:
    """``text`` broken into lines no wider than ``width`` (a long word keeps its own line)."""
    lines: list[str] = []
    line = ""
    for token in _tokens(text):
        if line and font.getlength((line + token).rstrip()) > width:
            lines.append(line.rstrip())
            line = token.lstrip() if not token.strip() else token
        else:
            line += token
    if line.strip():
        lines.append(line.rstrip())
    return lines


def _cap_height(font: Font) -> int:
    box = font.getbbox("H")
    return int(box[3] - box[1])


def _outline(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], width: float) -> None:
    """Stroke the closed polygon ``points`` with round joins."""
    radius = width / 2
    for index, (x, y) in enumerate(points):
        draw.line((x, y, *points[index - 1]), fill=255, width=round(width))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)


def house_icon(size: int, colour: tuple[int, int, int, int]) -> Image.Image:
    """The HOME icon, ``size`` pixels square, antialiased."""
    big = size * _SUPERSAMPLE
    scale = big / _HOUSE_UNITS
    house = [(x * scale, y * scale) for x, y in _HOUSE]
    window = [(x * scale, y * scale) for x, y in _WINDOW]
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(house, fill=255)
    _outline(draw, house, _HOUSE_STROKE * scale)
    draw.polygon(window, fill=0)
    _outline(draw, window, _HOUSE_STROKE * scale)
    icon = Image.new("RGBA", (size, size), colour)
    icon.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return icon


def _draw_message(image: Image.Image, text: str, font: Font) -> None:
    draw = ImageDraw.Draw(image)
    lines = wrap(text, font, _TEXT_WIDTH)
    cap = _cap_height(font)
    first_top = _MESSAGE_CENTRE - ((len(lines) - 1) * _LINE_HEIGHT + cap) / 2
    for index, line in enumerate(lines):
        baseline = round(first_top + index * _LINE_HEIGHT + cap)
        draw.text((WIDTH / 2, baseline), line, font=font, fill=_MESSAGE_COLOUR, anchor="ms")


def _draw_footer(image: Image.Image, text: str, font: Font) -> None:
    cap = _cap_height(font)
    icon_size = cap + 3
    width = icon_size + _ICON_GAP + font.getlength(text)
    left = round((WIDTH - width) / 2)
    baseline = _FOOTER_CAP_TOP + cap
    icon = house_icon(icon_size, _FOOTER_COLOUR)
    image.alpha_composite(icon, (left, baseline - icon_size + 1))
    ImageDraw.Draw(image).text(
        (left + icon_size + _ICON_GAP, baseline), text, font=font, fill=_FOOTER_COLOUR, anchor="ls"
    )


def render_bottom_screen(menu: str, style: BottomScreenStyle | None = None) -> Image.Image:
    """The idle touch screen for an emulator whose menu is called ``menu`` (e.g. ``RetroArch``)."""
    style = style or BottomScreenStyle()
    message, footer = MESSAGES.get(style.language, MESSAGES[DEFAULT_LANGUAGE])
    with Image.open(bundled("bottom_screen") / "background.png") as background:
        image = background.convert("RGBA").resize((WIDTH, HEIGHT))
    font = _font(style.font, _FONT_SIZE)
    _draw_message(image, message.format(menu=menu), font)
    _draw_footer(image, footer, font)
    return image


def render_bottom_screen_png(menu: str, style: BottomScreenStyle | None = None) -> bytes:
    """:func:`render_bottom_screen` as PNG data."""
    buffer = BytesIO()
    render_bottom_screen(menu, style).convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def render_bottom_screen_to_file(
    path: Path, menu: str, style: BottomScreenStyle | None = None
) -> Path:
    """Write :func:`render_bottom_screen` to ``path`` (PNG) and return it."""
    path.write_bytes(render_bottom_screen_png(menu, style))
    return path
