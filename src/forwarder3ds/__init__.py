"""3DS RetroArch forwarder generator.

Builds one installable ``.cia`` per game that launches the matching
RetroArch core with that game, without bundling RetroArch itself. A stub
compiled once is repackaged with a per-game RomFS and a unique Title ID.

The version is never written by hand: it is the git tag (``v1.2.3``). See
:mod:`forwarder3ds.version` for where it is read from.
"""

from forwarder3ds.version import detect_version

__version__ = detect_version()
