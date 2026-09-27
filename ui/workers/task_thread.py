"""task_thread.py — Run one blocking callable off the UI thread.

Every SteamGridDB call (search, asset listing, thumbnail downloads) is
network I/O and must not run on the UI thread. Rather than writing a
bespoke ``QThread`` subclass per operation, callers wrap the blocking call
in a zero-argument callable and get a result/error signal back.

Callers must keep a reference to the returned ``TaskThread`` until it
finishes (e.g. store it on ``self``) — PySide6 does not keep a Python
thread object alive on its own, and a garbage-collected running QThread
crashes the process.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class TaskThread(QThread):
    """Runs ``fn()`` in a background thread and reports the outcome via signals."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Deliberately broad: any failure in the wrapped callable must
            # reach the UI as a message instead of crashing the thread.
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.succeeded.emit(result)
