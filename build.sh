#!/bin/bash
set -e
# "make cia" ya incluye "make" (el .3dsx) como dependencia, y además genera
# el .cia instalable con FBI (icon.icn/banner.bnr se generan solos con
# assets placeholder la primera vez, ver tools/generate_placeholder_assets.py).
docker run --rm -it -v "$(pwd)":/work 3ds-forwarder-dev bash -c "make clean && make cia"
