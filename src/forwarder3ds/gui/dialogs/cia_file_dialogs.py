"""Open/Save file pickers for game ``.cia`` files.

Thin wrappers over ``QFileDialog`` so the main window does not repeat the
filters, the fallback directory or the rule that saved files always end in
``.cia`` (the extension rule itself lives in ``forwarder3ds.builder.injector``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from forwarder3ds.builder.injector import ensure_cia_extension

_OPEN_FILTER = "CIA files (*.cia);;All files (*)"
_SAVE_FILTER = "CIA files (*.cia)"


def _existing_dir(candidate: Path) -> Path:
    """``candidate`` if it is a directory, else the default save directory."""
    return candidate if candidate.is_dir() else Path.home()


def choose_cia_to_open(parent: QWidget, start_dir: Path) -> Path | None:
    """Ask for a ``.cia`` to load; ``None`` if the user cancelled."""
    path_str, _filter = QFileDialog.getOpenFileName(
        parent, "Open game CIA", str(_existing_dir(start_dir)), _OPEN_FILTER
    )
    return Path(path_str) if path_str else None


def choose_cia_to_save(parent: QWidget, start_dir: Path, default_name: str) -> Path | None:
    """Ask where to save a ``.cia``; ``None`` if the user cancelled.

    The result always ends in ``.cia``. When that means the name the user
    typed was changed, the dialog's own overwrite check no longer applies to
    it, so replacing an existing file is confirmed here instead.
    """
    dialog = QFileDialog(parent, "Save game CIA", str(_existing_dir(start_dir) / default_name))
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setFileMode(QFileDialog.AnyFile)
    dialog.setNameFilter(_SAVE_FILTER)
    dialog.setDefaultSuffix("cia")
    if dialog.exec() != QDialog.Accepted:
        return None

    chosen = Path(dialog.selectedFiles()[0])
    path = ensure_cia_extension(chosen)
    if path != chosen and path.exists():
        answer = QMessageBox.question(
            parent,
            "Save game CIA",
            f"'{path.name}' already exists.\nDo you want to replace it?",
        )
        if answer != QMessageBox.Yes:
            return None
    return path
