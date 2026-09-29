"""rom_picker.py — Pick a ROM on the 3DS SD card and get its SD-relative path.

The card is found through ``tools.sd_card``; this module only adds the
dialogs: a message when no card is mounted, a chooser when several are, and
a file picker that opens at the card's root.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from tools.sd_card import find_3ds_sd_cards, sd_relative_path

_TITLE = "Choose ROM on the SD card"


def _choose_card(parent: QWidget, cards: list[Path]) -> Path | None:
    """The card to browse: the only one, or the user's pick among several."""
    if len(cards) == 1:
        return cards[0]
    choice, accepted = QInputDialog.getItem(
        parent,
        _TITLE,
        "Several 3DS SD cards were found. Which one holds the ROM?",
        [str(card) for card in cards],
        0,
        False,
    )
    return Path(choice) if accepted else None


def choose_rom_on_sd(parent: QWidget) -> str | None:
    """Let the user pick a ROM on a mounted 3DS SD card.

    Returns its path relative to the card's root (as stored in the
    forwarder, e.g. ``roms/snes/game.sfc``), or ``None`` if there was no
    card, the user cancelled, or the file picked is not on the card.
    """
    cards = find_3ds_sd_cards()
    if not cards:
        QMessageBox.information(
            parent,
            _TITLE,
            "No 3DS SD card was detected.\n\n"
            "Insert it (it must contain a 'Nintendo 3DS' folder or 'boot.firm') "
            "and try again, or type the ROM path by hand.",
        )
        return None

    card = _choose_card(parent, cards)
    if card is None:
        return None

    path_str, _filter = QFileDialog.getOpenFileName(parent, _TITLE, str(card), "All files (*)")
    if not path_str:
        return None
    try:
        return sd_relative_path(card, Path(path_str))
    except ValueError:
        QMessageBox.warning(
            parent, _TITLE, f"That file is not on the SD card at '{card}'.\nPick one inside it."
        )
        return None
