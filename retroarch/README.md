# RetroArch bases

Every game CIA is built from a **base**: RetroArch for 3DS statically linked
with one core and patched for single-game mode. Bases are compiled once with
devkitARM and reused for every game of that core:

```bash
packaging/toolchain/build-base.sh toolchain gambatte snes9x2005   # some cores
packaging/toolchain/build-base.sh toolchain all                   # every recipe
```

`build-base.sh` checks out RetroArch at `RETROARCH_REF`
(`packaging/toolchain/versions.env`), applies [`patches/`](patches/), builds
each core from its recipe in [`cores/`](cores/) and writes
`toolchain/bases/<core>/`:

| File | Contents |
|---|---|
| `retroarch.elf` | RetroArch + core |
| `base.env` | memory mode (from RetroArch's `pkg/ctr/Makefile.cores`) and source revisions |
| `assets/bottom_menu.png` | the touch screen menu, from retroarch-assets |
| `icon.png`, `banner.png`, `audio.wav` | RetroArch's defaults for that core |
| `core_options.h` | the core's option definitions (`CORE_OPTIONS` in the recipe), read by the GUI's core options dialog |

Bases leave networking out (netplay, updaters, achievements, cloud sync) for
a smaller ELF; `RA_LEAN=0` builds RetroArch's full feature set instead.

## Patches

Written against the RetroArch release in `RETROARCH_REF`; bump both together.

- `0001-ctr-single-game-mode.patch`: when the CIA has `romfs:/manifest.cfg`,
  RetroArch loads `romfs:/game.<ext>` and keeps every writable path in the
  manifest's `data_dir` (`sdmc:/saves/<console>/<game>`), seeding its
  `retroarch.cfg`, `game.opt` (core options) and control remap
  (`<core name>/game.rmp`) from the RomFS on first boot. The core info
  folder points at the RomFS, so startup does not parse the `.info` files of
  `sdmc:/retroarch/cores/info`. Once the content is loaded, the game's
  `bezel.png` (from `data_dir`, else from the RomFS) is shown as a full
  screen overlay; with none, overlays are turned off.
- `0002-ctr-bottom-menu-null-texture.patch`: fixes a crash of RetroArch's
  touch screen menu when `bottom_menu.png` is missing (upstream bug).

## Core recipes

One `<core>.env` per core, with the repository, the pinned commit, the
makefile, the static library it produces for `platform=ctr` and the header
with its core option definitions (see `gambatte.env` for the format). Which console uses which core is in
`src/forwarder3ds/data/systems.json`.

| Core | Consoles | Notes |
|---|---|---|
| gambatte | gb, gbc | |
| gpsp | gba | needs `gba_bios.bin` in `sdmc:/saves/bios` |
| fceumm | nes, fds | FDS needs `disksys.rom` |
| snes9x2005 | snes | |
| genesis_plus_gx | mastersystem, megadrive, gamegear, sg1000, segacd | Mega-CD needs its BIOS |
| mednafen_pce_fast | pcengine, pcenginecd | PC Engine CD needs `syscard3.pce` |
| pcsx_rearmed | psx | `.chd` or `.pbp`; a BIOS is recommended |

Cores that need RetroArch's "big text section" (svchax: fbalpha2012,
mame2000, mame2003, mame2003_plus) are not supported yet.
