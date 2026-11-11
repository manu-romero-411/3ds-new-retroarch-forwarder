"""Fonts picked by name and found as files."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from forwarder3ds.core import fonts
from forwarder3ds.core.fonts import FontChoice, find_font, font_path, forget_fonts
from forwarder3ds.core.settings import load_settings, save_settings


def _make_font(path: Path, family: str, style: str) -> Path:
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef"])
    builder.setupCharacterMap({})
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": style})
    builder.setupOS2()
    builder.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(str(path))
    return path


@pytest.fixture(name="font_dir")
def _font_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "fonts"
    monkeypatch.setattr(fonts, "font_dirs", lambda: [directory])
    monkeypatch.setattr(fonts.shutil, "which", lambda _name: None)  # no fontconfig
    forget_fonts()
    yield directory
    forget_fonts()


def test_find_by_family_and_style(font_dir: Path) -> None:
    regular = _make_font(font_dir / "test-regular.ttf", "Test Sans", "Regular")
    bold = _make_font(font_dir / "sub" / "test-bold.ttf", "Test Sans", "Bold")
    assert find_font("Test Sans", "Bold") == bold
    assert find_font("test sans", "Regular") == regular
    assert find_font("Test Sans", "Black") == regular  # unknown style: the regular one
    assert find_font("Missing Font") is None
    assert font_path(FontChoice("Missing Font")) == ""


def test_file_wins(font_dir: Path, tmp_path: Path) -> None:
    loose = _make_font(tmp_path / "loose.otf", "Loose", "DB")
    _make_font(font_dir / "other.ttf", "Loose", "DB")
    assert font_path(FontChoice("Loose", "DB", str(loose))) == str(loose)
    assert font_path(FontChoice()) == "" and FontChoice().builtin
    assert FontChoice("Loose", "DB").describe() == "Loose DB"


def test_settings_keep_the_choice(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "settings.ini")
    settings.bottom_screen.font_choice = FontChoice("FOT-Rodin NTLG Pro", "DB", "/x/rodin.otf")
    path = save_settings(settings, tmp_path / "settings.ini")
    again = load_settings(path)
    assert again.bottom_screen.font_choice == FontChoice("FOT-Rodin NTLG Pro", "DB", "/x/rodin.otf")
    assert again.banner.font_choice.builtin
