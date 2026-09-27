"""game_picker_dialog.py — Modal dialog to disambiguate a SteamGridDB game search.

Shown whenever a search returns more than one plausible match, so the user
decides which game the icon/hero/logo search should be scoped to, instead
of silently guessing.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..sgdb.models import GameCandidate


class GamePickerDialog(QDialog):
    """Lets the user pick the intended game among several SteamGridDB matches."""

    def __init__(self, parent, query: str, candidates: list[GameCandidate]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Multiple matches for \u201c{query}\u201d")
        self.resize(480, 420)
        self.setModal(True)

        self._candidates = candidates
        self._chosen: GameCandidate | None = None

        layout = QVBoxLayout(self)

        info = QLabel(
            f"SteamGridDB returned {len(candidates)} results for \u201c{query}\u201d. "
            "Pick the game these assets belong to:"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        for candidate in candidates:
            suffix = "  \u2713 verified" if candidate.verified else ""
            item = QListWidgetItem(f"{candidate.name}{suffix}    [id={candidate.id}]")
            self._list.addItem(item)
        if candidates:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._candidates):
            self._chosen = self._candidates[row]
        super().accept()

    @staticmethod
    def choose(parent, query: str, candidates: list[GameCandidate]) -> GameCandidate | None:
        """Run the dialog and return the chosen candidate, or ``None`` if cancelled."""
        dialog = GamePickerDialog(parent, query, candidates)
        if dialog.exec() == QDialog.Accepted:
            return dialog._chosen  # pylint: disable=protected-access
        return None
