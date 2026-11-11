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
- `0003-ctr-bottom-screen-stays-lit.patch`: the touch screen no longer dims
  and switches off when idle (it left Rosalina's menu in the dark).
- `0004-ctr-bottom-idle-picture.patch`: while the game runs, the touch
  screen shows `romfs:/bottom_idle.png` (the injector's Virtual Console style
  picture) instead of RetroArch's "Tap the Touch Screen…" text.

## Core recipes

One `<core>.env` per core, with the repository, the pinned commit, the
makefile, the static library it produces for `platform=ctr` and the header
with its core option definitions (see `gambatte.env` for the format). Which console uses which core is in
`src/forwarder3ds/data/systems.json`.

| Core | Consoles | Notes |
|---|---|---|
| stella2014 | atari2600 | |
| prosystem | atari7800 | optional BIOS `7800 BIOS (U).rom` |
| handy | lynx | needs `lynxboot.img` |
| fceumm | nes, fds | FDS needs `disksys.rom` |
| nestopia | nes, fds (alternative) | FDS needs `disksys.rom` |
| snes9x2005 | snes | |
| gambatte | gb, gbc | |
| gpsp | gba | needs `gba_bios.bin` |
| pokemini | pokemini | optional BIOS `bios.min` |
| genesis_plus_gx | sg1000, mastersystem, megadrive, segacd, gamegear | Mega-CD needs `bios_CD_U.bin` / `_E` / `_J` |
| picodrive | sega32x; alternative for the Sega consoles | Mega-CD as above |
| mednafen_pce_fast | pcengine, pcenginecd | PC Engine CD needs `syscard3.pce` |
| pcsx_rearmed | psx | one-disc `.chd` or `.pbp`; a BIOS (`scph5501.bin`...) is recommended |
| mame2003, mame2000 | mame | 0.78 / 0.37b5 romsets; use non-merged sets |
| fbneo_neogeo, fbneo_cps12 | fbneo | FinalBurn Neo's Neo Geo and CPS-1/2 subsets (the whole FBNeo does not fit); `neogeo.zip` in `sdmc:/emu_bios/fbneo/` |
| fbalpha2012 (+ _cps1, _cps2, _cps3, _neogeo) | fbneo (alternatives) | 0.2.97.29 romsets |

BIOS files go in `sdmc:/emu_bios/` (RetroArch's system folder for every
game). The MAME and FB Alpha 2012 bases need RetroArch's "big text section":
they take kernel access (svchax) at boot, which Luma3DS allows.
