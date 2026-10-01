"""compositor.py — Compose a 3DS banner image from a SteamGridDB hero + logo.

The banner slot in the SMDH is a single flat image (see
``tools/media_prep.py``: it gets stretched to 256x128 right before
``bannertool`` runs, whatever its source). This module builds that single
image out of two optional SteamGridDB assets:

* the **hero** becomes the background, cover-cropped to fill the banner
  frame exactly (no letterboxing);
* the **logo** is pasted *on top of* the hero (i.e. the hero sits behind /
  below the logo in stacking order), scaled down to leave a margin, using
  its alpha channel so only the logo's opaque pixels show.

Either input may be missing (e.g. only a logo was picked, or neither was),
in which case a plain placeholder background is used so there is always a
valid image to preview and to hand to ``build_forwarder``.

A *platform frame* (see ``tools/media_catalog.py``) is drawn over the finished
banner by the build itself (``tools/media_prep.prepare_banner_image``). The
``frame_*`` helpers here repeat that exact operation -- stretch to 256x128,
then "source over" -- only so the preview shows what the build will produce.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

BANNER_WIDTH = 256
BANNER_HEIGHT = 128

# Matches tools/generate_placeholder_assets.PLACEHOLDER_COLOR, so a banner
# with no hero picked still looks consistent with the rest of the project.
PLACEHOLDER_BACKGROUND = (0x2E, 0x3A, 0x59)

# Logo is scaled to fit within this fraction of the banner, leaving a
# margin so it doesn't touch the edges.
LOGO_MAX_WIDTH_RATIO = 0.82
LOGO_MAX_HEIGHT_RATIO = 0.70


def _cover_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    """Resize+crop ``image`` to exactly ``width``x``height``, filling the frame."""
    src_ratio = image.width / image.height
    dst_ratio = width / height

    if src_ratio > dst_ratio:
        # Source is relatively wider than the target: match height, crop width.
        scale_height = height
        scale_width = round(height * src_ratio)
    else:
        # Source is relatively taller than the target: match width, crop height.
        scale_width = width
        scale_height = round(width / src_ratio)

    resized = image.resize((max(scale_width, 1), max(scale_height, 1)), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _fit_logo(logo: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """Scale ``logo`` down (never up) to fit within ``max_width``x``max_height``."""
    scale = min(max_width / logo.width, max_height / logo.height, 1.0)
    new_size = (max(round(logo.width * scale), 1), max(round(logo.height * scale), 1))
    return logo.resize(new_size, Image.Resampling.LANCZOS)


def compose_banner(
    hero_bytes: bytes | None,
    logo_bytes: bytes | None,
    width: int = BANNER_WIDTH,
    height: int = BANNER_HEIGHT,
) -> Image.Image:
    """Build the composite banner image (hero background + logo overlay)."""
    if hero_bytes:
        hero = Image.open(BytesIO(hero_bytes)).convert("RGB")
        background = _cover_crop(hero, width, height)
    else:
        background = Image.new("RGB", (width, height), PLACEHOLDER_BACKGROUND)

    canvas = background.convert("RGBA")

    if logo_bytes:
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        max_logo_width = round(width * LOGO_MAX_WIDTH_RATIO)
        max_logo_height = round(height * LOGO_MAX_HEIGHT_RATIO)
        logo = _fit_logo(logo, max_logo_width, max_logo_height)
        offset = ((width - logo.width) // 2, (height - logo.height) // 2)
        canvas.alpha_composite(logo, dest=offset)

    return canvas.convert("RGB")


def compose_banner_png_bytes(hero_bytes: bytes | None, logo_bytes: bytes | None) -> bytes:
    """Same as ``compose_banner``, encoded as in-memory PNG bytes (for previews)."""
    image = compose_banner(hero_bytes, logo_bytes)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def compose_banner_to_file(hero_bytes: bytes | None, logo_bytes: bytes | None, dest: Path) -> Path:
    """Same as ``compose_banner``, written to ``dest`` as a PNG. Returns ``dest``."""
    image = compose_banner(hero_bytes, logo_bytes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG")
    return dest


def frame_png_bytes(banner_png: bytes, frame_png: bytes) -> bytes:
    """Draw ``frame_png`` over ``banner_png`` as the build does, as PNG bytes (preview only).

    The banner is first stretched to 256x128 (whatever its size, like the
    build does), then the frame is alpha-composited on top of it.
    """
    banner = Image.open(BytesIO(banner_png)).convert("RGBA")
    banner = banner.resize((BANNER_WIDTH, BANNER_HEIGHT), Image.Resampling.BICUBIC)
    banner.alpha_composite(Image.open(BytesIO(frame_png)).convert("RGBA"))
    buffer = BytesIO()
    banner.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()
