#!/bin/bash

docker run --rm -v "$(pwd)":/work -it 3ds-forwarder-builder \
  python3 -m tools.interactive_build
exit $?
