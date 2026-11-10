#!/usr/bin/env bash
# Build one .deb for the system and architecture this runs on.
#
#   packaging/build-deb.sh --toolchain DIR --suffix debian13 [--vendor DIR]
#
# --toolchain   directory made by toolchain/build-tools.sh + build-base.sh
# --suffix      distribution tag appended to the version (debian13, ubuntu24.04...)
# --vendor      bundled Python packages (PySide6) for releases without them;
#               the package then depends on the Qt runtime libraries instead
#
# Output: dist/3ds-new-retroarch-forwarder_<version>-<release>~<suffix>_<arch>.deb
# Environment: PACKAGE_VERSION (default: from the git tag), PACKAGE_RELEASE
# (default 1), PACKAGE_MAINTAINER.
set -euo pipefail
# shellcheck source=packaging/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

readonly BASE_DEPENDS="python3 (>= 3.11), python3-requests, python3-pil, libc6, libstdc++6, libgcc-s1"
readonly SYSTEM_QT_DEPENDS="python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-pyside6.qtsvg"
readonly SYSTEM_QT_RECOMMENDS="python3-pyside6.qtmultimedia, qt6-wayland"
# What the PySide6 wheels expect from the system (xcb and wayland platforms).
readonly VENDOR_QT_DEPENDS="libegl1, libgl1, libopengl0, libfontconfig1, libfreetype6, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libxcb-xinerama0, libxcb-randr0, libxcb-render-util0, libxcb-image0, libwayland-client0, libwayland-cursor0, libwayland-egl1, libglib2.0-0t64 | libglib2.0-0"

main() {
    local toolchain="" suffix="" vendor=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --toolchain | --suffix | --vendor)
                [[ $# -ge 2 ]] || die "$1 needs a value"
                case "$1" in
                    --toolchain) toolchain="$2" ;;
                    --suffix) suffix="$2" ;;
                    --vendor) vendor="$2" ;;
                esac
                shift
                ;;
            *) die "Unknown option: $1" ;;
        esac
        shift
    done
    [[ -n "${toolchain}" && -n "${suffix}" ]] || die "Usage: build-deb.sh --toolchain DIR --suffix TAG"
    command -v dpkg-deb > /dev/null || die "dpkg-deb not found"

    local version release arch name root depends recommends
    version="$(package_version)"
    release="${PACKAGE_RELEASE:-1}"
    arch="$(dpkg --print-architecture)"
    name="${APP_NAME}_${version}-${release}~${suffix}_${arch}"
    root="${BUILD_DIR}/deb/${name}"
    depends="${BASE_DEPENDS}, ${SYSTEM_QT_DEPENDS}"
    recommends="ffmpeg, ${SYSTEM_QT_RECOMMENDS}"
    if [[ -n "${vendor}" ]]; then
        depends="${BASE_DEPENDS}, ${VENDOR_QT_DEPENDS}"
        recommends="ffmpeg, pipewire-bin | pulseaudio-utils | alsa-utils"
    fi

    stage_tree "${toolchain}" "${vendor}"
    rm -rf "${root}"
    mkdir -p "${root}/DEBIAN" "${root}/usr/share/doc/${APP_NAME}"
    cp -a "${STAGE_DIR}/." "${root}/"

    # Dependency lists contain "|", so no sed: plain substitutions.
    local control
    control="$(< "${REPO_ROOT}/packaging/deb/control.in")"
    control="${control//@VERSION@/${version}-${release}~${suffix}}"
    control="${control//@ARCH@/${arch}}"
    control="${control//@DEPENDS@/${depends}}"
    control="${control//@RECOMMENDS@/${recommends}}"
    control="${control//@MAINTAINER@/${PACKAGE_MAINTAINER:-${DEFAULT_MAINTAINER}}}"
    control="${control//@INSTALLED_SIZE@/$(du -sk --exclude=DEBIAN "${root}" | cut -f1)}"
    printf '%s\n' "${control}" > "${root}/DEBIAN/control"
    install -m 0755 "${REPO_ROOT}/packaging/deb/postinst" "${root}/DEBIAN/postinst"
    install -m 0755 "${REPO_ROOT}/packaging/deb/prerm" "${root}/DEBIAN/prerm"
    install -m 0644 "${REPO_ROOT}/packaging/deb/copyright" \
        "${root}/usr/share/doc/${APP_NAME}/copyright"

    (cd "${root}" && find . -path ./DEBIAN -prune -o -type f -printf '%P\0' \
        | sort -z | xargs -0 md5sum > DEBIAN/md5sums)
    chmod 0644 "${root}/DEBIAN/md5sums"

    mkdir -p "${DIST_DIR}"
    dpkg-deb --root-owner-group -Zxz --build "${root}" "${DIST_DIR}/${name}.deb" > /dev/null
    log_ok "Built ${DIST_DIR}/${name}.deb"
}

main "$@"
