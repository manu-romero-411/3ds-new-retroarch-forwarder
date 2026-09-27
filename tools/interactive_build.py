#!/usr/bin/env python3
"""Interactive, one-question-at-a-time forwarder builder.

Prompts for every field the non-interactive ``build_forwarder`` CLI needs,
validates the core against the core registry immediately (exiting with an
error if it's unknown, before asking anything else), then builds the .cia.

Usage::

    python3 -m tools.interactive_build
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.build_forwarder import (
    DEFAULT_MANUFACTURER,
    PROJECT_ROOT,
    ForwarderRequest,
    build_forwarder,
)
from tools.cores_registry import CoreRegistry, DEFAULT_CORES_JSON


def ask_text(question: str, default: str | None = None) -> str:
    """Prompt for a required (or defaulted) line of text."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{question}{suffix}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        print("  Este campo es obligatorio.")


def ask_optional_path(question: str) -> Path | None:
    """Prompt for an optional filesystem path; blank means 'use default'."""
    while True:
        answer = input(f"{question} [en blanco = usar valor por defecto]: ").strip()
        if not answer:
            return None
        path = Path(answer).expanduser()
        if not path.exists():
            print(f"  No existe el fichero: {path}")
            continue
        return path


def main() -> None:
    """Run the interactive prompt sequence and build the forwarder."""
    print("=== Generador interactivo de forwarders 3DS ===\n")

    core_registry = CoreRegistry.load(DEFAULT_CORES_JSON)

    core = ask_text("Core de RetroArch (nombre libretro, p. ej. snes9x2005)")
    if core_registry.get(core) is None:
        print(
            f"\nERROR: el core '{core}' no está en el catálogo "
            f"({DEFAULT_CORES_JSON}).",
            file=sys.stderr,
        )
        print(
            "Revisa el nombre exacto en ese fichero, o regenéralo con "
            "tools/parse_retroarch_cores.py si acabas de actualizar RetroArch.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  OK: core '{core}' encontrado en el catálogo.\n")

    rom = ask_text("Ruta de la ROM en la SD (p. ej. roms/snes/Super Mario World.zip)")
    name = ask_text("Nombre del forwarder (identificador interno / nombre de fichero)")
    short_name = ask_text("Nombre corto (SMDH)", default=name)
    long_name = ask_text("Nombre largo (SMDH)", default=name)
    manufacturer = ask_text("Manufacturer / publisher (SMDH)", default=DEFAULT_MANUFACTURER)

    print(
        "\nIcono y banner se redimensionan automáticamente (estirando, sin "
        "recortar) a 48x48 y 256x128. El audio se convierte a 16-bit / "
        "44.1kHz / estéreo y se recorta a 3 segundos, sea cual sea su "
        "formato de origen."
    )
    icon = ask_optional_path("Ruta al icono (PNG)")
    banner = ask_optional_path("Ruta al banner (PNG)")
    audio = ask_optional_path("Ruta al audio del banner (cualquier formato)")

    default_output = PROJECT_ROOT / "output" / f"{name}.cia"
    output_answer = input(f"Ruta de salida del .cia [{default_output}]: ").strip()
    output = Path(output_answer).expanduser() if output_answer else default_output

    request = ForwarderRequest(
        core=core,
        rom_path=rom,
        name=name,
        short_name=short_name,
        long_name=long_name,
        manufacturer=manufacturer,
        output=output,
        icon=icon,
        banner=banner,
        audio=audio,
    )

    print()
    build_forwarder(request)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.", file=sys.stderr)
        sys.exit(1)
