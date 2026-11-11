# Standalone emulators

Besides the RetroArch bases (`../retroarch/`), a game can be injected with a
standalone 3DS emulator. Each one has a folder here:

| File | What it is |
| --- | --- |
| `recipe.env` | source, commit, how to build it and what to ship (see `snes9x_3ds/recipe.env`) |
| `patches/*.patch` | applied in order to the checkout before building |

`packaging/toolchain/build-base.sh OUT_DIR <name>` (or `all`) builds it in
the devkitARM container, installing the devkitPro packages its recipe lists
(`EMU_PACKAGES`), and writes `OUT_DIR/bases/<name>/`:

| File | Contents |
| --- | --- |
| `app.elf` | the patched emulator |
| `app.rsf` | its own makerom settings (`APP_ROMFS`, `APP_SYSTEM_MODE`... are filled per game) |
| `romfs/` | its own RomFS files, copied into every game's RomFS |
| `icon.png`, `banner.png` | its default artwork |
| `base.env` | `KIND=standalone`, revision, patch digest and memory modes |

A game's RomFS then holds the emulator's files plus `game.<ext>` and the
same `manifest.cfg` RetroArch bases read (`content`, `data_dir`, ...). The
patch makes the emulator boot that ROM and keep its files in `data_dir`.

## snes9x_3ds

[matbo87/snes9x_3ds](https://github.com/matbo87/snes9x_3ds) v2.0, an
alternative to `snes9x2005` for the `snes` console (faster with Super FX
and SA-1 games). `0001-single-game-mode.patch`:

- reads `romfs:/manifest.cfg` first thing; with it, `data_dir` becomes the
  emulator's root directory, and saves, savestates, configs, screenshots
  and cheats go straight into it (`game.srm`, `game.auto.frz`, `game.cfg`,
  `game.chx`...), next to the global `settings.cfg`;
- loads the ROM at boot and resumes its auto savestate;
- leaves out the ROM browser ("Games" tab) and the online updater.

Building it on the host instead (`DEVKITARM` set) needs `3ds-curl`,
`3ds-mbedtls`, `3ds-libpng` and `3ds-zlib` installed with `dkp-pacman`.
Snes9x's licence is non-commercial: see the emulator's `LICENSE.md`.
