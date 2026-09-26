# 3ds-new-forwarder-generator

Generador de forwarders CIA para 3DS que cargan un juego directamente con
el core de RetroArch correspondiente, sin encapsular un RetroArch completo
dentro del CIA (a diferencia de New Super Ultimate Injector). Pensado para
Luma3DS/Rosalina (sin soporte para entrypoints legacy tipo *hax).

## Estado actual

- [x] Diseño de arquitectura (stub compilado una vez + reempaquetado por juego)
- [x] Esqueleto del stub (`stub/`): lee `core.path` y `content.path` desde su
      propia RomFS y construye las rutas absolutas de SD.
- [ ] **Pendiente crítico**: función `load_and_jump_to_3dsx()` en
      `stub/source/main.c` — hay que portarla desde el código real de
      RetroArch (`ctr/exec-3dsx/exec_3dsx.c` +
      `ctr/exec-3dsx/mini-hb-menu/loaders/rosalina.c`) o de new-hbmenu.
      No implementada a propósito hasta verificar la API exacta contra
      la fuente.
- [ ] Backend CLI que genere, por cada juego: RomFS temporal + `.rsf` con
      Title ID único + `makerom` → `.cia`.
- [ ] Registro de Title IDs ya usados (para no colisionar entre forwarders).
- [ ] Icono/banner (placeholder por ahora).
- [ ] UI.

## Arquitectura

El `.3dsx`/`.elf` del stub (`stub/`) se compila **una sola vez**. Lo único
que cambia entre forwarders es:

1. Su RomFS (`core.path` + `content.path`, texto plano, ruta relativa a la
   raíz de la SD, sin barra inicial ni salto de línea final).
2. Su Title ID (para que cada forwarder sea una entrada independiente en el
   HOME Menu).
3. Su icono/banner (más adelante).

El backend, por juego, arma una RomFS temporal + un `.rsf` con el Title ID
asignado, y llama a `makerom` para producir el `.cia` final — sin
recompilar el stub.

## Memoria de la conversación de diseño

- APP_SYSTEM_MODE_EXT lo declara el `.3dsx` del CORE (no el stub). Para
  cores de PSX (PCSX ReARMed), usar 124MB en su build para ir sobrado;
  verificar el valor real que usa el build oficial en
  `pkg/ctr/Makefile.cores` del repo de RetroArch antes de darlo por bueno.
- Toolchain en Docker: imagen base `devkitpro/devkitarm` (mantenida
  oficialmente, Docker Hub) + paquete de herramientas 3DS (`makerom`,
  `bannertool`) vía `dkp-pacman` dentro de la imagen — comprobar nombre
  exacto del paquete (`3ds-dev` / `general-tools`) en el momento de montarlo.
- El ticket del CIA no hay que forjarlo aparte: `makerom` genera uno válido
  al construir el `.cia`, suficiente para instalar con FBI bajo Luma3DS
  (que parchea la verificación de firmas).
- Rango de Title ID reservado para forwarders: por decidir (propuesta:
  bloque propio tipo `0004000000-7A0000`–`...7AFFFF`, con contador/registro
  local para no repetir).
