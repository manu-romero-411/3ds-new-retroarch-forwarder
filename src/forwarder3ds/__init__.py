"""3DS RetroArch injector: standalone CIAs of one game, each with its own RetroArch.

Builds one installable ``.cia`` per game, in the spirit of New Super
Ultimate Injector: a RetroArch build for the game's core (compiled once per
core, see ``retroarch/``) is repackaged with the ROM in its RomFS and a
unique Title ID. Each game keeps its data in ``sdmc:/saves/<console>/<game>``.

The version is never written by hand: it is the git tag (``v1.2.3``). See
:mod:`forwarder3ds.version` for where it is read from.
"""

from forwarder3ds.version import detect_version

__version__ = detect_version()
