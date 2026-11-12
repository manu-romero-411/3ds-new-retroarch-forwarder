# Packaging

A game build runs two native programs, `makerom` and `bannertool`, and
repackages one of the RetroArch **bases** (RetroArch + one core, compiled
with devkitARM). The packages therefore ship a **toolchain** next to the
Python code, built for each distribution and architecture, so nothing else
(and no Docker) is needed at run time.

## Layout on disk

`.deb` and `.rpm` install the same files:

| Path | Contents |
|---|---|
| `/opt/3ds-new-retroarch-forwarder/lib/forwarder3ds/` | Python package (byte-compiled on install) |
| `/opt/3ds-new-retroarch-forwarder/toolchain/bin/` | `makerom`, `bannertool` |
| `/opt/3ds-new-retroarch-forwarder/toolchain/bases/<core>/` | `retroarch.elf`, `base.env`, assets |
| `/opt/3ds-new-retroarch-forwarder/toolchain/VERSIONS` | source revisions of all of them |
| `/opt/3ds-new-retroarch-forwarder/vendor/` | PySide6, only where the distribution lacks it |
| `/usr/bin/3ds-forwarder`, `/usr/bin/3ds-forwarder-gui` | launchers using the system `python3` |
| `/usr/share/applications/io.github.manu_romero_411.forwarder3ds.desktop` | menu entry |
| `/usr/share/icons/hicolor/*/apps/io.github.manu_romero_411.forwarder3ds.*` | icon (SVG + PNG sizes) |
| `/usr/share/metainfo/io.github.manu_romero_411.forwarder3ds.metainfo.xml` | AppStream data |

The program finds the toolchain on its own (`3ds-forwarder doctor` shows
where); see `src/forwarder3ds/builder/toolchain.py` for the search order.

## Targets

Computed on every release by [`targets.py`](targets.py), so new distribution
releases are picked up without editing anything:

| Format | Distributions | Architectures |
|---|---|---|
| `.deb` | Debian stable; the two newest supported Ubuntu LTS | `amd64`, `arm64` |
| `.rpm` | the two newest stable Fedora releases | `x86_64`, `aarch64` |
| AppImage | any Linux desktop with glibc 2.28+ (built on Ubuntu 22.04) | `x86_64`, `aarch64` |
| `.zip` | Windows 10/11 (portable folder) | `x64` |

File names carry the distribution, e.g.
`3ds-new-retroarch-forwarder_0.1.0-1~ubuntu24.04_arm64.deb` or
`3ds-new-retroarch-forwarder-0.1.0-1.fc43.aarch64.rpm`.

## AppImage

[`appimage/build-appimage.sh`](appimage/build-appimage.sh), run as root in
`ubuntu:22.04`, puts everything in one file that opens the GUI when
double-clicked: its own Python (python-build-standalone, installed with
`uv`), the program with a trimmed PySide6-Essentials, statically linked
`makerom` and `bannertool`, and the RetroArch bases. `AppRun` points the
program at the bundled toolchain (`FORWARDER3DS_TOOLCHAIN`); `--cli` as the
first argument runs the command line tool instead
(`./3DS_Forwarder-*.AppImage --cli build ...`). The jingle preview plays
through `pw-play`, `paplay` or `aplay`, as with the bundled PySide6 of the
`.deb`s.

## Windows

[`windows/build-windows.sh`](windows/build-windows.sh) runs in Git Bash on
Windows after `toolchain/build-tools.sh --static` has built `makerom.exe`
and `bannertool.exe` in an MSYS2 MINGW64 shell. It freezes the program with
PyInstaller ([`windows/forwarder3ds.spec`](windows/forwarder3ds.spec)) into
a folder holding `3DS Forwarder.exe` (the GUI, no console window; with no
console its log goes to `%LOCALAPPDATA%\3ds-forwarder\3ds-forwarder.log`),
`toolchain/` (the two programs and the RetroArch bases) and
`cli/3ds-forwarder.exe` (the command line tool, built without Qt), and zips
it.
Settings and data go to `%APPDATA%\3ds-forwarder`, the cache to
`%LOCALAPPDATA%\3ds-forwarder`. Fonts are looked up in the Windows font
folders (there is no fontconfig).

## Dependencies

| | Debian / Ubuntu | Fedora |
|---|---|---|
| Required | `python3 (>= 3.11)`, `python3-requests`, `python3-pil`, PySide6 (`python3-pyside6.qtcore/qtgui/qtwidgets/qtsvg`) | `python3`, `python3-requests`, `python3-pillow`, `python3-pyside6` |
| Recommended | `ffmpeg`, `python3-pyside6.qtmultimedia`, `qt6-wayland` | `ffmpeg-free` or `ffmpeg`, `qt6-qtwayland` |

`ffmpeg` is only needed for jingles that are not 16-bit PCM WAVs. Where the
distribution has no PySide6 (Ubuntu 24.04), the package bundles
`PySide6-Essentials` in `vendor/` (trimmed of QML, Designer and developer
tools) and depends on the Qt runtime libraries instead; the jingle preview
then plays through `pw-play`, `paplay` or `aplay`.

## Toolchain sources

[`toolchain/versions.env`](toolchain/versions.env) pins what is built:

- **makerom** from [3DSGuy/Project_CTR](https://github.com/3DSGuy/Project_CTR) (MIT);
- **bannertool** from [CyberYoshi64/bannertool](https://github.com/CyberYoshi64/bannertool) (MIT);
- the **RetroArch bases**: [RetroArch](https://github.com/libretro/RetroArch)
  (GPL-3.0) patched with `retroarch/patches/` and linked with each core of
  `retroarch/cores/` (each core keeps its own licence), with the
  `devkitpro/devkitarm` image.

Their licences are installed in `toolchain/LICENSES/`.

## Building locally

```bash
# Toolchain for this machine, found automatically by a git checkout:
packaging/toolchain/build-tools.sh toolchain        # makerom + bannertool
packaging/toolchain/build-base.sh toolchain all     # bases, via docker/podman

# A package for this machine's distribution (as root, ideally in a container
# of the target distribution; the bases come from dist-bases/):
mkdir -p dist-bases && cp toolchain/VERSIONS toolchain/bases/VERSIONS
tar -C toolchain -czf dist-bases/retroarch-bases.tar.gz bases
packaging/ci/build-package.sh deb debian13           # in debian:13
packaging/ci/build-package.sh rpm fc43               # in fedora:43
packaging/ci/smoke-test.sh dist/<package>            # in a clean container
```

`PACKAGE_RELEASE` (default `1`) and `PACKAGE_MAINTAINER` can be set in the
environment.

## Version

The version is the git tag and nothing else: no file in the tree holds it.
`v1.2.3` gives `1.2.3`; a commit after it gives `1.2.3+git4.gabc1234`. It
reaches each kind of installation like this:

- **.deb/.rpm**: `common.sh` takes `PACKAGE_VERSION` (the release workflow
  passes the tag) or `git describe`, and writes `forwarder3ds/_version.py`
  into the package;
- **pip / install.sh**: setuptools-scm writes the same file at build time,
  from the git history or, for a GitHub source archive, from
  `.git_archival.txt` (filled in by `git archive` thanks to `.gitattributes`);
- **a plain checkout**: `forwarder3ds/version.py` runs `git describe`.

## Releases (GitHub Actions)

`.github/workflows/release.yml` runs only when a tag `vX.Y.Z` is pushed;
ordinary commits do not trigger it. It then:

1. checks that the tag points at a commit of `main` and looks like a
   version (`v1.2.3`), and runs pylint, pytest and shellcheck;
2. works out the target distributions (`targets.py`);
3. compiles the RetroArch bases once (ARM11 binaries for the console, the
   same whatever builds them);
4. for every distribution and architecture, on a GitHub runner of that
   architecture (`ubuntu-24.04` / `ubuntu-24.04-arm`) and inside a container
   of that distribution: compiles `makerom` and `bannertool`, builds the
   package, then installs it in a clean container, **builds a real game CIA
   with it**, reads it back, opens the main window off-screen and removes the
   package again;
5. builds an AppImage per architecture (in `ubuntu:22.04`) and the Windows
   x64 zip (on `windows-latest`), and checks that each one starts and finds
   its toolchain (`doctor --offline`);
6. publishes a GitHub release with every package, the AppImages, the
   Windows zip, `install.sh`, `retroarch-bases.tar.gz` and a `SHA256SUMS`
   file.

The maintainer field can be changed with the repository variable
`PACKAGE_MAINTAINER`.

## install.sh

For systems without a matching package (immutable ones such as Fedora
Atomic, Bazzite or SteamOS, Arch, openSUSE...). It uses podman if present or
installs Docker, compiles `makerom` and `bannertool` in a container of the
same distribution and version as the host (Debian, Ubuntu, Fedora and their
derivatives) or statically in Alpine otherwise, compiles the RetroArch bases
with devkitARM (falling back to the release's `retroarch-bases.tar.gz`), and
installs the program in a private virtual environment with the toolchain
next to it. See `./install.sh --help`.

## Icon

The only icon file in the repository is the SVG
`src/forwarder3ds/data/icons/io.github.manu_romero_411.forwarder3ds.svg`,
organised in named Inkscape layers. Edit it directly: the package build and
`install.sh` render the PNG sizes with `rsvg-convert`, and the application
renders it with QtSvg when the theme icon is not installed. Keep it
renderable by Qt's SVG engine (no masks or clip paths).
