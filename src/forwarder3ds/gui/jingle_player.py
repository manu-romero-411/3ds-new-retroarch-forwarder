"""Play a banner jingle so it can be auditioned before saving.

Uses ``QSoundEffect`` (QtMultimedia) when that module is installed. Some
distributions package it separately, and the PySide6 bundled with the
Ubuntu 24.04 package leaves it out, so the first command-line player found
among ``pw-play``, ``paplay`` and ``aplay`` is used otherwise. Either way the
interface is the same: ``play()``, ``stop()`` and two signals.

The ``QSoundEffect`` is only created on the first ``play()``: on some systems
without an audio device creating it can take the whole process down, and
the window must open regardless.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QUrl, Signal

try:
    from PySide6.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover - depends on the installed PySide6
    QSoundEffect = None  # pylint: disable=invalid-name

PLAYBACK_FAILED_MESSAGE = (
    "Could not play the jingle. Is an audio output device available? "
    "(The file itself is fine if it is listed as usable.)"
)
_PLAYERS = ("pw-play", "paplay", "aplay")


def _command_line_player() -> str | None:
    return next((found for name in _PLAYERS if (found := shutil.which(name))), None)


class JinglePlayer(QObject):
    """Plays one WAV at a time."""

    playing_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._play_when_ready = False
        self._effect: QSoundEffect | None = None
        self._process: QProcess | None = None
        self._player = None if QSoundEffect is not None else _command_line_player()

    @property
    def available(self) -> bool:
        """Whether anything can play audio at all."""
        return QSoundEffect is not None or self._player is not None

    @property
    def is_playing(self) -> bool:
        """Whether a jingle is sounding right now."""
        if self._effect is not None:
            return self._effect.isPlaying()
        return (
            self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def play(self, path: Path) -> None:
        """Play the WAV at ``path`` from the start, stopping whatever was playing."""
        self.stop()
        if QSoundEffect is not None:
            if self._effect is None:
                self._effect = QSoundEffect(self)
                self._effect.playingChanged.connect(self._on_playing_changed)
                self._effect.statusChanged.connect(self._on_status_changed)
            self._play_when_ready = True
            # Clearing the source first makes Qt re-read a file that changed on disk.
            self._effect.setSource(QUrl())
            self._effect.setSource(QUrl.fromLocalFile(str(path)))
            self._start_if_ready()
        elif self._player is not None:
            self._process = QProcess(self)
            self._process.finished.connect(self._on_process_finished)
            self._process.errorOccurred.connect(self._on_process_error)
            self._process.start(self._player, [str(path)])
            self.playing_changed.emit(True)
        else:
            self.failed.emit("No audio player found (QtMultimedia, pw-play, paplay or aplay).")

    def stop(self) -> None:
        """Silence the jingle, and cancel one that was still loading."""
        self._play_when_ready = False
        if self._effect is not None:
            self._effect.stop()
        elif self._process is not None:
            self._process.kill()
            self._process.waitForFinished(500)

    # ── QtMultimedia ─────────────────────────────────────────────────────

    def _start_if_ready(self) -> None:
        assert self._effect is not None
        if self._play_when_ready and self._effect.status() == QSoundEffect.Status.Ready:
            self._play_when_ready = False
            self._effect.play()

    def _on_status_changed(self) -> None:
        assert self._effect is not None
        if self._effect.status() == QSoundEffect.Status.Error:
            self._play_when_ready = False
            self.failed.emit(PLAYBACK_FAILED_MESSAGE)
        else:
            self._start_if_ready()

    def _on_playing_changed(self) -> None:
        assert self._effect is not None
        self.playing_changed.emit(self._effect.isPlaying())

    # ── Command-line player ──────────────────────────────────────────────

    def _on_process_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        self.playing_changed.emit(False)
        # A crash exit is stop() killing the player, not a failure.
        stopped = status == QProcess.ExitStatus.CrashExit
        if not stopped and exit_code != 0 and self._process is not None:
            output = bytes(self._process.readAllStandardError().data()).decode(errors="replace")
            self.failed.emit(f"{PLAYBACK_FAILED_MESSAGE}\n{output.strip()}")

    def _on_process_error(self, _error: QProcess.ProcessError) -> None:
        self.playing_changed.emit(False)
        self.failed.emit(PLAYBACK_FAILED_MESSAGE)
