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
  └── bezel.png           optional: replaces the CIA's bezel (bezel.cfg appears next to it)
  sdmc:/saves/bios/       BIOS files shared by every game
  ```

  `<console>` is Batocera's folder name (`gb`, `snes`, `megadrive`, `psx`...).
- An optional **bezel** over the top screen (`--bezel`, 400x240 with a
  transparent window: a 4:3 game is the middle 320x240), replaceable per
  game by dropping a `bezel.png` in its save folder.
- A trimmed pause menu: the touch screen shows RetroArch's 3DS menu
  (resume, save state, load state) and the Quick Menu keeps only what makes
  sense for one game. CD games are single `.chd` files.
- ROMs are **identified against the libretro database** (No-Intro dats by
  CRC for cartridges, Redump names for discs): title, publisher and year
  fill the CIA's names, and libretro's title screen and snapshot can be
  used as the banner background. Hacks, translations or other revisions are
  flagged and can be matched by hand.
- ROMs can stay zipped, as No-Intro sets come: the zip's ROM is identified
  by the CRC the zip stores and packed uncompressed into the CIA.
- Artwork comes from **SteamGridDB** (icon, hero and logo; the banner is the
  hero with the logo on top), or from your own image files.
- Existing CIAs can be opened, edited and rebuilt under the same Title ID,
  so the new CIA installs over the old one (the ROM is read back from it).
- Graphical interface (PySide6) and a command line with the same features.

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

See [packaging/README.md](packaging/README.md) for how packages are built.

## Graphical interface

```bash
3ds-forwarder-gui
```

The window goes from general to specific:

1. **Game** (left), laid out like New Super Ultimate Injector: *Game
   information* (the ROM, picked with *Open ROM…*, its console and its
   libretro database match, with title screen and snapshot), *CIA metadata*
   (names and publisher) and *Content options* (core, save folder, bezel).
   The console follows the ROM's extension, the core follows the console,
   the names and publisher follow the database (or the file name) and the
   save folder follows the long name, until you edit them.
2. **Presentation** (middle): the **icon**, the **banner** (SteamGridDB hero
   + logo, or a ready-made image, plus an optional platform frame) and the
   **jingle**, with a play button. *SteamGridDB…* searches by the long name;
   when several games match you pick one, then a gallery of thumbnails.
3. **Preview** (right): a 3DS showing the banner on the top screen and the
   icon on the HOME menu grid, exactly as they will be built.

The toolbar holds **New**, **Open…**, **Save** (builds the CIA), **Save As…**,
**Settings** and the **Title ID**, which updates live; untick *Auto* to type a
Unique ID yourself (collisions are flagged). The **Activity** panel at the
bottom shows what is going on and the log; the status bar shows the file
being edited and whether the toolchain is ready.

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
packaging/toolchain/build-base.sh toolchain all  # RetroArch bases (devkitARM via docker/podman)
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
├── core/               Title IDs, core and console catalogs, names, settings, paths
├── ctr/                3DS formats: CIA reader, SMDH/banner decoders, PNG
├── builder/            build pipeline, image/audio preparation, toolchain lookup
├── artwork/            SteamGridDB client, banner compositor
├── gui/                Qt interface (main window, panels, dialogs)
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
