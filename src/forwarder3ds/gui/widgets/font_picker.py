"""Pick a font the way the system does: family and style, or a font file.

A file that is not installed is registered with Qt for the session, so it
shows up in the list like any other family; the file is remembered too, so
it keeps working without installing it (see :mod:`forwarder3ds.core.fonts`).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from forwarder3ds.core.fonts import FontChoice


def register_font_file(path: str) -> tuple[str, str] | None:
    """Make ``path`` available to Qt; its ``(family, style)``, or ``None`` if unreadable."""
    font_id = QFontDatabase.addApplicationFont(path)
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if not families:
        return None
    styles = QFontDatabase.styles(families[0])
    return families[0], styles[0] if styles else ""


class FontPicker(QWidget):
    """"Custom font" check box, family list, style list and *From file…*."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file = ""
        self._custom = QCheckBox(self.tr("Custom:"))
        self._custom.setToolTip(self.tr("Unchecked: the built-in font"))
        self._family = QFontComboBox()
        self._family.setMinimumContentsLength(16)
        self._style = QComboBox()
        self._style.setMinimumContentsLength(8)
        from_file = QPushButton(self.tr("From file…"))
        from_file.setToolTip(self.tr("A TTF/OTF file, installed or not"))
        from_file.clicked.connect(self._pick_file)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._custom)
        layout.addWidget(self._family, 1)
        layout.addWidget(self._style)
        layout.addWidget(from_file)

        self._custom.toggled.connect(self._on_custom)
        self._family.currentFontChanged.connect(self._on_family)
        self._style.currentIndexChanged.connect(self.changed)
        self._on_custom(False)

    def _on_custom(self, custom: bool) -> None:
        self._family.setEnabled(custom)
        self._style.setEnabled(custom)
        self.changed.emit()

    def _fill_styles(self, family: str, selected: str = "") -> None:
        self._style.blockSignals(True)
        self._style.clear()
        styles = QFontDatabase.styles(family)
        self._style.addItems(styles)
        index = styles.index(selected) if selected in styles else 0
        if not selected and "Regular" in styles:
            index = styles.index("Regular")
        self._style.setCurrentIndex(index)
        self._style.blockSignals(False)

    def _on_family(self, font: QFont) -> None:
        self._file = ""  # picked by name from now on
        self._fill_styles(font.family())
        self.changed.emit()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Choose a font"), "", self.tr("Fonts (*.ttf *.otf *.ttc *.otc)")
        )
        if path:
            self._select_file(path)
            self.changed.emit()

    def _select_file(self, path: str) -> None:
        names = register_font_file(path)
        if names is None:
            return
        family, style = names
        self._family.blockSignals(True)
        self._family.setCurrentFont(QFont(family))
        self._family.blockSignals(False)
        self._fill_styles(family, style)
        self._file = path
        self._custom.blockSignals(True)
        self._custom.setChecked(True)
        self._custom.blockSignals(False)
        self._on_custom(True)

    def set_choice(self, choice: FontChoice) -> None:
        """Show ``choice``."""
        self.blockSignals(True)
        if choice.file and Path(choice.file).is_file():
            self._select_file(choice.file)
            if choice.style:
                self._fill_styles(self._family.currentFont().family(), choice.style)
        elif choice.family:
            self._family.blockSignals(True)
            self._family.setCurrentFont(QFont(choice.family))
            self._family.blockSignals(False)
            self._fill_styles(choice.family, choice.style)
            self._file = ""
        self._custom.setChecked(not choice.builtin)
        self._on_custom(not choice.builtin)
        self.blockSignals(False)

    def choice(self) -> FontChoice:
        """The font picked (empty: built-in)."""
        if not self._custom.isChecked():
            return FontChoice()
        family = self._family.currentFont().family()
        return FontChoice(family, self._style.currentText(), self._file)
