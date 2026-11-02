# Platform logos (banner frames)

Frames bundled with the program. Your own go in
`~/.local/share/3ds-forwarder/platform_logos/` (*Settings › Jingles and logos
› Open*), and are listed after these.

They show up in the **Platform logo** list of the window and can be used
from the command line with `--platform-logo <name>` (the file name without
`.png`; `3ds-forwarder media` lists them).

The image is drawn **on top of the finished banner** (hero + game logo, or a
ready-made banner), so use it for a console logo, a border or a badge. A file
must be:

- a **PNG** of exactly **256x128** pixels;
- designed with **transparency**: only its opaque pixels hide the banner.

Files that break these rules are still listed, greyed out, with the reason as
a tooltip.
