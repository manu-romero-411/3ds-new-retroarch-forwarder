#!/usr/bin/env bash
# Build one .rpm for the Fedora release and architecture this runs on.
#
#   packaging/build-rpm.sh --toolchain DIR
#
# --toolchain   directory made by toolchain/build-tools.sh + build-base.sh
#
# Output: dist/3ds-new-retroarch-forwarder-<version>-<release>.<dist>.<arch>.rpm
# (<dist> is the build system's own, e.g. fc43). Environment:
# PACKAGE_VERSION (default: from the git tag), PACKAGE_RELEASE (default 1),
# PACKAGE_MAINTAINER.
set -euo pipefail
# shellcheck source=packaging/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

main() {
    local toolchain=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --toolchain)
                [[ $# -ge 2 ]] || die "$1 needs a value"
                toolchain="$2"
                shift
                ;;
            *) die "Unknown option: $1" ;;
        esac
        shift
    done
    [[ -n "${toolchain}" ]] || die "Usage: build-rpm.sh --toolchain DIR"
    command -v rpmbuild > /dev/null || die "rpmbuild not found"

    local version release topdir
    version="$(package_version)"
    release="${PACKAGE_RELEASE:-1}"
    topdir="${BUILD_DIR}/rpm"

    stage_tree "${toolchain}"
    rm -rf "${topdir}"
    mkdir -p "${topdir}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

    rpmbuild -bb --quiet \
        --define "_topdir ${topdir}" \
        --define "pkg_version ${version}" \
        --define "pkg_release ${release}" \
        --define "pkg_packager ${PACKAGE_MAINTAINER:-${DEFAULT_MAINTAINER}}" \
        --define "stage_dir ${STAGE_DIR}" \
        --define "license_file ${REPO_ROOT}/LICENSE" \
        "${REPO_ROOT}/packaging/rpm/${APP_NAME}.spec"

    mkdir -p "${DIST_DIR}"
    find "${topdir}/RPMS" -name '*.rpm' -exec cp {} "${DIST_DIR}/" \;
    log_ok "Built $(find "${topdir}/RPMS" -name '*.rpm' -printf '%f\n')"
}

main "$@"
