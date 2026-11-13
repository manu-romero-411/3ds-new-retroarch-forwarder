# 3ds-new-retroarch-forwarder

A RetroArch **injector** for a 3DS running Luma3DS, in the spirit of New
Super Ultimate Injector: one installable **CIA per game**, each with its own
icon, banner and jingle on the HOME menu, its own up-to-date RetroArch build
and the game itself inside. Each CIA works on its own: it does not need
RetroArch installed and never touches `sdmc:/retroarch`.

- A RetroArch **base** per core (RetroArch statically linked with the core
  and patched for single-game mode, see [`retroarch/`](retroarch/)) is
  compiled once. Per game it is repackaged with the ROM in its RomFS and a
  **deterministic, collision-checked Title ID**.
- Each game keeps **everything in one flat folder** on the SD card:

  ```
  sdmc:/saves/<console>/<game>/
  ├── retroarch.cfg       the game's RetroArch settings
  ├── game.srm            in-game save
  ├── game.state*         save states (+ thumbnails)
  ├── game.opt            core options
  ├── <core name>/game.rmp  button mapping (RetroArch remap)
  ├── bezel.png           optional: replaces the CIA's bezel (bezel.cfg appears next to it)
  └── system/             RetroArch's system folder for this game: BIOS, and
                          what cores keep there (MAME's settings and hiscores)
  ```

  BIOS files travel inside each CIA: put them in
  `~/.local/share/3ds-forwarder/bios/<core>/` (`%APPDATA%\3ds-forwarder\bios\<core>\`
  on Windows), where `<core>` is the base's name (`pcsx_rearmed`,
  `fbneo_neogeo`...), laid out as in a system folder (`fbneo/neogeo.zip`).
  Every CIA of that core packs them, and RetroArch reads them from the CIA
  as if they were in the game's `system/` folder; nothing is copied. A file
  in that folder wins, so a BIOS left out of the CIA can be dropped there
  later, without reinstalling.

  `<console>` is Batocera's folder name (`gb`, `snes`, `megadrive`, `psx`...).
- **Consoles**: Atari 2600, 5200, 7800 and Lynx, NES and Famicom Disk
  System, SNES, Game Boy, Game Boy Color, Game Boy Advance, Pokémon Mini,
  Neo Geo Pocket and Pocket Color, WonderSwan and WonderSwan Color,
  ColecoVision, MSX and MSX2 (cartridges), SG-1000, Master System, Mega
  Drive, 32X, Mega-CD, Game Gear, PC Engine and PC Engine CD, Vectrex,
  Odyssey2, PlayStation (one-disc games: `.chd` or `.pbp`) and arcade
  (`mame`: MAME 2003 / 2000; `fbneo`: FinalBurn Neo's Neo Geo and CPS-1/2
  builds, FB Alpha 2012). The cores and the BIOS each needs are listed in
  [`retroarch/`](retroarch/README.md). An arcade game is its romset `.zip`,
  packed as it is under its own name and identified by it.
- An optional **bezel** over the top screen (`--bezel`, 400x240 with a
  transparent window: a 4:3 game is the middle 320x240), replaceable per
  game by dropping a `bezel.png` in its save folder.
- An optional **alternate mode** (RetroArch only, not for the PlayStation,
  and for games not already set to pixel perfect): holding START or SELECT while the game boots shows it pixel perfect,
  without filtering, inside a bezel of its own (a handheld's frame, say;
  `--alt-bezel`, or `--alt-mode` for none). Nothing is saved in that
  session, so the game's usual settings and bezel are never touched.
- A **Virtual Console style touch screen** while the game runs ("Tap the
  Touch Screen to go to the RetroArch menu." and "⌂: Return to HOME Menu"),
  in English, Japanese, French, German, Italian, Spanish, Dutch, Portuguese
  or Russian (Settings › Touch screen, `--touch-language`). Each project
  can pick another language, an image of its own (`--touch-image`) or the
  emulator's own screen. Nintendo's font is FOT-Rodin: it is not included;
  pick it from the system's fonts (or straight from its file) in the settings.
- The injection options **preview both screens**: the game (libretro's
  screenshot, when the ROM is matched) scaled as the screen mode says, the
  bezel and the touch screen picture.
- A trimmed pause menu (black theme, A confirms) on the top screen only:
  the touch screen stays black while it is open, and the Quick Menu keeps
  only what makes sense for one game. CD games are single `.chd` files.
- ROMs are **identified against the libretro database** (No-Intro dats by
  CRC for cartridges, Redump names for discs): title, publisher and year
  fill the CIA's names, and libretro's title screen and snapshot can be
  used as the banner background. Hacks, translations or other revisions are
  flagged and can be matched by hand.
- **SNES games can also run on [snes9x_3ds](https://github.com/matbo87/snes9x_3ds)**
  (matbo87's fork, faster with Super FX and SA-1 games) instead of
  RetroArch: pick `snes9x_3ds` as the project's core. It is patched
  (`emulators/snes9x_3ds/`) to boot straight into the game and keep its
  files flat in the same save folder (`game.srm`, `game.auto.frz`,
  `game.cfg`, `settings.cfg`); its own menu replaces RetroArch's, so the
  injection options (screen, controls, core options) do not apply. The
  bezel becomes its picture behind the game (flattened on black) and the
  touch screen picture its second screen background.
- ROMs can stay zipped, as No-Intro sets come: the zip's ROM is identified
  by the CRC the zip stores and packed uncompressed into the CIA.
- Artwork comes from **SteamGridDB** (icon, hero and logo; the banner is the
  hero with the logo on top), or from your own image files.
- Existing CIAs can be opened, edited and rebuilt under the same Title ID,
  so the new CIA installs over the old one (the ROM is read back from it).
- Per-game **injection options**: screen scaling and filter, button
  mapping and initial core options, all seeded into the save folder on
  first boot, where they can still be edited by hand (or from RetroArch's
  menu). RetroArch's menu confirms with A, as on the 3DS.
- Graphical interface (PySide6), organised as a project library like
  NSUI's, and a command line.

## Install

**Debian, Ubuntu (two latest LTS) and Fedora (two latest releases),
`amd64`/`arm64`:** download the package for your system from the
[latest release](https://github.com/manu-romero-411/3ds-new-retroarch-forwarder/releases/latest)
and install it with your package manager:

```bash
sudo apt install ./3ds-new-retroarch-forwarder_*~ubuntu24.04_amd64.deb
sudo dnf install ./3ds-new-retroarch-forwarder-*.fc43.x86_64.rpm
```

It adds *3DS RetroArch Injector* to the application menu. `makerom`,
`bannertool` and the RetroArch bases are inside the package, built for that
system and architecture.

**Anything else (Fedora Atomic, Bazzite, SteamOS, Arch, openSUSE...):** use
`install.sh`. It uses podman if you have it or installs Docker, compiles the
tools in a container of your own distribution and version (statically in
Alpine for distributions it does not know), and installs the program in a
private virtual environment. Python 3.11+ is required.

```bash
curl -fsSL https://raw.githubusercontent.com/manu-romero-411/3ds-new-retroarch-forwarder/main/install.sh | bash
# options: --system, --version vX.Y.Z, --static, --download-bases, --no-gui, --uninstall
```

**Any Linux desktop, no installation:** download
`3DS_Forwarder-*-x86_64.AppImage` (or `aarch64`), make it executable and
double-click it. `./3DS_Forwarder-*.AppImage --cli ...` runs the command
line tool.

**Windows 10/11 (x64):** unzip `3DS_Forwarder-*-windows-x64.zip` anywhere and
run `3DS Forwarder.exe`; `cli\3ds-forwarder.exe` is the command line tool.

See [packaging/README.md](packaging/README.md) for how packages are built.

## Graphical interface

```bash
3ds-forwarder-gui
```

It is organised like New Super Ultimate Injector: a **library** of
projects and one **tab** per project being edited.

- **Library**: every project grouped by console (with counts), a search
  box, *Select all*, and *Open*, *Delete*, *Export…* (settings and artwork,
  not ROMs) and *Generate CIA* for the ticked projects (built one after the
  other into the output folder). *New project from ROM…* starts one;
  *Import…* takes an export file or a game CIA built by this tool (its ROM
  is copied out, it keeps its Title ID).
- **Project tab**, left: *Game information* (the ROM, its console and its
  libretro database match, which can be changed by hand), *CIA metadata*
  (long and short names, publisher, icon from a file or SteamGridDB) and
  *Content options* (core, save folder, **Injection options…**). Right:
  *CIA header* (Title ID, *Auto* or typed, *Random*; hide from the
  Activity Log) and *CIA banner* (style: the game's logo over a tag with a
  pixel-art console and the year, SteamGridDB hero + logo, libretro title
  screen or screenshot, or an image file; preview; jingle). The default
  banner's colours and font are in Settings › Banner. Its console icons
  are PNGs in `src/forwarder3ds/data/console_icons/` (`<console>.png`,
  `generic.png` for the rest), and each project can pick any other image.
- **Injection options**: screen (pixel perfect, recommended, full screen
  400x240 or a custom size; bilinear filter), bezel, **button mapping** (on
  a picture of the 3DS: what each button does in the game; the menu keeps
  the 3DS layout and opens from the touch screen) and **core options** (the
  core's own option list, value by value).

Projects save themselves as you edit them. Names, publisher and save
folder follow the database match until you change them.

**Settings** holds everything configured once: default manufacturer, output
folder, Title ID registry, the SteamGridDB key and filters,
the toolchain (with overrides) and your own jingle and logo folders.

## Command line

```bash
3ds-forwarder build --rom "Super Mario World (USA).sfc" --steamgriddb --jingle smw_coin
3ds-forwarder build --rom "Castlevania (USA).chd" --console psx   # .chd: say which console
3ds-forwarder build ... --core snes9x2005 --folder "SMW" --long-name "Super Mario World"
3ds-forwarder build ... --icon icon.png --hero hero.png --logo logo.png --platform-logo snes
3ds-forwarder build ... --bezel snes-frame.png   # top screen bezel
3ds-forwarder build ... --alt-bezel gb-frame.png  # START/SELECT at boot: pixel perfect in it
3ds-forwarder build ... --screen custom:360x240 --smooth   # or pixel_perfect, recommended, full
3ds-forwarder build --rom game.gb --identify    # names and publisher from the libretro database
3ds-forwarder identify game.gb                  # what the libretro database says about a ROM
3ds-forwarder build ... --dry-run               # only print the Title ID and save folder
3ds-forwarder build --from-cia game.cia --short-name "SMW"   # rebuild, same Title ID
3ds-forwarder inspect game.cia [--extract DIR]  # what a game CIA contains (and its ROM)
3ds-forwarder cores                             # consoles, their cores, bases built
3ds-forwarder media                             # jingles and platform logos
3ds-forwarder doctor                            # toolchain and SteamGridDB key
3ds-forwarder config                            # settings (secrets masked)
```

`--steamgriddb` takes the first icon, hero and logo of the matching game
(`--sgdb-game ID` forces the game). Without artwork a plain placeholder is
used. Images of any size are stretched (never cropped) to 48×48 and 256×128.

## Configuration

Settings live in `~/.config/3ds-forwarder/config.ini` (owner-only
permissions: it holds the SteamGridDB key). The API key of the previous,
unpackaged UI is imported on first run.

| Data | Location |
|---|---|
| Title ID registry | `~/.local/share/3ds-forwarder/title_id_registry.json` (configurable) |
| Your jingles | `~/.local/share/3ds-forwarder/jingles/` |
| Your platform logos | `~/.local/share/3ds-forwarder/platform_logos/` |

Jingles must be 16-bit PCM WAVs of at most 3 s; platform logos 256×128 PNGs
with transparency. Other audio files can be used with `--audio` (needs
`ffmpeg`).

## Deterministic Title IDs

A 3DS Title ID is `(0x00040000 << 32) | (UniqueId << 8) | Variation`; the
only part a game CIA chooses is the 20-bit `UniqueId`. The RetroArch core
CIAs already use `0xBAC00`–`0xBACFF` (see `cores.json`), so game CIAs never
touch that block.

The `UniqueId` is derived from a SHA-256 of the fields that identify the
game (name, short name, long name, manufacturer, core and save folder),
inside a block of its own (`0xF0000`–`0xFFFFF`):

- **Deterministic**: the same fields always give the same ID, on any
  machine, without a shared counter.
- **No known collision**: every ID handed out is recorded in the registry
  with the key that produced it. Seen fields reuse their ID; if a hash lands
  on an ID used by another game or a core, a deterministic nonce is
  added until a free one is found, so only the colliding game changes.

Nintendo does not publish the ranges of retail titles, so no unofficial tool
can guarantee zero collisions; this one avoids the known core block and
keeps an auditable record. Point several computers at the same (synced)
registry file to keep the guarantee across them.

## Development

```bash
pip install -e '.[gui,dev]'
packaging/toolchain/build-tools.sh toolchain   # makerom + bannertool for this machine
packaging/toolchain/build-base.sh toolchain all  # bases (devkitARM via docker/podman)
3ds-forwarder doctor
pylint src/forwarder3ds tests scripts packaging/targets.py
QT_QPA_PLATFORM=offscreen pytest
```

A git checkout finds `./toolchain/` by itself (it is git-ignored).

**Releasing** is only pushing a tag on `main`; the tag is the version, there
is no version number to edit anywhere:

```bash
git push origin main
git tag v0.3.0 && git push origin v0.3.0
```

```
src/forwarder3ds/
├── cli.py              command line
├── core/               Title IDs, catalogs, projects, core options, game settings, paths
├── ctr/                3DS formats: CIA reader, SMDH/banner decoders, PNG
├── builder/            build pipeline, image/audio preparation, toolchain lookup
├── artwork/            SteamGridDB client, banner compositor
├── gui/                Qt interface (library, project tabs, dialogs)
└── data/               cores.json, systems.json, RSF, seed retroarch.cfg, jingles, logos...
retroarch/              RetroArch patches and core recipes for the bases
scripts/                maintainer tools: refresh cores.json
packaging/              toolchain builds, .deb/.rpm, CI scripts, release targets
install.sh              installer for systems without a package
```

To refresh the core list after a RetroArch update:

```bash
python3 scripts/parse_retroarch_cores.py <RetroArch>/pkg/ctr/Makefile.cores > src/forwarder3ds/data/cores.json
```

### Design notes

- Each base records the memory mode (`APP_SYSTEM_MODE`, `APP_SYSTEM_MODE_EXT`)
  RetroArch's `pkg/ctr/Makefile.cores` gives its core, and every CIA built
  from it asks for exactly that.
- No ticket has to be forged: `makerom` writes a valid one, enough to
  install with FBI under Luma3DS (which patches signature checks).
- The CIA content is stored unencrypted (`EnableCrypt: false`), which is
  what lets `inspect` and *Open…* read game CIAs back.

## Licence

GPL-3.0-only. The bundled `makerom` and `bannertool` are MIT-licensed; their
licences are installed with them. RetroArch is GPL-3.0; each core keeps its
own licence (some, such as snes9x, are non-commercial).

## Credits

- Console icons on the default banner: [Console Icon Pack](https://benjelter.itch.io/console-icon-pack)
  by BenJelter (see [`console_icons/CREDITS.md`](src/forwarder3ds/data/console_icons/CREDITS.md)).
