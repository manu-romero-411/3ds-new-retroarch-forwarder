#!/usr/bin/env python3
"""
Convierte cores.json (generado por parse_retroarch_cores.py) en un header C
con una tabla estática {nombre_core -> Title ID}, para embeber en el stub
del forwarder y evitar tener que llevar el Title ID + ruta del CIA por
duplicado en el RomFS de cada forwarder.

Uso:
    python3 generate_cores_table.py cores.json > source/cores_table.h
"""

import sys
import json


HEADER_TEMPLATE = """/* AUTO-GENERADO por generate_cores_table.py a partir de cores.json.
 * NO EDITAR A MANO. Para actualizar tras un cambio en RetroArch:
 *
 *   python3 parse_retroarch_cores.py <RetroArch>/pkg/ctr/Makefile.cores > cores.json
 *   python3 generate_cores_table.py cores.json > source/cores_table.h
 *
 * Total de cores: {count}
 */
#ifndef _CORES_TABLE_H_
#define _CORES_TABLE_H_

#include <3ds/types.h>

typedef struct {{
    const char *libretro_name;
    u64 title_id;
    const char *cia_filename;
}} core_entry_t;

static const core_entry_t CORES_TABLE[] = {{
{entries}
}};

#define CORES_TABLE_COUNT (sizeof(CORES_TABLE) / sizeof(CORES_TABLE[0]))

#endif /* _CORES_TABLE_H_ */
"""

ENTRY_TEMPLATE = '    {{ "{name}", 0x{title_id}ULL, "{cia_filename}" }}, /* {title} */'


def generate(cores: dict) -> str:
    entries = []
    # Orden alfabético para que los diffs del header sean legibles
    for name in sorted(cores.keys()):
        core = cores[name]
        title = core.get('title', name).replace('"', "'")
        entries.append(ENTRY_TEMPLATE.format(
            name=core['libretro_name'],
            title_id=core['title_id'],
            cia_filename=core['cia_filename'],
            title=title,
        ))

    return HEADER_TEMPLATE.format(
        count=len(cores),
        entries="\n".join(entries),
    )


def main():
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <cores.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        cores = json.load(f)

    print(generate(cores))
    print(f"# Total entradas generadas: {len(cores)}", file=sys.stderr)


if __name__ == '__main__':
    main()
