#!/usr/bin/env python3
"""Generate PLACEHOLDER assets (icon.png, banner.png, audio.wav).

These let the stub (or any per-game forwarder) be packaged as a .cia with
bannertool/makerom without needing final artwork yet. Uses only the Python
standard library (zlib, struct, wave) so no new dependency is added to the
Docker build image.

Replace the three files with real ones whenever artwork is ready (same
names: icon.png 48x48, banner.png 256x128, audio.wav for the HOME Menu
banner jingle).

Usage::

    python3 tools/generate_placeholder_assets.py [--out-dir DIR]

Also importable, e.g. from ``build_forwarder.py``, to fill in missing
per-game assets on the fly::

    from tools.generate_placeholder_assets import ensure_placeholder_assets
    ensure_placeholder_assets(out_dir)
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

from tools.png_codec import encode_png

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = PROJECT_ROOT / "stub"

# Generic dark-blue placeholder color (RGB).
PLACEHOLDER_COLOR = (0x2E, 0x3A, 0x59)


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    """Write a solid-color 8-bit truecolor PNG."""
    path.write_bytes(encode_png(width, height, bytes(rgb) * (width * height)))


def write_silence_wav(
    path: Path,
    seconds: float = 1.0,
    rate: int = 44100,
    channels: int = 2,
    sample_width: int = 2,
) -> None:
    """Write a short, silent WAV file (valid audio track for bannertool)."""
    frame_count = int(rate * seconds)
    # pylint infers the "wb"-mode return type as Wave_read (it's actually
    # Wave_write); this is a known limitation of wave's type stubs, not a
    # real issue with this code.
    # pylint: disable=no-member
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00" * (frame_count * channels * sample_width))
    # pylint: enable=no-member


def ensure_placeholder_assets(out_dir: Path) -> tuple[Path, Path, Path]:
    """Create icon.png/banner.png/audio.wav in ``out_dir`` if missing.

    Returns the three paths regardless of whether they were just created or
    already existed, so callers can use the result unconditionally.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    icon_path = out_dir / "icon.png"
    banner_path = out_dir / "banner.png"
    audio_path = out_dir / "audio.wav"

    if not icon_path.exists():
        write_png(icon_path, 48, 48, PLACEHOLDER_COLOR)
        print(f"[assets] Generated placeholder: {icon_path}")
    if not banner_path.exists():
        write_png(banner_path, 256, 128, PLACEHOLDER_COLOR)
        print(f"[assets] Generated placeholder: {banner_path}")
    if not audio_path.exists():
        write_silence_wav(audio_path)
        print(f"[assets] Generated placeholder: {audio_path}")

    return icon_path, banner_path, audio_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory to write icon.png/banner.png/audio.wav into "
        "(default: stub/, used by the stub Makefile).",
    )
    args = parser.parse_args()
    ensure_placeholder_assets(args.out_dir)


if __name__ == "__main__":
    main()
