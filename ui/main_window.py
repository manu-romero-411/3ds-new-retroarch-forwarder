"""main_window.py — Top-level window: form + artwork panel + build action + log.

This is the only place that actually calls into ``tools.build_forwarder``
(via ``BuildWorker``): it validates the core against the registry the same
way ``tools/interactive_build.py`` does, materializes whatever artwork was
picked in ``ArtworkPanel`` to temporary files, assembles a
``ForwarderRequest`` and hands it to a background worker.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.build_forwarder import ForwarderRequest

from .settings import AppSettings
from .widgets.artwork_panel import ArtworkPanel
from .widgets.build_form import BuildForm
from .widgets.log_panel import LogPanel
from .workers.build_worker import BuildWorker

WINDOW_TITLE = "3DS Forwarder Builder"


class MainWindow(QWidget):
    """Assembles the form, artwork panel, log, and the Build action."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(760, 760)

        self._settings = AppSettings()
        self._build_worker: BuildWorker | None = None
        self._build_tmp_dir: Path | None = None

        self._build_form = BuildForm(self)
        self._artwork_panel = ArtworkPanel(self._settings, self._build_form.long_name_text, self)
        self._artwork_panel.log_message.connect(self._append_log)

        self._log_panel = LogPanel(self)

        self._build_button = QPushButton("Build .cia")
        self._build_button.clicked.connect(self._on_build_clicked)

        self._assemble_layout()

    def _assemble_layout(self) -> None:
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(self._build_form)
        # No horizontal scrollbar: the form must shrink to fit the column
        # instead of the column growing/scrolling to fit the form.
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        artwork_scroll = QScrollArea()
        artwork_scroll.setWidgetResizable(True)
        artwork_scroll.setWidget(self._artwork_panel)
        artwork_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Keeps the artwork column narrow (it stacks Icon/Hero/Logo/banner
        # preview vertically) so the window doesn't need to grow wide to
        # fit a horizontal row of slots.
        artwork_scroll.setMinimumWidth(260)
        artwork_scroll.setMaximumWidth(320)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(form_scroll)
        splitter.addWidget(artwork_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([460, 300])

        outer = QVBoxLayout(self)
        outer.addWidget(splitter, 3)
        outer.addWidget(self._build_button)
        outer.addWidget(self._log_panel, 1)

    # ── Build action ─────────────────────────────────────────────────────

    def _append_log(self, message: str) -> None:
        self._log_panel.append(message)

    def _validate_fields(self, fields: dict) -> str | None:
        """Return an error message if something required is missing/invalid, else ``None``."""
        if not self._build_form.core_registry_valid():
            return (
                f"The core catalog could not be loaded from "
                f"'{self._build_form.cores_json_path()}'. Check the path under Advanced."
            )
        if not fields["core"]:
            return "Pick a RetroArch core."
        if not self._build_form.core_exists(fields["core"]):
            return f"Core '{fields['core']}' is not in the core catalog."
        if not fields["rom_path"]:
            return "Enter the ROM path on the SD card."
        if not fields["name"]:
            return "Enter a name for this forwarder."
        return None

    def _on_build_clicked(self) -> None:
        fields = self._build_form.collect_fields()
        error = self._validate_fields(fields)
        if error:
            self._append_log(f"\u2717 {error}")
            QMessageBox.warning(self, WINDOW_TITLE, error)
            return

        self._build_tmp_dir = Path(tempfile.mkdtemp(prefix="3ds_forwarder_ui_"))
        icon_path, banner_path = self._artwork_panel.write_temp_assets(self._build_tmp_dir)

        request = ForwarderRequest(
            core=fields["core"],
            rom_path=fields["rom_path"],
            name=fields["name"],
            short_name=fields["short_name"],
            long_name=fields["long_name"],
            manufacturer=fields["manufacturer"],
            output=fields["output"],
            icon=icon_path,
            banner=banner_path,
            audio=fields["audio"],
        )

        self._append_log(f"\u25b8 Building '{fields['name']}'\u2026")
        self._build_button.setEnabled(False)

        self._build_worker = BuildWorker(
            request,
            cores_json=self._build_form.cores_json_path(),
            title_id_registry_path=self._build_form.title_id_registry_path(),
            parent=self,
        )
        self._build_worker.log_line.connect(self._append_log)
        self._build_worker.succeeded.connect(self._on_build_succeeded)
        self._build_worker.failed.connect(self._on_build_failed)
        self._build_worker.finished.connect(self._cleanup_build_tmp_dir)
        self._build_worker.start()

    def _cleanup_build_tmp_dir(self) -> None:
        if self._build_tmp_dir and self._build_tmp_dir.exists():
            shutil.rmtree(self._build_tmp_dir, ignore_errors=True)
        self._build_tmp_dir = None
        self._build_button.setEnabled(True)

    def _on_build_succeeded(self, unique_id: int, output: Path) -> None:
        self._append_log(f"\u2713 Done. Unique ID 0x{unique_id:05X} \u2192 {output}")
        QMessageBox.information(self, WINDOW_TITLE, f"Forwarder built successfully:\n{output}")

    def _on_build_failed(self, message: str) -> None:
        self._append_log(f"\u2717 {message}")
        QMessageBox.critical(self, WINDOW_TITLE, message)
