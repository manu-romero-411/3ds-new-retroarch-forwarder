"""Bring icon, banner and jingle to the exact spec ``bannertool`` expects.

* Images (any size, any format Pillow reads) are **stretched**, never
  cropped, to 48x48 (icon), 256x128 (banner) and 400x240 (bezel, the top
  screen). A platform frame, if any, is drawn over the resized banner.
* Audio becomes a 16-bit PCM, 44.1 kHz, stereo WAV of at most 3 seconds.
  A 16-bit PCM WAV (every catalog jingle) is converted in pure Python;
  any other format is handed to ``ffmpeg``, which is then required.
"""

from __future__ import annotations

import array
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.placeholders import write_silence_wav
from forwarder3ds.ctr.formats import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH,
    BANNER_HEIGHT,
    BANNER_WIDTH,
    ICON_HEIGHT,
    ICON_WIDTH,
    MAX_AUDIO_SECONDS,
)

_RESAMPLE = Image.Resampling.BICUBIC
#: The 3DS top screen; the bezel covers it whole.
BEZEL_WIDTH, BEZEL_HEIGHT = 400, 240
BOTTOM_WIDTH, BOTTOM_HEIGHT = 320, 240


def _open_image(src: Path) -> Image.Image:
    try:
        with Image.open(src) as image:
            return image.convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise BuildError(f"Cannot read the image {src}: {exc}") from exc


def resize_image_stretch(src: Path, dst: Path, width: int, height: int) -> None:
    """Resize ``src`` to exactly ``width``x``height`` (stretching, no crop) as a PNG."""
    _open_image(src).resize((width, height), _RESAMPLE).save(dst, format="PNG")


def prepare_icon(src: Path, dst: Path) -> None:
    """Resize ``src`` into a 48x48 SMDH icon at ``dst``."""
    resize_image_stretch(src, dst, ICON_WIDTH, ICON_HEIGHT)


def prepare_banner_image(src: Path, dst: Path, overlay: Path | None = None) -> None:
    """Resize ``src`` into a 256x128 banner at ``dst``, with ``overlay`` drawn on top.

    ``overlay`` is a platform frame (a 256x128 PNG with transparency); the
    blend is a plain "source over".
    """
    banner = _open_image(src).resize((BANNER_WIDTH, BANNER_HEIGHT), _RESAMPLE)
    if overlay is not None:
        frame = _open_image(overlay)
        if frame.size != banner.size:
            frame = frame.resize(banner.size, _RESAMPLE)
        banner.alpha_composite(frame)
    banner.save(dst, format="PNG")


def prepare_bezel(src: Path, dst: Path) -> None:
    """Resize ``src`` into a 400x240 PNG at ``dst``, keeping its transparency.

    The game shows through the transparent part: a 4:3 picture is 320x240 in
    the middle of the screen, leaving 40-pixel bands on each side.
    """
    resize_image_stretch(src, dst, BEZEL_WIDTH, BEZEL_HEIGHT)


def prepare_bottom_image(src: Path, dst: Path) -> None:
    """Stretch ``src`` over the 320x240 touch screen, as an opaque PNG at ``dst``."""
    flat = Image.new("RGBA", (BOTTOM_WIDTH, BOTTOM_HEIGHT), (0, 0, 0, 255))
    flat.alpha_composite(_open_image(src).resize(flat.size, _RESAMPLE))
    flat.convert("RGB").save(dst, format="PNG")


def prepare_flat_bezel(src: Path | None, dst: Path) -> None:
    """Like :func:`prepare_bezel`, but opaque: the bezel over black (black if ``src`` is None).

    For emulators that draw a plain picture behind the game (snes9x_3ds keeps
    it as RGB565, without transparency).
    """
    flat = Image.new("RGBA", (BEZEL_WIDTH, BEZEL_HEIGHT), (0, 0, 0, 255))
    if src is not None:
        flat.alpha_composite(_open_image(src).resize(flat.size, _RESAMPLE))
    flat.convert("RGB").save(dst, format="PNG")


# ── Audio ────────────────────────────────────────────────────────────────


def _read_pcm16(src: Path) -> tuple[array.array, int, int] | None:
    """``(samples, channels, rate)`` of a 16-bit PCM WAV, or ``None`` for anything else."""
    try:
        with wave.open(str(src), "rb") as audio:
            if audio.getsampwidth() != AUDIO_SAMPLE_WIDTH or audio.getnchannels() not in (1, 2):
                return None
            channels, rate = audio.getnchannels(), audio.getframerate()
            frames = audio.readframes(audio.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % AUDIO_SAMPLE_WIDTH])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples, channels, rate


def _to_stereo(samples: array.array, channels: int) -> array.array:
    if channels == AUDIO_CHANNELS:
        return samples
    stereo = array.array("h", bytes(len(samples) * 2 * AUDIO_SAMPLE_WIDTH))
    stereo[0::2] = samples
    stereo[1::2] = samples
    return stereo


def _resample(samples: array.array, rate: int) -> array.array:
    """Linear-interpolation resampling of interleaved stereo ``samples`` to 44.1 kHz."""
    if rate == AUDIO_SAMPLE_RATE:
        return samples
    left, right = samples[0::2], samples[1::2]
    count = len(left)
    out_count = int(count * AUDIO_SAMPLE_RATE / rate)
    out = array.array("h", bytes(out_count * 2 * AUDIO_SAMPLE_WIDTH))
    step = rate / AUDIO_SAMPLE_RATE
    for index in range(out_count):
        position = index * step
        base = int(position)
        nxt = min(base + 1, count - 1)
        frac = position - base
        out[2 * index] = round(left[base] + (left[nxt] - left[base]) * frac)
        out[2 * index + 1] = round(right[base] + (right[nxt] - right[base]) * frac)
    return out


def _write_pcm16(dst: Path, samples: array.array) -> None:
    if sys.byteorder == "big":
        samples = array.array("h", samples)
        samples.byteswap()
    # pylint: disable=no-member  # wave.open(..., "wb") returns a Wave_write
    with wave.open(str(dst), "wb") as out:
        out.setnchannels(AUDIO_CHANNELS)
        out.setsampwidth(AUDIO_SAMPLE_WIDTH)
        out.setframerate(AUDIO_SAMPLE_RATE)
        out.writeframes(samples.tobytes())
    # pylint: enable=no-member


def _convert_with_ffmpeg(src: Path, dst: Path, ffmpeg: Path | None) -> None:
    if ffmpeg is None:
        raise BuildError(
            f"{src.name} is not a 16-bit PCM WAV, so ffmpeg is needed to convert it, "
            "and ffmpeg was not found. Install it, or use a WAV jingle."
        )
    cmd = [
        str(ffmpeg), "-y", "-loglevel", "error", "-i", str(src),
        "-ac", str(AUDIO_CHANNELS), "-ar", str(AUDIO_SAMPLE_RATE),
        "-acodec", "pcm_s16le", "-t", str(MAX_AUDIO_SECONDS), str(dst),
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BuildError(f"ffmpeg could not convert {src.name}: {result.stderr.strip()}")


def prepare_banner_audio(src: Path | None, dst: Path, ffmpeg: Path | None = None) -> None:
    """Write a bannertool-ready WAV at ``dst``.

    With no ``src``, a short silent track. Otherwise ``src`` is converted to
    16-bit PCM / 44.1 kHz / stereo and trimmed to ``MAX_AUDIO_SECONDS``.
    """
    if src is None:
        write_silence_wav(dst)
        return
    pcm = _read_pcm16(src)
    if pcm is None:
        _convert_with_ffmpeg(src, dst, ffmpeg)
        return
    samples, channels, rate = pcm
    if not samples or not rate:
        raise BuildError(f"{src.name} contains no audio.")
    stereo = _resample(_to_stereo(samples, channels), rate)
    limit = int(MAX_AUDIO_SECONDS * AUDIO_SAMPLE_RATE) * AUDIO_CHANNELS
    _write_pcm16(dst, stereo[:limit])
