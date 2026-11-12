"""Entry point of the Windows build's 3ds-forwarder.exe (the command line tool)."""

import sys

from forwarder3ds.cli import main

sys.exit(main())
