from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest

from hs80_control import i18n
from hs80_control.config import ConfigStore, validate_config
from hs80_control.notifications import LowBatteryMonitor
from hs80_control.protocol import ProtocolError
from hs80_control.state import DeviceState, StateStore
from hs80_control.voice import (
    CLIP_DIRECTORY,
    CLIPS,
    AnnouncementMonitor,
    ClipPlayer,
    VoiceAnnouncer,
)


ONLINE = DeviceState(
    headset_connected=True,
    connection_mode="wireless",
    battery_percent=60,
    charging=0,
    microphone_muted=0,
)


class AnnouncementMonitorTests(unittest.TestCase):
    def _monitor(self, first: DeviceState = ONLINE) -> AnnouncementMonitor:
        monitor = AnnouncementMonitor()
        self.assertEqual([], monitor.observe(first))
        return monitor

    def test_microphone_arm_is_announced_both_ways(self) -> None:
        monitor = self._monitor()
        muted = replace(ONLINE, microphone_muted=1)
        self.assertEqual(["microphone_muted"], monitor.observe(muted))
        self.assertEqual([], monitor.observe(muted))
        self.assertEqual(["microphone_active"], monitor.observe(ONLINE))

    def test_cable_is_announced_both_ways(self) -> None:
        monitor = self._monitor()
        charging = replace(ONLINE, charging=1)
        self.assertEqual(["charging"], monitor.observe(charging))
        self.assertEqual(["unplugged"], monitor.observe(ONLINE))

    def test_a_full_battery_is_announced_once(self) -> None:
        monitor = self._monitor(replace(ONLINE, charging=1, battery_percent=99))
        full = replace(ONLINE, charging=1, battery_percent=100)
        self.assertEqual(["battery_full"], monitor.observe(full))
        self.assertEqual([], monitor.observe(full))

    def test_what_the_headset_reports_while_connecting_is_not_news(self) -> None:
        monitor = AnnouncementMonitor()
        offline = DeviceState()
        self.assertEqual([], monitor.observe(offline))
        # First readings after switching on: unknown -> known.
        self.assertEqual([], monitor.observe(replace(ONLINE, microphone_muted=1)))
        # Gone and back with a different arm position and on the charger.
        self.assertEqual(
            [], monitor.observe(replace(ONLINE, headset_connected=False))
        )
        self.assertEqual([], monitor.observe(replace(ONLINE, charging=1)))
        # Moving from the receiver to the cable is a new session, too.
        self.assertEqual(
            [], monitor.observe(replace(ONLINE, connection_mode="usb", charging=0))
        )

    def test_low_battery_is_spoken_even_right_after_connecting(self) -> None:
        monitor = AnnouncementMonitor(LowBatteryMonitor(20, 10))
        self.assertEqual([], monitor.observe(DeviceState()))
        self.assertEqual(
            ["battery_low"], monitor.observe(replace(ONLINE, battery_percent=18))
        )
        self.assertEqual(
            ["battery_critical"], monitor.observe(replace(ONLINE, battery_percent=9))
        )
        # Pulling the cable at a low level: the warning comes last and wins.
        monitor = AnnouncementMonitor(LowBatteryMonitor(20, 10))
        monitor.observe(replace(ONLINE, battery_percent=15, charging=1))
        self.assertEqual(
            ["unplugged", "battery_low"],
            monitor.observe(replace(ONLINE, battery_percent=15)),
        )

    def test_switches_silence_their_group(self) -> None:
        changed = replace(ONLINE, microphone_muted=1, charging=1)
        for switch in ("voice_enabled", "voice_microphone", "voice_charging"):
            monitor = self._monitor()
            clips = monitor.observe(replace(changed, **{switch: False}))
            if switch != "voice_charging":
                self.assertNotIn("microphone_muted", clips)
            if switch != "voice_microphone":
                self.assertNotIn("charging", clips)
        monitor = self._monitor()
        low = replace(ONLINE, battery_percent=5, voice_battery=False)
        self.assertEqual([], monitor.observe(low))


class FakeProcess:
    def __init__(self, command: list[str], environment: dict[str, str]) -> None:
        self.command = command
        self.environment = environment
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.terminated = True


class ClipPlayerTests(unittest.TestCase):
    language = "en"

    def _player(self, sink: str | None = "hs80-sink"):
        started: list[FakeProcess] = []
        played = threading.Semaphore(0)

        def popen(command: list[str], **options: object) -> FakeProcess:
            process = FakeProcess(command, options["env"])  # type: ignore[arg-type]
            started.append(process)
            played.release()
            return process

        modes: list[str] = []

        def finder(mode: str) -> str | None:
            modes.append(mode)
            if sink is None:
                played.release()
            return sink

        player = ClipPlayer(
            sink_finder=finder,
            popen=popen,  # type: ignore[arg-type]
            language=lambda: self.language,
        )
        self.addCleanup(player.close)
        return player, started, played, modes

    def test_every_clip_ships_in_every_interface_language(self) -> None:
        self.assertEqual(set(i18n.LANGUAGES), set(CLIPS))
        for language, texts in CLIPS.items():
            self.assertEqual(set(CLIPS["en"]), set(texts), language)
            for name in texts:
                path = CLIP_DIRECTORY / language / f"{name}.wav"
                with open(path, "rb") as handle:
                    self.assertEqual(b"RIFF", handle.read(4), str(path))

    def test_clips_follow_the_app_language(self) -> None:
        player, started, played, _modes = self._player()
        self.language = "de"
        player.play("charging", 70)
        self.assertTrue(played.acquire(timeout=2))
        self.assertEqual(
            str(CLIP_DIRECTORY / "de" / "charging.wav"), started[0].command[-1]
        )

    def test_clip_goes_to_the_headset_sink_at_the_set_volume(self) -> None:
        player, started, played, modes = self._player()
        player.play("charging", 65, "usb")
        self.assertTrue(played.acquire(timeout=2))
        command = started[0].command
        self.assertEqual("pw-play", command[0])
        self.assertEqual("hs80-sink", command[command.index("--target") + 1])
        self.assertEqual("0.65", command[command.index("--volume") + 1])
        self.assertEqual(str(CLIP_DIRECTORY / "en" / "charging.wav"), command[-1])
        self.assertEqual(["usb"], modes)
        # A German locale would read "0.65" as zero.
        self.assertEqual("C", started[0].environment["LC_ALL"])

    def test_a_newer_clip_cuts_the_running_one_short(self) -> None:
        player, started, played, _modes = self._player()
        player.play("microphone_muted", 70)
        self.assertTrue(played.acquire(timeout=2))
        player.play("microphone_active", 70)
        self.assertTrue(played.acquire(timeout=2))
        self.assertTrue(started[0].terminated)
        self.assertFalse(started[1].terminated)

    def test_without_a_headset_sink_nothing_is_played(self) -> None:
        player, started, played, _modes = self._player(sink=None)
        player.play("charging", 70)
        self.assertTrue(played.acquire(timeout=2))
        player.close()
        self.assertEqual([], started)


class RecordingPlayer:
    def __init__(self) -> None:
        self.played: list[tuple[str, int, str]] = []
        self.closed = False

    def play(self, clip: str, volume: int, connection_mode: str = "wireless") -> None:
        self.played.append((clip, volume, connection_mode))

    def close(self) -> None:
        self.closed = True


class VoiceAnnouncerTests(unittest.TestCase):
    def test_state_changes_reach_the_player(self) -> None:
        state = StateStore()
        player = RecordingPlayer()
        announcer = VoiceAnnouncer(state, player=player)  # type: ignore[arg-type]
        self.assertFalse(announcer.play_sample())

        state.update(
            headset_connected=True,
            connection_mode="wireless",
            battery_percent=60,
            charging=1,
            microphone_muted=1,
            voice_volume=40,
        )
        self.assertEqual([], player.played)
        state.update(microphone_muted=0)
        state.update(charging=0)
        # Unrelated state must not replay anything.
        state.update(last_error="x", rgb_brightness=10)
        self.assertEqual(
            [("microphone_active", 40, "wireless"), ("unplugged", 40, "wireless")],
            player.played,
        )
        self.assertTrue(announcer.play_sample())
        self.assertEqual(("sample", 40, "wireless"), player.played[-1])

        announcer.close()
        state.update(microphone_muted=1)
        self.assertEqual(3, len(player.played))
        self.assertTrue(player.closed)


class VoiceSettingsTests(unittest.TestCase):
    def test_defaults_and_partial_updates_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            self.assertEqual(
                {
                    "enabled": True,
                    "volume": 70,
                    "microphone": True,
                    "charging": True,
                    "battery": True,
                },
                store.snapshot()["voice"],
            )
            store.update_voice(volume=35, charging=False, enabled=None)
            voice = ConfigStore(path).snapshot()["voice"]
            self.assertEqual((True, 35, False), (voice["enabled"], voice["volume"], voice["charging"]))
            with self.assertRaises(ProtocolError):
                store.update_voice(volume=101)

    def test_invalid_voice_settings_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "voice enabled"):
            validate_config({"voice": {"enabled": "yes"}})
        with self.assertRaisesRegex(ProtocolError, "voice volume"):
            validate_config({"voice": {"volume": True}})


if __name__ == "__main__":
    unittest.main()
