"""asset_choice.py — A drop-down of ready-made files, plus "pick your own".

Used for the banner jingle and the platform frame: both are "one of the files
in a project folder, or any file of mine that follows the same rules".

The folder is read through a callable returning ``tools.media_catalog``
entries, and re-read every time the list is opened, so files dropped into the
folder while the app runs just appear. Entries that break the rules are shown
greyed out with the reason as a tooltip, never silently hidden. A file picked
with "Browse…" is checked with the same validator before it is accepted.

The widget only tracks a *selected path* (or ``None``); what that path means
is up to the owner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QSizePolicy,
    QWidget,
)

from tools.build_forwarder import default_save_dir
from tools.media_catalog import CatalogEntry

_ROLE_PATH = Qt.UserRole
_ROLE_KIND = Qt.UserRole + 1
_KIND_NONE = "none"
_KIND_FILE = "file"
_KIND_BROWSE = "browse"
_BROWSE_LABEL = "Browse for a file\u2026"
_UNUSABLE_SUFFIX = " (unusable)"


class _ComboBox(QComboBox):
    """A combo box that announces that its list is about to open."""

    popup_opening = Signal()

    def showPopup(self) -> None:  # pylint: disable=invalid-name
        self.popup_opening.emit()
        super().showPopup()


class AssetChoice(QWidget):
    """Choose nothing, a file from a catalog folder, or a custom file."""

    changed = Signal()

    def __init__(
        self,
        none_label: str,
        list_entries: Callable[[], list[CatalogEntry]],
        validate: Callable[[Path], str | None],
        dialog_title: str,
        file_filter: str,
        rules: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._none_label = none_label
        self._list_entries = list_entries
        self._validate = validate
        self._dialog_title = dialog_title
        self._file_filter = file_filter

        self._selected: Path | None = None
        self._custom: tuple[Path, str] | None = None
        self._last_dir = default_save_dir()

        self._combo = _ComboBox()
        self._combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(12)
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.setToolTip(f"Required: {rules}")
        self._combo.popup_opening.connect(self._rebuild)
        self._combo.activated.connect(self._on_activated)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._combo)

        self._rebuild()

    # ── Public API ───────────────────────────────────────────────────────

    def selected_path(self) -> Path | None:
        """The chosen file, or ``None`` for "nothing"."""
        return self._selected

    def select_path(self, path: Path | None, label: str | None = None) -> None:
        """Select ``path`` programmatically (it is not validated, e.g. a loaded CIA's audio).

        A file that is not in the catalog folder is listed as a custom entry
        named ``label`` (default: its file name). ``None`` selects "nothing"
        and forgets any custom entry. Emits ``changed``.
        """
        self._selected = path
        self._custom = (path, label or f"Custom: {path.name}") if path else None
        self._rebuild()
        self.changed.emit()

    # ── Internals ────────────────────────────────────────────────────────

    def _add_item(self, text: str, kind: str, path: Path | None = None) -> int:
        self._combo.addItem(text)
        index = self._combo.count() - 1
        self._combo.setItemData(index, kind, _ROLE_KIND)
        self._combo.setItemData(index, str(path) if path else None, _ROLE_PATH)
        return index

    def _rebuild(self) -> None:
        """Re-read the folder and redraw the list, keeping the selection."""
        entries = self._list_entries()
        catalog_paths = {entry.path for entry in entries}
        if self._custom and self._custom[0] in catalog_paths:
            self._custom = None  # now it is just one of the catalog's entries

        self._combo.blockSignals(True)
        self._combo.clear()
        self._add_item(self._none_label, _KIND_NONE)
        for entry in entries:
            if entry.usable:
                self._add_item(entry.name, _KIND_FILE, entry.path)
                continue
            index = self._add_item(entry.name + _UNUSABLE_SUFFIX, _KIND_FILE, entry.path)
            self._combo.model().item(index).setEnabled(False)
            self._combo.setItemData(index, entry.problem, Qt.ToolTipRole)
        if self._custom:
            self._add_item(self._custom[1], _KIND_FILE, self._custom[0])
        self._add_item(_BROWSE_LABEL, _KIND_BROWSE)
        self._point_combo_at_selection()
        self._combo.blockSignals(False)

    def _point_combo_at_selection(self) -> None:
        index = self._combo.findData(str(self._selected), _ROLE_PATH) if self._selected else 0
        self._combo.setCurrentIndex(max(index, 0))

    def _on_activated(self, index: int) -> None:
        """The user picked an item of the list."""
        if self._combo.itemData(index, _ROLE_KIND) == _KIND_BROWSE:
            self._browse()
            self._point_combo_at_selection()  # undo the "Browse" highlight if nothing was picked
            return
        path_str = self._combo.itemData(index, _ROLE_PATH)
        chosen = Path(path_str) if path_str else None
        if chosen != self._selected:
            self._selected = chosen
            self.changed.emit()

    def _browse(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self, self._dialog_title, str(self._last_dir), self._file_filter
        )
        if not path_str:
            return
        path = Path(path_str)
        problem = self._validate(path)
        if problem:
            QMessageBox.warning(
                self, self._dialog_title, f"'{path.name}' cannot be used.\n\n{problem}"
            )
            return
        self._last_dir = path.parent
        self.select_path(path)
