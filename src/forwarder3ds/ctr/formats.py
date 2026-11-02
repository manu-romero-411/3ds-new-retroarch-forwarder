"""Fixed sizes and audio parameters of the 3DS HOME menu assets.

The SMDH icon and the banner image have a fixed pixel size set by the 3DS
formats themselves. The jingle parameters (16-bit PCM, 44.1 kHz, stereo,
3 seconds at most) are the ones used by published ``bannertool`` workflows
and by RetroArch's own 3DS packaging (``pkg/ctr/assets/silent.wav``).
"""

ICON_WIDTH = 48
ICON_HEIGHT = 48
BANNER_WIDTH = 256
BANNER_HEIGHT = 128

AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS = 2
AUDIO_SAMPLE_WIDTH = 2  # bytes: 16-bit PCM
MAX_AUDIO_SECONDS = 3.0

#: Plain background used when there is no icon or banner (dark blue).
PLACEHOLDER_COLOR = (0x2E, 0x3A, 0x59)
