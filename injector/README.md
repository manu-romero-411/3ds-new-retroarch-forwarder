# Injector (proof of concept)

Standalone single-game CIAs, in the spirit of New Super Ultimate Injector:
each CIA carries its own RetroArch + core build and the game itself, and
only writes to its own folder on the SD card.

> Status: proof of concept, Game Boy / Game Boy Color (gambatte) only.
> Not yet wired into the `forwarder3ds` CLI or GUI.

## How it works

1. **Base**: RetroArch for 3DS, statically linked with one core and patched
   with [`patches/retroarch/`](patches/retroarch/). The patch adds a
   *single-game mode*: when the CIA has `romfs:/game/manifest.cfg`,
   RetroArch loads the content from the RomFS and keeps every writable path
   in the manifest's `data_dir`. Without that file it behaves like stock
   RetroArch.
2. **CIA**: the base ELF plus a RomFS with:

   ```
   romfs:/game/<rom file>
   romfs:/game/manifest.cfg    content, data_dir, optional system_dir
   romfs:/game/retroarch.cfg   seed config, copied to data_dir on first boot
   ```

On the SD card each game gets `sdmc:/3ds/injected/<slug>/` with
`retroarch.cfg`, `saves/`, `states/`, `config/` (core options, remaps),
`logs/`, `temp/` and `screenshots/`. Nothing under `sdmc:/retroarch/` is
written. BIOS files go in `<data_dir>/system/` unless `--system-dir` points
somewhere else (for example the shared `sdmc:/retroarch/cores/system`).

The seed config turns on RetroArch's kiosk mode and hides the menu entries
that make no sense for a single game (load core/content, updaters, close
content). Quick Menu, save states, core options and *Quit RetroArch* stay.

## Try it

```bash
# 1. makerom + bannertool, if the toolchain is not there yet
packaging/toolchain/build-tools.sh toolchain

# 2. The gambatte base (RetroArch is checked out and built in build/base/)
packaging/toolchain/build-base.sh toolchain gambatte

# 3. A CIA for one game
injector/make-poc-cia.sh --toolchain toolchain gambatte "Some Game.gb"
```

Install the CIA with FBI. The first boot creates the data folder and its
`retroarch.cfg`.

## Pinned sources

| What      | Where |
|-----------|-------|
| RetroArch | `RETROARCH_REF` in `packaging/toolchain/versions.env` |
| Cores     | `CORE_REF` in `injector/cores/<core>.env` |

The patch is written against that RetroArch release; bump both together.

## Things to check on the console

- [ ] The game boots straight from the HOME Menu icon.
- [ ] In-game saves land in `saves/` and survive a reboot.
- [ ] Save states work from the Quick Menu.
- [ ] Settings changed in the menu persist (`retroarch.cfg` in data_dir).
- [ ] *Quit RetroArch* returns to the HOME Menu cleanly.
- [ ] `sdmc:/retroarch/` is left untouched.
