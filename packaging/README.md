# Packaging

A forwarder build runs two native programs, `makerom` and `bannertool`, and
repackages a stub compiled with devkitARM. The packages therefore ship a
small **toolchain** next to the Python code, built for each distribution and
architecture, so nothing else (and no Docker) is needed at run time.

## Layout on disk

`.deb` and `.rpm` install the same files:

| Path | Contents |
|---|---|
| `/opt/3ds-new-retroarch-forwarder/lib/forwarder3ds/` | Python package (byte-compiled on install) |
| `/opt/3ds-new-retroarch-forwarder/toolchain/bin/` | `makerom`, `bannertool` |
| `/opt/3ds-new-retroarch-forwarder/toolchain/stub/` | `3ds-forwarder-stub.elf` |
| `/opt/3ds-new-retroarch-forwarder/toolchain/VERSIONS` | source revisions of the three |
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

File names carry the distribution, e.g.
`3ds-new-retroarch-forwarder_0.1.0-1~ubuntu24.04_arm64.deb` or
`3ds-new-retroarch-forwarder-0.1.0-1.fc43.aarch64.rpm`.

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
- the **stub** from `stub/` with the `devkitpro/devkitarm` image.

Their licences are installed in `toolchain/LICENSES/`.

## Building locally

```bash
# Toolchain for this machine, found automatically by a git checkout:
packaging/toolchain/build-tools.sh toolchain        # makerom + bannertool
packaging/toolchain/build-stub.sh toolchain         # stub, via docker/podman

# A package for this machine's distribution (as root, ideally in a container
# of the target distribution; the stub comes from dist-stub/):
mkdir -p dist-stub && cp toolchain/stub/3ds-forwarder-stub.elf dist-stub/
packaging/ci/build-package.sh deb debian13           # in debian:13
packaging/ci/build-package.sh rpm fc43               # in fedora:43
packaging/ci/smoke-test.sh dist/<package>            # in a clean container
```

`PACKAGE_RELEASE` (default `1`) and `PACKAGE_MAINTAINER` can be set in the
environment. The version always comes from `src/forwarder3ds/__init__.py`.

## Releases (GitHub Actions)

`.github/workflows/release.yml` runs only when a tag `vX.Y.Z` is pushed;
ordinary commits do not trigger it. It then:

1. checks that the tag points at a commit of `main` and matches
   `__version__`, that `stub/source/cores_table.h` matches `cores.json`, and
   runs pylint, pytest and shellcheck;
2. works out the target distributions (`targets.py`);
3. compiles the stub once (it is an ARM11 binary for the console, the same
   whatever builds it);
4. for every distribution and architecture, on a GitHub runner of that
   architecture (`ubuntu-24.04` / `ubuntu-24.04-arm`) and inside a container
   of that distribution: compiles `makerom` and `bannertool`, builds the
   package, then installs it in a clean container, **builds a real forwarder
   with it**, reads it back, opens the main window off-screen and removes the
   package again;
5. publishes a GitHub release with every package, `install.sh`, the stub and
   a `SHA256SUMS` file.

The maintainer field can be changed with the repository variable
`PACKAGE_MAINTAINER`.

## install.sh

For systems without a matching package (immutable ones such as Fedora
Atomic, Bazzite or SteamOS, Arch, openSUSE...). It uses podman if present or
installs Docker, compiles `makerom` and `bannertool` in a container of the
same distribution and version as the host (Debian, Ubuntu, Fedora and their
derivatives) or statically in Alpine otherwise, compiles the stub with
devkitARM (falling back to the release's `3ds-forwarder-stub.elf`), and
installs the program in a private virtual environment with the toolchain
next to it. See `./install.sh --help`.

## Icon

The only icon file in the repository is the SVG
`src/forwarder3ds/data/icons/io.github.manu_romero_411.forwarder3ds.svg`,
organised in named Inkscape layers. Edit it directly: the package build and
`install.sh` render the PNG sizes with `rsvg-convert`, and the application
renders it with QtSvg when the theme icon is not installed. Keep it
renderable by Qt's SVG engine (no masks or clip paths).
