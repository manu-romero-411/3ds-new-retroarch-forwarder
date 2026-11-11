"""The default banner: the game's logo over a tag with the console and year.

Layout of the 256x128 image::

    ┌──────────────────────────────┐   background colour with a checker
    │        GAME LOGO             │   pattern a shade lighter (or darker)
    │   (or the title, as text)    │
    │   ╭──────────────────────╮   │   tag: console icon, then the
    │   │ [icon]  Name · 1990  │   │   caption (name and/or year)
    │   ╰──────────────────────╯   │
    └──────────────────────────────┘

The logo is the SteamGridDB one (or any image the user picks); without it
the title is written instead. Colours and font come from
:class:`CardStyle` (the settings); the caption's name and year come from
the project and can be edited there.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from forwarder3ds.artwork.console_icons import console_icon
from forwarder3ds.ctr.formats import BANNER_HEIGHT, BANNER_WIDTH

_CELL = 8
_SHADE = 14
_MARGIN = 10
_LOGO_HEIGHT = 80
_TAG_TOP = 92
_TAG_HEIGHT = 28
_TAG_PADDING = 9
_TAG_GAP = 7
_CAPTION_SIZE = 14
_TITLE_SIZE = 28
_SEPARATOR = " · "

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@dataclass(frozen=True)
class CardStyle:
    """Colours (``#rrggbb``) and font (a TTF/OTF path; empty: built-in)."""

    background: str = "#1e1e22"
    text: str = "#ffffff"
    font: str = ""


def _rgb(colour: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = colour.strip().lstrip("#")
    try:
        if len(value) == 6:
            return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        pass
    return fallback


def _shade(colour: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """``colour`` a step lighter, or darker if it is already light."""
    step = -amount if _is_light(colour) else amount
    return tuple(max(0, min(255, part + step)) for part in colour)  # type: ignore[return-value]


def _font(path: str, size: int) -> Font:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _is_light(colour: tuple[int, int, int]) -> bool:
    return 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2] >= 140


def _mix(colour: tuple[int, int, int], other: tuple[int, int, int], amount: float):
    return tuple(round(a + (b - a) * amount) for a, b in zip(colour, other))


def _ellipsize(text: str, font: Font, width: int) -> str:
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _fitting_font(path: str, text: str, size: int, width: int, minimum: int = 10) -> Font:
    """The largest font up to ``size`` in which ``text`` fits in ``width``."""
    font = _font(path, size)
    while size > minimum and font.getlength(text) > width:
        size -= 1
        font = _font(path, size)
    return font


def _caption(name: str, year: str, font_path: str, room: int) -> tuple[str, Font | None]:
    """The tag's text (name and/or year) and its font; a long name is shortened."""
    name, year = name.strip(), year.strip()
    full = _SEPARATOR.join(part for part in (name, year) if part)
    if not full:
        return "", None
    font = _fitting_font(font_path, full, _CAPTION_SIZE, room)
    if font.getlength(full) <= room or not name:
        return _ellipsize(full, font, room), font
    tail = _SEPARATOR + year if year else ""
    return _ellipsize(name, font, room - round(font.getlength(tail))) + tail, font


def _checker(size: tuple[int, int], background: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    other = _shade(background, _SHADE)
    for y in range(0, size[1], _CELL):
        for x in range(0, size[0], _CELL):
            if (x // _CELL + y // _CELL) % 2:
                draw.rectangle((x, y, x + _CELL - 1, y + _CELL - 1), fill=other)
    return image


def _draw_logo(canvas: Image.Image, logo: bytes) -> bool:
    try:
        image = Image.open(BytesIO(logo)).convert("RGBA")
    except OSError:
        return False
    box_width, box_height = BANNER_WIDTH - 2 * _MARGIN, _LOGO_HEIGHT - 4
    scale = min(box_width / image.width, box_height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(size, Image.Resampling.LANCZOS)
    offset = ((BANNER_WIDTH - size[0]) // 2, 4 + (box_height - size[1]) // 2)
    canvas.alpha_composite(image, dest=offset)
    return True


def _draw_title(canvas: Image.Image, title: str, style: CardStyle) -> None:
    """The title as text, in up to two lines, when there is no logo."""
    width = BANNER_WIDTH - 2 * _MARGIN
    words = title.split()
    lines = [title]
    if len(words) > 1 and _font(style.font, _TITLE_SIZE).getlength(title) > width:
        half = len(title) / 2
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - half))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    font = _fitting_font(style.font, max(lines, key=len), _TITLE_SIZE, width)
    draw = ImageDraw.Draw(canvas)
    line_height = font.size + 4 if isinstance(font, ImageFont.FreeTypeFont) else 14
    top = (_LOGO_HEIGHT - line_height * len(lines)) // 2 + 4
    colour = _rgb(style.text, (255, 255, 255))
    shadow = (0, 0, 0, 160) if _is_light(colour) else (255, 255, 255, 140)
    for index, line in enumerate(lines):
        x = (BANNER_WIDTH - font.getlength(line)) / 2
        y = top + index * line_height
        draw.text((x + 2, y + 2), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=colour)


def _with_halo(icon: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    """``icon`` with a 1px outline of ``colour``, so dark consoles show on a dark tag."""
    alpha = icon.getchannel("A")
    halo = Image.new("RGBA", (icon.width + 2, icon.height + 2), (*colour, 0))
    for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
        layer = Image.new("RGBA", halo.size, (0, 0, 0, 0))
        layer.paste(Image.new("RGBA", icon.size, (*colour, 200)), (dx, dy), alpha)
        halo.alpha_composite(layer)
    halo.alpha_composite(icon, dest=(1, 1))
    return halo


def _draw_tag(  # pylint: disable=too-many-locals
    canvas: Image.Image, console: str, name: str, year: str, style: CardStyle
) -> None:
    background = _rgb(style.background, (30, 30, 34))
    text = _rgb(style.text, (255, 255, 255))
    fill = (
        _mix(background, (0, 0, 0), 0.65)
        if _is_light(text)
        else _mix(background, (255, 255, 255), 0.7)
    )
    icon = console_icon(console)
    if icon.height > _TAG_HEIGHT - 6:
        ratio = (_TAG_HEIGHT - 6) / icon.height
        icon = icon.resize(
            (max(1, round(icon.width * ratio)), _TAG_HEIGHT - 6), Image.Resampling.NEAREST
        )
    room = BANNER_WIDTH - 2 * _MARGIN - 2 * _TAG_PADDING - icon.width - _TAG_GAP
    caption, font = _caption(name, year, style.font, room)
    icon = _with_halo(icon, _mix(fill, text, 0.45))
    text_width = round(font.getlength(caption)) if font is not None else 0
    width = 2 * _TAG_PADDING + icon.width + (_TAG_GAP + text_width if caption else 0)
    left = (BANNER_WIDTH - width) // 2
    box = (left, _TAG_TOP, left + width - 1, _TAG_TOP + _TAG_HEIGHT - 1)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=_TAG_HEIGHT // 2, fill=fill, outline=text, width=2)
    icon_top = _TAG_TOP + (_TAG_HEIGHT - icon.height) // 2
    canvas.alpha_composite(icon, dest=(left + _TAG_PADDING, icon_top))
    if font is not None:
        x = left + _TAG_PADDING + icon.width + _TAG_GAP
        bbox = draw.textbbox((0, 0), caption, font=font)
        y = _TAG_TOP + (_TAG_HEIGHT - (bbox[3] - bbox[1])) / 2 - bbox[1]
        draw.text((x, y), caption, font=font, fill=text)


def render_card(
    *,
    console: str,
    title: str,
    name: str = "",
    year: str = "",
    logo: bytes | None = None,
    style: CardStyle | None = None,
) -> Image.Image:
    """The 256x128 banner for one game; the tag shows ``name`` and ``year`` if given."""
    style = style or CardStyle()
    background = _rgb(style.background, (30, 30, 34))
    canvas = _checker((BANNER_WIDTH, BANNER_HEIGHT), background).convert("RGBA")
    if not (logo and _draw_logo(canvas, logo)):
        _draw_title(canvas, title, style)
    _draw_tag(canvas, console, name, year, style)
    return canvas.convert("RGB")


def render_card_png(**kwargs: object) -> bytes:
    """:func:`render_card` as PNG data."""
    buffer = BytesIO()
    render_card(**kwargs).save(buffer, format="PNG")  # type: ignore[arg-type]
    return buffer.getvalue()


def render_card_to_file(dest: Path, **kwargs: object) -> Path:
    """:func:`render_card` written to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    render_card(**kwargs).save(dest, format="PNG")  # type: ignore[arg-type]
    return dest
