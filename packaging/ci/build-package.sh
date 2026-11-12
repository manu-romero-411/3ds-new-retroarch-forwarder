#!/usr/bin/env bash
# Build the package of one target inside that target's own container.
#
#   packaging/ci/build-package.sh deb debian13      (in debian:13)
#   packaging/ci/build-package.sh deb ubuntu24.04   (in ubuntu:24.04)
#   packaging/ci/build-package.sh rpm fc43          (in fedora:43)
#
# Runs as root in a throw-away container whose system and architecture are
# the package's: installs the build dependencies, compiles makerom and
# bannertool there, adds the RetroArch bases from BASES_DIR (default:
# dist-bases/retroarch-bases.tar.gz, built once by the workflow) and builds
# the package into dist/. When the
# distribution has no PySide6 (Ubuntu 24.04), PySide6-Essentials is bundled.
# HOST_UID/HOST_GID, if set, become the owners of build/ and dist/;
# PACKAGE_VERSION (the tag without "v") is passed on to the package build.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
readonly HERE REPO_ROOT
readonly BASES_ARCHIVE="retroarch-bases.tar.gz"
readonly PYSIDE_VERSION="${PYSIDE_VERSION:-6.12.0}"

log() {
    printf '%s %s %s\n' "$1" "$(date '+%Y-%m-%d_%H:%M:%S')" "${*:2}" >&2
}
die() {
    log "[ERR ]" "$@"
    exit 1
}

restore_ownership() {
    if [[ -n "${HOST_UID:-}" ]]; then
        chown -R "${HOST_UID}:${HOST_GID:-${HOST_UID}}" \
            "${REPO_ROOT}/build" "${REPO_ROOT}/dist" 2> /dev/null || true
    fi
}
trap restore_ownership EXIT

install_deb_build_deps() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q --no-install-recommends \
        build-essential git ca-certificates dpkg-dev librsvg2-bin python3 python3-pip
}

install_rpm_build_deps() {
    dnf install -y -q --setopt=install_weak_deps=False \
        gcc gcc-c++ make git rpm-build librsvg2-tools python3 findutils
}

# True when apt can install the Qt for Python modules the GUI needs.
distro_has_pyside6() {
    apt-cache show python3-pyside6.qtwidgets > /dev/null 2>&1 \
        && apt-cache show python3-pyside6.qtsvg > /dev/null 2>&1
}

vendor_pyside6() {
    local vendor="$1"
    log "[INFO]" "No PySide6 in this release: bundling PySide6-Essentials ${PYSIDE_VERSION}"
    rm -rf "${vendor}"
    python3 -m pip install --quiet --no-compile --break-system-packages \
        --target "${vendor}" "PySide6-Essentials==${PYSIDE_VERSION}"
    rm -rf "${vendor:?}/bin" "${vendor:?}"/*.dist-info/RECORD
    find "${vendor}" -name '__pycache__' -type d -prune -exec rm -rf {} +
    prune_pyside6 "${vendor}/PySide6"
}

# prune_pyside6 (shared with the AppImage build).
# shellcheck source=packaging/pyside6-prune.sh
source "${REPO_ROOT}/packaging/pyside6-prune.sh"

main() {
    [[ $# -eq 2 ]] || die "Usage: build-package.sh deb|rpm SUFFIX"
    local format="$1" suffix="$2" arch toolchain vendor=""
    local bases_dir="${BASES_DIR:-${REPO_ROOT}/dist-bases}"
    [[ -f "${bases_dir}/${BASES_ARCHIVE}" ]] || die "${BASES_ARCHIVE} not found in ${bases_dir}"
    arch="$(uname -m)"
    toolchain="${REPO_ROOT}/build/toolchain-${suffix}-${arch}"

    case "${format}" in
        deb) install_deb_build_deps ;;
        rpm) install_rpm_build_deps ;;
        *) die "Unknown format: ${format}" ;;
    esac

    rm -rf "${toolchain}"
    "${REPO_ROOT}/packaging/toolchain/build-tools.sh" "${toolchain}"
    tar -xzf "${bases_dir}/${BASES_ARCHIVE}" -C "${toolchain}"
    if [[ -f "${toolchain}/bases/VERSIONS" ]]; then
        cat "${toolchain}/bases/VERSIONS" >> "${toolchain}/VERSIONS"
        rm "${toolchain}/bases/VERSIONS"
    fi

    case "${format}" in
        deb)
            if ! distro_has_pyside6; then
                vendor="${REPO_ROOT}/build/vendor-${suffix}-${arch}"
                vendor_pyside6 "${vendor}"
            fi
            "${REPO_ROOT}/packaging/build-deb.sh" --toolchain "${toolchain}" \
                --suffix "${suffix}" ${vendor:+--vendor "${vendor}"}
            ;;
        rpm)
            "${REPO_ROOT}/packaging/build-rpm.sh" --toolchain "${toolchain}"
            ;;
    esac
}

main "$@"
