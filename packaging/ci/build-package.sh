#!/usr/bin/env bash
# Build the package of one target inside that target's own container.
#
#   packaging/ci/build-package.sh deb debian13      (in debian:13)
#   packaging/ci/build-package.sh deb ubuntu24.04   (in ubuntu:24.04)
#   packaging/ci/build-package.sh rpm fc43          (in fedora:43)
#
# Runs as root in a throw-away container whose system and architecture are
# the package's: installs the build dependencies, compiles makerom and
# bannertool there, adds the stub from STUB_DIR (default: dist-stub/, built
# once by the workflow) and builds the package into dist/. When the
# distribution has no PySide6 (Ubuntu 24.04), PySide6-Essentials is bundled.
# HOST_UID/HOST_GID, if set, become the owners of build/ and dist/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
readonly HERE REPO_ROOT
readonly STUB_NAME="3ds-forwarder-stub.elf"
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

# Libraries that some file under $1 needs and the loader cannot find.
missing_libraries() {
    find "$1" -name '*.so*' -type f -exec ldd {} + 2> /dev/null \
        | sed -n 's/^[[:space:]]*\([^ ]*\) => not found$/\1/p' | sort -u
}

# Drop what the program never loads (QML/Quick, Designer, developer tools,
# stubs). The wheel already has plugins needing libraries it does not ship
# (Pdf, VirtualKeyboard...), so the check afterwards only fails on libraries
# that the pruning itself made go missing.
prune_pyside6() {
    local pyside="$1" qt="$1/Qt" name before after
    before="$(missing_libraries "${pyside}")"
    rm -rf "${pyside}"/{assistant,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls} \
        "${pyside}"/{svgtoqml,include,typesystems,glue,doc,scripts} "${pyside}"/*.pyi
    for name in Designer Help LabsStyleKit Qml QmlFeatures Quick QuickControls2 QuickTest \
        QuickWidgets Sql Test UiTools Xml Concurrent OpenGLWidgets; do
        rm -f "${pyside}/Qt${name}.abi3.so"
    done
    rm -f "${pyside}"/libpyside6qml.*
    rm -rf "${qt}"/{qml,metatypes,libexec} \
        "${qt}"/plugins/{designer,qmltooling,sqldrivers,vectorimageformats} \
        "${qt}"/plugins/wayland-graphics-integration-server \
        "${qt}"/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
    find "${qt}/translations" -type f ! -name 'qtbase_*' -delete
    for name in Designer DesignerComponents Help Labs Lottie Qml Quick Sql Test UiTools \
        WaylandCompositor WaylandEglCompositor; do
        rm -f "${qt}/lib/libQt6${name}"*
    done
    after="$(missing_libraries "${pyside}")"
    name="$(comm -13 <(printf '%s\n' "${before}") <(printf '%s\n' "${after}"))"
    [[ -z "${name}" ]] || die "Pruning PySide6 broke these libraries:"$'\n'"${name}"
    log "[INFO]" "Bundled PySide6: $(du -sh "${pyside}" | cut -f1)"
}

main() {
    [[ $# -eq 2 ]] || die "Usage: build-package.sh deb|rpm SUFFIX"
    local format="$1" suffix="$2" arch toolchain vendor=""
    local stub_dir="${STUB_DIR:-${REPO_ROOT}/dist-stub}"
    [[ -f "${stub_dir}/${STUB_NAME}" ]] || die "Stub not found in ${stub_dir}"
    arch="$(uname -m)"
    toolchain="${REPO_ROOT}/build/toolchain-${suffix}-${arch}"

    case "${format}" in
        deb) install_deb_build_deps ;;
        rpm) install_rpm_build_deps ;;
        *) die "Unknown format: ${format}" ;;
    esac

    rm -rf "${toolchain}"
    "${REPO_ROOT}/packaging/toolchain/build-tools.sh" "${toolchain}"
    install -D -m 0644 "${stub_dir}/${STUB_NAME}" "${toolchain}/stub/${STUB_NAME}"
    if [[ -f "${stub_dir}/VERSIONS" ]]; then
        grep '^stub=' "${stub_dir}/VERSIONS" >> "${toolchain}/VERSIONS" || true
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
