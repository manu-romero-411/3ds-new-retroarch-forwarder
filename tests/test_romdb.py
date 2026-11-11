"""libretro database: dat parsing, metadata merge, ROM identification."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest

from forwarder3ds.artwork.libretro import ThumbnailKind, thumbnail_url
from forwarder3ds import cli
from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.injector import make_request, manifest_text, write_romfs
from forwarder3ds.builder.toolchain import Base
from forwarder3ds.core.names import database_title
from forwarder3ds.core.romdb import GameDatabase, MatchKind, identify, parse_dat, rom_crcs
from forwarder3ds.core.systems import SystemCatalog

ROM_DATA = b"TETRIS" * 1000
ROM_CRC = zlib.crc32(ROM_DATA) & 0xFFFFFFFF

MAIN_DAT = f"""clrmamepro (
\tname "Nintendo - Game Boy"
\tversion "2026.10.07"
)

game (
\tname "Tetris (World) (Rev 1)"
\tregion "World"
\trom ( name "Tetris (World) (Rev 1).gb" size {len(ROM_DATA)} crc {ROM_CRC:08X} md5 00 )
)
game (
\tname "Legend of Zelda, The - Link's Awakening (USA, Europe)"
\trom ( name "Zelda.gb" size 1 crc 12345678 )
)
"""
PUBLISHER_DAT = f"""clrmamepro ( name "Nintendo - Game Boy" )
game (
\tcomment "Tetris (World) (Rev 1)"
\tpublisher "Nintendo"
\trom ( crc {ROM_CRC:08X} )
)
"""
YEAR_DAT = f"""clrmamepro ( name "Nintendo - Game Boy" )
game (
\tcomment "Tetris (World) (Rev 1)"
\treleaseyear "1989"
\trom ( crc {ROM_CRC:08X} )
)
"""
DISC_DAT = """clrmamepro ( name "Sony - PlayStation" )
game (
\tname "Castlevania - Symphony of the Night (USA)"
\tserial "SLUS-00067"
\trom ( name "Castlevania - Symphony of the Night (USA) (Track 1).bin" size 1 crc AAAAAAAA )
\trom ( name "Castlevania - Symphony of the Night (USA) (Track 2).bin" size 1 crc BBBBBBBB )
)
game (
\tname "Castlevania - Symphony of the Night (Europe)"
\trom ( name "x.bin" size 1 crc CCCCCCCC )
)
"""


@pytest.fixture(name="database")
def fixture_database() -> GameDatabase:
    return GameDatabase.from_dats(MAIN_DAT, {"publisher": PUBLISHER_DAT, "releaseyear": YEAR_DAT})


@pytest.fixture(name="systems")
def fixture_systems() -> SystemCatalog:
    return SystemCatalog.load()


def test_parse_dat_reads_games_and_roms() -> None:
    games = parse_dat(DISC_DAT)
    assert [game["name"] for game in games] == [
        "Castlevania - Symphony of the Night (USA)",
        "Castlevania - Symphony of the Night (Europe)",
    ]
    assert len(games[0]["rom"]) == 2
    assert games[0]["serial"] == "SLUS-00067"


def test_metadata_is_merged_by_crc(database: GameDatabase) -> None:
    tetris = database.by_crc(ROM_CRC)
    assert tetris is not None
    assert (tetris.title, tetris.publisher, tetris.year) == ("Tetris", "Nintendo", "1989")
    assert database.by_crc(0xDEADBEEF) is None


def test_search_and_titles(database: GameDatabase) -> None:
    hits = database.search("zelda link")
    assert [game.title for game in hits] == ["The Legend of Zelda - Link's Awakening"]
    assert len(database.search("")) == 2
    assert database_title("Dr. Mario (World) (Rev 1)") == "Dr. Mario"


def test_identify_cartridge(tmp_path: Path, database: GameDatabase, systems: SystemCatalog) -> None:
    rom = tmp_path / "whatever.gb"
    rom.write_bytes(ROM_DATA)
    found = identify(rom, systems.require("gb"), database)
    assert found.kind is MatchKind.CRC and found.crc == ROM_CRC
    assert found.game is not None and found.game.name == "Tetris (World) (Rev 1)"

    hack = tmp_path / "Tetris (Hack).gb"
    hack.write_bytes(ROM_DATA + b"!")
    found = identify(hack, systems.require("gb"), database)
    assert found.kind is MatchKind.NONE and not found.matched


def test_identify_zipped_rom(
    tmp_path: Path, database: GameDatabase, systems: SystemCatalog
) -> None:
    archive = tmp_path / "Tetris (World) (Rev 1).zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("Tetris (World) (Rev 1).gb", ROM_DATA)
        zipped.writestr("readme.txt", "hello")
    assert systems.guess(archive) == systems.require("gb")
    found = identify(archive, systems.require("gb"), database)
    assert found.kind is MatchKind.CRC and found.crc == ROM_CRC

    request = make_request(rom=archive, long_name="Tetris", output=tmp_path / "t.cia")
    assert (request.console, request.rom_name, request.content_name) == (
        "gb",
        "Tetris (World) (Rev 1).gb",
        "game.gb",
    )
    base = Base("gambatte", tmp_path / "x.elf", "64MB", "Legacy", False, None, {})
    romfs = write_romfs(tmp_path / "scratch", request, base)
    assert (romfs / "game.gb").read_bytes() == ROM_DATA
    assert 'rom_name = "Tetris (World) (Rev 1).gb"' in manifest_text(request)


def test_zip_with_several_roms_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "two.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a.gb", b"a")
        zipped.writestr("b.gb", b"b")
    with pytest.raises(BuildError, match="several ROMs"):
        make_request(rom=archive, long_name="Two", output=tmp_path / "t.cia", console="gb")


def test_headers_are_skipped(tmp_path: Path) -> None:
    nes = tmp_path / "game.nes"
    nes.write_bytes(b"NES\x1a" + b"\0" * 12 + ROM_DATA)
    assert rom_crcs(nes)[1] == ROM_CRC
    snes = tmp_path / "game.smc"
    data = b"\1" * 1024
    snes.write_bytes(b"\0" * 512 + data)
    assert rom_crcs(snes)[-1] == zlib.crc32(data) & 0xFFFFFFFF


def test_identify_disc_by_name(tmp_path: Path, systems: SystemCatalog) -> None:
    database = GameDatabase.from_dats(DISC_DAT)
    disc = tmp_path / "Castlevania - Symphony of the Night (USA).chd"
    disc.write_bytes(b"\0")
    found = identify(disc, systems.require("psx"), database)
    assert found.kind is MatchKind.NAME
    assert found.game is not None and found.game.name.endswith("(USA)")
    assert len(found.candidates) == 2


def test_thumbnail_url(systems: SystemCatalog) -> None:
    url = thumbnail_url(systems.require("gb"), "Q*bert & Co: Test (USA)", ThumbnailKind.TITLE)
    assert url == (
        "https://thumbnails.libretro.com/Nintendo%20-%20Game%20Boy/Named_Titles/"
        "Q_bert%20_%20Co_%20Test%20%28USA%29.png"
    )


def test_cli_identify(
    tmp_path: Path,
    database: GameDatabase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "load_database", lambda _system, _refresh=False: database)
    rom = tmp_path / "t.gb"
    rom.write_bytes(ROM_DATA)
    assert cli.main(["identify", str(rom)]) == 0
    out = capsys.readouterr().out
    assert "Tetris (World) (Rev 1)" in out and "Nintendo" in out and "1989" in out
    assert cli.main(["build", "--rom", str(rom), "--identify", "--dry-run"]) == 0
    assert "sdmc:/saves/gb/Tetris" in capsys.readouterr().out
    unknown = tmp_path / "u.gb"
    unknown.write_bytes(b"x")
    assert cli.main(["identify", str(unknown)]) == 3
