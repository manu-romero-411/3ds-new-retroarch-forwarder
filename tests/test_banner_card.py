"""The default banner: logo or title over a console + year tag."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from forwarder3ds.artwork import banner_card, console_icons
from forwarder3ds.artwork.banner_card import CardStyle, render_card, render_card_png
from forwarder3ds.core.projects import ProjectStore


def _logo() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (400, 100), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("console", ["gb", "snes", "psx", "megadrive", "unknown"])
def test_card_size_and_colours(console: str) -> None:
    style = CardStyle("#102030", "#ffffff")
    image = render_card(console=console, title="Some Game", year="1991", style=style)
    assert image.size == (256, 128)
    assert image.getpixel((0, 0)) == (16, 32, 48)
    assert image.getpixel((8, 0)) != (16, 32, 48)  # the checker pattern


def test_card_logo_replaces_title() -> None:
    with_logo = render_card(console="snes", title="X", logo=_logo())
    assert with_logo.getpixel((128, 40))[0] > 200  # the red logo, centred
    assert render_card_png(console="snes", title="X", logo=b"broken").startswith(b"\x89PNG")


def test_caption_keeps_the_year() -> None:
    caption, font = banner_card._caption(  # pylint: disable=protected-access
        "A Very Long Game Name That Does Not Fit In The Tag At All", "1997", "", 120
    )
    assert font is not None and caption.endswith("… · 1997")
    assert banner_card._caption("", "", "", 120) == ("", None)  # pylint: disable=protected-access


def test_custom_icon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_icons, "custom_icons_dir", lambda: tmp_path)
    Image.new("RGBA", (5, 5), (1, 2, 3, 255)).save(tmp_path / "snes.png")
    assert console_icons.console_icon("snes").size == (5, 5)
    assert console_icons.console_icon("gb").size == (22, 26)


def test_project_tag_fields(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create(tmp_path / "x.gb", "gb", long_name="Tetris", year="1989")
    assert (project.tag_name, project.tag_year) == ("", "1989")
    project.banner_show_name, project.banner_year = True, "1990"
    store.save(project)
    (loaded,) = store.list()
    assert (loaded.tag_name, loaded.tag_year) == ("Tetris", "1990")
