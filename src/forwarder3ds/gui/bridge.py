"""Thread plumbing between the backend and the Qt main thread.

* :class:`TaskThread` runs one blocking call (a SteamGridDB request, a
  download) off the UI thread and reports its result or error.
* :class:`BuildWorker` runs :func:`~forwarder3ds.builder.forwarder.build_forwarder`.
* :class:`QtLogHandler` forwards the package's log records to the Activity
  panel, so the GUI shows exactly what the command line prints.

Callers must keep a reference to a running thread (store it on ``self``):
PySide6 does not keep the Python object alive, and a garbage-collected
running ``QThread`` crashes the process.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from forwarder3ds.builder.errors import BuildError
from forwarder3ds.builder.forwarder import ForwarderRequest, build_forwarder
from forwarder3ds.builder.toolchain import Toolchain


class TaskThread(QThread):
    """Runs ``fn()`` in a background thread and reports the outcome via signals."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # pylint: disable=missing-function-docstring
        try:
            result = self._fn()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Any failure must reach the UI as a message, not kill the thread.
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.succeeded.emit(result)


class BuildWorker(QThread):
    """Builds one forwarder; progress arrives through the log handler."""

    succeeded = Signal(int, Path)  # unique_id, output path
    failed = Signal(str)

    def __init__(
        self,
        request: ForwarderRequest,
        tools: Toolchain,
        registry: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._tools = tools
        self._registry = registry

    def run(self) -> None:  # pylint: disable=missing-function-docstring
        try:
            result = build_forwarder(self._request, self._tools, self._registry)
        except BuildError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.failed.emit(f"Unexpected error: {exc!r}")
        else:
            self.succeeded.emit(result.unique_id, result.output)


class _LogEmitter(QObject):
    record = Signal(int, str)


class QtLogHandler(logging.Handler):
    """Logging handler that forwards formatted records to a Qt slot (thread-safe)."""

    def __init__(self) -> None:
        super().__init__()
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.record.emit(record.levelno, self.format(record))
        except RuntimeError:  # emitter deleted during shutdown
            pass
