from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from hs80_control.config import ConfigStore
from hs80_control.protocol import ProtocolError


class ConfigTests(unittest.TestCase):
    def test_defaults_and_atomic_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            self.assertFalse(store.snapshot()["rgb"]["apply_on_connect"])
            store.update_rgb("off", 0, "#000000", "#000000", "#000000")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("off", loaded["rgb"]["mode"])
            self.assertTrue(loaded["rgb"]["apply_on_connect"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)

    def test_invalid_update_does_not_replace_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            with self.assertRaises(ProtocolError):
                store.update_rgb("fire", 100, "#ffffff", "#ffffff", "#ffffff")
            self.assertEqual("static", store.snapshot()["rgb"]["mode"])

    def test_partial_rgb_updates_merge_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json")

            store.patch_rgb(logo="#112233")
            store.patch_rgb(indicator="#445566")

            profile = store.snapshot()["rgb"]
            self.assertEqual("#112233", profile["logo"])
            self.assertEqual("#445566", profile["indicator"])
            self.assertEqual("#00ffff", profile["microphone"])

    def test_unknown_keys_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"unknown": true, "rgb": {"extra": 1}}', encoding="utf-8")
            store = ConfigStore(path)
            snapshot = store.snapshot()
            self.assertNotIn("unknown", snapshot)
            self.assertNotIn("extra", snapshot["rgb"])

    def test_previous_default_is_persisted_and_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.update_spatial(previous_default="alsa_output.test")
            self.assertEqual("alsa_output.test", store.snapshot()["spatial"]["previous_default"])
            store.update_spatial(previous_default="")
            self.assertEqual("", json.loads(path.read_text(encoding="utf-8"))["spatial"]["previous_default"])

    def test_spatial_default_sink_preference_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            self.assertTrue(store.snapshot()["spatial"]["make_default"])

            store.update_spatial(make_default=False)

            self.assertFalse(store.snapshot()["spatial"]["make_default"])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["spatial"]["make_default"])


if __name__ == "__main__":
    unittest.main()
