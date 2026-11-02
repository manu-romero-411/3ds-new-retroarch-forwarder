#!/usr/bin/env bash
# Shared helpers for the packaging scripts. Source it; do not run it.
#
# Package layout (same for .deb and .rpm):
#   /opt/3ds-new-retroarch-forwarder/lib/forwarder3ds/   Python package
#   /opt/3ds-new-retroarch-forwarder/vendor/             PySide6, when the distro lacks it
#   /opt/3ds-new-retroarch-forwarder/toolchain/          makerom, bannertool, stub .elf
#   /usr/bin/3ds-forwarder[-gui]                         launchers (system python3)
#   /usr/share/applications|icons|metainfo               desktop integration

readonly APP_NAME="3ds-new-retroarch-forwarder"
readonly APP_ID="io.github.manu_romero_411.forwarder3ds"
readonly MODULE="forwarder3ds"
readonly COMMAND="3ds-forwarder"
readonly INSTALL_PREFIX="/opt/${APP_NAME}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly BUILD_DIR="${REPO_ROOT}/build"
readonly STAGE_DIR="${BUILD_DIR}/stage"
# shellcheck disable=SC2034  # used by the scripts that source this file
readonly DIST_DIR="${REPO_ROOT}/dist"
# shellcheck disable=SC2034
readonly DEFAULT_MAINTAINER="manu-romero-411 <manu-romero-411@users.noreply.github.com>"
readonly ICON_SVG="${REPO_ROOT}/src/${MODULE}/data/icons/${APP_ID}.svg"
readonly ICON_SIZES=(16 24 32 48 64 128 256 512)

log() {
    local tag="$1"
    shift
    printf '%s %s %s\n' "${tag}" "$(date '+%Y-%m-%d_%H:%M:%S')" "$*" >&2
}
log_info() { log "[INFO]" "$@"; }
log_ok() { log "[ OK ]" "$@"; }
log_error() { log "[ERR ]" "$@"; }

die() {
    log_error "$@"
    exit 1
}

# Package version: $PACKAGE_VERSION if set (the release workflow passes the
# tag without its "v"), otherwise derived from "git describe" like the
# program does: v1.2.3 -> 1.2.3, v1.2.3-4-gabc -> 1.2.3+git4.gabc.
package_version() {
    local described
    if [[ -n "${PACKAGE_VERSION:-}" ]]; then
        printf '%s\n' "${PACKAGE_VERSION#v}"
        return 0
    fi
    described="$(git -C "${REPO_ROOT}" describe --tags --match 'v[0-9]*' 2> /dev/null)" \
        || die "No v* tag to take the version from: tag the commit or set PACKAGE_VERSION"
    described="${described#v}"
    if [[ "${described}" =~ ^([0-9.]+)-([0-9]+)-g([0-9a-f]+)$ ]]; then
        printf '%s+git%s.g%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}"
    else
        printf '%s\n' "${described}"
    fi
}

# A toolchain directory must hold both programs and the stub.
check_toolchain() {
    local dir="$1" item
    for item in bin/makerom bin/bannertool stub/3ds-forwarder-stub.elf; do
        [[ -f "${dir}/${item}" ]] || die "Toolchain ${dir} lacks ${item}"
    done
}

# Write a launcher that runs a module with the system interpreter.
write_launcher() {
    local dest="$1" module="$2"
    cat > "${dest}" <<LAUNCHER
#!/bin/sh
# Launcher installed by the ${APP_NAME} package.
PYTHONPATH="${INSTALL_PREFIX}/lib:${INSTALL_PREFIX}/vendor\${PYTHONPATH:+:\${PYTHONPATH}}"
export PYTHONPATH
exec /usr/bin/python3 -m ${module} "\$@"
LAUNCHER
    chmod 0755 "${dest}"
}

# Install the SVG icon and render its PNG sizes into a hicolor theme dir.
install_icons() {
    local hicolor="$1" size dir
    command -v rsvg-convert > /dev/null \
        || die "rsvg-convert not found (librsvg2-bin on Debian, librsvg2-tools on Fedora)"
    install -D -m 0644 "${ICON_SVG}" "${hicolor}/scalable/apps/${APP_ID}.svg"
    for size in "${ICON_SIZES[@]}"; do
        dir="${hicolor}/${size}x${size}/apps"
        mkdir -p "${dir}"
        rsvg-convert --width "${size}" --height "${size}" "${ICON_SVG}" \
            --output "${dir}/${APP_ID}.png"
    done
}

# Build the file tree shared by both package formats in ${STAGE_DIR}.
#   stage_tree TOOLCHAIN_DIR [VENDOR_DIR]
stage_tree() {
    local toolchain="$1" vendor="${2:-}"
    local prefix="${STAGE_DIR}${INSTALL_PREFIX}"
    local share="${STAGE_DIR}/usr/share"
    check_toolchain "${toolchain}"
    rm -rf "${STAGE_DIR}"
    mkdir -p "${prefix}/lib" "${STAGE_DIR}/usr/bin" "${share}/applications" "${share}/metainfo"

    cp -r "${REPO_ROOT}/src/${MODULE}" "${prefix}/lib/"
    find "${prefix}/lib" -name '__pycache__' -type d -prune -exec rm -rf {} +
    find "${prefix}/lib" -type f -name '*.py[co]' -delete
    # The installed program reads its version from here (see version.py).
    printf '__version__ = "%s"\n' "$(package_version)" > "${prefix}/lib/${MODULE}/_version.py"

    mkdir -p "${prefix}/toolchain"
    cp -r "${toolchain}/." "${prefix}/toolchain/"
    if [[ -n "${vendor}" ]]; then
        cp -r "${vendor}" "${prefix}/vendor"
    fi

    write_launcher "${STAGE_DIR}/usr/bin/${COMMAND}" "${MODULE}"
    write_launcher "${STAGE_DIR}/usr/bin/${COMMAND}-gui" "${MODULE}.gui.app"

    install -m 0644 "${REPO_ROOT}/packaging/linux/${APP_ID}.desktop" "${share}/applications/"
    install -m 0644 "${REPO_ROOT}/packaging/linux/${APP_ID}.metainfo.xml" "${share}/metainfo/"
    install_icons "${share}/icons/hicolor"

    find "${STAGE_DIR}" -type d -exec chmod 0755 {} +
    find "${STAGE_DIR}" -type f ! -path '*/usr/bin/*' ! -path '*/toolchain/bin/*' \
        ! -name '*.so*' -exec chmod 0644 {} +
    chmod 0755 "${prefix}/toolchain/bin/"*
    log_ok "Staged files in ${STAGE_DIR}"
}
