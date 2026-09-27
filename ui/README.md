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

1. Fill in the **Forwarder details** form: core, ROM path, name, short/long
   name, manufacturer, optional banner audio, and output path. These map
   1:1 onto `build_forwarder`'s `--core`/`--rom`/`--name`/... flags. The
   core field autocompletes against `data/cores.json` and is validated
   before a build starts, exactly like `interactive_build.py` does.
2. In **Artwork (SteamGridDB)**, paste a SteamGridDB API key (get one from
   your SteamGridDB account preferences). Check "Remember" to keep it
   between runs.
3. Each of **Icon**, **Hero** and **Logo** can be searched independently.
   Searching uses the **Long name** field as the query:
   - if SteamGridDB returns exactly one match, it's used automatically;
   - if there's a single exact (case-insensitive) name match among several
     results, that one is used automatically;
   - otherwise, a dialog lists every candidate so you decide which game the
     assets belong to. This resolved game is then reused for the other two
     asset searches, so you're not asked to disambiguate three times.
4. Picking an asset opens a thumbnail gallery. Every tile shows a
   lower-quality preview (SteamGridDB's own thumbnail rendition, not the
   full asset) so the gallery loads quickly; clicking a tile downloads the
   full asset and applies it.
5. The **Composed banner preview** always reflects the current Hero +
   Logo: the hero is cover-cropped to 256x128 as the background, and the
   logo is pasted on top of it (scaled down, alpha-blended), so the logo
   sits in front of / above the hero. Either can be missing. You can also
   bypass this entirely with "Use a local banner file instead...".
6. Any of the three slots can also be filled from a local file instead of
   SteamGridDB ("Browse local file...") — useful for artwork you already
   have.
7. Click **Build .cia**. Progress and any errors from `build_forwarder()`
   stream into the log panel at the bottom in real time.

## Notes

- The icon and the composed banner are written to a temporary directory
  right before a build starts, and handed to `build_forwarder()` as plain
  file paths — the same `--icon`/`--banner` inputs the CLI accepts. They're
  cleaned up once the build finishes (success or failure).
- If neither an icon nor a banner is picked, `build_forwarder()` falls back
  to its own placeholder assets, exactly like the CLI does with no
  `--icon`/`--banner` flags.
