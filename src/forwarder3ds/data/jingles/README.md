# Banner jingles

Jingles bundled with the program. Your own go in
`~/.local/share/3ds-forwarder/jingles/` (*Settings › Jingles and logos ›
Open*), and are listed after these.

They show up in the **Jingle** list of the window and can be used from the
command line with `--jingle <name>` (the file name without `.wav`;
`3ds-forwarder media` lists them).

This is the tune that plays when the forwarder's icon is selected on the
HOME menu. A file must be:

- a PCM **WAV**, **16-bit**, mono or stereo;
- **3 seconds at most** (the banner audio limit).

Files that break these rules are still listed, greyed out, with the reason as
a tooltip. Export the file already in this format (e.g. in Audacity:
*Export Audio → WAV → Signed 16-bit PCM*); any sample rate works.
