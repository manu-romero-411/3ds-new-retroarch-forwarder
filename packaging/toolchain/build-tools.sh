#!/usr/bin/env bash
# Build makerom and bannertool from the revisions pinned in versions.env.
#
#   packaging/toolchain/build-tools.sh [--static] OUT_DIR
#
# Writes OUT_DIR/bin/{makerom,bannertool}, their licences in
# OUT_DIR/LICENSES/ and what was built in OUT_DIR/VERSIONS. Runs on the
# machine (or in the container) whose system and architecture the binaries
# are for: it needs git, make, a C and a C++ compiler. --static links
# everything statically (meant for an Alpine/musl container), so the result
# runs on any Linux of the same architecture. In an MSYS2 MINGW64 shell it
# builds the Windows programs (makerom.exe, bannertool.exe); use --static
# there too, so they need no MinGW DLLs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
# shellcheck source=packaging/toolchain/versions.env
source "${HERE}/versions.env"

STATIC=0
OUT_DIR=""
JOBS="$(nproc 2> /dev/null || echo 2)"
WORK_DIR=""
# Executable suffix: .exe when building for Windows (MSYS2/MinGW).
# Executable suffix and compilers: MinGW's gcc/g++ when building for Windows.
case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) EXE=".exe" CC_CMD="gcc" CXX_CMD="g++" ;;
    *) EXE="" CC_CMD="cc" CXX_CMD="c++" ;;
esac
readonly EXE CC_CMD CXX_CMD

log() {
    local tag="$1"
    shift
    printf '%s %s %s\n' "${tag}" "$(date '+%Y-%m-%d_%H:%M:%S')" "$*" >&2
}
log_info() { log "[INFO]" "$@"; }
log_ok() { log "[ OK ]" "$@"; }
die() {
    log "[ERR ]" "$@"
    exit 1
}

cleanup() {
    if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
        rm -rf "${WORK_DIR}"
    fi
}
trap cleanup EXIT

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --static) STATIC=1 ;;
            -h | --help)
                sed -n '2,11s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
                exit 0
                ;;
            -*) die "Unknown option: $1" ;;
            *) OUT_DIR="$1" ;;
        esac
        shift
    done
    [[ -n "${OUT_DIR}" ]] || die "Usage: build-tools.sh [--static] OUT_DIR"
}

# Shallow checkout of one revision (tag, branch or commit) into $3.
fetch() {
    local repo="$1" ref="$2" dest="$3"
    log_info "Fetching ${repo} @ ${ref}"
    git init -q "${dest}"
    git -C "${dest}" remote add origin "${repo}"
    git -C "${dest}" fetch -q --depth 1 origin "${ref}"
    git -C "${dest}" checkout -q FETCH_HEAD
}

build_makerom() {
    local src="${WORK_DIR}/Project_CTR" cc="${CC_CMD}" cxx="${CXX_CMD}"
    fetch "${MAKEROM_REPO}" "${MAKEROM_REF}" "${src}"
    if [[ "${STATIC}" -eq 1 ]]; then
        cc="${CC_CMD} -static"
        cxx="${CXX_CMD} -static"
    fi
    log_info "Building makerom"
    make -C "${src}/makerom" -j"${JOBS}" CC="${cc}" CXX="${cxx}" deps > /dev/null
    make -C "${src}/makerom" -j"${JOBS}" CC="${cc}" CXX="${cxx}" > /dev/null
    install -D -m 0755 "${src}/makerom/bin/makerom${EXE}" "${OUT_DIR}/bin/makerom${EXE}"
    install -D -m 0644 "${src}/makerom/LICENSE" "${OUT_DIR}/LICENSES/makerom.txt"
}

# bannertool's own makefile (Steveice10/buildtools) rejects aarch64 hosts, so
# its handful of sources are compiled here with the flags that makefile uses.
build_bannertool() {
    local src="${WORK_DIR}/bannertool" obj="${WORK_DIR}/bannertool-obj" file out
    local -a flags=(-O2 -Wall -Wno-unused-function
        -DVERSION_MAJOR=1 -DVERSION_MINOR=2 -DVERSION_MICRO=0
        -I"${src}/source" -I"${src}/source/3ds" -I"${src}/source/pc")
    local -a objects=() link=()
    fetch "${BANNERTOOL_REPO}" "${BANNERTOOL_REF}" "${src}"
    [[ "${STATIC}" -eq 1 ]] && link=(-static)
    log_info "Building bannertool"
    mkdir -p "${obj}"
    while IFS= read -r -d '' file; do
        out="${obj}/$(basename "${file%.*}").o"
        case "${file}" in
            *.c) "${CC_CMD}" "${flags[@]}" -std=gnu11 -c "${file}" -o "${out}" ;;
            *.cpp) "${CXX_CMD}" "${flags[@]}" -std=gnu++11 -c "${file}" -o "${out}" ;;
        esac
        objects+=("${out}")
    done < <(find "${src}/source" -type f \( -name '*.c' -o -name '*.cpp' \) -print0 | sort -z)
    "${CXX_CMD}" "${link[@]}" "${objects[@]}" -o "${obj}/bannertool${EXE}"
    install -D -m 0755 "${obj}/bannertool${EXE}" "${OUT_DIR}/bin/bannertool${EXE}"
    install -D -m 0644 "${src}/LICENSE.txt" "${OUT_DIR}/LICENSES/bannertool.txt"
}

write_versions() {
    local versions="${OUT_DIR}/VERSIONS"
    {
        echo "# Built by packaging/toolchain/build-tools.sh"
        echo "arch=$(uname -m)"
        echo "linkage=$([[ "${STATIC}" -eq 1 ]] && echo static || echo dynamic)"
        echo "makerom=${MAKEROM_REF}"
        echo "bannertool=${BANNERTOOL_REF:0:12}"
    } > "${versions}.tools"
    # Keep a stub line written by build-stub.sh, if any.
    if [[ -f "${versions}" ]]; then
        grep '^stub=' "${versions}" >> "${versions}.tools" || true
    fi
    mv "${versions}.tools" "${versions}"
}

# Both tools print a banner with their name when run without arguments
# (makerom then exits non-zero): proof that the binary starts on this system.
check_runs() {
    local tool="$1" expected="$2" output
    output="$("${OUT_DIR}/bin/${tool}${EXE}" 2>&1 || true)"
    [[ "${output}" == *"${expected}"* ]] || die "The built ${tool} does not run: ${output:0:200}"
}

main() {
    parse_args "$@"
    local tool
    for tool in git make "${CC_CMD}" "${CXX_CMD}"; do
        command -v "${tool}" > /dev/null || die "${tool} is required"
    done
    mkdir -p "${OUT_DIR}"
    OUT_DIR="$(cd "${OUT_DIR}" && pwd)"
    WORK_DIR="$(mktemp -d)"
    build_makerom
    build_bannertool
    strip "${OUT_DIR}/bin/makerom${EXE}" "${OUT_DIR}/bin/bannertool${EXE}" 2> /dev/null || true
    write_versions
    check_runs makerom "CTR MAKEROM"
    check_runs bannertool "bannertool v"
    log_ok "makerom and bannertool built in ${OUT_DIR}/bin"
}

main "$@"
