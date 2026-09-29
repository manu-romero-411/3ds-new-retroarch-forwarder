# 3ds-new-forwarder-generator

Generador de forwarders CIA para 3DS que cargan un juego directamente con
el core de RetroArch correspondiente, sin encapsular un RetroArch completo
dentro del CIA (a diferencia de New Super Ultimate Injector). Pensado para
Luma3DS/Rosalina (sin soporte para entrypoints legacy tipo *hax).

> Convención del proyecto: el código (C y Python — nombres, comentarios,
> mensajes de log) está en inglés; esta documentación está en español.

## Estructura del proyecto

```
3ds-new-forwarder-generator/
├── README.md
├── Dockerfile                    # entorno devkitARM + makerom + bannertool
├── pyproject.toml                # config de pylint
├── stub/                         # el .3dsx/.elf que se compila UNA sola vez
│   ├── Makefile
│   ├── forwarder.rsf
│   ├── romfs/                    # RomFS de ejemplo para "make cia" suelto
│   └── source/
│       ├── main.c
│       └── cores_table.h         # AUTO-GENERADO, ver tools/generate_cores_table.py
├── data/
│   ├── cores.json                # catálogo de cores RetroArch -> Title ID
│   └── title_id_registry.json    # registro de IDs ya asignados (se versiona)
├── tools/                        # toolchain Python (paquete, ver más abajo)
│   ├── cores_registry.py
│   ├── title_id.py
│   ├── parse_retroarch_cores.py
│   ├── generate_cores_table.py
│   ├── generate_placeholder_assets.py
│   ├── png_codec.py              # codificador PNG (solo stdlib)
│   ├── ctr_assets.py             # decodifica icono/banner/audio de un CIA
│   ├── cia_reader.py             # lee un forwarder .cia existente
│   ├── sd_card.py                # detecta la SD de la 3DS y rutas relativas a ella
│   ├── rom_names.py              # título sugerido a partir del nombre de la ROM
│   └── build_forwarder.py        # generador por juego (backend, punto de entrada para una UI futura)
├── ui/                            # UI de escritorio (PySide6/Qt), ver ui/README.md
│   ├── app.py                    # entry point (`python3 -m ui.app`)
│   ├── main_window.py            # barra superior + flujo New/Open/Save/Save As
│   ├── document.py               # estado del documento (fichero, Title ID, cambios)
│   ├── settings.py
│   ├── sgdb/                     # cliente SteamGridDB + composición hero+logo
│   ├── dialogs/                  # diálogos modales (conflicto de juego, galería)
│   ├── widgets/                  # formulario + panel de artwork + log
│   └── workers/                  # hilos de fondo (red y build)
├── run_ui.py                      # lanzador de la UI desde la raíz del proyecto
├── requirements-ui.txt            # dependencias extra de la UI (PySide6, requests, Pillow)
├── scripts/
│   └── build_stub.sh
└── output/                       # .cia generados (gitignored)
```

Los scripts de `tools/` son un paquete Python de verdad (tienen
`__init__.py`), así que se ejecutan como módulo, desde la raíz del
proyecto:

```bash
python3 -m tools.build_forwarder \
    --core snes9x \
    --rom "roms/snes/Super Mario World.sfc" \
    --name "Super Mario World" \
    --short-name "SMW" \
    --long-name "Super Mario World (SNES)" \
    --manufacturer "Nintendo"
```

Si no se pasan `--icon/--banner/--audio`, se generan placeholders
automáticamente. El icono y el banner que sí pases (o el placeholder) se
redimensionan siempre a 48×48 y 256×128 estirando (sin recortar); el audio
se re-codifica siempre a PCM 16-bit / 44.1kHz / estéreo y se recorta a 3
segundos, sea cual sea su formato de origen (usa `ffmpeg`, ya incluido en
la imagen Docker). El `.cia` sale en `output/<name>.cia`.

### Modificar un CIA existente

`--from-cia` carga un forwarder ya generado (core, ruta de la ROM, nombres,
manufacturer, icono, banner y audio) y lo **reconstruye desde cero**
manteniendo su Title ID. Cualquier otro flag sobrescribe el valor cargado, y
si no se pasa `--output` se reemplaza el propio fichero:

```bash
python3 -m tools.build_forwarder --from-cia output/mario.cia --long-name "Super Mario World (USA)"
```

Solo se leen CIAs generados por esta herramienta (contenido sin cifrar y
RomFS con `core.txt`/`content.path`); cualquier otro se rechaza con un
mensaje claro. El banner se recupera como imagen final: la composición
original hero+logo no se puede deshacer.

### Modo interactivo

Si prefieres que te vaya preguntando campo a campo (y cortando al momento
si el core no existe en el catálogo, antes de pedirte nada más):

```bash
docker run --rm -v "$(pwd)":/work -it 3ds-forwarder-builder \
  python3 -m tools.interactive_build
```

Las rutas de icono/banner/audio son opcionales (Enter en blanco = usar el
valor por defecto) y, si las das, también se validan que el fichero
exista antes de seguir.

### UI gráfica (PySide6/Qt)

También hay una UI de escritorio en `ui/` con los mismos campos que la CLI,
más un buscador de artwork contra SteamGridDB (icono, hero y logo, con
composición automática del banner y previsualización). Documentación
completa (instalación, flujo de uso) en `ui/README.md`; arranque rápido:

```bash
pip3 install -r requirements-ui.txt
python3 run_ui.py
```

## Estado actual

- [x] Diseño de arquitectura (stub compilado una vez + reempaquetado por juego)
- [x] Stub funcional (`stub/`): lee `core.txt` y `content.path` desde su
      propia RomFS, resuelve el core contra `cores_table.h`, instala el CIA
      del core si falta y salta a él con `APT_DoApplicationJump`.
- [x] Backend CLI (`tools/build_forwarder.py`) que genera, por cada juego:
      RomFS temporal + `.rsf` con Title ID único + `makerom` → `.cia`.
- [x] Generación determinista de Title ID con registro anti-colisión
      (`tools/title_id.py`, ver sección de abajo).
- [x] Nombre corto, nombre largo y manufacturer independientes (campos SMDH
      reales: `-s`/`-l`/`-p` de bannertool), en vez de un único `--title`.
- [x] Redimensionado automático de icono (48x48) y banner (256x128) por
      estiramiento, y normalización del audio del banner a PCM 16-bit /
      44.1kHz / estéreo / máx. 3s, sea cual sea el formato de entrada
      (`tools/media_prep.py`, vía `ffmpeg`).
- [x] Cargar CIAs existentes y reconstruirlos conservando su Title ID
      (`tools/cia_reader.py`, `--from-cia` y Open/Save/Save As en la UI).
- [x] Modo interactivo (`tools/interactive_build.py`): pide cada campo uno
      a uno y corta con error en cuanto el core no existe en el catálogo.
- [x] Icono/banner por juego reales de tu colección: la UI (`ui/`) permite
      buscarlos en SteamGridDB (icono, hero y logo por separado) o
      cargarlos desde un fichero local; si no se elige ninguno, se sigue
      cayendo al placeholder de siempre.
- [x] UI / frontend (`ui/`, PySide6/Qt) — reutiliza directamente
      `build_forwarder()` sin duplicar lógica; ver `ui/README.md` (en
      inglés) para el flujo completo, incluida la búsqueda/composición de
      artwork vía SteamGridDB.

## Generación determinista del Title ID

Un Title ID de 3DS es `(0x00040000 << 32) | (UniqueId << 8) | Variation`.
Lo único que un forwarder puede elegir es `UniqueId` (20 bits). Los CIA de
los cores de RetroArch ya ocupan el bloque `0xBAC00`-`0xBACFF`
(`data/cores.json`), así que los forwarders nunca pueden pisar ese rango.

`tools/title_id.py` deriva el `UniqueId` de un hash SHA-256 de los campos
que identifican al forwarder — nombre, nombre corto, nombre largo,
manufacturer, core y ruta de la ROM — dentro de un bloque propio reservado
(`0xF0000`-`0xFFFFF`, convención habitual para forwarders/homebrew, lejos
del bloque de los cores). Esto da dos propiedades:

- **Determinista**: los mismos datos siempre producen el mismo ID, en
  cualquier máquina, sin necesitar un contador compartido.
- **Sin colisión conocida**: cada ID asignado se guarda en
  `data/title_id_registry.json` junto con la clave que lo generó. Al pedir
  un ID para datos ya vistos, se reutiliza el mismo (idempotente). Si el
  hash cae en un ID ya usado por otro forwarder o por un core, se prueba
  de forma determinista con un "nonce" incremental hasta encontrar uno
  libre — así que solo el juego que realmente choca cambia de ID, y el
  resultado sigue siendo 100% reproducible mientras el registro no cambie.

Nintendo no publica los rangos que ha asignado a títulos reales, así que
ningún generador no oficial puede garantizar cero colisión al 100%; lo que
sí se puede (y se hace aquí) es evitar el rango conocido de los cores y
dejar rastro de cada asignación para poder auditarla o corregirla a mano
si algún día hiciera falta.

`data/title_id_registry.json` se versiona en el repositorio (no está en
`.gitignore`) precisamente para que la propiedad "sin colisión" se
mantenga entre máquinas y clones, no solo en la tuya.

## Calidad de código Python

`pyproject.toml` trae la configuración de `pylint` para este proyecto
(`pylint tools/`). Los módulos usan type hints, dataclasses y docstrings;
las únicas reglas desactivadas son las que penalizarían la firma "plana"
de `build_forwarder()` sin ganar legibilidad real a este tamaño.

## Memoria de la conversación de diseño

- APP_SYSTEM_MODE_EXT lo declara el `.3dsx` del CORE (no el stub). Para
  cores de PSX (PCSX ReARMed), usar 124MB en su build para ir sobrado;
  verificar el valor real que usa el build oficial en
  `pkg/ctr/Makefile.cores` del repo de RetroArch antes de darlo por bueno.
- Toolchain en Docker: imagen base `devkitpro/devkitarm` (mantenida
  oficialmente, Docker Hub) + paquete de herramientas 3DS (`makerom`,
  `bannertool`) vía `dkp-pacman` dentro de la imagen.
- El ticket del CIA no hay que forjarlo aparte: `makerom` genera uno válido
  al construir el `.cia`, suficiente para instalar con FBI bajo Luma3DS
  (que parchea la verificación de firmas).
