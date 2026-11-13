#!/usr/bin/env python3
"""Regenerate ``data/bottom_screen/home_icon.png`` from ``home_icon.svg``.

The touch screen draws the HOME icon from the SVG when Qt is installed and
from this PNG otherwise (the command-line tool): run this after editing the
SVG. Needs PySide6.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from forwarder3ds.artwork.bottom_screen import (
    HOME_ICON_PNG,
    HOME_ICON_PNG_SIZE,
    HOME_ICON_SVG,
    render_svg_alpha,
)
from forwarder3ds.core.paths import bundled


def main() -> int:
    """Render the SVG's shape, in white, into the PNG."""
    alpha = render_svg_alpha(bundled(HOME_ICON_SVG), HOME_ICON_PNG_SIZE)
    if alpha is None:
        print("PySide6 is needed, and a valid home_icon.svg", file=sys.stderr)
        return 1
    image = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    image.putalpha(alpha)
    target = Path(bundled(HOME_ICON_PNG))
    image.save(target, optimize=True)
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
