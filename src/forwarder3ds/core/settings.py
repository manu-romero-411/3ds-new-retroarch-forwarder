"""User settings, stored as INI in the user's config directory.

The model is plain dataclasses with no I/O; :func:`load_settings` and
:func:`save_settings` are the only functions that touch the file. It holds
the SteamGridDB API key, so it is written with ``0600`` permissions.

Settings of the first, unpackaged UI (a ``QSettings`` file under
``~/.config/3ds-new-forwarder-generator``) are imported on first run.
"""

from __future__ import annotations

import configparser
import dataclasses
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from forwarder3ds.core import paths
from forwarder3ds.core.fonts import FontChoice
from forwarder3ds.core.logs import get_logger

_log = get_logger("settings")

DEFAULT_MANUFACTURER = "Homebrew"
_LEGACY_UI_SETTINGS = Path("3ds-new-forwarder-generator") / "ForwarderBuilderUI.conf"


@dataclass
class GeneralSettings:
    """Defaults for new games and where files go."""

    manufacturer: str = DEFAULT_MANUFACTURER
    output_dir: str = ""
    registry: str = ""

    @property
    def output_path(self) -> Path:
        """Folder offered when saving a new ``.cia`` (home directory if unset)."""
        return Path(self.output_dir).expanduser() if self.output_dir else Path.home()

    @property
    def registry_path(self) -> Path:
        """Title ID registry file."""
        return Path(self.registry).expanduser() if self.registry else paths.default_registry_file()


@dataclass
class SteamGridDBSettings:
    """SteamGridDB account and search filters."""

    api_key: str = ""
    nsfw: bool = False
    humor: bool = True

    @property
    def configured(self) -> bool:
        """True if an API key is set."""
        return bool(self.api_key)


@dataclass
class ToolchainSettings:
    """Explicit tool locations; empty means "find it" (see ``builder.toolchain``)."""

    makerom: str = ""
    bannertool: str = ""
    bases: str = ""
    ffmpeg: str = ""


@dataclass
class _FontSettings:
    """A font picked by name, with its file (see :mod:`forwarder3ds.core.fonts`)."""

    #: A TTF/OTF file picked directly; empty when picked by name or built-in.
    font: str = ""
    font_family: str = ""
    font_style: str = ""

    @property
    def font_choice(self) -> FontChoice:
        """The font as picked."""
        return FontChoice(self.font_family, self.font_style, self.font)

    @font_choice.setter
    def font_choice(self, choice: FontChoice) -> None:
        self.font_family, self.font_style, self.font = choice.family, choice.style, choice.file


@dataclass
class BannerSettings(_FontSettings):
    """Look of the default banner (logo + console tag), the same for every game."""

    background: str = "#1e1e22"
    text: str = "#ffffff"


@dataclass
class BottomScreenSettings(_FontSettings):
    """The touch screen shown while a game runs (Virtual Console style)."""

    #: Draw it; off leaves the emulator's own idle screen.
    enabled: bool = True
    #: Language of the message (a code of ``artwork.bottom_screen.MESSAGES``).
    language: str = "en"


@dataclass
class Settings:
    """Everything the user can configure."""

    general: GeneralSettings = field(default_factory=GeneralSettings)
    steamgriddb: SteamGridDBSettings = field(default_factory=SteamGridDBSettings)
    toolchain: ToolchainSettings = field(default_factory=ToolchainSettings)
    banner: BannerSettings = field(default_factory=BannerSettings)
    bottom_screen: BottomScreenSettings = field(default_factory=BottomScreenSettings)


_SECTIONS = ("general", "steamgriddb", "toolchain", "banner", "bottom_screen")


def _read_ini(parser: configparser.ConfigParser) -> Settings:
    settings = Settings()
    for section in _SECTIONS:
        group = getattr(settings, section)
        for item in dataclasses.fields(group):
            default = getattr(group, item.name)
            if isinstance(default, bool):
                try:
                    value = parser.getboolean(section, item.name, fallback=default)
                except ValueError:
                    value = default
            else:
                value = parser.get(section, item.name, fallback=default).strip()
            setattr(group, item.name, value)
    if not settings.general.manufacturer:
        settings.general.manufacturer = DEFAULT_MANUFACTURER
    return settings


def _write_ini(settings: Settings) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    for section in _SECTIONS:
        group = getattr(settings, section)
        parser[section] = {
            item.name: _format(getattr(group, item.name)) for item in dataclasses.fields(group)
        }
    return parser


def _format(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _migrate_legacy(legacy: Path) -> Settings | None:
    """Import the API key and output folder from the old ``QSettings`` file."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        if not parser.read(legacy, encoding="utf-8"):
            return None
    except configparser.Error:
        return None
    settings = Settings()
    settings.steamgriddb.api_key = parser.get("sgdb", "api_key", fallback="").strip()
    settings.general.output_dir = parser.get("paths", "last_output_dir", fallback="").strip()
    if not (settings.steamgriddb.api_key or settings.general.output_dir):
        return None
    _log.info("Imported settings from the previous version (%s)", legacy)
    return settings


def legacy_settings_file() -> Path:
    """Settings file of the unpackaged UI, read once for migration."""
    return paths.config_dir().parent / _LEGACY_UI_SETTINGS


def load_settings(path: Path | None = None) -> Settings:
    """Read settings, importing the old UI's ones on first run."""
    path = path or paths.config_file()
    if not path.is_file():
        migrated = _migrate_legacy(legacy_settings_file())
        if migrated is None:
            return Settings()
        try:  # once: the next start reads the new file
            save_settings(migrated, path)
        except OSError as exc:
            _log.warning("Cannot save the imported settings to %s: %s", path, exc)
        return migrated
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        _log.error("Invalid settings file %s (%s); using defaults", path, exc)
        return Settings()
    return _read_ini(parser)


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Write settings atomically with owner-only permissions. Returns the file path."""
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    parser = _write_ini(settings)  # fail before touching the file
    fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".ini", dir=path.parent)
    try:
        os.chmod(tmp_name, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def masked(settings: Settings) -> dict[str, dict[str, str]]:
    """Settings as nested strings with secrets hidden, for ``3ds-forwarder config``."""
    table = {section: dict(values) for section, values in _write_ini(settings).items()}
    table.pop("DEFAULT", None)
    key = settings.steamgriddb.api_key
    if key:
        table["steamgriddb"]["api_key"] = f"{key[:4]}…" if len(key) > 8 else "…"
    return table
