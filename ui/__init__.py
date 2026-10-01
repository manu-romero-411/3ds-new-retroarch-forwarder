"""Qt UI for 3ds-new-forwarder-generator.

This package is a thin frontend over the existing ``tools`` package: it
never re-implements forwarder-building logic, only collects the same
fields the CLI asks for (see ``tools/build_forwarder.py``) through
widgets, plus an optional SteamGridDB artwork picker (``ui/sgdb``).

Run it as a module from the project root::

    python3 -m ui.app

or via the convenience launcher at the project root::

    python3 run_ui.py
"""
