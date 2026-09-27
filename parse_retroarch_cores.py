#!/usr/bin/env python3
"""
Parsea pkg/ctr/Makefile.cores de RetroArch y genera un JSON con el
mapeo core -> Title ID (y datos asociados) para el generador de forwarders.

Uso:
    python3 parse_retroarch_cores.py /ruta/a/RetroArch/pkg/ctr/Makefile.cores > cores.json

El Title ID se deriva del patrón confirmado:
    TitleID = 0x0004000000000000 | (APP_UNIQUE_ID << 8)

Esto es coherente con el formato estándar de 3DS:
    TitleID = (High32 << 32) | (UniqueId << 8) | Variation
donde High32 = 0x00040000 (categoría "aplicación") y Variation = 0x00.
"""

import re
import sys
import json


BLOCK_RE = re.compile(
    r'(?:^|\n)\s*(?:else\s+)?ifeq\s*\(\s*\$\(LIBRETRO\)\s*,\s*([^\)]+?)\s*\)(.*?)'
    r'(?=\n\s*else\s+ifeq|\n\s*endif)',
    re.DOTALL
)

FIELD_RE = re.compile(r'^\s*(APP_[A-Z_]+)\s*=\s*(.+?)\s*$', re.MULTILINE)


def parse_makefile_cores(text: str):
    cores = {}

    for match in BLOCK_RE.finditer(text):
        libretro_name = match.group(1).strip()
        block = match.group(2)

        fields = {}
        for fmatch in FIELD_RE.finditer(block):
            key = fmatch.group(1).strip()
            val = fmatch.group(2).strip()
            fields[key] = val

        unique_id_raw = fields.get('APP_UNIQUE_ID')
        if not unique_id_raw:
            # Bloque sin UNIQUE_ID (no debería pasar, pero por si acaso)
            continue

        try:
            unique_id = int(unique_id_raw, 16)
        except ValueError:
            print(f"WARN: no se pudo parsear APP_UNIQUE_ID={unique_id_raw!r} "
                  f"para core {libretro_name}", file=sys.stderr)
            continue

        title_id = 0x0004000000000000 | (unique_id << 8)

        cores[libretro_name] = {
            "libretro_name": libretro_name,
            "title": fields.get('APP_TITLE', libretro_name),
            "author": fields.get('APP_AUTHOR', ''),
            "product_code": fields.get('APP_PRODUCT_CODE', ''),
            "unique_id": f"0x{unique_id:X}",
            "title_id": f"{title_id:016X}",
            "title_id_hex": f"0x{title_id:016X}",
            "cia_filename": f"{libretro_name}_libretro.cia",
            "cia_path_convention": f"retroarch/cores/{libretro_name}_libretro.cia",
            "system_mode": fields.get('APP_SYSTEM_MODE', ''),
            "use_svchax": fields.get('APP_USE_SVCHAX', ''),
        }

    return cores


def main():
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <ruta/a/Makefile.cores>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    cores = parse_makefile_cores(text)

    if not cores:
        print("WARN: no se encontró ningún core. ¿Es el Makefile.cores correcto?",
              file=sys.stderr)

    print(json.dumps(cores, indent=2, ensure_ascii=False))
    print(f"\n# Total cores parseados: {len(cores)}", file=sys.stderr)


if __name__ == '__main__':
    main()
