# Platform logos (banner frames)

Drop `.png` files here. They show up in the **Platform logo** dropdown of the
UI and can be used from the CLI with `--platform-logo <name>` (the file name
without `.png`; `--list-platform-logos` shows what is available).

The image is drawn **on top of the finished banner** (hero + game logo, or
whatever banner you provided), so use it for a console logo, a border or a
badge. A file must be:

- a **PNG** of exactly **256x128** pixels;
- designed with **transparency**: only its opaque pixels hide the banner.

Files that break these rules are still listed, greyed out, with the reason as
a tooltip.
