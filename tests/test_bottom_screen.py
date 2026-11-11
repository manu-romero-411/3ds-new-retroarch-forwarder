"""The Virtual Console style touch screen picture."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFont

from forwarder3ds.artwork.bottom_screen import (
    LANGUAGE_NAMES,
    MESSAGES,
    BottomScreenStyle,
    house_icon,
    render_bottom_screen,
    render_bottom_screen_png,
    wrap,
)


def test_every_language_has_a_name_and_a_menu_placeholder() -> None:
    assert set(MESSAGES) == set(LANGUAGE_NAMES)
    assert all("{menu}" in message for message, _footer in MESSAGES.values())


def test_render_size_and_text() -> None:
    image = render_bottom_screen("RetroArch")
    assert image.size == (320, 240)
    assert image.tobytes() == render_bottom_screen("RetroArch").tobytes()  # deterministic
    # some text is drawn in the band and in the footer
    band = image.crop((0, 80, 320, 140)).convert("L")
    footer = image.crop((0, 210, 320, 236)).convert("L")
    assert band.getextrema()[1] > 60 and footer.getextrema()[1] > 60


def test_unknown_language_falls_back_to_english() -> None:
    english = render_bottom_screen("snes9x", BottomScreenStyle("en"))
    unknown = render_bottom_screen("snes9x", BottomScreenStyle("xx"))
    assert english.tobytes() == unknown.tobytes()


def test_png_output() -> None:
    with Image.open(BytesIO(render_bottom_screen_png("RetroArch"))) as image:
        assert image.size == (320, 240) and image.mode == "RGB"


def test_wrap_keeps_words_and_latin_runs() -> None:
    font = ImageFont.load_default(16)
    text = "Tap the Touch Screen to go to the RetroArch menu."
    lines = wrap(text, font, 200)
    assert len(lines) > 1 and " ".join(lines).split() == text.split()
    japanese = wrap("タッチするとsnes9xメニューに移ります。", font, 60)
    assert any("snes9x" in line for line in japanese)


def test_house_icon_has_a_window() -> None:
    icon = house_icon(32, (255, 255, 255, 255))
    alpha = icon.getchannel("A")
    assert alpha.getpixel((16, 21)) < 64  # the window
    assert alpha.getpixel((16, 10)) > 192  # the roof
