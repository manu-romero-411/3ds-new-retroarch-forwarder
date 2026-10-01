"""artwork_panel.py — Icon/Hero/Logo SteamGridDB picker + composed banner preview.

Owns the whole SteamGridDB workflow for one forwarder: the API key field,
three independently-searchable asset slots (icon, hero, logo), and a live
banner preview that composites hero (background) + logo (overlay) — see
``ui/sgdb/compositor.py``. A manual "browse a local banner file instead"
override is also available, matching what the CLI already supports
(``--banner`` accepts any single image).

Network calls never block the UI: every SteamGridDB request runs on a
``TaskThread`` (see ``ui/workers/task_thread.py``); this widget just wires
their signals to dialogs and to the preview slots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.media_catalog import PLATFORM_LOGO_RULES, list_platform_logos, validate_platform_logo

from ..dialogs.game_picker_dialog import GamePickerDialog
from ..dialogs.image_gallery_dialog import ImageGalleryDialog
from ..settings import AppSettings
from ..sgdb.client import SGDBClient
from ..sgdb.compositor import compose_banner_png_bytes, frame_png_bytes
from ..sgdb.downloader import download_bytes
from ..sgdb.models import (
    ASSET_KIND_HERO,
    ASSET_KIND_ICON,
    ASSET_KIND_LOGO,
    ASSET_KIND_LABELS,
    GameCandidate,
    ImageCandidate,
)
from ..workers.task_thread import TaskThread
from .asset_choice import AssetChoice
from .asset_slot import AssetSlot

IMAGE_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"


class ArtworkPanel(QGroupBox):
    """SteamGridDB artwork picker: icon, hero+logo banner compositing, previews."""

    log_message = Signal(str)
    # The user changed the artwork (not emitted by reset()/load_*()).
    changed = Signal()
    # The icon and the banner as they will be built (``bytes`` or ``None``),
    # platform frame included, for whoever previews them.
    previews_changed = Signal(object, object)

    def __init__(
        self, settings: AppSettings, long_name_provider: Callable[[], str], parent=None
    ) -> None:
        super().__init__("Artwork (SteamGridDB)", parent)

        self._settings = settings
        self._long_name_provider = long_name_provider

        self._icon_bytes: bytes | None = None
        self._hero_bytes: bytes | None = None
        self._logo_bytes: bytes | None = None
        self._banner_override_bytes: bytes | None = None
        # The platform frame's pixels, for the preview only: the build gets
        # the frame's *path* (see platform_logo_path) and draws it itself.
        self._frame_bytes: bytes | None = None

        self._resolved_game: GameCandidate | None = None
        self._resolved_query: str = ""

        self._active_threads: list[TaskThread] = []

        # Populated by _build_ui() below; declared here so the attributes
        # exist from construction (pylint attribute-defined-outside-init).
        self._api_key_edit: QLineEdit
        self._remember_key_check: QCheckBox
        self._icon_slot: AssetSlot
        self._hero_slot: AssetSlot
        self._logo_slot: AssetSlot
        self._reset_banner_button: QPushButton
        self._frame_choice: AssetChoice

        self._build_ui()
        self._load_settings()

    # ── UI construction ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addLayout(self._build_api_key_row())

        # Slots stack vertically (rather than side by side) so this whole
        # panel stays narrow enough to sit as a column next to the form.
        slots_column = QVBoxLayout()
        self._icon_slot = self._build_slot(
            slots_column,
            ASSET_KIND_ICON,
            "Icon",
            "Used as the 48\u00d748 SMDH icon (stretched to fit).",
        )
        self._hero_slot = self._build_slot(
            slots_column,
            ASSET_KIND_HERO,
            "Hero",
            "Banner background. Cover-cropped to 256\u00d7128.",
        )
        self._logo_slot = self._build_slot(
            slots_column,
            ASSET_KIND_LOGO,
            "Logo",
            "Pasted on top of the hero, scaled to fit with a margin.",
        )

        layout.addLayout(slots_column)
        layout.addWidget(self._build_banner_box())

    def _build_slot(self, column: QVBoxLayout, kind: str, title: str, hint: str) -> AssetSlot:
        """Build one AssetSlot and wire its three actions to this kind of asset."""
        slot = AssetSlot(title, hint, self)
        slot.search_requested.connect(lambda: self._start_asset_search(kind, slot))
        slot.browse_requested.connect(lambda: self._browse_local(kind, slot))
        slot.clear_requested.connect(lambda: self._clear_asset(kind, slot))
        column.addWidget(slot)
        return slot

    def _build_api_key_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("API key:"))

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._api_key_edit.setPlaceholderText("SteamGridDB API key\u2026")
        self._api_key_edit.textChanged.connect(self._on_api_key_changed)
        row.addWidget(self._api_key_edit, 1)

        self._remember_key_check = QCheckBox("Remember")
        self._remember_key_check.toggled.connect(self._on_remember_toggled)
        row.addWidget(self._remember_key_check)
        return row

    def _build_banner_box(self) -> QWidget:
        """Banner-wide options: the platform frame and a ready-made banner file."""
        box = QGroupBox("Banner")
        layout = QVBoxLayout(box)

        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Platform logo:"))
        self._frame_choice = AssetChoice(
            none_label="None",
            list_entries=list_platform_logos,
            validate=validate_platform_logo,
            dialog_title="Choose a platform logo",
            file_filter="PNG images (*.png)",
            rules=PLATFORM_LOGO_RULES,
        )
        self._frame_choice.changed.connect(self._on_frame_changed)
        frame_row.addWidget(self._frame_choice, 1)
        layout.addLayout(frame_row)

        button_row = QHBoxLayout()
        override_button = QPushButton("Use local banner file\u2026")
        override_button.setToolTip("Use a ready-made image instead of the hero + logo composite.")
        override_button.clicked.connect(self._browse_banner_override)
        button_row.addWidget(override_button)

        self._reset_banner_button = QPushButton("Reset to composite")
        self._reset_banner_button.clicked.connect(self._reset_banner_override)
        self._reset_banner_button.setEnabled(False)
        button_row.addWidget(self._reset_banner_button)
        layout.addLayout(button_row)

        return box

    def _load_settings(self) -> None:
        stored_key = self._settings.sgdb_api_key
        if stored_key:
            self._remember_key_check.setChecked(True)
            self._api_key_edit.setText(stored_key)

    # ── API key persistence ─────────────────────────────────────────────

    def _on_api_key_changed(self, text: str) -> None:
        if self._remember_key_check.isChecked():
            self._settings.sgdb_api_key = text.strip()

    def _on_remember_toggled(self, checked: bool) -> None:
        self._settings.sgdb_api_key = self._api_key_edit.text().strip() if checked else ""

    # ── Search / resolve / fetch chain ──────────────────────────────────

    def _log(self, message: str) -> None:
        self.log_message.emit(message)

    def _keep_alive(self, thread: TaskThread) -> None:
        """Hold a reference until the thread finishes, so PySide6 can't GC it mid-run."""
        self._active_threads.append(thread)

        def _release() -> None:
            if thread in self._active_threads:
                self._active_threads.remove(thread)

        thread.finished.connect(_release)

    def _current_client(self) -> SGDBClient | None:
        api_key = self._api_key_edit.text().strip()
        if not api_key:
            self._log("Enter a SteamGridDB API key first.")
            return None
        return SGDBClient(api_key)

    def _start_asset_search(self, kind: str, slot: AssetSlot) -> None:
        query = self._long_name_provider().strip()
        if not query:
            self._log("Fill in the long name field before searching SteamGridDB.")
            return

        client = self._current_client()
        if client is None:
            return

        if self._resolved_game is not None and self._resolved_query.lower() == query.lower():
            self._fetch_assets(client, self._resolved_game, kind, slot)
            return

        self._log(f"Searching SteamGridDB for \u201c{query}\u201d\u2026")
        thread = TaskThread(lambda: client.search_games(query), parent=self)
        thread.succeeded.connect(
            lambda results: self._on_game_search_done(client, query, kind, slot, results)
        )
        thread.failed.connect(self._on_sgdb_error)
        self._keep_alive(thread)
        thread.start()

    def _on_game_search_done(
        self,
        client: SGDBClient,
        query: str,
        kind: str,
        slot: AssetSlot,
        results: list[GameCandidate],
    ) -> None:
        if not results:
            self._log(f"No SteamGridDB results for \u201c{query}\u201d.")
            return

        exact = [candidate for candidate in results if candidate.name.lower() == query.lower()]
        if len(results) == 1:
            chosen: GameCandidate | None = results[0]
        elif len(exact) == 1:
            chosen = exact[0]
            self._log(
                f"Matched \u201c{chosen.name}\u201d (exact match among {len(results)} results)."
            )
        else:
            self._log(
                f"{len(results)} possible matches for \u201c{query}\u201d "
                "\u2014 asking which one to use."
            )
            chosen = GamePickerDialog.choose(self, query, results)
            if chosen is None:
                self._log("Game selection cancelled.")
                return

        self._resolved_game = chosen
        self._resolved_query = query
        self._log(f"Using SteamGridDB game \u201c{chosen.name}\u201d (id={chosen.id}).")
        self._fetch_assets(client, chosen, kind, slot)

    def _fetch_assets(
        self, client: SGDBClient, game: GameCandidate, kind: str, slot: AssetSlot
    ) -> None:
        label = ASSET_KIND_LABELS[kind].lower()
        self._log(f"Fetching {label} candidates for \u201c{game.name}\u201d\u2026")
        thread = TaskThread(lambda: client.get_assets(game.id, kind), parent=self)
        thread.succeeded.connect(
            lambda candidates: self._on_assets_ready(game, kind, slot, candidates)
        )
        thread.failed.connect(self._on_sgdb_error)
        self._keep_alive(thread)
        thread.start()

    def _on_assets_ready(
        self, game: GameCandidate, kind: str, slot: AssetSlot, candidates: list[ImageCandidate]
    ) -> None:
        label = ASSET_KIND_LABELS[kind].lower()
        if not candidates:
            self._log(f"No {label} found for \u201c{game.name}\u201d.")
            return

        title = f"Choose {label} \u2014 {game.name}"
        chosen = ImageGalleryDialog.choose(self, title, candidates)
        if chosen is None:
            return

        self._log(f"Downloading selected {label}\u2026")
        thread = TaskThread(lambda: download_bytes(chosen.url), parent=self)
        source = f"SteamGridDB \u00b7 {chosen.author}" if chosen.author else "SteamGridDB"
        thread.succeeded.connect(lambda data: self._apply_asset(kind, slot, data, source))
        thread.failed.connect(self._on_sgdb_error)
        self._keep_alive(thread)
        thread.start()

    def _on_sgdb_error(self, message: str) -> None:
        self._log(f"SteamGridDB error: {message}")

    # ── Local file browsing ─────────────────────────────────────────────

    def _browse_local(self, kind: str, slot: AssetSlot) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "Choose an image", "", IMAGE_FILE_FILTER
        )
        if not path_str:
            return
        try:
            data = Path(path_str).read_bytes()
        except OSError as exc:
            self._log(f"Could not read {path_str}: {exc}")
            return
        self._apply_asset(kind, slot, data, f"Local file \u00b7 {Path(path_str).name}")

    def _browse_banner_override(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "Choose a banner image", "", IMAGE_FILE_FILTER
        )
        if not path_str:
            return
        try:
            data = Path(path_str).read_bytes()
        except OSError as exc:
            self._log(f"Could not read {path_str}: {exc}")
            return
        self._set_banner_override(data)
        self._log(f"Banner overridden with local file \u00b7 {Path(path_str).name}")
        self.changed.emit()

    def _reset_banner_override(self) -> None:
        self._banner_override_bytes = None
        self._reset_banner_button.setEnabled(False)
        self._refresh_previews()
        self._log("Banner reset to the hero + logo composite.")
        self.changed.emit()

    # ── Applying results ─────────────────────────────────────────────────

    def _apply_asset(
        self, kind: str, slot: AssetSlot, data: bytes | None, source_text: str
    ) -> None:
        if not data:
            self._log("Download failed: the file could not be retrieved.")
            return

        slot.set_source(source_text)
        self._store_asset(kind, data)
        self._refresh_previews()
        self.changed.emit()

    def _clear_asset(self, kind: str, slot: AssetSlot) -> None:
        slot.set_source()
        self._store_asset(kind, None)
        self._refresh_previews()
        self.changed.emit()

    def _store_asset(self, kind: str, data: bytes | None) -> None:
        if kind == ASSET_KIND_ICON:
            self._icon_bytes = data
        elif kind == ASSET_KIND_HERO:
            self._hero_bytes = data
        elif kind == ASSET_KIND_LOGO:
            self._logo_bytes = data

    def _set_banner_override(self, png_bytes: bytes) -> None:
        self._banner_override_bytes = png_bytes
        self._reset_banner_button.setEnabled(True)
        self._refresh_previews()

    def current_previews(self) -> tuple[bytes | None, bytes]:
        """The icon (``None``: the placeholder) and banner as they will be built.

        The banner is the override or the hero + logo composite -- a plain
        placeholder when neither exists -- with the platform frame drawn over it.
        """
        banner = self._banner_override_bytes
        if banner is None:
            banner = compose_banner_png_bytes(self._hero_bytes, self._logo_bytes)
        if self._frame_bytes:
            banner = frame_png_bytes(banner, self._frame_bytes)
        return self._icon_bytes, banner

    def _refresh_previews(self) -> None:
        self.previews_changed.emit(*self.current_previews())

    def _on_frame_changed(self) -> None:
        path = self._frame_choice.selected_path()
        self._frame_bytes = None
        if path is not None:
            try:
                self._frame_bytes = path.read_bytes()
            except OSError as exc:
                self._log(f"Could not read {path}: {exc}")
        self._refresh_previews()
        self.changed.emit()

    # ── Public API for the document (new / open) ────────────────────────

    def reset(self) -> None:
        """Forget every picked asset and the resolved SteamGridDB game."""
        self._icon_bytes = None
        self._hero_bytes = None
        self._logo_bytes = None
        self._banner_override_bytes = None
        self._frame_bytes = None
        self._frame_choice.select_path(None)
        self._resolved_game = None
        self._resolved_query = ""
        for slot in (self._icon_slot, self._hero_slot, self._logo_slot):
            slot.set_source()
        self._reset_banner_button.setEnabled(False)
        self._refresh_previews()

    def load_icon(self, png_bytes: bytes, source_text: str) -> None:
        """Show ``png_bytes`` in the icon slot, as if it had been picked there."""
        self._icon_bytes = png_bytes
        self._icon_slot.set_source(source_text)
        self._refresh_previews()

    def load_banner(self, png_bytes: bytes) -> None:
        """Use a ready-made 256\u00d7128 banner (e.g. from a loaded CIA) as the banner override."""
        self._set_banner_override(png_bytes)

    # ── Public API for the build step ───────────────────────────────────

    def platform_logo_path(self) -> Path | None:
        """The chosen platform frame, or ``None``. The build draws it over the banner."""
        return self._frame_choice.selected_path()

    def final_banner_bytes(self) -> bytes | None:
        """The banner to build, *without* the platform frame: override, composite or ``None``."""
        if self._banner_override_bytes is not None:
            return self._banner_override_bytes
        if self._hero_bytes is None and self._logo_bytes is None:
            return None
        return compose_banner_png_bytes(self._hero_bytes, self._logo_bytes)

    def final_icon_bytes(self) -> bytes | None:
        """The icon to actually build, or ``None`` to fall back to the placeholder."""
        return self._icon_bytes

    def write_temp_assets(self, tmp_dir: Path) -> tuple[Path | None, Path | None]:
        """Materialize the chosen icon/banner to files under ``tmp_dir``.

        ``build_forwarder`` (see ``tools/build_forwarder.py``) expects
        filesystem paths, not in-memory bytes, so this is called right
        before a build starts. Returns ``(icon_path, banner_path)``, either
        of which may be ``None`` if nothing was picked (the backend then
        falls back to its own placeholder).
        """
        icon_path: Path | None = None
        banner_path: Path | None = None

        icon_bytes = self.final_icon_bytes()
        if icon_bytes:
            icon_path = tmp_dir / "ui_icon_source.png"
            icon_path.write_bytes(icon_bytes)

        banner_bytes = self.final_banner_bytes()
        if banner_bytes:
            banner_path = tmp_dir / "ui_banner_source.png"
            banner_path.write_bytes(banner_bytes)

        return icon_path, banner_path
