"""Placeholder icon, banner and silent jingle.

Used whenever a forwarder has no icon or banner of its own, and by the
stub's ``make cia`` target (a loose stub CIA for testing). Standard library
only, so it also runs from the stub Makefile without any dependency::

    PYTHONPATH=src python3 -m forwarder3ds.builder.placeholders --out-dir stub
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

from forwarder3ds.ctr.formats import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH,
    BANNER_HEIGHT,
    BANNER_WIDTH,
    ICON_HEIGHT,
    ICON_WIDTH,
    PLACEHOLDER_COLOR,
)
from forwarder3ds.ctr.png import encode_png


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    """Write a solid-colour 8-bit truecolor PNG."""
    path.write_bytes(encode_png(width, height, bytes(rgb) * (width * height)))


def write_silence_wav(
    path: Path,
    seconds: float = 1.0,
    rate: int = AUDIO_SAMPLE_RATE,
    channels: int = AUDIO_CHANNELS,
    sample_width: int = AUDIO_SAMPLE_WIDTH,
) -> None:
    """Write a short, silent WAV file (a valid jingle for bannertool)."""
    frame_count = int(rate * seconds)
    # pylint infers wave.open(..., "wb") as Wave_read; it returns a Wave_write.
    # pylint: disable=no-member
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00" * (frame_count * channels * sample_width))
    # pylint: enable=no-member


def ensure_placeholder_assets(out_dir: Path) -> tuple[Path, Path, Path]:
    """Create ``icon.png``, ``banner.png`` and ``audio.wav`` in ``out_dir`` if missing.

    Existing files are kept, so real artwork dropped in under those names
    is never overwritten. Returns the three paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    icon_path = out_dir / "icon.png"
    banner_path = out_dir / "banner.png"
    audio_path = out_dir / "audio.wav"
    if not icon_path.exists():
        write_png(icon_path, ICON_WIDTH, ICON_HEIGHT, PLACEHOLDER_COLOR)
    if not banner_path.exists():
        write_png(banner_path, BANNER_WIDTH, BANNER_HEIGHT, PLACEHOLDER_COLOR)
    if not audio_path.exists():
        write_silence_wav(audio_path)
    return icon_path, banner_path, audio_path


def main() -> None:
    """Command line entry point (used by ``stub/Makefile``)."""
    parser = argparse.ArgumentParser(description="Write placeholder icon/banner/audio files.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Destination folder")
    args = parser.parse_args()
    for path in ensure_placeholder_assets(args.out_dir):
        print(path)


if __name__ == "__main__":
    main()
