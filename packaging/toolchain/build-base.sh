#!/usr/bin/env bash
# Build the bases: one RetroArch 3DS ELF per core, statically linked and
# patched with retroarch/patches/ for single-game CIAs, or a standalone
# emulator patched with emulators/<NAME>/patches/.
#
#   packaging/toolchain/build-base.sh OUT_DIR NAME [NAME...]
#   packaging/toolchain/build-base.sh OUT_DIR all
#
# NAME is a core recipe, retroarch/cores/<NAME>.env, or an emulator recipe,
# emulators/<NAME>/recipe.env. An emulator writes OUT_DIR/bases/<NAME>/
# app.elf, app.rsf, romfs/, icon.png, banner.png and base.env. A core writes
#   OUT_DIR/bases/<CORE>/retroarch.elf   patched RetroArch + core
#   OUT_DIR/bases/<CORE>/base.env        system mode and source revisions
#   OUT_DIR/bases/<CORE>/{icon,banner}.png, audio.wav   RetroArch's defaults
#   OUT_DIR/bases/<CORE>/assets/bottom_menu.png         touch screen menu
#   OUT_DIR/bases/<CORE>/core_options.h  the core's option definitions
# and records the revision in OUT_DIR/VERSIONS. Sources are checked out in
# build/base/ (WORK_DIR overrides it). With DEVKITARM set (inside
# devkitpro/devkitarm) it builds directly; otherwise it runs itself in that
# image with docker or podman (CONTAINER_ENGINE overrides which), as the
# calling user.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
readonly HERE REPO_ROOT
# shellcheck source=packaging/toolchain/versions.env
source "${HERE}/versions.env"
readonly RECIPES_DIR="${REPO_ROOT}/retroarch/cores"
readonly PATCHES_DIR="${REPO_ROOT}/retroarch/patches"
readonly EMULATORS_DIR="${REPO_ROOT}/emulators"
# Current devkitPro ships libctru 2.x, with picasso and bin2s in tools/bin.
RA_MAKE_FLAGS=(-f Makefile.ctr USE_CTRULIB_2=1)
# A single-game CIA has no use for networking (netplay, updaters,
# achievements, cloud sync): leaving it out makes the ELF smaller and quicker
# to load. RA_LEAN=0 builds RetroArch's default feature set.
if [[ "${RA_LEAN:-1}" == 1 ]]; then
    RA_MAKE_FLAGS+=(HAVE_NETWORKING=0 HAVE_CHEEVOS=0 HAVE_CLOUDSYNC=0
        HAVE_IFINFO=0 HAVE_BUILTINMBEDTLS=0)
fi
readonly -a RA_MAKE_FLAGS
# devkitARM's GCC (16.x) defaults to C23 and turns old warnings into errors
# (e.g. int* passed as int32_t*, which is long* on ARM newlib). Cores predate
# that, so they build as gnu17 with those errors back to warnings. Passed in
# the environment: libretro makefiles add their own flags with "CFLAGS +=".
readonly CORE_COMPAT_CFLAGS="-std=gnu17 -Wno-error=incompatible-pointer-types \
-Wno-error=int-conversion -Wno-error=implicit-function-declaration -Wno-error=implicit-int"

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

# Checks out REF of REPO in DIR, shallow, discarding local changes.
checkout() {
    local repo="$1" ref="$2" dir="$3"
    if [[ ! -d "${dir}/.git" ]]; then
        git init -q "${dir}"
        git -C "${dir}" remote add origin "${repo}"
    fi
    git -C "${dir}" fetch -q --depth 1 origin "${ref}"
    git -C "${dir}" checkout -q -f FETCH_HEAD
    git -C "${dir}" clean -q -fdx
}

# Checks out a single file of a big repository (blobless partial clone).
fetch_file() {
    local repo="$1" ref="$2" path="$3" dir="$4"
    if [[ ! -d "${dir}/.git" ]]; then
        git init -q "${dir}"
        git -C "${dir}" remote add origin "${repo}"
        git -C "${dir}" config remote.origin.promisor true
        git -C "${dir}" config remote.origin.partialclonefilter blob:none
    fi
    git -C "${dir}" fetch -q --depth 1 --filter=blob:none origin "${ref}"
    git -C "${dir}" checkout -q -f FETCH_HEAD -- "${path}"
}

patch_retroarch() {
    local ra_dir="$1" patch
    for patch in "${PATCHES_DIR}"/*.patch; do
        [[ -e "${patch}" ]] || continue
        log "[INFO]" "Applying $(basename "${patch}")"
        git -C "${ra_dir}" apply "${patch}"
    done
}

patches_digest() {
    cat "${PATCHES_DIR}"/*.patch 2> /dev/null | sha256sum | cut -c1-12
}

# Prints a variable as Makefile.ctr resolves it for this core.
ra_make_var() {
    local ra_dir="$1" core="$2" var="$3"
    # shellcheck disable=SC2016 # $($*) is make syntax, not shell
    make -s --no-print-directory -C "${ra_dir}" "${RA_MAKE_FLAGS[@]}" LIBRETRO="${core}" \
        --eval 'print-%: ; @echo $($*)' "print-${var}"
}

build_core() {
    local work="$1" recipe="$2" out_dir="$3" ra_dir="$1/RetroArch"
    local CORE_NAME CORE_REPO CORE_REF CORE_SUBDIR CORE_MAKEFILE CORE_LIB CORE_CFLAGS=""
    local CORE_OPTIONS="" CORE_MAKE_ARGS=""
    # shellcheck source=retroarch/cores/gambatte.env
    source "${recipe}"
    local core_dir="${work}/cores/${CORE_NAME}" dest="${out_dir}/bases/${CORE_NAME}"
    local jobs
    local -a make_args
    jobs="$(nproc 2> /dev/null || echo 2)"
    read -ra make_args <<< "${CORE_MAKE_ARGS}"

    log "[INFO]" "Building core ${CORE_NAME} (${CORE_REF})"
    checkout "${CORE_REPO}" "${CORE_REF}" "${core_dir}"
    # Some cores (picodrive: Cyclone, libpicofe...) build from submodules.
    if [[ -f "${core_dir}/.gitmodules" ]]; then
        git -C "${core_dir}" submodule update -q --init --recursive --depth 1 \
            || git -C "${core_dir}" submodule update -q --init --recursive
    fi
    CFLAGS="${CORE_COMPAT_CFLAGS} ${CORE_CFLAGS}" \
        make -C "${core_dir}/${CORE_SUBDIR}" -f "${CORE_MAKEFILE}" platform=ctr \
        "${make_args[@]}" -j"${jobs}" > /dev/null
    install -m 0644 "${core_dir}/${CORE_SUBDIR}/${CORE_LIB}" "${ra_dir}/libretro_ctr.a"

    log "[INFO]" "Linking RetroArch ${RETROARCH_REF} with ${CORE_NAME}"
    rm -f "${ra_dir}/retroarch_3ds.elf"
    make -C "${ra_dir}" "${RA_MAKE_FLAGS[@]}" LIBRETRO="${CORE_NAME}" -j"${jobs}" \
        retroarch_3ds.elf > /dev/null

    install -D -m 0644 "${ra_dir}/retroarch_3ds.elf" "${dest}/retroarch.elf"
    install -m 0644 "${ra_dir}/$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_ICON)" "${dest}/icon.png"
    install -m 0644 "${ra_dir}/$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_BANNER)" "${dest}/banner.png"
    install -m 0644 "${ra_dir}/$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_AUDIO)" "${dest}/audio.wav"
    install -D -m 0644 "${work}/retroarch-assets/ctr/bottom_menu.png" \
        "${dest}/assets/bottom_menu.png"
    # The GUI reads the option definitions (keys, values, defaults) from it.
    if [[ -n "${CORE_OPTIONS}" ]]; then
        install -m 0644 "${core_dir}/${CORE_OPTIONS}" "${dest}/core_options.h"
    else
        rm -f "${dest}/core_options.h"
    fi
    {
        echo "CORE_NAME=${CORE_NAME}"
        echo "CORE_REF=${CORE_REF}"
        echo "RETROARCH_REF=${RETROARCH_REF}"
        echo "PATCHES=$(patches_digest)"
        echo "LEAN=${RA_LEAN:-1}"
        echo "APP_SYSTEM_MODE=$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_SYSTEM_MODE)"
        echo "APP_SYSTEM_MODE_EXT=$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_SYSTEM_MODE_EXT)"
        echo "APP_BIG_TEXT_SECTION=$(ra_make_var "${ra_dir}" "${CORE_NAME}" APP_BIG_TEXT_SECTION)"
    } > "${dest}/base.env"
    log "[ OK ]" "Base ready: ${dest}/retroarch.elf"
}

# Every patch of emulator NAME, concatenated, as a short digest.
emulator_patches_digest() {
    cat "${EMULATORS_DIR}/$1/patches"/*.patch 2> /dev/null | sha256sum | cut -c1-12
}

is_emulator() {
    [[ -f "${EMULATORS_DIR}/$1/recipe.env" ]]
}

build_emulator() {
    local work="$1" name="$2" out_dir="$3" patch jobs
    local EMU_NAME EMU_REPO EMU_REF EMU_MAKE_ARGS="" EMU_ELF EMU_RSF EMU_ROMFS
    local EMU_ICON EMU_BANNER APP_SYSTEM_MODE APP_SYSTEM_MODE_EXT EMU_PACKAGES=""
    local EMU_MENU_NAME="" EMU_BOTTOM_SCREEN="" EMU_TOP_BACKGROUND=""
    # shellcheck source=emulators/snes9x_3ds/recipe.env
    source "${EMULATORS_DIR}/${name}/recipe.env"
    local src="${work}/emulators/${EMU_NAME}" dest="${out_dir}/bases/${EMU_NAME}"
    local -a make_args
    read -ra make_args <<< "${EMU_MAKE_ARGS}"
    jobs="$(nproc 2> /dev/null || echo 2)"

    log "[INFO]" "Building ${EMU_NAME} (${EMU_REF})"
    checkout "${EMU_REPO}" "${EMU_REF}" "${src}"
    git -C "${src}" submodule update -q --init --depth 1 --recursive
    for patch in "${EMULATORS_DIR}/${name}/patches"/*.patch; do
        [[ -e "${patch}" ]] || continue
        log "[INFO]" "Applying $(basename "${patch}")"
        git -C "${src}" apply "${patch}"
    done
    make -C "${src}" "${make_args[@]}" -j"${jobs}" elf > /dev/null

    rm -rf "${dest}"
    install -D -m 0644 "${src}/${EMU_ELF}" "${dest}/app.elf"
    install -m 0644 "${src}/${EMU_RSF}" "${dest}/app.rsf"
    install -m 0644 "${src}/${EMU_ICON}" "${dest}/icon.png"
    install -m 0644 "${src}/${EMU_BANNER}" "${dest}/banner.png"
    cp -r "${src}/${EMU_ROMFS}" "${dest}/romfs"
    find "${dest}/romfs" -name '*.t3s' -delete
    {
        echo "KIND=standalone"
        echo "CORE_NAME=${EMU_NAME}"
        echo "CORE_REF=${EMU_REF}"
        echo "PATCHES=$(emulator_patches_digest "${name}")"
        echo "APP_SYSTEM_MODE=${APP_SYSTEM_MODE}"
        echo "APP_SYSTEM_MODE_EXT=${APP_SYSTEM_MODE_EXT}"
        echo "MENU_NAME=${EMU_MENU_NAME:-${EMU_NAME}}"
        echo "BOTTOM_SCREEN_FILES=${EMU_BOTTOM_SCREEN}"
        echo "TOP_BACKGROUND_FILES=${EMU_TOP_BACKGROUND}"
    } > "${dest}/base.env"
    log "[ OK ]" "Base ready: ${dest}/app.elf"
}

build_here() {
    local out_dir="$1"
    shift
    local work="${WORK_DIR:-${REPO_ROOT}/build/base}" core recipe
    command -v git > /dev/null || die "git is required"
    command -v make > /dev/null || die "make is required"
    export CTRULIB="${CTRULIB:-${DEVKITPRO:-/opt/devkitpro}/libctru}"
    [[ -d "${CTRULIB}" ]] || die "libctru not found at ${CTRULIB}"

    # Validate every recipe before the long checkouts.
    local -a cores=() emulators=()
    for core in "$@"; do
        if is_emulator "${core}"; then
            emulators+=("${core}")
        elif [[ -f "${RECIPES_DIR}/${core}.env" ]]; then
            cores+=("${core}")
        else
            die "No recipe: retroarch/cores/${core}.env or emulators/${core}/recipe.env"
        fi
    done

    mkdir -p "${work}"
    for core in "${emulators[@]}"; do
        build_emulator "${work}" "${core}" "${out_dir}"
        record_version "${out_dir}" "${core}" "$(emulator_patches_digest "${core}")"
    done
    [[ ${#cores[@]} -gt 0 ]] || return 0

    log "[INFO]" "Checking out RetroArch ${RETROARCH_REF}"
    checkout "${RETROARCH_REPO}" "${RETROARCH_REF}" "${work}/RetroArch"
    patch_retroarch "${work}/RetroArch"
    log "[INFO]" "Fetching the 3DS bottom screen assets"
    fetch_file "${RETROARCH_ASSETS_REPO}" "${RETROARCH_ASSETS_REF}" ctr "${work}/retroarch-assets"

    for core in "${cores[@]}"; do
        recipe="${RECIPES_DIR}/${core}.env"
        build_core "${work}" "${recipe}" "${out_dir}"
        record_version "${out_dir}" "${core}" "${RETROARCH_REF}+$(patches_digest)"
    done
}

record_version() {
    local out_dir="$1" core="$2" version="$3" versions="$1/VERSIONS"
    touch "${versions}"
    grep -v "^base-${core}=" "${versions}" > "${versions}.new" || true
    echo "base-${core}=${version}" >> "${versions}.new"
    mv "${versions}.new" "${versions}"
}

# devkitPro packages the requested emulators link (their EMU_PACKAGES).
emulator_packages() {
    local name
    for name in "$@"; do
        is_emulator "${name}" || continue
        # shellcheck disable=SC1090 # recipes are data files
        (source "${EMULATORS_DIR}/${name}/recipe.env" && echo "${EMU_PACKAGES:-}")
    done | tr ' ' '\n' | sort -u | tr '\n' ' '
}

build_in_container() {
    local out_dir="$1" engine z packages build
    shift
    local -a run user_args
    engine="$(container_engine)" || die "Set DEVKITARM, or install docker or podman"
    read -ra run <<< "${engine}"
    z="$(volume_suffix)"
    packages="$(emulator_packages "$@")"
    build="bash /src/packaging/toolchain/build-base.sh /out $(printf '%q ' "$@")"
    user_args=(-u "$(id -u):$(id -g)")
    if [[ "${run[-1]}" == podman ]]; then
        # Rootless podman maps the calling user to root inside the container.
        user_args=()
    elif [[ -n "${packages// /}" ]]; then
        # Install the packages as root, then build as the calling user.
        user_args=()
        build="setpriv --reuid=$(id -u) --regid=$(id -g) --clear-groups ${build}"
    fi
    if [[ -n "${packages// /}" ]]; then
        build="dkp-pacman -Sy --needed --noconfirm ${packages} > /dev/null && ${build}"
    fi
    log "[INFO]" "Building bases ($*) in ${DEVKITARM_IMAGE} (${engine})"
    "${run[@]}" run --rm "${user_args[@]}" -e HOME=/tmp -e RA_LEAN="${RA_LEAN:-1}" \
        -v "${REPO_ROOT}:/src${z}" -v "${out_dir}:/out${z}" -w /src "${DEVKITARM_IMAGE}" \
        bash -c "${build}"
}

# Every recipe in retroarch/cores/ and emulators/, by name.
all_recipes() {
    local recipe
    for recipe in "${RECIPES_DIR}"/*.env; do
        basename "${recipe}" .env
    done
    for recipe in "${EMULATORS_DIR}"/*/recipe.env; do
        [[ -e "${recipe}" ]] && basename "$(dirname "${recipe}")"
    done
}

main() {
    [[ $# -ge 2 ]] || die "Usage: build-base.sh OUT_DIR CORE [CORE...] | all"
    mkdir -p "$1"
    local out_dir
    out_dir="$(cd "$1" && pwd)"
    shift
    if [[ "$1" == all ]]; then
        mapfile -t cores < <(all_recipes)
        set -- "${cores[@]}"
    fi
    if [[ -n "${DEVKITARM:-}" ]]; then
        build_here "${out_dir}" "$@"
    else
        build_in_container "${out_dir}" "$@"
    fi
}

main "$@"
