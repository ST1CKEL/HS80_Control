from __future__ import annotations

import unittest

from hs80_control.effects import (
    BLACK,
    frame_interval,
    render_frame,
    speed_factor,
)


SETTINGS = {
    "mode": "static",
    "brightness": 80,
    "logo": "#ff0000",
    "indicator": "#00ff00",
    "microphone": "#0000ff",
    "mute_indicator": True,
    "mute_color": "#ff8800",
    "speed": 3,
    "battery_saver": "none",
}


def frame(now: float = 0.0, muted: bool = False, battery_low: bool = False, **changes):
    return render_frame(
        {**SETTINGS, **changes}, now, muted=muted, battery_low=battery_low
    )


class EffectTests(unittest.TestCase):
    def test_static_passes_colours_through(self) -> None:
        self.assertEqual(
            ((255, 0, 0), (0, 255, 0), (0, 0, 255), 80), frame()
        )

    def test_off_is_dark_even_when_muted(self) -> None:
        self.assertEqual((BLACK, BLACK, BLACK, 100), frame(mode="off", muted=True))

    def test_mute_indicator_uses_the_chosen_colour_and_can_be_disabled(self) -> None:
        self.assertEqual((255, 136, 0), frame(muted=True)[2])
        self.assertEqual((0, 0, 255), frame(muted=True, mute_indicator=False)[2])
        # The indicator stays readable inside animated modes too.
        self.assertEqual((255, 136, 0), frame(1.7, muted=True, mode="cycle")[2])

    def test_default_speed_keeps_the_tempo_of_earlier_releases(self) -> None:
        self.assertEqual(1.0, speed_factor(3))
        # Pulse: sin(now * pi), i.e. a two second period, peak at 0.5 s.
        self.assertEqual(80, frame(0.5, mode="pulse")[3])
        self.assertEqual(round(80 * 0.15), frame(1.5, mode="pulse")[3])
        # Rainbow: six seconds per turn, zones half a turn apart.
        logo, indicator, _mic, _brightness = frame(0.0, mode="rainbow")
        self.assertEqual((255, 0, 0), logo)
        self.assertEqual((0, 255, 255), indicator)
        self.assertEqual(frame(0.0, mode="rainbow"), frame(6.0, mode="rainbow"))

    def test_speed_scales_the_period(self) -> None:
        self.assertLess(speed_factor(1), speed_factor(3))
        self.assertGreater(speed_factor(5), speed_factor(3))
        slow = frame(0.5 / speed_factor(1), mode="pulse", speed=1)[3]
        fast = frame(0.5 / speed_factor(5), mode="pulse", speed=5)[3]
        self.assertEqual(80, slow)
        self.assertEqual(80, fast)

    def test_cycle_visits_the_three_colours_on_all_zones(self) -> None:
        for now, colour in ((0.0, (255, 0, 0)), (3.0, (0, 255, 0)), (6.0, (0, 0, 255))):
            logo, indicator, microphone, brightness = frame(now, mode="cycle")
            self.assertEqual((colour, colour, colour, 80), (logo, indicator, microphone, brightness))
        halfway = frame(1.5, mode="cycle")[0]
        self.assertEqual((128, 128, 0), halfway)
        self.assertEqual(frame(0.0, mode="cycle"), frame(9.0, mode="cycle"))

    def test_battery_saver_only_acts_on_a_low_battery(self) -> None:
        self.assertEqual(80, frame(battery_saver="dim")[3])
        self.assertEqual(24, frame(battery_saver="dim", battery_low=True)[3])
        self.assertEqual(
            (BLACK, BLACK, BLACK, 100),
            frame(battery_saver="off", battery_low=True, mode="rainbow"),
        )
        self.assertEqual(80, frame(battery_saver="none", battery_low=True)[3])

    def test_frame_rate_is_ten_per_second_unless_fast(self) -> None:
        self.assertEqual([0.1, 0.1, 0.1, 0.07, 0.05], [frame_interval(s) for s in range(1, 6)])


if __name__ == "__main__":
    unittest.main()
