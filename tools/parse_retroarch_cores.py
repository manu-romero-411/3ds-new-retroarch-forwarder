#!/usr/bin/env python3
"""Parse RetroArch's ``pkg/ctr/Makefile.cores`` into ``data/cores.json``.

Produces the core -> Title ID mapping (and associated metadata) consumed by
the forwarder generator.

Usage::

    python3 tools/parse_retroarch_cores.py \\
        /path/to/RetroArch/pkg/ctr/Makefile.cores > data/cores.json

The Title ID follows the confirmed pattern::

    TitleID = 0x0004000000000000 | (APP_UNIQUE_ID << 8)

which matches the standard 3DS layout::

    TitleID = (High32 << 32) | (UniqueID << 8) | Variation

where ``High32 = 0x00040000`` (the "application" category) and
``Variation = 0x00``.
"""

from __future__ import annotations

import json
import re
import sys

BLOCK_RE = re.compile(
    r"(?:^|\n)\s*(?:else\s+)?ifeq\s*\(\s*\$\(LIBRETRO\)\s*,\s*([^)]+?)\s*\)(.*?)"
    r"(?=\n\s*else\s+ifeq|\n\s*endif)",
    re.DOTALL,
)

FIELD_RE = re.compile(r"^\s*(APP_[A-Z_]+)\s*=\s*(.+?)\s*$", re.MULTILINE)


def parse_makefile_cores(text: str) -> dict[str, dict]:
    """Extract one entry per ``ifeq ($(LIBRETRO), <core>)`` block."""
    cores: dict[str, dict] = {}

    for match in BLOCK_RE.finditer(text):
        libretro_name = match.group(1).strip()
        block = match.group(2)

        fields = {}
        for field_match in FIELD_RE.finditer(block):
            fields[field_match.group(1).strip()] = field_match.group(2).strip()

        unique_id_raw = fields.get("APP_UNIQUE_ID")
        if not unique_id_raw:
            # Block without a UNIQUE_ID (should not normally happen).
            continue

        try:
            unique_id = int(unique_id_raw, 16)
        except ValueError:
            print(
                f"WARN: could not parse APP_UNIQUE_ID={unique_id_raw!r} "
                f"for core {libretro_name}",
                file=sys.stderr,
            )
            continue

        title_id = 0x0004000000000000 | (unique_id << 8)

        cores[libretro_name] = {
            "libretro_name": libretro_name,
            "title": fields.get("APP_TITLE", libretro_name),
            "author": fields.get("APP_AUTHOR", ""),
            "product_code": fields.get("APP_PRODUCT_CODE", ""),
            "unique_id": f"0x{unique_id:X}",
            "title_id": f"{title_id:016X}",
            "title_id_hex": f"0x{title_id:016X}",
            "cia_filename": f"{libretro_name}_libretro.cia",
            "cia_path_convention": f"retroarch/cores/{libretro_name}_libretro.cia",
            "system_mode": fields.get("APP_SYSTEM_MODE", ""),
            "use_svchax": fields.get("APP_USE_SVCHAX", ""),
        }

    return cores


def main() -> None:
    """CLI entry point: read a Makefile.cores path, print JSON to stdout."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path/to/Makefile.cores>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    cores = parse_makefile_cores(text)

    if not cores:
        print(
            "WARN: no cores found. Is this the right Makefile.cores?",
            file=sys.stderr,
        )

    print(json.dumps(cores, indent=2, ensure_ascii=False))
    print(f"\n# Total cores parsed: {len(cores)}", file=sys.stderr)


if __name__ == "__main__":
    main()
