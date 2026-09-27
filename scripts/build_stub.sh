#!/bin/bash
set -e
# "make cia" already depends on "make" (the .3dsx), and also produces the
# installable .cia (icon.icn/banner.bnr are generated on first run from
# placeholder assets, see tools/generate_placeholder_assets.py).
#
# Runs as the host UID/GID so files left behind under stub/ (build/,
# *.elf, *.cia, ...) are owned by the calling user, not root -- the
# devkitpro/devkitarm base image runs as root by default.
#
# Run from the project root: ./scripts/build_stub.sh
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm -it \
    -u "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "${PROJECT_ROOT}":/work \
    3ds-forwarder-dev \
    bash -c "cd stub && make clean && make cia"
