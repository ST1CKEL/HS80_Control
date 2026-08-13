from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from hs80_control.config import ConfigStore
from hs80_control.spatial import SPATIAL_NODE_NAME, SpatialError, SpatialManager, generate_pipewire_config


PHYSICAL_SINK = "alsa_output.usb-Corsair_HS80.analog-stereo"


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def node_dump(*nodes: tuple[int, str]) -> str:
    return json.dumps(
        [
            {
                "id": node_id,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": name,
                        "alsa.components": (
                            "USB1b1c:0a6b"
                            if name.startswith("alsa_output.usb-Corsair_HS80")
                            else ""
                        ),
                    }
                },
            }
            for node_id, name in nodes
        ]
    )


class SpatialTests(unittest.TestCase):
    def test_generated_graph_has_eight_inputs_and_pinned_sink(self) -> None:
        config = generate_pipewire_config(
            Path('/home/user/HRTF "reference".sofa'),
            "alsa_output.usb-Corsair_HS80.analog-stereo",
        )
        self.assertIn('node.name = "hs80_spatial"', config)
        self.assertIn("audio.channels = 8", config)
        self.assertIn("[ FL FR FC LFE RL RR SL SR ]", config)
        self.assertIn(
            'target.object = "alsa_output.usb-Corsair_HS80.analog-stereo"', config
        )
        self.assertEqual(8, config.count("type = sofa"))
        self.assertIn('filename = "/home/user/HRTF \\"reference\\".sofa"', config)
        playback = config.split("playback.props", 1)[1]
        capture = config.split("capture.props", 1)[1].split("playback.props", 1)[0]
        self.assertIn("node.linger = true", playback)
        self.assertNotIn("node.linger", capture)

    def test_configure_imports_sofa_into_private_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selected.sofa"
            source.write_bytes(b"SOFA")
            config = ConfigStore(root / "config" / "config.json")
            manager = SpatialManager(config)

            with (
                patch.object(manager, "_service_is_active", return_value=False),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
            ):
                result = manager.configure(source)

            imported = root / "config" / "hrtf.sofa"
            self.assertEqual(root / "config" / "pipewire.conf", result)
            self.assertEqual(b"SOFA", imported.read_bytes())
            self.assertEqual(str(imported), config.snapshot()["spatial"]["sofa_file"])
            self.assertIn(str(imported), result.read_text(encoding="utf-8"))

    def test_configure_rolls_back_files_and_settings_when_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.sofa"
            second = root / "second.sofa"
            first.write_bytes(b"FIRST")
            second.write_bytes(b"SECOND")
            config = ConfigStore(root / "config" / "config.json")
            manager = SpatialManager(config)

            with (
                patch.object(manager, "_service_is_active", return_value=False),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
            ):
                manager.configure(first)

            old_settings = config.snapshot()
            old_graph = manager.config_path.read_bytes()
            with (
                patch.object(manager, "_service_is_active", return_value=True),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
                patch.object(
                    manager,
                    "_enable_locked",
                    side_effect=[SpatialError("restart failed"), True],
                ),
            ):
                with self.assertRaisesRegex(SpatialError, "restart failed"):
                    manager.configure(second)

            self.assertEqual(b"FIRST", manager.sofa_path.read_bytes())
            self.assertEqual(old_graph, manager.config_path.read_bytes())
            self.assertEqual(old_settings, config.snapshot())

    def test_find_sink_rejects_ambiguous_hs80_outputs(self) -> None:
        dump = node_dump(
            (66, "alsa_output.usb-Corsair_HS80.stereo"),
            (67, "alsa_output.usb-Corsair_HS80.pro-output"),
        )
        with patch.object(SpatialManager, "_run_checked", return_value=completed(dump)):
            with self.assertRaisesRegex(SpatialError, "multiple physical HS80"):
                SpatialManager.find_hs80_sink()

    def test_configure_restarts_active_service_even_before_sink_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selected.sofa"
            source.write_bytes(b"SOFA")
            manager = SpatialManager(
                ConfigStore(root / "config" / "config.json")
            )
            with (
                patch.object(manager, "_service_is_active", return_value=True),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
                patch.object(manager, "_enable_locked", return_value=True) as enable,
            ):
                manager.configure(source)

            enable.assert_called_once_with()

    def test_enable_captures_default_and_disable_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sofa = root / "hrtf.sofa"
            sofa.write_bytes(b"SOFA")
            config = ConfigStore(root / "config.json")
            config.update_spatial(sofa_file=str(sofa))
            manager = SpatialManager(config, root / "pipewire.conf")
            defaults = [PHYSICAL_SINK, SPATIAL_NODE_NAME, SPATIAL_NODE_NAME, PHYSICAL_SINK]
            systemctl_calls: list[tuple[str, ...]] = []

            def systemctl(*arguments: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
                del timeout
                systemctl_calls.append(arguments)
                return completed()

            def default_name(_timeout: float = 3.0) -> str:
                return defaults.pop(0)

            with (
                patch.object(manager, "plugin_available", return_value=True),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
                patch.object(
                    manager,
                    "_service_state",
                    side_effect=[("loaded", "inactive"), ("loaded", "active")],
                ),
                patch.object(manager, "_systemctl", side_effect=systemctl),
                patch.object(SpatialManager, "_default_sink_name", side_effect=default_name),
                patch.object(
                    SpatialManager,
                    "_pipewire_nodes",
                    return_value={PHYSICAL_SINK: "66", SPATIAL_NODE_NAME: "77"},
                ),
                patch.object(manager, "_wait_for_sink", return_value="77"),
                patch.object(SpatialManager, "_set_default"),
            ):
                self.assertTrue(manager.set_enabled(True))
                self.assertTrue(config.snapshot()["spatial"]["enabled"])
                self.assertEqual(PHYSICAL_SINK, config.snapshot()["spatial"]["previous_default"])
                self.assertTrue(manager.set_enabled(False))

            settings = config.snapshot()["spatial"]
            self.assertFalse(settings["enabled"])
            self.assertEqual("", settings["previous_default"])
            self.assertIn(("enable", "--now", "hs80-spatial.service"), systemctl_calls)
            self.assertIn(("disable", "--now", "hs80-spatial.service"), systemctl_calls)

    def test_enable_failure_stops_service_and_preserves_recovery_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sofa = root / "hrtf.sofa"
            sofa.write_bytes(b"SOFA")
            config = ConfigStore(root / "config.json")
            config.update_spatial(sofa_file=str(sofa))
            manager = SpatialManager(config, root / "pipewire.conf")

            with (
                patch.object(manager, "plugin_available", return_value=True),
                patch.object(manager, "find_hs80_sink", return_value=PHYSICAL_SINK),
                patch.object(manager, "_service_state", return_value=("loaded", "inactive")),
                patch.object(manager, "_default_sink_name", return_value=PHYSICAL_SINK),
                patch.object(manager, "_systemctl", return_value=completed()),
                patch.object(manager, "_wait_for_sink", side_effect=SpatialError("not ready")),
                patch.object(manager, "_restore_previous", side_effect=SpatialError("missing")),
                patch.object(manager, "_stop_service") as stop_service,
            ):
                with self.assertRaisesRegex(SpatialError, "not ready"):
                    manager.set_enabled(True)

            settings = config.snapshot()["spatial"]
            self.assertFalse(settings["enabled"])
            self.assertEqual(PHYSICAL_SINK, settings["previous_default"])
            stop_service.assert_called_once()

    def test_checked_runner_uses_requested_timeout(self) -> None:
        with patch("hs80_control.spatial.subprocess.run", return_value=completed()) as run:
            SpatialManager._run_checked(["test-command"], timeout=0.25)
        self.assertEqual(0.25, run.call_args.kwargs["timeout"])

    def test_enabled_requires_service_and_ready_sink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = SpatialManager(
                ConfigStore(Path(directory) / "config.json"),
                Path(directory) / "pipewire.conf",
            )
            with (
                patch.object(manager, "_service_state", return_value=("loaded", "active")),
                patch.object(manager, "_pipewire_nodes", return_value={PHYSICAL_SINK: "66"}),
            ):
                self.assertFalse(manager.is_enabled())

            with (
                patch.object(manager, "_service_state", return_value=("loaded", "active")),
                patch.object(manager, "_pipewire_nodes", return_value={SPATIAL_NODE_NAME: "77"}),
            ):
                self.assertTrue(manager.is_enabled())

    def test_generated_graph_is_valid_spa_json(self) -> None:
        config = generate_pipewire_config(Path("/tmp/reference.sofa"), PHYSICAL_SINK)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipewire.conf"
            path.write_text(config, encoding="utf-8")
            try:
                result = subprocess.run(
                    ["spa-json-dump", str(path)],
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=3,
                )
            except FileNotFoundError:
                self.skipTest("spa-json-dump is not installed")
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
