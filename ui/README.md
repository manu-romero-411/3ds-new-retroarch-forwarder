# Forwarder Builder UI

A PySide6 (Qt) frontend over the existing `tools/build_forwarder.py`
backend. It exposes the same fields as the CLI/interactive builders
(`tools/build_forwarder.py`, `tools/interactive_build.py`) as a form, plus
an artwork picker backed by the [SteamGridDB](https://www.steamgriddb.com/)
API for the icon and the banner.

The UI never re-implements forwarder-building logic: it collects fields
into the same `ForwarderRequest` dataclass the CLI uses and calls the same
`build_forwarder()` function, in a background thread so the window stays
responsive.

## Installing

The UI needs a couple of Python packages the CLI toolchain doesn't:

```bash
pip3 install -r requirements-ui.txt
```

(This is on top of `makerom`, `bannertool` and `ffmpeg`, which the actual
`.cia` build step still needs — see the Dockerfile at the project root.)

## Running

From the project root:

```bash
python3 -m ui.app
# or, equivalently:
python3 run_ui.py
```

If you're running inside the project's Docker container, the UI needs a
display to draw to. On Linux, forward X11 into the container:

```bash
docker run --rm -v "$(pwd)":/work -e DISPLAY="$DISPLAY" \
  -v /tmp/.X11-unix:/tmp/.X11-unix -it 3ds-forwarder-builder \
  python3 run_ui.py
```

Running the UI directly on the host (outside Docker) works too, as long as
`makerom`/`bannertool`/`ffmpeg` are on `PATH` when you actually click
"Build .cia".

## Workflow

The top bar holds the file actions (**New**, **Open…**, **Save**, **Save As…**,
with the usual Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S shortcuts) and the
**Title ID** controls. The window title shows the current file and a `*`
while there are unsaved changes; a small line under the bar shows the file's
name, or "Creating new CIA…" for a document that has none yet.

1. Fill in the **Forwarder details** form: core, ROM path, short/long name,
   manufacturer and optional banner audio. These map 1:1 onto
   `build_forwarder`'s `--core`/`--rom`/`--short-name`/... flags. There is no
   separate "name" field: the **long name** is the forwarder's identifier.
   **Browse SD…** picks the ROM on an inserted 3DS SD card and fills in its
   path relative to the card's root. Both name fields are filled from the ROM's
   file name (extension and `(...)`/`[...]` tags removed) until you edit them.
   The core field autocompletes against `data/cores.json` and is validated
   before a save starts, exactly like `interactive_build.py` does.
2. The **Title ID** in the top bar updates live from those fields. Untick
   **Auto** to type a Unique ID by hand; a value that collides with a core
   CIA or another forwarder is flagged and blocks saving. On narrow windows
   the Title ID controls wrap onto a second row.
3. In **Artwork (SteamGridDB)**, paste a SteamGridDB API key (get one from
   your SteamGridDB account preferences). Check "Remember" to keep it
   between runs.
4. Each of **Icon**, **Hero** and **Logo** can be searched independently.
   Searching uses the **Long name** field as the query:
   - if SteamGridDB returns exactly one match, it's used automatically;
   - if there's a single exact (case-insensitive) name match among several
     results, that one is used automatically;
   - otherwise, a dialog lists every candidate so you decide which game the
     assets belong to. This resolved game is then reused for the other two
     asset searches, so you're not asked to disambiguate three times.
5. Picking an asset opens a thumbnail gallery. Every tile shows a
   lower-quality preview (SteamGridDB's own thumbnail rendition, not the
   full asset) so the gallery loads quickly; clicking a tile downloads the
   full asset and applies it.
6. The **Composed banner preview** always reflects the current Hero +
   Logo: the hero is cover-cropped to 256x128 as the background, and the
   logo is pasted on top of it (scaled down, alpha-blended), so the logo
   sits in front of / above the hero. Either can be missing. You can also
   bypass this entirely with "Use a local banner file instead...".
7. Any of the three slots can also be filled from a local file instead of
   SteamGridDB ("Browse local file...") — useful for artwork you already
   have.
8. **Save** builds the `.cia`. Progress and any errors from
   `build_forwarder()` stream into the (monospaced) log panel in real time.

## Opening and saving `.cia` files

- **New** clears the form and artwork (after confirming, if there are
  unsaved changes).
- **Open…** reads a forwarder `.cia` built by this tool
  (`tools/cia_reader.py`) and fills in the whole window: core, ROM path,
  names, manufacturer, icon, banner image, banner audio and Title ID. A file
  that is not such a CIA is rejected with an explanation and nothing changes.
- **Save** replaces the open file. With no file yet, it asks where to save
  (starting in your home directory, defaulting to the ROM's file name without
  its extension). **Save As…** always asks. The `.cia` extension is enforced.
- A CIA is never patched: saving **rebuilds it from scratch**. Its Title ID is
  kept, so the new file installs over the old one. The loaded banner is shown
  as a *local banner override*, because the original hero/logo composition
  can't be recovered from the finished image; use "Reset to composite" or
  Clear to discard it.
- Once a document has a file, its Unique ID stays pinned to that file. Tick
  **Auto** to derive a fresh one from the fields instead.

## Notes

- The icon and the composed banner are written to a temporary directory
  right before a build starts, and handed to `build_forwarder()` as plain
  file paths — the same `--icon`/`--banner` inputs the CLI accepts. They're
  cleaned up once the build finishes (success or failure).
- If neither an icon nor a banner is picked, `build_forwarder()` falls back
  to its own placeholder assets, exactly like the CLI does with no
  `--icon`/`--banner` flags.

## Finding the 3DS SD card

`Browse SD…` looks for a mounted volume whose root has a `Nintendo 3DS` folder
or a `boot.firm` file (`tools/sd_card.py`). It scans the usual removable-media
locations only: `/run/media/*/*`, `/media/*/*` and `/media/*` on Linux,
`/Volumes/*` on macOS and the drive letters on Windows. If several cards match
you are asked which one; if none does, type the path by hand.
