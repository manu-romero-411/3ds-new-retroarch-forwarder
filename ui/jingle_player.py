"""jingle_player.py — Play a banner jingle so it can be auditioned before saving.

A thin wrapper over ``QSoundEffect`` (QtMultimedia, part of the ``PySide6``
package) that turns its asynchronous loading and its status codes into three
simple things: ``play()``, ``stop()`` and two signals. Jingles are short
16-bit PCM WAVs (see ``tools/media_catalog.py``), which is what
``QSoundEffect`` is meant for.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QSoundEffect

PLAYBACK_FAILED_MESSAGE = (
    "Could not play the jingle. Is an audio output device available? "
    "(The file itself is not the problem if it is listed as usable.)"
)


class JinglePlayer(QObject):
    """Plays one WAV at a time."""

    playing_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._effect = QSoundEffect(self)
        self._play_when_ready = False
        self._effect.playingChanged.connect(self._on_playing_changed)
        self._effect.statusChanged.connect(self._on_status_changed)

    @property
    def is_playing(self) -> bool:
        """Whether a jingle is sounding right now."""
        return self._effect.isPlaying()

    def play(self, path: Path) -> None:
        """Play the WAV at ``path`` from the start, stopping whatever was playing."""
        self._effect.stop()
        self._play_when_ready = True
        # Clearing the source first makes Qt re-read a file that changed on
        # disk; setting an identical URL again would be ignored.
        self._effect.setSource(QUrl())
        self._effect.setSource(QUrl.fromLocalFile(str(path)))
        self._start_if_ready()

    def stop(self) -> None:
        """Silence the jingle, and cancel one that was still loading."""
        self._play_when_ready = False
        self._effect.stop()

    def _start_if_ready(self) -> None:
        if self._play_when_ready and self._effect.status() == QSoundEffect.Status.Ready:
            self._play_when_ready = False
            self._effect.play()

    def _on_status_changed(self) -> None:
        if self._effect.status() == QSoundEffect.Status.Error:
            self._play_when_ready = False
            self.failed.emit(PLAYBACK_FAILED_MESSAGE)
        else:
            self._start_if_ready()

    def _on_playing_changed(self) -> None:
        self.playing_changed.emit(self._effect.isPlaying())
