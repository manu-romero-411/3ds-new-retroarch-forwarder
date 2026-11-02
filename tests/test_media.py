"""Catalog rules, image/audio preparation and the bannertool round trip."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import shutil
import wave
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from forwarder3ds.artwork.compositor import compose_banner_png_bytes
from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.media import prepare_banner_audio, prepare_banner_image, prepare_icon
from forwarder3ds.builder.placeholders import write_silence_wav
from forwarder3ds.builder.toolchain import find_toolchain, run_tool
from forwarder3ds.core import catalog, paths
from forwarder3ds.ctr.assets import decode_banner_audio, decode_banner_image, parse_smdh


def _wav(path: Path, rate: int, channels: int, seconds: float, width: int = 2) -> Path:
    write_silence_wav(path, seconds=seconds, rate=rate, channels=channels, sample_width=width)
    return path


def test_bundled_jingle_is_usable() -> None:
    names = {entry.name: entry for entry in catalog.list_jingles()}
    assert names["smw_coin"].usable


def test_user_folders_are_listed(tmp_path: Path) -> None:
    folder = paths.user_jingles_dir()
    folder.mkdir(parents=True)
    _wav(folder / "mine.wav", 22050, 1, 1.0)
    _wav(folder / "long.wav", 44100, 2, 5.0)
    _wav(folder / "eight_bit.wav", 44100, 1, 1.0, width=1)
    entries = {entry.name: entry for entry in catalog.list_jingles()}
    assert entries["mine"].usable
    assert "lasts" in (entries["long"].problem or "")
    assert "8-bit" in (entries["eight_bit"].problem or "")
    assert catalog.resolve_jingle("mine") == folder / "mine.wav"
    with pytest.raises(catalog.MediaCatalogError):
        catalog.resolve_jingle("long")
    with pytest.raises(catalog.MediaCatalogError):
        catalog.resolve_jingle(str(tmp_path / "missing"))


def test_platform_logo_rules(tmp_path: Path) -> None:
    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    Image.new("RGBA", (256, 128)).save(good)
    Image.new("RGBA", (100, 100)).save(bad)
    assert catalog.validate_platform_logo(good) is None
    assert "100x100" in (catalog.validate_platform_logo(bad) or "")


def test_images_are_stretched(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (300, 50), (255, 0, 0)).save(source)
    frame = tmp_path / "frame.png"
    framed = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    framed.putpixel((0, 0), (0, 255, 0, 255))
    framed.save(frame)
    prepare_icon(source, tmp_path / "icon.png")
    prepare_banner_image(source, tmp_path / "banner.png", frame)
    with Image.open(tmp_path / "icon.png") as icon:
        assert icon.size == (48, 48)
    with Image.open(tmp_path / "banner.png") as banner:
        assert banner.size == (256, 128)
        assert banner.convert("RGB").getpixel((0, 0)) == (0, 255, 0)
        assert banner.convert("RGB").getpixel((100, 60)) == (255, 0, 0)


def test_unreadable_image(tmp_path: Path) -> None:
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    with pytest.raises(BuildError):
        prepare_icon(junk, tmp_path / "out.png")


def test_wav_converted_without_ffmpeg(tmp_path: Path) -> None:
    source = _wav(tmp_path / "mono.wav", 22050, 1, 5.0)
    out = tmp_path / "out.wav"
    prepare_banner_audio(source, out, ffmpeg=None)
    with wave.open(str(out)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (2, 2, 44100)
        assert audio.getnframes() == 3 * 44100


def test_non_wav_needs_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "song.ogg"
    source.write_bytes(b"OggS fake")
    with pytest.raises(BuildError, match="ffmpeg"):
        prepare_banner_audio(source, tmp_path / "out.wav", ffmpeg=None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_eight_bit_wav_through_ffmpeg(tmp_path: Path) -> None:
    source = _wav(tmp_path / "u8.wav", 8000, 1, 1.0, width=1)
    out = tmp_path / "out.wav"
    prepare_banner_audio(source, out, ffmpeg=Path(shutil.which("ffmpeg") or ""))
    with wave.open(str(out)) as audio:
        assert (audio.getnchannels(), audio.getframerate()) == (2, 44100)


def test_composite_banner_size() -> None:
    logo = Image.new("RGBA", (400, 100), (255, 255, 255, 255))
    data = BytesIO()
    logo.save(data, format="PNG")
    composed = compose_banner_png_bytes(None, data.getvalue())
    with Image.open(BytesIO(composed)) as banner:
        assert banner.size == (256, 128)


@pytest.mark.skipif(find_toolchain().bannertool is None, reason="bannertool not available")
def test_bannertool_round_trip(tmp_path: Path) -> None:
    """What bannertool writes, ctr.assets reads back (names, icon, banner, jingle)."""
    bannertool = str(find_toolchain().bannertool)
    source = tmp_path / "art.png"
    Image.new("RGB", (64, 64), (200, 30, 30)).save(source)
    prepare_icon(source, tmp_path / "icon.png")
    prepare_banner_image(source, tmp_path / "banner.png")
    prepare_banner_audio(paths.bundled("jingles/smw_coin.wav"), tmp_path / "audio.wav")
    run_tool(
        [bannertool, "makesmdh", "-s", "Short", "-l", "Long name", "-p", "Pub",
         "-f", "visible,recordusage", "-i", str(tmp_path / "icon.png"),
         "-o", str(tmp_path / "icon.icn")],
        "test",
    )  # fmt: skip
    run_tool(
        [bannertool, "makebanner", "-i", str(tmp_path / "banner.png"),
         "-a", str(tmp_path / "audio.wav"), "-o", str(tmp_path / "banner.bnr")],
        "test",
    )  # fmt: skip
    smdh = parse_smdh((tmp_path / "icon.icn").read_bytes())
    assert (smdh.short_name, smdh.long_name, smdh.publisher) == ("Short", "Long name", "Pub")
    bnr = (tmp_path / "banner.bnr").read_bytes()
    with Image.open(BytesIO(decode_banner_image(bnr))) as banner:
        assert banner.size == (256, 128)
    assert decode_banner_audio(bnr)
