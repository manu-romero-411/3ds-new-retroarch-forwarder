"""Small pure helpers: ROM titles, SD paths, output names, settings, toolchain lookup."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from forwarder3ds.builder.forwarder import (
    default_cia_filename,
    ensure_cia_extension,
    normalize_sd_path,
)
from forwarder3ds.builder.toolchain import find_toolchain
from forwarder3ds.core import paths
from forwarder3ds.core.names import suggest_title
from forwarder3ds.core.sd_card import find_3ds_sd_cards, sd_relative_path
from forwarder3ds.core.settings import Settings, load_settings, masked, save_settings


@pytest.mark.parametrize(
    ("rom", "title"),
    [
        ("roms/snes/Super Mario World (USA) (Rev 1) [!].sfc", "Super Mario World"),
        ("roms\\psx\\Bust-a-Move 4 (Europe).chd", "Bust-a-Move 4"),
        ("roms/snes/", ""),
        ("(Only Tags).zip", "(Only Tags)"),
    ],
)
def test_suggest_title(rom: str, title: str) -> None:
    assert suggest_title(rom) == title


def test_sd_paths() -> None:
    assert normalize_sd_path("sdmc:/roms/a.sfc") == "roms/a.sfc"
    assert normalize_sd_path(" /roms\\b.sfc ") == "roms/b.sfc"
    assert default_cia_filename("roms/snes/Game (USA).sfc") == "Game (USA).cia"
    assert default_cia_filename("") == "forwarder.cia"
    assert ensure_cia_extension(Path("x.v2")) == Path("x.v2.cia")
    assert ensure_cia_extension(Path("x.CIA")) == Path("x.CIA")


def test_sd_card_detection(tmp_path: Path) -> None:
    card = tmp_path / "media" / "user" / "SD"
    (card / "Nintendo 3DS").mkdir(parents=True)
    (tmp_path / "media" / "user" / "USB").mkdir()
    assert find_3ds_sd_cards((str(tmp_path / "media" / "*" / "*"),)) == [card]
    assert sd_relative_path(card, card / "roms" / "a.sfc") == "roms/a.sfc"
    with pytest.raises(ValueError):
        sd_relative_path(card, tmp_path / "elsewhere.sfc")


def test_settings_round_trip() -> None:
    settings = Settings()
    settings.steamgriddb.api_key = "0123456789abcdef"
    settings.general.manufacturer = "Me"
    settings.steamgriddb.nsfw = True
    path = save_settings(settings)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_settings() == settings
    assert masked(settings)["steamgriddb"]["api_key"] == "0123…"


def test_settings_import_from_old_ui() -> None:
    legacy = paths.config_dir().parent / "3ds-new-forwarder-generator" / "ForwarderBuilderUI.conf"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[sgdb]\napi_key=abc\n[paths]\nlast_output_dir=/tmp/out\n", "utf-8")
    settings = load_settings()
    assert settings.steamgriddb.api_key == "abc"
    assert settings.general.output_dir == "/tmp/out"


def test_toolchain_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toolchain = tmp_path / "toolchain"
    for relative in ("bin/makerom", "bin/bannertool", "stub/3ds-forwarder-stub.elf"):
        (toolchain / relative).parent.mkdir(parents=True, exist_ok=True)
        (toolchain / relative).write_bytes(b"")
    (toolchain / "VERSIONS").write_text("makerom=v1\nstub=abc\n", encoding="utf-8")
    monkeypatch.setenv(paths.TOOLCHAIN_ENV, str(toolchain))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    tools = find_toolchain()
    assert tools.complete
    assert tools.makerom == toolchain / "bin" / "makerom"
    assert tools.versions() == {"makerom": "v1", "stub": "abc"}
    assert tools.rsf.is_file()
