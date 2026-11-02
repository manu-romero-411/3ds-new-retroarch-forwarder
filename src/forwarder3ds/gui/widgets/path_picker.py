"""A line edit with a *Browse…* button, for a folder or a file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget


class PathPicker(QWidget):
    """Line edit plus a *Browse…* button for a folder or a file."""

    def __init__(
        self,
        select_dir: bool,
        placeholder: str = "",
        file_filter: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._select_dir = select_dir
        self._filter = file_filter or self.tr("All files (*)")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        browse = QPushButton(self.tr("Browse…"))
        browse.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def text(self) -> str:
        """Current path text."""
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        """Set the path text."""
        self.edit.setText(value)

    def set_placeholder(self, text: str) -> None:
        """Text shown while the field is empty (e.g. what is used instead)."""
        self.edit.setPlaceholderText(text)

    def _browse(self) -> None:
        current = Path(self.text()).expanduser() if self.text() else Path.home()
        start = str(current if current.is_dir() or not current.exists() else current.parent)
        if self._select_dir:
            chosen = QFileDialog.getExistingDirectory(self, self.tr("Choose a folder"), start)
        else:
            chosen, _filter = QFileDialog.getOpenFileName(
                self, self.tr("Choose a file"), start, self._filter
            )
        if chosen:
            self.edit.setText(chosen)
