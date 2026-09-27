"""Prepare icon/banner/audio assets to the exact spec bannertool expects.

3DS SMDH icons and banners must be an exact pixel size, and the banner
jingle must be a short, specifically-encoded WAV. This module normalizes
whatever the user hands in (any resolution, any common audio format) into
that spec using ``ffmpeg``, which is already part of the project's Docker
image (see ``Dockerfile``).

Reference for the constants below: the SMDH/BNR sizes are fixed by the 3DS
format itself; the audio spec (16-bit PCM, 44.1 kHz, stereo, a few seconds
at most) is the combination used across published bannertool workflows and
RetroArch's own 3DS packaging (``pkg/ctr/assets/silent.wav``), not a value
this project invented.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.generate_placeholder_assets import write_silence_wav

ICON_WIDTH = 48
ICON_HEIGHT = 48
BANNER_WIDTH = 256
BANNER_HEIGHT = 128

AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS = 2
AUDIO_CODEC = "pcm_s16le"  # 16-bit PCM
MAX_AUDIO_SECONDS = 3.0


def _run_ffmpeg(cmd: list[str], context: str) -> None:
    """Run an ffmpeg command, exiting with its stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg failed while {context}.", file=sys.stderr)
        print(f"    stderr: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def resize_image_stretch(src: Path, dst: Path, width: int, height: int) -> None:
    """Resize ``src`` to exactly ``width``x``height``, stretching (no crop).

    ffmpeg's ``scale`` filter maps directly onto the target dimensions
    unless told to preserve aspect ratio, which is exactly the "stretch,
    don't crop" behaviour wanted here.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"scale={width}:{height}",
        "-frames:v",
        "1",
        str(dst),
    ]
    _run_ffmpeg(cmd, f"resizing {src} to {width}x{height}")


def prepare_icon(src: Path, dst: Path) -> None:
    """Resize ``src`` into a 48x48 SMDH icon at ``dst``."""
    resize_image_stretch(src, dst, ICON_WIDTH, ICON_HEIGHT)


def prepare_banner_image(src: Path, dst: Path) -> None:
    """Resize ``src`` into a 256x128 banner image at ``dst``."""
    resize_image_stretch(src, dst, BANNER_WIDTH, BANNER_HEIGHT)


def prepare_banner_audio(src: Path | None, dst: Path) -> None:
    """Write a bannertool-ready WAV at ``dst``.

    With no ``src``, writes a short silent track (already in spec). With a
    source file, re-encodes it to 16-bit PCM / 44.1 kHz / stereo and trims
    it to ``MAX_AUDIO_SECONDS``, regardless of its original format, sample
    rate or channel layout.
    """
    if src is None:
        write_silence_wav(dst, seconds=1.0, rate=AUDIO_SAMPLE_RATE, channels=AUDIO_CHANNELS)
        return

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        str(AUDIO_CHANNELS),
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-acodec",
        AUDIO_CODEC,
        "-t",
        str(MAX_AUDIO_SECONDS),
        str(dst),
    ]
    _run_ffmpeg(cmd, f"converting banner audio from {src}")
