"""Pure lighting-effect maths: one frame from settings and a clock.

The daemon generates every effect itself and sends it frame by frame, so
frame rate is battery: each frame is a radio round trip to the headset.
"""

from __future__ import annotations

import colorsys
import math
from typing import Any, Final

from .protocol import parse_color


Color = tuple[int, int, int]

ANIMATED_MODES: Final = frozenset({"pulse", "rainbow", "cycle"})
BATTERY_SAVERS: Final = frozenset({"none", "dim", "off"})
SPEED_MIN: Final = 1
SPEED_MAX: Final = 5
DEFAULT_SPEED: Final = 3

# Speed 3 keeps the tempo of earlier releases.
_SPEED_FACTORS: Final = {1: 0.4, 2: 0.65, 3: 1.0, 4: 1.6, 5: 2.5}
_PULSE_PERIOD: Final = 2.0
_RAINBOW_PERIOD: Final = 6.0
_CYCLE_PERIOD: Final = 9.0
# Share of the configured brightness kept by the "dim" battery saver.
DIM_FACTOR: Final = 0.3
BLACK: Final[Color] = (0, 0, 0)


def speed_factor(speed: int) -> float:
    return _SPEED_FACTORS[max(SPEED_MIN, min(SPEED_MAX, int(speed)))]


def frame_interval(speed: int) -> float:
    """Seconds between animation frames.

    Ten frames a second are smooth for these slow fades and cost well under
    half the radio traffic of the former 25. Only the fast settings, where
    steps would become visible, get more.
    """

    return {4: 0.07, 5: 0.05}.get(int(speed), 0.1)


def _hsv(phase: float) -> Color:
    red, green, blue = colorsys.hsv_to_rgb(phase % 1.0, 1.0, 1.0)
    return (round(red * 255), round(green * 255), round(blue * 255))


def _blend(first: Color, second: Color, amount: float) -> Color:
    return tuple(  # type: ignore[return-value]
        round(a + (b - a) * amount) for a, b in zip(first, second)
    )


def render_frame(
    settings: dict[str, Any],
    now: float,
    *,
    muted: bool = False,
    battery_low: bool = False,
) -> tuple[Color, Color, Color, int]:
    """Return (logo, indicator, microphone, brightness) for this instant."""

    mode = settings["mode"]
    brightness = int(settings["brightness"])
    logo = parse_color(settings["logo"])
    indicator = parse_color(settings["indicator"])
    microphone = parse_color(settings["microphone"])
    factor = speed_factor(settings.get("speed", DEFAULT_SPEED))
    saver = settings.get("battery_saver", "none") if battery_low else "none"

    if mode == "off" or saver == "off":
        # The mute indicator is a status light, but "off" means dark.
        return BLACK, BLACK, BLACK, 100

    if mode == "pulse":
        wave = (math.sin(now * math.tau * factor / _PULSE_PERIOD) + 1.0) / 2.0
        brightness = round(brightness * (0.15 + 0.85 * wave))
    elif mode == "rainbow":
        phase = now * factor / _RAINBOW_PERIOD
        logo = _hsv(phase)
        indicator = _hsv(phase + 0.5)
    elif mode == "cycle":
        # All zones travel together through the three configured colours.
        stops = (logo, indicator, microphone)
        position = (now * factor / _CYCLE_PERIOD * 3.0) % 3.0
        index = int(position)
        # Smoothstep: linger on each colour, glide between them.
        amount = position - index
        amount = amount * amount * (3.0 - 2.0 * amount)
        logo = indicator = microphone = _blend(
            stops[index], stops[(index + 1) % 3], amount
        )

    if muted and settings.get("mute_indicator", True):
        microphone = parse_color(settings.get("mute_color", "#ff0000"))

    if saver == "dim":
        brightness = round(brightness * DIM_FACTOR)
    return logo, indicator, microphone, brightness
