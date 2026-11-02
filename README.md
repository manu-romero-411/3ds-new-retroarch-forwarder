# 3ds-new-retroarch-forwarder

Builds one installable **CIA per game** for a 3DS running Luma3DS. Each
forwarder shows its own icon, banner and jingle on the HOME menu and launches
the game directly with the matching RetroArch core, **without bundling a
whole RetroArch** in every CIA (unlike New Super Ultimate Injector).

- A stub compiled once with devkitARM is repackaged per game with a RomFS
  holding the core name and the ROM path, and a **deterministic,
  collision-checked Title ID**. Nothing is compiled per game.
- On first launch the forwarder installs the core's CIA from
  `sdmc:/retroarch/cores/` if it is not installed yet, then jumps to it.
- Artwork comes from **SteamGridDB** (icon, hero and logo; the banner is the
  hero with the logo on top), or from your own image files.
- Existing forwarders can be opened, edited and rebuilt under the same
  Title ID, so the new CIA installs over the old one.
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

It adds *3DS Forwarder* to the application menu. `makerom`, `bannertool` and
the stub are inside the package, built for that system and architecture.

**Anything else (Fedora Atomic, Bazzite, SteamOS, Arch, openSUSE...):** use
`install.sh`. It uses podman if you have it or installs Docker, compiles the
tools in a container of your own distribution and version (statically in
Alpine for distributions it does not know), and installs the program in a
private virtual environment. Python 3.11+ is required.

```bash
curl -fsSL https://raw.githubusercontent.com/manu-romero-411/3ds-new-retroarch-forwarder/main/install.sh | bash
# options: --system, --version vX.Y.Z, --static, --download-stub, --no-gui, --uninstall
```

See [packaging/README.md](packaging/README.md) for how packages are built.

## Graphical interface

```bash
3ds-forwarder-gui
```

The window goes from general to specific:

1. **Game** (left): the RetroArch core, the ROM path on the SD card
   (*Browse SD…* picks it on a mounted card) and the names shown on the HOME
   menu. The names follow the ROM's file name until you edit them.
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
folder, SD card folder, Title ID registry, the SteamGridDB key and filters,
the toolchain (with overrides) and your own jingle and logo folders.

## Command line

```bash
3ds-forwarder build --core snes9x2005 --rom "roms/snes/Super Mario World (USA).sfc" \
    --long-name "Super Mario World" --steamgriddb --jingle smw_coin
3ds-forwarder build ... --icon icon.png --hero hero.png --logo logo.png --platform-logo snes
3ds-forwarder build ... --dry-run               # only print the Title ID
3ds-forwarder build --from-cia game.cia --short-name "SMW"   # rebuild, same Title ID
3ds-forwarder inspect game.cia [--extract DIR]  # what a forwarder contains
3ds-forwarder cores snes                        # cores that can be forwarded
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
only part a forwarder chooses is the 20-bit `UniqueId`. The RetroArch core
CIAs already use `0xBAC00`–`0xBACFF` (see `cores.json`), so forwarders never
touch that block.

The `UniqueId` is derived from a SHA-256 of the fields that identify the
forwarder (name, short name, long name, manufacturer, core and ROM path),
inside a block of its own (`0xF0000`–`0xFFFFF`):

- **Deterministic**: the same fields always give the same ID, on any
  machine, without a shared counter.
- **No known collision**: every ID handed out is recorded in the registry
  with the key that produced it. Seen fields reuse their ID; if a hash lands
  on an ID used by another forwarder or a core, a deterministic nonce is
  added until a free one is found, so only the colliding game changes.

Nintendo does not publish the ranges of retail titles, so no unofficial tool
can guarantee zero collisions; this one avoids the known core block and
keeps an auditable record. Point several computers at the same (synced)
registry file to keep the guarantee across them.

## Development

```bash
pip install -e '.[gui,dev]'
packaging/toolchain/build-tools.sh toolchain   # makerom + bannertool for this machine
packaging/toolchain/build-stub.sh toolchain    # stub (devkitARM via docker/podman)
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
├── core/               Title IDs, core catalog, names, SD card, settings, paths
├── ctr/                3DS formats: CIA reader, SMDH/banner decoders, PNG
├── builder/            build pipeline, image/audio preparation, toolchain lookup
├── artwork/            SteamGridDB client, banner compositor
├── gui/                Qt interface (main window, panels, dialogs)
└── data/               cores.json, RSF template, jingles, logos, icon, 3DS frame
stub/                   the stub (C, devkitARM); cores_table.h is generated
scripts/                maintainer tools: refresh cores.json / cores_table.h
packaging/              toolchain builds, .deb/.rpm, CI scripts, release targets
install.sh              installer for systems without a package
```

To refresh the core list after a RetroArch update:

```bash
python3 scripts/parse_retroarch_cores.py <RetroArch>/pkg/ctr/Makefile.cores > src/forwarder3ds/data/cores.json
python3 scripts/generate_cores_table.py src/forwarder3ds/data/cores.json > stub/source/cores_table.h
```

### Design notes

- `APP_SYSTEM_MODE_EXT` is declared by the **core's** `.3dsx`, not the stub.
  For PSX (PCSX ReARMed) check the value of the official build in RetroArch's
  `pkg/ctr/Makefile.cores` before relying on a different one.
- No ticket has to be forged: `makerom` writes a valid one, enough to
  install with FBI under Luma3DS (which patches signature checks).
- The CIA content is stored unencrypted (`EnableCrypt: false`), which is
  what lets `inspect` and *Open…* read forwarders back.

## Licence

GPL-3.0-only. The bundled `makerom` and `bannertool` are MIT-licensed; their
licences are installed with them.
