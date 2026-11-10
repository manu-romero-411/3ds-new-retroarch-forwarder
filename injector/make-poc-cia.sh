#!/usr/bin/env bash
# Proof of concept: pack one ROM into a standalone single-game CIA.
#
#   injector/make-poc-cia.sh [options] CORE ROM
#
#   --title TEXT      HOME Menu title (default: ROM file name)
#   --author TEXT     Publisher line (default: "RetroArch")
#   --icon PNG        48x48 icon (default: the core's RetroArch icon)
#   --banner PNG      256x128 banner (default: the core's RetroArch banner)
#   --audio WAV       Banner jingle (default: RetroArch's silent.wav)
#   --unique-id HEX   Title ID unique part (default: derived from core + title)
#   --system-dir DIR  BIOS folder on the SD (default: <data_dir>/system)
#   --toolchain DIR   Toolchain with bin/{makerom,bannertool} and bases/
#   -o, --output CIA  Output file (default: ./<slug>.cia)
#
# The base comes from packaging/toolchain/build-base.sh. Saves, states and
# the game's retroarch.cfg end up in sdmc:/3ds/injected/<slug>/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
readonly HERE REPO_ROOT
readonly RSF="${HERE}/data/injected.rsf"
readonly SEED_CFG="${HERE}/data/retroarch.cfg"
# Injected titles live in 0xD0000-0xDFFFF: clear of RetroArch's cores
# (0xBACxx) and of the forwarders (0xF0000-0xFFFFF).
readonly UNIQUE_ID_BASE=$((0xD0000))
readonly DATA_ROOT="sdmc:/3ds/injected"

log() {
    local tag="$1"
    shift
    printf '%s %s %s\n' "${tag}" "$(date '+%Y-%m-%d_%H:%M:%S')" "$*" >&2
}
die() {
    log "[ERR ]" "$@"
    exit 1
}
usage() {
    sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# Same search order as forwarder3ds.core.paths.toolchain_dirs().
find_toolchain() {
    local dir
    for dir in "${FORWARDER3DS_TOOLCHAIN:-}" "${REPO_ROOT}/toolchain" \
        "${HOME}/.local/share/3ds-forwarder/toolchain"; do
        if [[ -n "${dir}" && -x "${dir}/bin/makerom" && -x "${dir}/bin/bannertool" ]]; then
            printf '%s\n' "${dir}"
            return 0
        fi
    done
    return 1
}

slugify() {
    local slug
    slug="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' \
        | tr -s '-' | sed 's/^-//; s/-$//')"
    printf '%s\n' "${slug:-game}"
}

derive_unique_id() {
    local digest
    digest="$(printf '%s' "injected/$1/$2" | sha256sum | cut -c1-4)"
    printf '0x%05X\n' $((UNIQUE_ID_BASE + 0x${digest}))
}

write_manifest() {
    local file="$1" content="$2" data_dir="$3" system_dir="$4"
    {
        echo "# Read by RetroArch's single-game mode (injector/patches/retroarch)."
        echo "content = \"${content}\""
        echo "data_dir = \"${data_dir}\""
        [[ -z "${system_dir}" ]] || echo "system_dir = \"${system_dir}\""
    } > "${file}"
}

main() {
    local title="" author="RetroArch" icon="" banner="" audio="" unique_id=""
    local system_dir="" toolchain="" output=""
    local -a positional=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --title) title="$2"; shift 2 ;;
            --author) author="$2"; shift 2 ;;
            --icon) icon="$2"; shift 2 ;;
            --banner) banner="$2"; shift 2 ;;
            --audio) audio="$2"; shift 2 ;;
            --unique-id) unique_id="$2"; shift 2 ;;
            --system-dir) system_dir="$2"; shift 2 ;;
            --toolchain) toolchain="$2"; shift 2 ;;
            -o | --output) output="$2"; shift 2 ;;
            -h | --help) usage 0 ;;
            -*) die "Unknown option: $1" ;;
            *) positional+=("$1"); shift ;;
        esac
    done
    [[ ${#positional[@]} -eq 2 ]] || usage 1

    local core="${positional[0]}" rom="${positional[1]}"
    [[ -f "${rom}" ]] || die "ROM not found: ${rom}"
    local rom_name
    rom_name="$(basename "${rom}")"
    [[ "${rom_name}" != *'"'* ]] || die "ROM file names cannot contain double quotes"

    if [[ -z "${toolchain}" ]]; then
        toolchain="$(find_toolchain)" || die "No toolchain found (build it with packaging/toolchain/build-tools.sh)"
    fi
    local base_dir="${toolchain}/bases/${core}"
    [[ -f "${base_dir}/retroarch.elf" ]] \
        || die "No base for ${core}: run packaging/toolchain/build-base.sh ${toolchain} ${core}"

    # shellcheck source=/dev/null
    source "${base_dir}/base.env"
    [[ "${APP_BIG_TEXT_SECTION:-0}" != 1 ]] \
        || die "${core} needs a big text section (svchax), not supported yet"

    title="${title:-${rom_name%.*}}"
    local slug
    slug="$(slugify "${title}")"
    unique_id="${unique_id:-$(derive_unique_id "${core}" "${slug}")}"
    output="${output:-${PWD}/${slug}.cia}"
    icon="${icon:-${base_dir}/icon.png}"
    banner="${banner:-${base_dir}/banner.png}"
    audio="${audio:-${base_dir}/audio.wav}"

    # Global, so the EXIT trap can still see it.
    WORK_DIR="$(mktemp -d)"
    trap 'rm -rf "${WORK_DIR}"' EXIT
    local work="${WORK_DIR}"
    mkdir -p "${work}/romfs/game"
    cp "${rom}" "${work}/romfs/game/${rom_name}"
    cp "${SEED_CFG}" "${work}/romfs/game/retroarch.cfg"
    if [[ -d "${base_dir}/assets" ]]; then
        cp -r "${base_dir}/assets" "${work}/romfs/game/assets"
    else
        log "[WARN]" "Base without assets/: the touch screen menu will not be available"
    fi
    write_manifest "${work}/romfs/game/manifest.cfg" "${rom_name}" \
        "${DATA_ROOT}/${slug}" "${system_dir}"

    log "[INFO]" "Title '${title}', unique ID ${unique_id}, data in ${DATA_ROOT}/${slug}"
    "${toolchain}/bin/bannertool" makesmdh -s "${title}" -l "${title}" -p "${author}" \
        -i "${icon}" -f visible,recordusage -o "${work}/icon.icn" > /dev/null
    "${toolchain}/bin/bannertool" makebanner -i "${banner}" -a "${audio}" \
        -o "${work}/banner.bnr" > /dev/null

    "${toolchain}/bin/makerom" -f cia -o "${output}" -rsf "${RSF}" -target t -exefslogo \
        -elf "${base_dir}/retroarch.elf" -icon "${work}/icon.icn" -banner "${work}/banner.bnr" \
        -DAPP_TITLE="${title}" \
        -DAPP_PRODUCT_CODE="CTR-I-${unique_id: -4}" \
        -DAPP_UNIQUE_ID="${unique_id}" \
        -DAPP_SYSTEM_MODE="${APP_SYSTEM_MODE}" \
        -DAPP_SYSTEM_MODE_EXT="${APP_SYSTEM_MODE_EXT}" \
        -DAPP_ENCRYPTED=false \
        -DROMFS_DIR="${work}/romfs"

    log "[ OK ]" "CIA ready: ${output}"
}

main "$@"
