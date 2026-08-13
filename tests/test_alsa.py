from __future__ import annotations

import unittest
from unittest.mock import patch

from hs80_control.alsa import AlsaMixer, MixerError, parse_amixer_value


class AlsaTests(unittest.TestCase):
    def test_parse_sidetone(self) -> None:
        output = """Simple mixer control 'Sidetone',0
  Capabilities: pvolume pvolume-joined pswitch pswitch-joined
  Playback channels: Mono
  Limits: Playback 0 - 23
  Mono: Playback 3 [13%] [-36.00dB] [off]
"""
        value = parse_amixer_value(output)
        self.assertEqual(3, value.raw)
        self.assertEqual(13, value.percent)
        self.assertEqual(-36.0, value.db)
        self.assertFalse(value.enabled)

    def test_parse_microphone(self) -> None:
        output = "  Mono: Capture 36 [100%] [0.00dB] [on]\n"
        value = parse_amixer_value(output)
        self.assertTrue(value.enabled)
        self.assertEqual(0.0, value.db)

    def test_reject_unknown_output(self) -> None:
        with self.assertRaises(MixerError):
            parse_amixer_value("no mixer data")

    def test_execution_oserror_is_reported_as_mixer_error(self) -> None:
        mixer = AlsaMixer()
        with (
            patch.object(mixer, "find_card", return_value=0),
            patch(
                "hs80_control.alsa.subprocess.run",
                side_effect=PermissionError("sandbox denied execution"),
            ),
        ):
            with self.assertRaisesRegex(MixerError, "sandbox denied execution"):
                mixer.get_control("Mic")


if __name__ == "__main__":
    unittest.main()
