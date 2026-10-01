# Banner jingles

Drop `.wav` files here. They show up in the **Banner jingle** dropdown of the
UI and can be used from the CLI with `--jingle <name>` (the file name without
`.wav`; `--list-jingles` shows what is available).

This is the tune that plays when the forwarder's icon is selected on the
HOME menu. A file must be:

- a PCM **WAV**, **16-bit**, mono or stereo;
- **3 seconds at most** (the banner audio limit).

Files that break these rules are still listed, greyed out, with the reason as
a tooltip. Nothing is converted for you here: export the file already in this
format (e.g. in Audacity: *Export Audio → WAV → Signed 16-bit PCM*).
