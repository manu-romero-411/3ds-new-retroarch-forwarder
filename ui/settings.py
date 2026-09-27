"""settings.py — Small persistent-settings wrapper (QSettings) for the UI.

Only what genuinely benefits from surviving a restart is stored here: the
SteamGridDB API key and the last output directory. Everything else (core,
ROM path, names...) is per-forwarder and not worth remembering.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

ORG_NAME = "3ds-new-forwarder-generator"
APP_NAME = "ForwarderBuilderUI"

_KEY_SGDB_API_KEY = "sgdb/api_key"
_KEY_LAST_OUTPUT_DIR = "paths/last_output_dir"


class AppSettings:
    """Thin, typed wrapper around ``QSettings`` for this app's few stored values."""

    def __init__(self) -> None:
        self._qsettings = QSettings(ORG_NAME, APP_NAME)

    @property
    def sgdb_api_key(self) -> str:
        return str(self._qsettings.value(_KEY_SGDB_API_KEY, ""))

    @sgdb_api_key.setter
    def sgdb_api_key(self, value: str) -> None:
        self._qsettings.setValue(_KEY_SGDB_API_KEY, value)

    @property
    def last_output_dir(self) -> str:
        return str(self._qsettings.value(_KEY_LAST_OUTPUT_DIR, ""))

    @last_output_dir.setter
    def last_output_dir(self, value: str) -> None:
        self._qsettings.setValue(_KEY_LAST_OUTPUT_DIR, value)
