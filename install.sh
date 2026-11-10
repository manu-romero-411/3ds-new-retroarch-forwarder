#!/usr/bin/env bash
# Install 3ds-new-retroarch-forwarder without the distribution's package manager.
#
# For immutable systems (Fedora Atomic, Bazzite, SteamOS...) and any
# distribution without a release package. It:
#   1. makes sure a container engine is available (podman if present,
#      otherwise Docker, which it installs with the system package manager);
#   2. compiles makerom and bannertool inside a container of *your* system and
#      version (Debian, Ubuntu, Fedora and their derivatives), or statically
#      in Alpine for anything else, for your architecture;
#   3. compiles the RetroArch bases (RetroArch + one core each) with devkitARM,
#      or downloads the release's (compiling them takes a while);
#   4. installs the program into a private Python virtual environment.
#
#   ./install.sh                     install for the current user (~/.local)
#   sudo ./install.sh --system       install for all users (/opt/3ds-new-retroarch-forwarder)
#   ./install.sh --version v0.2.0    install a given release
#   ./install.sh --ref main          install a branch or commit
#   ./install.sh --static            portable static tools, whatever the system
#   ./install.sh --download-bases    use the release's RetroArch bases instead of compiling them
#   ./install.sh --no-gui            command line only (skips PySide6)
#   ./install.sh --uninstall         remove a previous install.sh installation
#
# Run it from a clone to install that working tree, or on its own
# (curl ... | bash -s -- [options]) to download a release.
set -euo pipefail

readonly APP_NAME="3ds-new-retroarch-forwarder"
readonly APP_ID="io.github.manu_romero_411.forwarder3ds"
readonly MODULE="forwarder3ds"
readonly COMMAND="3ds-forwarder"
readonly REPO="manu-romero-411/3ds-new-retroarch-forwarder"
readonly BASES_ARCHIVE="retroarch-bases.tar.gz"
readonly MIN_PYTHON="3.11"
readonly MARKER=".installed-by-install-sh"

SCOPE=""
REF=""
WITH_GUI=1
STATIC=0
DOWNLOAD_BASES=0
ACTION="install"
WORK_DIR=""
SOURCE_DIR=""
ENGINE=()

log() {
    local tag="$1"
    shift
    printf '%s %s %s\n' "${tag}" "$(date '+%Y-%m-%d_%H:%M:%S')" "$*" >&2
}
log_info() { log "[INFO]" "$@"; }
log_ok() { log "[ OK ]" "$@"; }
log_warn() { log "[WARN]" "$@"; }
log_error() { log "[ERR ]" "$@"; }

die() {
    log_error "$@"
    exit 1
}

cleanup() {
    if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
        rm -rf "${WORK_DIR}"
    fi
}
trap cleanup EXIT

usage() {
    sed -n '2,24s/^# \{0,1\}//p' "${BASH_SOURCE[0]}" 2> /dev/null \
        || echo "Usage: install.sh [--user|--system] [--version TAG|--ref REF] [--static] [--no-gui] [--uninstall]"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --user) SCOPE="user" ;;
            --system) SCOPE="system" ;;
            --version | --ref)
                [[ $# -ge 2 ]] || die "$1 needs a value"
                REF="$2"
                shift
                ;;
            --static) STATIC=1 ;;
            --download-bases) DOWNLOAD_BASES=1 ;;
            --no-gui) WITH_GUI=0 ;;
            --uninstall) ACTION="uninstall" ;;
            -h | --help)
                usage
                exit 0
                ;;
            *) die "Unknown option: $1 (see --help)" ;;
        esac
        shift
    done
    if [[ -z "${SCOPE}" ]]; then
        if [[ "${EUID}" -eq 0 ]]; then SCOPE="system"; else SCOPE="user"; fi
    fi
    if [[ "${SCOPE}" == "system" && "${EUID}" -ne 0 ]]; then
        die "--system needs root (run it with sudo)"
    fi
}

set_paths() {
    if [[ "${SCOPE}" == "system" ]]; then
        PREFIX="/opt/${APP_NAME}"
        BIN_DIR="/usr/local/bin"
        SHARE_DIR="/usr/local/share"
    else
        local data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
        PREFIX="${data_home}/${APP_NAME}"
        BIN_DIR="${HOME}/.local/bin"
        SHARE_DIR="${data_home}"
    fi
    readonly PREFIX BIN_DIR SHARE_DIR
    readonly MANIFEST="${PREFIX}/${MARKER}"
}

# ── Host system ──────────────────────────────────────────────────────────

os_release() {
    local key="$1"
    # shellcheck disable=SC1091
    (. /etc/os-release 2> /dev/null && eval "printf '%s' \"\${${key}:-}\"")
}

as_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        "$@"
    elif command -v sudo > /dev/null; then
        sudo "$@"
    else
        die "Root privileges are needed for: $* (install sudo or run as root)"
    fi
}

is_immutable() {
    [[ -e /run/ostree-booted ]] || command -v steamos-readonly > /dev/null 2>&1
}

# Image of the same distribution and version as this machine, if there is one.
# Derivatives map to their base (Linux Mint -> its Ubuntu, Bazzite -> its
# Fedora). Anything else gets static binaries built in Alpine.
build_image() {
    local id like version codename
    id="$(os_release ID)"
    like=" $(os_release ID_LIKE) "
    version="$(os_release VERSION_ID)"
    codename="$(os_release UBUNTU_CODENAME)"
    if [[ "${STATIC}" -eq 1 ]]; then
        echo "alpine:latest"
    elif [[ "${id}" == ubuntu && -n "${version}" ]]; then
        echo "ubuntu:${version}"
    elif [[ -n "${codename}" ]]; then
        echo "ubuntu:${codename}"
    elif [[ "${id}" == debian && "${version}" =~ ^[0-9]+$ ]]; then
        echo "debian:${version}"
    elif [[ ("${id}" == fedora || "${like}" == *" fedora "*) && "${version}" =~ ^[0-9]+$ ]]; then
        echo "fedora:${version}"
    else
        echo "alpine:latest"
    fi
}

find_python() {
    local candidate
    for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
        if command -v "${candidate}" > /dev/null 2>&1 \
            && "${candidate}" -c "import sys; sys.exit(sys.version_info < (${MIN_PYTHON/./, }))" \
            && "${candidate}" -c "import venv, ensurepip" > /dev/null 2>&1; then
            command -v "${candidate}"
            return 0
        fi
    done
    return 1
}

# ── Container engine ─────────────────────────────────────────────────────

install_docker() {
    is_immutable && die "No podman or docker found. On an image-based system install one \
with its tools (e.g. 'rpm-ostree install podman' and reboot), then run this again."
    log_info "Installing Docker with the system package manager"
    if command -v apt-get > /dev/null; then
        as_root apt-get update -q
        as_root apt-get install -y -q docker.io
    elif command -v dnf > /dev/null; then
        as_root dnf install -y -q moby-engine || as_root dnf install -y -q docker
    elif command -v zypper > /dev/null; then
        as_root zypper --non-interactive install docker
    elif command -v pacman > /dev/null; then
        as_root pacman -S --needed --noconfirm docker
    else
        die "Cannot install Docker on this system: install docker or podman, then run this again"
    fi
    if command -v systemctl > /dev/null; then
        as_root systemctl enable --now docker.service
    fi
}

choose_engine() {
    if command -v podman > /dev/null; then
        ENGINE=(podman)
    else
        command -v docker > /dev/null || install_docker
        if docker info > /dev/null 2>&1; then
            ENGINE=(docker)
        elif [[ "${EUID}" -ne 0 ]] && sudo docker info > /dev/null 2>&1; then
            # Not in the docker group yet: use sudo instead of asking for a re-login.
            ENGINE=(sudo docker)
        else
            die "Docker is installed but not running (try: sudo systemctl start docker)"
        fi
    fi
    log_info "Container engine: ${ENGINE[*]}"
}

# ── Toolchain ────────────────────────────────────────────────────────────

# Commands run inside the build container (as root) before build-tools.sh.
deps_command() {
    case "$1" in
        alpine:*) echo "apk add --no-cache bash build-base git linux-headers" ;;
        fedora:*) echo "dnf install -y -q gcc gcc-c++ make git findutils" ;;
        *) echo "apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
--no-install-recommends build-essential git ca-certificates" ;;
    esac
}

# SELinux hosts (Fedora and friends) need relabelled bind mounts.
volume_suffix() {
    if command -v selinuxenabled > /dev/null 2>&1 && selinuxenabled; then
        echo ",z"
    fi
}

build_tools() {
    local toolchain="$1" image static_flag="" chown_cmd="true" z
    image="$(build_image)"
    z="$(volume_suffix)"
    [[ "${image}" == alpine:* ]] && static_flag="--static"
    # Rootless podman already maps the container's root to this user.
    if [[ "${ENGINE[0]}" != podman || "${EUID}" -eq 0 ]]; then
        chown_cmd="chown -R $(id -u):$(id -g) /out"
    fi
    log_info "Compiling makerom and bannertool in ${image} for $(uname -m)"
    "${ENGINE[@]}" run --rm -v "${SOURCE_DIR}:/src:ro${z}" -v "${toolchain}:/out:rw${z}" \
        "${image}" sh -c "$(deps_command "${image}") > /dev/null \
            && bash /src/packaging/toolchain/build-tools.sh ${static_flag} /out \
            && ${chown_cmd}"
}

download_bases() {
    local toolchain="$1" tag="$2" url
    url="https://github.com/${REPO}/releases/download/${tag}/${BASES_ARCHIVE}"
    log_info "Downloading the RetroArch bases of ${tag}"
    curl -fsSL "${url}" | tar -xz -C "${toolchain}" || return 1
    if [[ -f "${toolchain}/bases/VERSIONS" ]]; then
        cat "${toolchain}/bases/VERSIONS" >> "${toolchain}/VERSIONS"
        rm "${toolchain}/bases/VERSIONS"
    fi
}

build_bases() {
    local toolchain="$1" tag
    tag="$(release_tag)"
    if [[ "${DOWNLOAD_BASES}" -eq 0 ]]; then
        log_info "Compiling the RetroArch bases with devkitARM (this takes a while)"
        if CONTAINER_ENGINE="${ENGINE[*]}" "${SOURCE_DIR}/packaging/toolchain/build-base.sh" \
            "${toolchain}" all; then
            return 0
        fi
        log_warn "Could not compile the bases here; falling back to the release download"
    fi
    [[ -n "${tag}" ]] || die "No release to download the bases from; compile them instead"
    download_bases "${toolchain}" "${tag}" || die "Cannot download the bases of ${tag}"
}

# ── Source ───────────────────────────────────────────────────────────────

LATEST_TAG=""
release_tag() {
    if [[ -n "${REF}" && "${REF}" == v* ]]; then
        echo "${REF}"
        return
    fi
    if [[ -z "${LATEST_TAG}" ]] && command -v curl > /dev/null; then
        LATEST_TAG="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2> /dev/null \
            | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1 || true)"
    fi
    echo "${LATEST_TAG}"
}

# Set SOURCE_DIR to a source tree: this clone, or a downloaded archive.
fetch_source() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2> /dev/null && pwd)" || here=""
    if [[ -z "${REF}" && -n "${here}" && -f "${here}/pyproject.toml" \
        && -d "${here}/src/${MODULE}" ]]; then
        log_info "Installing from the local tree ${here}"
        SOURCE_DIR="${here}"
        return 0
    fi
    command -v curl > /dev/null || die "curl is needed to download ${APP_NAME}"
    command -v tar > /dev/null || die "tar is needed to unpack ${APP_NAME}"
    local ref="${REF}" url
    if [[ -z "${ref}" ]]; then
        ref="$(release_tag)"
        if [[ -z "${ref}" ]]; then
            log_warn "No published release found; using the main branch"
            ref="main"
        fi
    fi
    url="https://github.com/${REPO}/archive/${ref}.tar.gz"
    log_info "Downloading ${ref}"
    curl -fsSL "${url}" | tar -xz -C "${WORK_DIR}" || die "Cannot download ${url}"
    SOURCE_DIR="$(find "${WORK_DIR}" -mindepth 1 -maxdepth 1 -type d ! -name toolchain | head -n 1)"
    [[ -f "${SOURCE_DIR}/pyproject.toml" ]] || die "Unexpected archive layout in ${url}"
}

# ── Install / uninstall ──────────────────────────────────────────────────

record() {
    printf '%s\n' "$1" >> "${MANIFEST}"
}

install_desktop_files() {
    local src="$1" apps="${SHARE_DIR}/applications" icons="${SHARE_DIR}/icons/hicolor"
    mkdir -p "${apps}" "${SHARE_DIR}/metainfo"
    sed "s|^Exec=.*|Exec=${PREFIX}/venv/bin/${COMMAND}-gui|" \
        "${src}/packaging/linux/${APP_ID}.desktop" > "${apps}/${APP_ID}.desktop"
    record "${apps}/${APP_ID}.desktop"
    install -m 0644 "${src}/packaging/linux/${APP_ID}.metainfo.xml" "${SHARE_DIR}/metainfo/"
    record "${SHARE_DIR}/metainfo/${APP_ID}.metainfo.xml"

    local svg="${src}/src/${MODULE}/data/icons/${APP_ID}.svg" size target
    install -D -m 0644 "${svg}" "${icons}/scalable/apps/${APP_ID}.svg"
    record "${icons}/scalable/apps/${APP_ID}.svg"
    if command -v rsvg-convert > /dev/null 2>&1; then
        for size in 16 24 32 48 64 128 256 512; do
            target="${icons}/${size}x${size}/apps/${APP_ID}.png"
            mkdir -p "$(dirname "${target}")"
            rsvg-convert --width "${size}" --height "${size}" "${svg}" --output "${target}" \
                && record "${target}"
        done
    fi
    refresh_desktop_caches
}

refresh_desktop_caches() {
    if command -v gtk-update-icon-cache > /dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "${SHARE_DIR}/icons/hicolor" 2> /dev/null || true
    fi
    if command -v update-desktop-database > /dev/null 2>&1; then
        update-desktop-database -q "${SHARE_DIR}/applications" 2> /dev/null || true
    fi
}

do_install() {
    if [[ -d "${PREFIX}" && ! -f "${MANIFEST}" ]]; then
        die "${PREFIX} exists but was not created by install.sh (a .deb/.rpm package?)"
    fi
    local python extra="" staged
    python="$(find_python)" \
        || die "Python >= ${MIN_PYTHON} with the venv module is required (python3-venv on Debian)"
    WORK_DIR="$(mktemp -d)"
    fetch_source
    [[ "${WITH_GUI}" -eq 1 ]] && extra="[gui]"

    # Build everything first, so a failure leaves a previous installation intact.
    choose_engine
    staged="${WORK_DIR}/toolchain"
    mkdir -p "${staged}"
    build_tools "${staged}"
    build_bases "${staged}"

    if [[ -f "${MANIFEST}" ]]; then
        log_info "Replacing the previous installation in ${PREFIX}"
        do_uninstall quiet
    fi
    mkdir -p "${PREFIX}" "${BIN_DIR}"
    : > "${MANIFEST}"
    cp -r "${staged}" "${PREFIX}/toolchain"

    log_info "Creating the virtual environment in ${PREFIX}/venv"
    "${python}" -m venv "${PREFIX}/venv"
    log_info "Installing ${APP_NAME}${extra} and its dependencies (this can take a while)"
    "${PREFIX}/venv/bin/python" -m pip install --quiet --disable-pip-version-check \
        "${SOURCE_DIR}${extra}"

    local command
    for command in "${COMMAND}" "${COMMAND}-gui"; do
        [[ "${WITH_GUI}" -eq 0 && "${command}" == *-gui ]] && continue
        ln -sf "${PREFIX}/venv/bin/${command}" "${BIN_DIR}/${command}"
        record "${BIN_DIR}/${command}"
    done
    [[ "${WITH_GUI}" -eq 1 ]] && install_desktop_files "${SOURCE_DIR}"

    "${PREFIX}/venv/bin/${COMMAND}" doctor --offline || die "The installed toolchain is incomplete"
    log_ok "$("${PREFIX}/venv/bin/${COMMAND}" --version) installed in ${PREFIX}"
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) log_warn "${BIN_DIR} is not in your PATH; add it to run '${COMMAND}' from a terminal" ;;
    esac
}

do_uninstall() {
    local quiet="${1:-}"
    if [[ ! -f "${MANIFEST}" ]]; then
        [[ -n "${quiet}" ]] && return 0
        die "No install.sh installation found in ${PREFIX}"
    fi
    local path
    while IFS= read -r path; do
        [[ -n "${path}" ]] && rm -f -- "${path}"
    done < "${MANIFEST}"
    rm -rf -- "${PREFIX}"
    refresh_desktop_caches
    [[ -n "${quiet}" ]] || log_ok "${APP_NAME} removed from ${PREFIX}"
}

main() {
    parse_args "$@"
    set_paths
    if [[ "${ACTION}" == "uninstall" ]]; then
        do_uninstall
    else
        do_install
    fi
}

main "$@"
