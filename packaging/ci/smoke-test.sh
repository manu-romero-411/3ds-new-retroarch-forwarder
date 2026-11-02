#!/usr/bin/env bash
# Install a built package in a clean container and check that it works.
#
#   packaging/ci/smoke-test.sh dist/<package>.deb|.rpm
#
# Installs with apt or dnf (dependencies included), builds a real forwarder
# with the bundled toolchain and reads it back, opens the main window
# off-screen, then removes the package and checks nothing is left behind.
set -euo pipefail

readonly PREFIX="/opt/3ds-new-retroarch-forwarder"
readonly APP_ID="io.github.manu_romero_411.forwarder3ds"

log() {
    printf '%s %s %s\n' "$1" "$(date '+%Y-%m-%d_%H:%M:%S')" "${*:2}" >&2
}

install_package() {
    local package="$1"
    case "${package}" in
        *.deb)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -q
            apt-get install -y -q --no-install-recommends "./${package#./}"
            ;;
        *.rpm) dnf install -y -q --setopt=install_weak_deps=False "${package}" ;;
        *) log "[ERR ]" "Not a package: ${package}" && exit 1 ;;
    esac
}

remove_package() {
    case "$1" in
        *.deb) apt-get remove -y -q 3ds-new-retroarch-forwarder ;;
        *.rpm) dnf remove -y -q 3ds-new-retroarch-forwarder ;;
    esac
    test ! -e "${PREFIX}"
}

check_files() {
    test -x "${PREFIX}/toolchain/bin/makerom"
    test -x "${PREFIX}/toolchain/bin/bannertool"
    test -f "${PREFIX}/toolchain/stub/3ds-forwarder-stub.elf"
    test -f "/usr/share/applications/${APP_ID}.desktop"
    test -f "/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
    test -f "/usr/share/icons/hicolor/48x48/apps/${APP_ID}.png"
}

build_forwarder() {
    local work
    work="$(mktemp -d)"
    export HOME="${work}"
    3ds-forwarder --version
    3ds-forwarder doctor --offline
    3ds-forwarder build --core snes9x2005 --rom "roms/snes/Smoke Test (USA).sfc" \
        --long-name "Smoke Test" --jingle smw_coin -o "${work}/smoke.cia"
    3ds-forwarder inspect "${work}/smoke.cia" | tee "${work}/inspect.txt"
    grep -q 'snes9x2005' "${work}/inspect.txt"
    grep -q 'Jingle: *yes' "${work}/inspect.txt"
    3ds-forwarder build --from-cia "${work}/smoke.cia" --short-name "Smoke"
    3ds-forwarder inspect "${work}/smoke.cia" | grep -q 'Short name: *Smoke$'
}

open_window() {
    QT_QPA_PLATFORM=offscreen PYTHONPATH="${PREFIX}/lib:${PREFIX}/vendor" python3 -c "
from PySide6.QtWidgets import QApplication
app = QApplication([])
from forwarder3ds.gui.main_window import MainWindow
window = MainWindow()
window.show()
app.processEvents()
print('main window OK')
"
}

main() {
    [[ $# -eq 1 ]] || { log "[ERR ]" "Usage: smoke-test.sh PACKAGE" && exit 1; }
    install_package "$1"
    check_files
    build_forwarder
    open_window
    remove_package "$1"
    log "[ OK ]" "$(basename "$1") works"
}

main "$@"
