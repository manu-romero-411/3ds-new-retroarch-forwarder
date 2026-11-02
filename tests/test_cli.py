"""Command line: argument handling and the commands that need no toolchain."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from pathlib import Path

import pytest

from forwarder3ds.artwork.steamgriddb import GameCandidate, pick_game
from forwarder3ds.builder.toolchain import find_toolchain
from forwarder3ds.cli import main
from forwarder3ds.ctr.cia import read_forwarder_cia

BUILD = [
    "build",
    "--core",
    "snes9x2005",
    "--rom",
    "roms/snes/Game (USA).sfc",
    "--long-name",
    "Game",
]


def test_dry_run_prints_the_title_id(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BUILD, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Title ID:  0x000400000F" in out
    assert "Game (USA).cia" in out


def test_dry_run_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    main([*BUILD, "--dry-run"])
    first = capsys.readouterr().out
    main([*BUILD, "--dry-run"])
    assert capsys.readouterr().out == first


def test_missing_arguments() -> None:
    assert main(["build", "--core", "snes9x"]) == 2


def test_unknown_core() -> None:
    assert main(["build", "--core", "nope", "--rom", "a.sfc", "--long-name", "A", "--dry-run"]) == 1


def test_core_id_rejected() -> None:
    assert main([*BUILD, "--unique-id", "BAC07", "--dry-run"]) == 1


def test_listing_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["cores", "pcsx"]) == 0
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


@pytest.mark.skipif(not find_toolchain().complete, reason="toolchain (with stub) not available")
def test_build_and_read_back(tmp_path: Path) -> None:
    """End to end: build a CIA, read it back, rebuild it keeping its Title ID."""
    out = tmp_path / "game.cia"
    assert main([*BUILD, "--jingle", "smw_coin", "-o", str(out)]) == 0
    loaded = read_forwarder_cia(out)
    assert (loaded.core, loaded.rom_path, loaded.long_name) == (
        "snes9x2005",
        "roms/snes/Game (USA).sfc",
        "Game",
    )
    assert loaded.icon_png and loaded.banner_png and loaded.audio_wav
    assert main(["build", "--from-cia", str(out), "--short-name", "G"]) == 0
    rebuilt = read_forwarder_cia(out)
    assert rebuilt.unique_id == loaded.unique_id
    assert rebuilt.short_name == "G"
