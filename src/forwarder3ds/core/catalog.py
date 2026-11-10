"""Catalog of ready-made banner jingles and platform frames, plus their rules.

Two kinds of drop-in assets give a game CIA personality:

* jingles -- the tune that plays when the icon is selected on the HOME menu
  (banner audio);
* platform logos -- transparent frames drawn *over* the finished banner,
  e.g. a console logo.

Each kind is read from the folder bundled with the program and from the
user's own folder (``~/.local/share/3ds-forwarder/jingles`` and
``.../platform_logos``), in that order. Every file is validated against the
rules below, and whatever the user picks elsewhere on disk is held to the
same rules via :func:`validate_jingle` and :func:`validate_platform_logo`.
Frontends list the catalog with :func:`list_jingles` / :func:`list_platform_logos`
and show the ``problem`` of entries that fail instead of hiding them; the
CLI resolves a name or path with :func:`resolve_jingle` /
:func:`resolve_platform_logo`. Standard library only.
"""

from __future__ import annotations

import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from forwarder3ds.core import paths
from forwarder3ds.ctr.formats import BANNER_HEIGHT, BANNER_WIDTH, MAX_AUDIO_SECONDS
from forwarder3ds.ctr.png import png_dimensions

JINGLE_EXTENSION = ".wav"
PLATFORM_LOGO_EXTENSION = ".png"

JINGLE_RULES = f"WAV, 16-bit PCM, mono or stereo, at most {MAX_AUDIO_SECONDS:g} seconds."
PLATFORM_LOGO_RULES = f"PNG of exactly {BANNER_WIDTH}x{BANNER_HEIGHT} pixels (with transparency)."

Validator = Callable[[Path], "str | None"]


def jingle_dirs() -> tuple[Path, ...]:
    """Folders searched for jingles: the bundled one, then the user's."""
    return (paths.bundled("jingles"), paths.user_jingles_dir())


def platform_logo_dirs() -> tuple[Path, ...]:
    """Folders searched for platform logos: the bundled one, then the user's."""
    return (paths.bundled("platform_logos"), paths.user_platform_logos_dir())


_JINGLE_SAMPLE_WIDTH_BYTES = 2
_JINGLE_MAX_CHANNELS = 2
# Float rounding slack so a jingle of exactly the limit is not rejected.
_DURATION_TOLERANCE_SECONDS = 1e-3


class MediaCatalogError(ValueError):
    """A requested jingle/frame does not exist or breaks the rules."""


@dataclass(frozen=True)
class CatalogEntry:
    """One file of a catalog folder.

    ``problem`` is ``None`` for a usable file, otherwise why it is not.
    """

    name: str
    path: Path
    problem: str | None = None

    @property
    def usable(self) -> bool:
        """Whether the file meets the rules."""
        return self.problem is None


def _jingle_format_problem(channels: int, width: int, frames: int, rate: int) -> str | None:
    """Check the audio properties of a jingle against :data:`JINGLE_RULES`."""
    if width != _JINGLE_SAMPLE_WIDTH_BYTES:
        return f"It is {width * 8}-bit. Required: {JINGLE_RULES}"
    if not 1 <= channels <= _JINGLE_MAX_CHANNELS:
        return f"It has {channels} channels. Required: {JINGLE_RULES}"
    if not frames or not rate:
        return "It contains no audio."
    seconds = frames / rate
    if seconds > MAX_AUDIO_SECONDS + _DURATION_TOLERANCE_SECONDS:
        return f"It lasts {seconds:.1f} s. Required: {JINGLE_RULES}"
    return None


def validate_jingle(path: Path) -> str | None:
    """Why ``path`` cannot be used as a banner jingle, or ``None`` if it can."""
    try:
        with wave.open(str(path), "rb") as audio:
            properties = (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getnframes(),
                audio.getframerate(),
            )
    except (wave.Error, EOFError):
        return f"Not a PCM WAV file. Required: {JINGLE_RULES}"
    except OSError as exc:
        return f"Cannot be read: {exc.strerror or exc}"
    return _jingle_format_problem(*properties)


def validate_platform_logo(path: Path) -> str | None:
    """Why ``path`` cannot be used as a platform frame, or ``None`` if it can."""
    try:
        width, height = png_dimensions(path)
    except ValueError:
        return f"Not a PNG file. Required: {PLATFORM_LOGO_RULES}"
    except OSError as exc:
        return f"Cannot be read: {exc.strerror or exc}"
    if (width, height) != (BANNER_WIDTH, BANNER_HEIGHT):
        return f"It is {width}x{height}. Required: {PLATFORM_LOGO_RULES}"
    return None


def _list_folders(
    directories: Sequence[Path], extension: str, validate: Validator
) -> list[CatalogEntry]:
    """Every ``*<extension>`` file directly inside ``directories``, folder by folder.

    Within a folder entries are sorted by name. A missing folder is not an
    error: it just has no entries.
    """
    entries: list[CatalogEntry] = []
    for directory in directories:
        try:
            files = [
                item
                for item in directory.iterdir()
                if item.is_file() and item.suffix.lower() == extension
            ]
        except OSError:
            continue
        files.sort(key=lambda item: (item.stem.lower(), item.name))
        entries.extend(CatalogEntry(item.stem, item, validate(item)) for item in files)
    return entries


def list_jingles(directories: Sequence[Path] | None = None) -> list[CatalogEntry]:
    """The ``.wav`` jingles, each checked against :data:`JINGLE_RULES`."""
    return _list_folders(
        jingle_dirs() if directories is None else directories, JINGLE_EXTENSION, validate_jingle
    )


def list_platform_logos(directories: Sequence[Path] | None = None) -> list[CatalogEntry]:
    """The ``.png`` frames, each checked against :data:`PLATFORM_LOGO_RULES`."""
    return _list_folders(
        platform_logo_dirs() if directories is None else directories,
        PLATFORM_LOGO_EXTENSION,
        validate_platform_logo,
    )


def _resolve(value: str, entries: list[CatalogEntry], validate: Validator, kind: str) -> Path:
    """Turn a CLI value -- an existing file, or a catalog name -- into a valid path."""
    candidate = Path(value).expanduser()
    if candidate.is_file():
        path = candidate
    else:
        wanted = value.lower()
        match = next((e for e in entries if wanted in (e.name.lower(), e.path.name.lower())), None)
        if match is None:
            available = ", ".join(e.name for e in entries if e.usable) or "none"
            raise MediaCatalogError(
                f"No {kind} named '{value}' and no such file. Available: {available}."
            )
        path = match.path

    problem = validate(path)
    if problem:
        raise MediaCatalogError(f"{kind.capitalize()} '{path.name}': {problem}")
    return path


def resolve_jingle(value: str, directories: Sequence[Path] | None = None) -> Path:
    """Path of the jingle ``value`` names (a file path, or a name in the catalog).

    Raises :class:`MediaCatalogError` if it does not exist or breaks the rules.
    """
    return _resolve(value, list_jingles(directories), validate_jingle, "jingle")


def resolve_platform_logo(value: str, directories: Sequence[Path] | None = None) -> Path:
    """Path of the frame ``value`` names (a file path, or a name in the catalog).

    Raises :class:`MediaCatalogError` if it does not exist or breaks the rules.
    """
    return _resolve(
        value, list_platform_logos(directories), validate_platform_logo, "platform logo"
    )
