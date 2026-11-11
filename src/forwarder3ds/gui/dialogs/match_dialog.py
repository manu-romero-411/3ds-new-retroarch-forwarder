"""Pick a ROM's libretro database entry by hand.

Shown from *Change match…*: when a ROM is not in the database (a hack, a
translation, a different revision) or was only matched by file name, the
user searches the system's dat and picks the entry whose metadata and
thumbnails should be used -- or explicitly none.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from forwarder3ds.core.romdb import DbGame, GameDatabase


@dataclass(frozen=True)
class MatchChoice:
    """What the dialog ended with: an entry, or ``None`` for "not in the database"."""

    game: DbGame | None


class MatchDialog(QDialog):
    """Search box plus the matching entries of one system's database."""

    def __init__(
        self, parent: QWidget | None, database: GameDatabase, system_name: str, query: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Match with the libretro database"))
        self.resize(620, 480)
        self._database = database
        self._choice: MatchChoice | None = None

        info = QLabel(
            self.tr(
                "Pick the {system} entry this ROM corresponds to. Its title, publisher, "
                "year and libretro thumbnails will be used."
            ).format(system=system_name)
        )
        info.setWordWrap(True)
        self._search = QLineEdit(query)
        self._search.setPlaceholderText(self.tr("Search by name…"))
        self._search.setClearButtonEnabled(True)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self.accept)
        self._count = QLabel()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        no_match = QPushButton(self.tr("Not in the database"))
        no_match.setToolTip(self.tr("Use no entry: names stay as typed, no thumbnails."))
        buttons.addButton(no_match, QDialogButtonBox.ButtonRole.ActionRole)
        no_match.clicked.connect(self._choose_none)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        column = QVBoxLayout(self)
        column.addWidget(info)
        column.addWidget(self._search)
        column.addWidget(self._list, 1)
        column.addWidget(self._count)
        column.addWidget(buttons)

        self._search.textChanged.connect(self._refresh)
        self._refresh(query)

    def _refresh(self, text: str) -> None:
        self._list.clear()
        hits = self._database.search(text)
        for game in hits:
            details = " · ".join(part for part in (game.publisher, game.year) if part)
            label = game.name + (f"    — {details}" if details else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, game)
            self._list.addItem(item)
        if hits:
            self._list.setCurrentRow(0)
        self._count.setText(
            self.tr("{shown} of {total} entries").format(shown=len(hits), total=len(self._database))
        )

    def _choose_none(self) -> None:
        self._choice = MatchChoice(None)
        super().accept()

    def accept(self) -> None:  # pylint: disable=missing-function-docstring
        item = self._list.currentItem()
        if item is None:
            return
        self._choice = MatchChoice(item.data(Qt.ItemDataRole.UserRole))
        super().accept()

    @staticmethod
    def choose(
        parent: QWidget | None, database: GameDatabase, system_name: str, query: str
    ) -> MatchChoice | None:
        """Run the dialog; ``None`` if cancelled."""
        dialog = MatchDialog(parent, database, system_name, query)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog._choice  # pylint: disable=protected-access
        return None
