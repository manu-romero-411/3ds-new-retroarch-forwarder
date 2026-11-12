#!/usr/bin/env bash
# Build a self-contained AppImage: double-click it to open the GUI.
#
#   packaging/appimage/build-appimage.sh            (in ubuntu:22.04, as root)
#
# The AppImage carries its own Python (python-build-standalone, through uv),
# the program with PySide6-Essentials, statically linked makerom and
# bannertool, and the RetroArch bases from BASES_DIR (default:
# dist-bases/retroarch-bases.tar.gz). It needs nothing installed but a
# desktop (glibc 2.28 or newer, as PySide6's wheels).
#
#   ./3DS_Forwarder-x86_64.AppImage                 the GUI
#   ./3DS_Forwarder-x86_64.AppImage --cli build ... the command line tool
#
# PACKAGE_VERSION (the tag without "v") names the file; HOST_UID/HOST_GID,
# if set, become the owners of build/ and dist/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=packaging/common.sh
source "${HERE}/../common.sh"
# shellcheck source=packaging/pyside6-prune.sh
source "${HERE}/../pyside6-prune.sh"

readonly PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
# The newest PySide6 that runs on the build system's glibc (2.35): on x86_64
# that is this version; on aarch64 the newer wheels need glibc 2.39, so pip
# settles for an older one (6.8), which keeps Raspberry Pi OS and the like.
readonly PYSIDE_VERSION="${PYSIDE_VERSION:-6.12.0}"
readonly APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous"
readonly BASES_ARCHIVE="retroarch-bases.tar.gz"

restore_ownership() {
    if [[ -n "${HOST_UID:-}" ]]; then
        chown -R "${HOST_UID}:${HOST_GID:-${HOST_UID}}" "${BUILD_DIR}" "${DIST_DIR}" 2> /dev/null || true
    fi
}
trap restore_ownership EXIT

install_build_deps() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q --no-install-recommends \
        build-essential git ca-certificates curl file librsvg2-bin python3 python3-pip \
        libegl1 libgl1 libfontconfig1 libxkbcommon0 libdbus-1-3 libglib2.0-0
}

# A relocatable Python in $1/usr/python, with the program and PySide6.
install_python() {
    local appdir="$1" python
    python3 -m pip install --quiet --break-system-packages uv 2> /dev/null \
        || python3 -m pip install --quiet uv
    python3 -m uv python install "${PYTHON_VERSION}" --install-dir "${BUILD_DIR}/uv-python"
    python="$(find "${BUILD_DIR}/uv-python" -maxdepth 1 -type d -name "cpython-${PYTHON_VERSION}*" | head -1)"
    [[ -n "${python}" ]] || die "uv did not install Python ${PYTHON_VERSION}"
    mkdir -p "${appdir}/usr"
    cp -a "${python}" "${appdir}/usr/python"
    # uv marks its Pythons as externally managed (PEP 668); this copy is ours.
    find "${appdir}/usr/python/lib" -maxdepth 2 -name EXTERNALLY-MANAGED -delete

    log_info "Installing the program and PySide6-Essentials (at most ${PYSIDE_VERSION})"
    "${appdir}/usr/python/bin/python3" -m pip install --quiet --no-compile --no-warn-script-location \
        "${REPO_ROOT}" "PySide6-Essentials>=6.6,<=${PYSIDE_VERSION}"
    local site
    site="$("${appdir}/usr/python/bin/python3" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    printf '__version__ = "%s"\n' "$(package_version)" > "${site}/${MODULE}/_version.py"
    prune_pyside6 "${site}/PySide6"
    find "${appdir}/usr/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
    rm -rf "${appdir}/usr/python/share" "${appdir}/usr/python/include"
}

install_toolchain() {
    local appdir="$1" bases_dir="${BASES_DIR:-${REPO_ROOT}/dist-bases}"
    [[ -f "${bases_dir}/${BASES_ARCHIVE}" ]] || die "${BASES_ARCHIVE} not found in ${bases_dir}"
    "${REPO_ROOT}/packaging/toolchain/build-tools.sh" --static "${appdir}/toolchain"
    tar -C "${appdir}/toolchain" -xzf "${bases_dir}/${BASES_ARCHIVE}"
    if [[ -f "${appdir}/toolchain/bases/VERSIONS" ]]; then
        cat "${appdir}/toolchain/bases/VERSIONS" >> "${appdir}/toolchain/VERSIONS"
    fi
}

write_apprun() {
    cat > "$1/AppRun" << 'EOF'
#!/bin/sh
# 3DS Forwarder: the GUI, or the command line tool with --cli.
HERE="$(dirname "$(readlink -f "$0")")"
export FORWARDER3DS_TOOLCHAIN="${HERE}/toolchain"
PYTHON="${HERE}/usr/python/bin/python3"
if [ "$1" = "--cli" ]; then
    shift
    exec "${PYTHON}" -m forwarder3ds "$@"
fi
exec "${PYTHON}" -m forwarder3ds.gui.app "$@"
EOF
    chmod 0755 "$1/AppRun"
}

write_desktop_entry() {
    local appdir="$1"
    sed -e 's/^Exec=.*/Exec=AppRun/' "${REPO_ROOT}/packaging/linux/${APP_ID}.desktop" \
        > "${appdir}/${APP_ID}.desktop"
    rsvg-convert --width 256 --height 256 "${ICON_SVG}" --output "${appdir}/${APP_ID}.png"
    install_icons "${appdir}/usr/share/icons/hicolor"
    install -D -m 0644 "${REPO_ROOT}/packaging/linux/${APP_ID}.metainfo.xml" \
        "${appdir}/usr/share/metainfo/${APP_ID}.appdata.xml"
}

pack() {
    local appdir="$1" arch="$2" tool="${BUILD_DIR}/appimagetool"
    curl -fsSL -o "${tool}" "${APPIMAGETOOL_URL}/appimagetool-${arch}.AppImage"
    chmod 0755 "${tool}"
    mkdir -p "${DIST_DIR}"
    # No FUSE in containers: let appimagetool run from its extracted self.
    APPIMAGE_EXTRACT_AND_RUN=1 ARCH="${arch}" "${tool}" --no-appstream "${appdir}" \
        "${DIST_DIR}/3DS_Forwarder-$(package_version)-${arch}.AppImage"
}

main() {
    local arch appdir
    arch="$(uname -m)"
    appdir="${BUILD_DIR}/AppDir"
    install_build_deps
    rm -rf "${appdir}"
    mkdir -p "${appdir}"
    install_python "${appdir}"
    install_toolchain "${appdir}"
    write_apprun "${appdir}"
    write_desktop_entry "${appdir}"
    pack "${appdir}" "${arch}"
    log_ok "AppImage ready in ${DIST_DIR}"
}

main "$@"
