#!/usr/bin/env bash
# Build the Windows x64 version: a portable folder, zipped.
#
#   packaging/windows/build-windows.sh TOOLS_DIR
#
# Runs in Git Bash on Windows with Python 3.11+ on PATH. TOOLS_DIR holds
# bin/makerom.exe and bin/bannertool.exe, built beforehand in an MSYS2
# MINGW64 shell with:
#
#   packaging/toolchain/build-tools.sh --static TOOLS_DIR
#
# The RetroArch bases come from BASES_DIR (default:
# dist-bases/retroarch-bases.tar.gz): they are console binaries, the same
# for every system. The result, dist/3DS_Forwarder-<version>-windows-x64.zip,
# unzips to a folder with "3DS Forwarder.exe" (the GUI), 3ds-forwarder.exe
# (the command line tool) and toolchain/. PACKAGE_VERSION (the tag without
# "v") is the version.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=packaging/common.sh
source "${HERE}/../common.sh"

readonly PYSIDE_VERSION="${PYSIDE_VERSION:-6.12.0}"
readonly BASES_ARCHIVE="retroarch-bases.tar.gz"
readonly VERSION_FILE="${REPO_ROOT}/src/${MODULE}/_version.py"

remove_version_file() {
    rm -f "${VERSION_FILE}"
}

main() {
    local tools="${1:-}" bases_dir="${BASES_DIR:-${REPO_ROOT}/dist-bases}" version folder zip
    [[ -n "${tools}" ]] || die "Usage: build-windows.sh TOOLS_DIR"
    [[ -f "${tools}/bin/makerom.exe" && -f "${tools}/bin/bannertool.exe" ]] \
        || die "makerom.exe and bannertool.exe not found in ${tools}/bin"
    [[ -f "${bases_dir}/${BASES_ARCHIVE}" ]] || die "${BASES_ARCHIVE} not found in ${bases_dir}"
    version="$(package_version)"

    # The installed program reads its version from here (see version.py).
    trap remove_version_file EXIT
    printf '__version__ = "%s"\n' "${version}" > "${VERSION_FILE}"
    log_info "Installing the program, PySide6 ${PYSIDE_VERSION} and PyInstaller"
    python -m pip install --quiet "${REPO_ROOT}" "PySide6==${PYSIDE_VERSION}" pyinstaller

    log_info "Freezing with PyInstaller"
    python -m PyInstaller --noconfirm --clean \
        --distpath "${BUILD_DIR}/windows-dist" --workpath "${BUILD_DIR}/windows-work" \
        "${HERE}/forwarder3ds.spec"
    folder="${BUILD_DIR}/windows-dist/3DS Forwarder"

    mkdir -p "${folder}/toolchain"
    cp -r "${tools}/." "${folder}/toolchain/"
    tar -C "${folder}/toolchain" -xzf "${bases_dir}/${BASES_ARCHIVE}"
    if [[ -f "${folder}/toolchain/bases/VERSIONS" ]]; then
        cat "${folder}/toolchain/bases/VERSIONS" >> "${folder}/toolchain/VERSIONS"
    fi
    cp "${REPO_ROOT}/LICENSE" "${folder}/LICENSE.txt"

    mkdir -p "${DIST_DIR}"
    zip="${DIST_DIR}/3DS_Forwarder-${version}-windows-x64.zip"
    rm -f "${zip}"
    (cd "${BUILD_DIR}/windows-dist" && 7z a -tzip -mx=9 "${zip}" "3DS Forwarder" > /dev/null)
    log_ok "Windows build ready: ${zip}"
}

main "$@"
