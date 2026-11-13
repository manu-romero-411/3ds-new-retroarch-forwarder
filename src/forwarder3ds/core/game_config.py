"""Per-game RetroArch settings: screen scaling and control remaps.

Both end up in the CIA's RomFS and seed the game's folder on the SD card
the first time it boots (see ``retroarch/patches/0001``):

* :class:`ScreenSettings` becomes lines of the seed ``retroarch.cfg``;
* :func:`remap_text` is ``game.rmp``, a RetroArch *remap*: it changes the
  buttons the game sees, while the menu keeps the console's own layout. It
  also says what the Circle Pad drives (:data:`CIRCLE_PAD`): the D-Pad, or
  a PlayStation game's DualShock stick.

Edited later on the SD card, those files win: the CIA only seeds them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The 3DS top screen.
SCREEN_WIDTH = 400
SCREEN_HEIGHT = 240

# RetroArch v1.22.2 ``enum aspect_ratio`` (gfx/video_defines.h).
_ASPECT_SQUARE = 21
_ASPECT_CORE = 22
_ASPECT_CUSTOM = 23
_ASPECT_FULL = 24


# RetroArch's analog_dpad_mode: 0 off, 1 the left stick drives the D-Pad.
_ANALOG_DPAD_OFF, _ANALOG_DPAD_LEFT = 0, 1
# pcsx_rearmed's DualShock: RETRO_DEVICE_SUBCLASS(RETRO_DEVICE_ANALOG, 1).
_DEVICE_DUALSHOCK = (2 << 8) | 5

#: A remap entry of its own: what the Circle Pad drives in the game.
CIRCLE_PAD = "circle_pad"
#: ... the D-Pad (the default, never stored);
CIRCLE_PAD_DPAD = "dpad"
#: ... an analog stick, on consoles of :data:`ANALOG_DEVICES`.
CIRCLE_PAD_STICK = "stick"
#: Consoles whose games can take the Circle Pad as a stick, and the libretro
#: controller that gives them one (the PlayStation's DualShock).
ANALOG_DEVICES = {"psx": _DEVICE_DUALSHOCK}
#: Consoles without the alternate boot mode: some PAL PlayStation games are
#: taller than the 3DS screen, so they cannot be shown pixel perfect.
NO_ALT_MODE = frozenset({"psx"})


def supports_alt_mode(console: str) -> bool:
    """Whether games of ``console`` can have the alternate boot mode."""
    return console not in NO_ALT_MODE


class ScreenMode(str, Enum):
    """How the game's picture is scaled on the top screen."""

    #: Square pixels at an integer scale: exactly the console's pixels,
    #: never resampled (a 320x224 game stays 320x224, centred).
    PIXEL_PERFECT = "pixel_perfect"
    #: As large as it fits, keeping the core's aspect ratio.
    RECOMMENDED = "recommended"
    #: Stretched over the whole 400x240 screen.
    FULL = "full"
    #: A given size, centred.
    CUSTOM = "custom"


@dataclass
class ScreenSettings:
    """The ``Screen`` group of the injection options."""

    mode: ScreenMode = ScreenMode.RECOMMENDED
    width: int = SCREEN_WIDTH
    height: int = SCREEN_HEIGHT
    #: Bilinear filtering.
    #: Bilinear filtering (on by default; pixel perfect is unaffected).
    smooth: bool = True

    def config_lines(self) -> dict[str, str]:
        """The ``retroarch.cfg`` entries for these settings."""
        lines = {
            "video_smooth": _bool(self.smooth),
            "video_scale_integer": _bool(self.mode is ScreenMode.PIXEL_PERFECT),
        }
        if self.mode is ScreenMode.PIXEL_PERFECT:
            # The core's aspect (4:3 for most) would scale columns by a
            # fraction, leaving uneven pixels: square ones keep them whole.
            lines["aspect_ratio_index"] = str(_ASPECT_SQUARE)
        elif self.mode is ScreenMode.FULL:
            lines["aspect_ratio_index"] = str(_ASPECT_FULL)
        elif self.mode is ScreenMode.CUSTOM:
            width = max(1, min(self.width, SCREEN_WIDTH))
            height = max(1, min(self.height, SCREEN_HEIGHT))
            lines.update(
                {
                    "aspect_ratio_index": str(_ASPECT_CUSTOM),
                    "custom_viewport_width": str(width),
                    "custom_viewport_height": str(height),
                    "custom_viewport_x": str((SCREEN_WIDTH - width) // 2),
                    "custom_viewport_y": str((SCREEN_HEIGHT - height) // 2),
                }
            )
        else:
            lines["aspect_ratio_index"] = str(_ASPECT_CORE)
        return lines

    @classmethod
    def from_config(cls, config: dict[str, str]) -> ScreenSettings:
        """The settings :meth:`config_lines` wrote into ``config`` (a parsed ``retroarch.cfg``)."""
        smooth = config.get("video_smooth") == "true"
        if config.get("video_scale_integer") == "true":
            return cls(mode=ScreenMode.PIXEL_PERFECT, smooth=smooth)
        index = config.get("aspect_ratio_index", "")
        if index == str(_ASPECT_FULL):
            return cls(mode=ScreenMode.FULL, smooth=smooth)
        if index == str(_ASPECT_CUSTOM):
            return cls(
                mode=ScreenMode.CUSTOM,
                width=_int(_parse_int(config.get("custom_viewport_width")), SCREEN_WIDTH),
                height=_int(_parse_int(config.get("custom_viewport_height")), SCREEN_HEIGHT),
                smooth=smooth,
            )
        return cls(mode=ScreenMode.RECOMMENDED, smooth=smooth)

    def to_json(self) -> dict[str, object]:
        """A JSON-friendly copy."""
        return {
            "mode": self.mode.value,
            "width": self.width,
            "height": self.height,
            "smooth": self.smooth,
        }

    @classmethod
    def from_json(cls, data: object) -> ScreenSettings:
        """Read :meth:`to_json` output; bad or missing fields get the defaults."""
        if not isinstance(data, dict):
            return cls()
        try:
            mode = ScreenMode(data.get("mode", ScreenMode.RECOMMENDED.value))
        except ValueError:
            mode = ScreenMode.RECOMMENDED
        return cls(
            mode=mode,
            width=_int(data.get("width"), SCREEN_WIDTH),
            height=_int(data.get("height"), SCREEN_HEIGHT),
            smooth=bool(data.get("smooth", True)),
        )


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _parse_int(text: str | None) -> int | None:
    try:
        return int(text or "")
    except ValueError:
        return None


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


# ── Controls ─────────────────────────────────────────────────────────────

#: RetroPad buttons as RetroArch numbers them (``RETRO_DEVICE_ID_JOYPAD_*``)
#: and names them in remap files.
RETROPAD_BUTTONS: tuple[str, ...] = (
    "b", "y", "select", "start", "up", "down", "left", "right",
    "a", "x", "l", "r", "l2", "r2", "l3", "r3",
)  # fmt: skip

#: The 3DS buttons, by the RetroPad slot RetroArch's 3DS driver gives them.
CONSOLE_BUTTONS: dict[str, str] = {
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "l": "L",
    "r": "R",
    "l2": "ZL",
    "r2": "ZR",
    "start": "START",
    "select": "SELECT",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}

#: What a 3DS button does when it is mapped to nothing.
UNMAPPED = "none"


def normalize_remap(remap: dict[str, str]) -> dict[str, str]:
    """``remap`` without unknown buttons and without buttons left as they are."""
    result = {}
    for button, target in remap.items():
        if button == CIRCLE_PAD:
            if target == CIRCLE_PAD_STICK:
                result[button] = target
            continue
        if button not in CONSOLE_BUTTONS or button == target:
            continue
        if target == UNMAPPED or target in RETROPAD_BUTTONS:
            result[button] = target
    return result


def remap_text(remap: dict[str, str], console: str = "") -> str:
    """``game.rmp`` for ``remap`` (3DS button -> RetroPad button the game sees).

    Buttons not listed keep their default. The Circle Pad drives the D-Pad,
    unless the remap makes it ``console``'s analog stick (:data:`CIRCLE_PAD`).
    """
    remap = normalize_remap(remap)
    text = []
    for button in RETROPAD_BUTTONS:
        if button in remap:
            target = remap[button]
            value = -1 if target == UNMAPPED else RETROPAD_BUTTONS.index(target)
            text.append(f'input_player1_btn_{button} = "{value}"')
    if remap.get(CIRCLE_PAD) == CIRCLE_PAD_STICK:
        if console in ANALOG_DEVICES:
            text.append(f'input_libretro_device_p1 = "{ANALOG_DEVICES[console]}"')
        text.append(f'input_player1_analog_dpad_mode = "{_ANALOG_DPAD_OFF}"')
    else:
        text.append(f'input_player1_analog_dpad_mode = "{_ANALOG_DPAD_LEFT}"')
    return "\n".join(text) + "\n"


def parse_remap(entries: dict[str, str]) -> dict[str, str]:
    """The remap :func:`remap_text` wrote, from the parsed lines of a ``game.rmp``."""
    remap = {}
    for button in CONSOLE_BUTTONS:
        value = _parse_int(entries.get(f"input_player1_btn_{button}"))
        if value is None:
            continue
        if value < 0:
            remap[button] = UNMAPPED
        elif value < len(RETROPAD_BUTTONS):
            remap[button] = RETROPAD_BUTTONS[value]
    if _parse_int(entries.get("input_player1_analog_dpad_mode")) == _ANALOG_DPAD_OFF:
        remap[CIRCLE_PAD] = CIRCLE_PAD_STICK
    return normalize_remap(remap)


#: Default names of the RetroPad buttons.
RETROPAD_LABELS: dict[str, str] = {
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "l": "L",
    "r": "R",
    "l2": "L2",
    "r2": "R2",
    "l3": "L3",
    "r3": "R3",
    "start": "Start",
    "select": "Select",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}

_GENESIS = {"b": "B", "a": "C", "y": "A", "x": "Y", "l": "X", "r": "Z", "select": "Mode"}
_MASTER = {"b": "1", "a": "2", "start": "Pause"}
_PCE = {"a": "I", "b": "II", "select": "Select", "start": "Run"}
_ARCADE = {
    "b": "Button 1", "a": "Button 2", "y": "Button 3", "x": "Button 4",
    "l": "Button 5", "r": "Button 6", "select": "Coin", "start": "Start",
}  # fmt: skip
#: What the game's own controller calls each RetroPad button, by console
#: (as the console's default core lays them out). Only the buttons it has.
CONSOLE_LABELS: dict[str, dict[str, str]] = {
    "atari2600": {
        "b": "Fire", "select": "Select", "start": "Reset",
        "l": "Left difficulty", "r": "Right difficulty",
    },
    "atari7800": {"b": "Fire 1", "a": "Fire 2", "select": "Select", "start": "Pause"},
    "lynx": {"a": "A", "b": "B", "l": "Option 1", "r": "Option 2", "start": "Pause"},
    "pokemini": {"a": "A", "b": "B", "r": "C", "l": "Shake", "select": "Power"},
    "gb": {"a": "A", "b": "B", "start": "Start", "select": "Select"},
    "gbc": {"a": "A", "b": "B", "start": "Start", "select": "Select"},
    "gba": {"a": "A", "b": "B", "l": "L", "r": "R", "start": "Start", "select": "Select"},
    "nes": {"a": "A", "b": "B", "start": "Start", "select": "Select"},
    "fds": {"a": "A", "b": "B", "start": "Start", "select": "Select", "l": "Disk side"},
    "snes": {
        "a": "A", "b": "B", "x": "X", "y": "Y", "l": "L", "r": "R",
        "start": "Start", "select": "Select",
    },
    "megadrive": _GENESIS | {"start": "Start"},
    "segacd": _GENESIS | {"start": "Start"},
    "sega32x": _GENESIS | {"start": "Start"},
    "mastersystem": _MASTER,
    "sg1000": _MASTER,
    "gamegear": {"b": "1", "a": "2", "start": "Start"},
    "pcengine": _PCE,
    "pcenginecd": _PCE,
    "psx": {
        "b": "Cross", "a": "Circle", "y": "Square", "x": "Triangle",
        "l": "L1", "r": "R1", "l2": "L2", "r2": "R2", "l3": "L3", "r3": "R3",
        "start": "Start", "select": "Select",
    },
    "mame": _ARCADE,
    "fbneo": _ARCADE,
}  # fmt: skip
_DPAD = ("up", "down", "left", "right")


def target_labels(console: str) -> dict[str, str]:
    """RetroPad button -> the name the console's controller gives it."""
    own = CONSOLE_LABELS.get(console)
    if own is None:
        return dict(RETROPAD_LABELS)
    return {button: own.get(button, label) for button, label in RETROPAD_LABELS.items()}


def console_targets(console: str) -> list[str]:
    """The RetroPad buttons ``console``'s controller has (every one if unknown)."""
    own = CONSOLE_LABELS.get(console)
    if own is None:
        return list(RETROPAD_BUTTONS)
    return [button for button in RETROPAD_BUTTONS if button in own or button in _DPAD]
