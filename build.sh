#!/bin/bash
set -e
docker run --rm -it -v "$(pwd)":/work 3ds-forwarder-dev bash -c "make clean && make"
