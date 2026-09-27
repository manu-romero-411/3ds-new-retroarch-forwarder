"""build_worker.py — Runs tools.build_forwarder.build_forwarder in the background.

``build_forwarder()`` (and the helpers it calls) reports progress with
plain ``print()`` calls and signals failure with ``sys.exit(1)`` — that is
fine for a CLI, but a GUI needs those as log lines and a catchable error
instead. This worker redirects stdout to a line-buffered Qt signal for the
duration of the call and turns ``SystemExit`` into a normal ``failed``
signal, without touching ``tools/build_forwarder.py`` itself.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from tools.build_forwarder import ForwarderRequest, build_forwarder
from tools.cores_registry import DEFAULT_CORES_JSON
from tools.title_id import DEFAULT_REGISTRY_PATH


class _LineEmittingStream:
    """A write-only, file-like object that emits one signal per complete line."""

    def __init__(self, line_signal: Signal) -> None:
        self._line_signal = line_signal
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._line_signal.emit(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._line_signal.emit(self._buffer)
            self._buffer = ""


class BuildWorker(QThread):
    """Builds one forwarder .cia, streaming ``build_forwarder``'s output as log lines."""

    log_line = Signal(str)
    succeeded = Signal(int, Path)  # unique_id, output path
    failed = Signal(str)

    def __init__(
        self,
        request: ForwarderRequest,
        cores_json: Path = DEFAULT_CORES_JSON,
        title_id_registry_path: Path = DEFAULT_REGISTRY_PATH,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._cores_json = cores_json
        self._title_id_registry_path = title_id_registry_path

    def run(self) -> None:
        stream = _LineEmittingStream(self.log_line)
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                unique_id = build_forwarder(
                    self._request,
                    cores_json=self._cores_json,
                    title_id_registry_path=self._title_id_registry_path,
                )
        except SystemExit:
            stream.flush()
            self.failed.emit("Build failed — see the log above for the exact error.")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Deliberately broad: any failure in build_forwarder() must reach
            # the UI as a message instead of crashing the worker thread.
            stream.flush()
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            stream.flush()
            self.succeeded.emit(unique_id, self._request.output)
