"""Command line: argument handling and the commands that need no toolchain."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from pathlib import Path

import pytest

from forwarder3ds.artwork.steamgriddb import GameCandidate, pick_game
from forwarder3ds.builder.toolchain import find_toolchain
from forwarder3ds.cli import main
from forwarder3ds.ctr.cia import read_game_cia


@pytest.fixture(name="rom")
def fixture_rom(tmp_path: Path) -> Path:
    path = tmp_path / "Game (USA).sfc"
    path.write_bytes(b"\0" * 1024)
    return path


def build_args(rom: Path) -> list[str]:
    return ["build", "--rom", str(rom)]


def test_dry_run_prints_the_title_id(rom: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*build_args(rom), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Title ID:  0x000400000F" in out
    assert "snes9x2005 (snes)" in out
    assert "sdmc:/saves/snes/Game" in out
    assert "Game.cia" in out


def test_dry_run_is_deterministic(rom: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([*build_args(rom), "--dry-run"])
    first = capsys.readouterr().out
    main([*build_args(rom), "--dry-run"])
    assert capsys.readouterr().out == first


def test_missing_arguments() -> None:
    assert main(["build", "--core", "snes9x"]) == 2


def test_unknown_core(rom: Path) -> None:
    assert main([*build_args(rom), "--core", "nope", "--dry-run"]) == 1


def test_cd_images_need_the_console(tmp_path: Path) -> None:
    disc = tmp_path / "Disc.chd"
    disc.write_bytes(b"\0")
    assert main(["build", "--rom", str(disc), "--dry-run"]) == 1
    assert main(["build", "--rom", str(disc), "--console", "psx", "--dry-run"]) == 0


def test_bad_save_folder(rom: Path) -> None:
    assert main([*build_args(rom), "--folder", "a/b", "--dry-run"]) == 1


def test_core_id_rejected(rom: Path) -> None:
    assert main([*build_args(rom), "--unique-id", "BAC07", "--dry-run"]) == 1


def test_listing_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["cores", "psx"]) == 0
    assert "pcsx_rearmed" in capsys.readouterr().out
    assert main(["media"]) == 0
    assert "smw_coin" in capsys.readouterr().out
    assert main(["config"]) == 0
    assert "[steamgriddb]" in capsys.readouterr().out


def test_inspect_rejects_non_cia(tmp_path: Path) -> None:
    junk = tmp_path / "junk.cia"
    junk.write_bytes(b"\0" * 64)
    assert main(["inspect", str(junk)]) == 1


def test_pick_game() -> None:
    one = [GameCandidate(1, "Ristar")]
    many = [GameCandidate(1, "Ristar"), GameCandidate(2, "Ristar 2")]
    ambiguous = [GameCandidate(1, "Sonic"), GameCandidate(2, "Sonic CD")]
    assert pick_game("anything", one) == one[0]
    assert pick_game("ristar", many) == many[0]
    assert pick_game("Sonic 2", ambiguous) is None


@pytest.mark.skipif(
    "snes9x2005" not in find_toolchain().available_cores() or not find_toolchain().complete,
    reason="toolchain with the snes9x2005 base not available",
)
def test_build_and_read_back(rom: Path, tmp_path: Path) -> None:
    """End to end: build a CIA, read it back, rebuild it keeping its Title ID."""
    out = tmp_path / "game.cia"
    args = [*build_args(rom), "--jingle", "smw_coin", "--screen", "custom:360x240", "--smooth",
            "--alt-mode"]  # fmt: skip
    assert main([*args, "-o", str(out)]) == 0
    loaded = read_game_cia(out)
    assert loaded.screen is not None and loaded.screen.smooth
    assert (loaded.screen.mode.value, loaded.screen.width) == ("custom", 360)
    assert (loaded.core, loaded.console, loaded.folder, loaded.long_name) == (
        "snes9x2005",
        "snes",
        "Game",
        "Game",
    )
    assert loaded.rom_name == rom.name
    assert loaded.alt_mode and loaded.alt_bezel_png is None
    assert loaded.extract_rom(tmp_path / "out").read_bytes() == rom.read_bytes()
    assert loaded.icon_png and loaded.banner_png and loaded.audio_wav
    assert main(["build", "--from-cia", str(out), "--short-name", "G"]) == 0
    rebuilt = read_game_cia(out)
    assert rebuilt.unique_id == loaded.unique_id
    assert rebuilt.short_name == "G"
    assert rebuilt.screen == loaded.screen
    assert rebuilt.alt_mode
