"""document.py — What "the forwarder being edited" means for the window.

A tiny state holder, deliberately free of Qt: which ``.cia`` on disk the
form is bound to (if any), which Unique ID that binding implies, and
whether there are edits that were not saved yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

UNTITLED = "Untitled"
NEW_DOCUMENT_LABEL = "Creating new CIA\u2026"


@dataclass
class Document:
    """The current forwarder: its file, its Title ID and its unsaved-changes flag."""

    path: Path | None = None
    unique_id: int | None = None
    dirty: bool = False

    @property
    def display_name(self) -> str:
        """File name for the window title (``Untitled`` before the first save)."""
        return self.path.name if self.path else UNTITLED

    @property
    def status_text(self) -> str:
        """One-line description of what is being edited: the file's name, or that it is new."""
        return self.path.name if self.path else NEW_DOCUMENT_LABEL

    def bind(self, path: Path, unique_id: int) -> None:
        """Tie the document to ``path`` (just loaded or saved) and mark it clean."""
        self.path = path
        self.unique_id = unique_id
        self.dirty = False

    def reset(self) -> None:
        """Back to a brand-new, unsaved, unbound document."""
        self.path = None
        self.unique_id = None
        self.dirty = False
