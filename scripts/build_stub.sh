#!/bin/bash
set -e
# "make cia" already depends on "make" (the .3dsx), and also produces the
# installable .cia (icon.icn/banner.bnr are generated on first run from
# placeholder assets, see tools/generate_placeholder_assets.py).
#
# Run from the project root: ./scripts/build_stub.sh
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm -it -v "${PROJECT_ROOT}":/work 3ds-forwarder-dev \
    bash -c "cd stub && make clean && make cia"
