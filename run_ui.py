#!/usr/bin/env python3
"""run_ui.py — Convenience launcher for the Qt UI from the project root.

Equivalent to ``python3 -m ui.app``; this just exists so the UI can also be
started as a single script (e.g. double-clicked from a file manager, or
referenced by a desktop shortcut) without remembering the module form.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.app import main  # pylint: disable=wrong-import-position  # after sys.path fix-up above

if __name__ == "__main__":
    sys.exit(main())
