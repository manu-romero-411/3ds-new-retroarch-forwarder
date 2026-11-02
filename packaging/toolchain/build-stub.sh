#!/usr/bin/env bash
# Compile the forwarder stub (stub/) with devkitARM and copy it to a toolchain.
#
#   packaging/toolchain/build-stub.sh OUT_DIR
#
# Writes OUT_DIR/stub/3ds-forwarder-stub.elf and records the source revision
# in OUT_DIR/VERSIONS. With DEVKITARM set (inside devkitpro/devkitarm) it runs
# make directly; otherwise it runs itself in that image with docker or podman
# (CONTAINER_ENGINE overrides which), as the calling user.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
readonly HERE REPO_ROOT
# shellcheck source=packaging/toolchain/versions.env
source "${HERE}/versions.env"
readonly STUB_NAME="3ds-forwarder-stub.elf"

log() {
    local tag="$1"
    shift
    printf '%s %s %s\n' "${tag}" "$(date '+%Y-%m-%d_%H:%M:%S')" "$*" >&2
}
die() {
    log "[ERR ]" "$@"
    exit 1
}

# The container engine command (CONTAINER_ENGINE may be e.g. "sudo docker").
container_engine() {
    local engine
    for engine in "${CONTAINER_ENGINE:-}" docker podman; do
        if [[ -n "${engine}" ]] && command -v "${engine##* }" > /dev/null; then
            printf '%s\n' "${engine}"
            return 0
        fi
    done
    return 1
}

# SELinux hosts (Fedora and friends) need relabelled bind mounts.
volume_suffix() {
    if command -v selinuxenabled > /dev/null 2>&1 && selinuxenabled; then
        echo ":z"
    fi
}

source_revision() {
    git -C "${REPO_ROOT}" describe --tags --always --dirty 2> /dev/null || echo unknown
}

record_version() {
    local out_dir="$1" revision="$2" versions="$1/VERSIONS"
    touch "${versions}"
    grep -v '^stub=' "${versions}" > "${versions}.new" || true
    echo "stub=${revision}" >> "${versions}.new"
    mv "${versions}.new" "${versions}"
}

build_here() {
    local out_dir="$1"
    command -v make > /dev/null || die "make is required"
    if [[ ! -d "${DEVKITPRO:-/opt/devkitpro}/libctru" ]]; then
        if [[ "${EUID}" -eq 0 ]] && command -v dkp-pacman > /dev/null; then
            dkp-pacman -S --needed --noconfirm 3ds-dev > /dev/null
        else
            die "libctru not found: install the 3ds-dev group with dkp-pacman"
        fi
    fi
    log "[INFO]" "Compiling the stub with ${DEVKITARM}"
    # Only the .elf is needed (not the loose stub CIA), so plain "make".
    make -C "${REPO_ROOT}/stub" clean > /dev/null
    make -C "${REPO_ROOT}/stub" > /dev/null
    install -D -m 0644 "${REPO_ROOT}/stub/${STUB_NAME}" "${out_dir}/stub/${STUB_NAME}"
}

build_in_container() {
    local out_dir="$1" engine z
    local -a run
    engine="$(container_engine)" || die "Set DEVKITARM, or install docker or podman"
    read -ra run <<< "${engine}"
    z="$(volume_suffix)"
    log "[INFO]" "Compiling the stub in ${DEVKITARM_IMAGE} (${engine})"
    local -a user_args=(-u "$(id -u):$(id -g)")
    # Rootless podman maps the calling user to root inside the container.
    [[ "${run[-1]}" == podman ]] && user_args=()
    "${run[@]}" run --rm "${user_args[@]}" -e HOME=/tmp \
        -v "${REPO_ROOT}:/src${z}" -v "${out_dir}:/out${z}" -w /src "${DEVKITARM_IMAGE}" \
        bash /src/packaging/toolchain/build-stub.sh /out
}

main() {
    [[ $# -eq 1 ]] || die "Usage: build-stub.sh OUT_DIR"
    mkdir -p "$1"
    local out_dir
    out_dir="$(cd "$1" && pwd)"
    if [[ -n "${DEVKITARM:-}" ]]; then
        build_here "${out_dir}"
    else
        build_in_container "${out_dir}"
    fi
    record_version "${out_dir}" "$(source_revision)"
    log "[ OK ]" "Stub ready: ${out_dir}/stub/${STUB_NAME}"
}

main "$@"
