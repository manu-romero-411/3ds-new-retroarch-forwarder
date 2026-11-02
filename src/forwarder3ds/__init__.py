"""3DS RetroArch forwarder generator.

Builds one installable ``.cia`` per game that launches the matching
RetroArch core with that game, without bundling RetroArch itself. A stub
compiled once is repackaged with a per-game RomFS and a unique Title ID.
"""
