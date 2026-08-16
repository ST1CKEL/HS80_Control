from __future__ import annotations

from pathlib import Path
import logging
import tempfile
import time
import unittest

from hs80_control.alsa import MixerError, MixerSnapshot, MixerValue
from hs80_control.config import ConfigStore
from hs80_control.controller import (
    NO_HEADSET_MESSAGE,
    ControllerError,
    DeviceController,
)
from hs80_control.discovery import HidNode
from hs80_control.protocol import (
    CMD_BATTERY,
    CMD_FIRMWARE,
    CMD_HARDWARE_MODE,
    CMD_MIC_STATUS,
    CMD_PRODUCT_ID,
    CMD_RGB_CLOSE,
    CMD_RGB_OPEN,
    CMD_RGB_WRITE,
    CMD_SUBDEVICE_BITFIELD,
    CMD_VENDOR_ID,
    RECEIVER_TARGET,
)
from hs80_control.transport import DeviceStatusError


class FakeMixer:
    value = MixerValue(0, 0, -42.0, False)
    microphone = MixerValue(36, 100, 0.0, True)

    def __init__(self) -> None:
        self.serial: str | None = None

    def bind_serial(self, serial: str) -> None:
        self.serial = serial

    def snapshot(self) -> MixerSnapshot:
        return MixerSnapshot(self.value, self.microphone)

    def set_sidetone(self, enabled: bool, db: float) -> MixerValue:
        self.value = MixerValue(1, 10, db, enabled)
        return self.value

    def set_microphone_gain(self, db: float) -> MixerValue:
        self.microphone = MixerValue(1, 10, db, self.microphone.enabled)
        return self.microphone

    def set_microphone_muted(self, muted: bool) -> MixerValue:
        self.microphone = MixerValue(1, 10, self.microphone.db, not muted)
        return self.microphone


class FakeSpatial:
    def __init__(self) -> None:
        self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled

    def configure(self, _path: str) -> Path:
        return Path("/tmp/pipewire.conf")

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = enabled
        return True


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bytes, bytes]] = []
        self.closed = False

    def transfer(
        self,
        target: int,
        command: bytes,
        payload: bytes = b"",
        timeout_ms: int = 1000,
    ) -> bytes:
        del timeout_ms
        self.calls.append((target, command, payload))
        response = bytearray(64)
        if target == RECEIVER_TARGET and command == CMD_FIRMWARE:
            response[4:8] = bytes((1, 2, 3, 0))
        elif command == CMD_FIRMWARE:
            response[4:7] = bytes((4, 5, 6))
        elif command == CMD_BATTERY:
            response[4:6] = (730).to_bytes(2, "little")
        elif command == CMD_MIC_STATUS:
            response[4] = 1
        return bytes(response)

    def read_resource(self, _resource: bytes, timeout_ms: int = 1000) -> bytes:
        del timeout_ms
        serial = b"PAIRED-HS80"
        report = bytearray(64)
        report[6] = 1
        report[7:15] = bytes((0x1C, 0x1B, 0, 0, 0x69, 0x0A, 1, len(serial)))
        report[15 : 15 + len(serial)] = serial
        return bytes(report)

    def poll_event(self, timeout_ms: int = 100) -> None:
        del timeout_ms
        return None

    def close(self) -> None:
        self.closed = True


class ControllerTests(unittest.TestCase):
    def test_initialization_and_safe_writes(self) -> None:
        node = HidNode(
            path=Path("/dev/hidraw-test"),
            sysfs_path=Path("/sys/test"),
            interface=3,
            vendor_id=0x1B1C,
            product_id=0x0A6B,
            serial="RECEIVER",
            product="HS80 Receiver",
            readable=True,
            writable=True,
        )
        transport = FakeTransport()

        with tempfile.TemporaryDirectory() as directory:
            config = ConfigStore(Path(directory) / "config.json")
            mixer = FakeMixer()
            controller = DeviceController(
                config=config,
                mixer=mixer,  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
                node_finder=lambda: node,
                transport_factory=lambda _node, _callback: transport,  # type: ignore[arg-type]
            )
            controller.start()
            deadline = time.monotonic() + 1
            while not controller.snapshot().headset_connected and time.monotonic() < deadline:
                time.sleep(0.01)

            state = controller.snapshot()
            self.assertTrue(state.receiver_connected)
            self.assertTrue(state.headset_connected)
            self.assertEqual(73, state.battery_percent)
            self.assertEqual(1, state.microphone_muted)
            self.assertEqual("1.2.3", state.receiver_firmware)
            self.assertEqual("4.5.6", state.firmware)
            self.assertEqual("RECEIVER", mixer.serial)
            rgb_close_index = next(
                index for index, call in enumerate(transport.calls) if call[1] == CMD_RGB_CLOSE
            )
            rgb_open_index = next(
                index for index, call in enumerate(transport.calls) if call[1] == CMD_RGB_OPEN
            )
            self.assertLess(rgb_close_index, rgb_open_index)

            self.assertTrue(
                controller.set_rgb("static", 50, "#ff0000", "#00ff00", "#0000ff")
            )
            rgb_calls = [call for call in transport.calls if call[1] == CMD_RGB_WRITE]
            self.assertEqual(1, len(rgb_calls))
            self.assertEqual(bytes((9, 0, 0, 0)), rgb_calls[0][2][:4])

            self.assertTrue(
                controller.update_rgb(None, None, "#112233", None, None)
            )
            profile = config.snapshot()["rgb"]
            self.assertEqual("#112233", profile["logo"])
            self.assertEqual("#00ff00", profile["indicator"])
            self.assertEqual("#112233", controller.snapshot().rgb_logo)

            self.assertTrue(controller.set_spatial_make_default(False))
            self.assertFalse(config.snapshot()["spatial"]["make_default"])
            self.assertFalse(controller.snapshot().spatial_make_default)

            controller.stop()
            self.assertTrue(transport.closed)
            self.assertGreaterEqual(
                len([call for call in transport.calls if call[1] == CMD_HARDWARE_MODE]), 2
            )

            with self.assertRaises(ControllerError):
                controller.refresh()

    def test_io_disconnect_restores_tracked_software_modes(self) -> None:
        node = HidNode(
            path=Path("/dev/hidraw-test"),
            sysfs_path=Path("/sys/test"),
            interface=3,
            vendor_id=0x1B1C,
            product_id=0x0A6B,
            serial="RECEIVER",
            product="HS80 Receiver",
            readable=True,
            writable=True,
        )

        class PollFailureTransport(FakeTransport):
            def poll_event(self, timeout_ms: int = 100) -> None:
                del timeout_ms
                raise OSError("receiver read failed")

        transport = PollFailureTransport()
        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FakeMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
                node_finder=lambda: node,
                transport_factory=lambda _node, _callback: transport,  # type: ignore[arg-type]
            )
            with self.assertLogs("hs80_control.controller", logging.WARNING):
                controller.start()
                deadline = time.monotonic() + 1
                while not transport.closed and time.monotonic() < deadline:
                    time.sleep(0.01)
                controller.stop()

            self.assertTrue(transport.closed)
            self.assertFalse(controller.snapshot().receiver_connected)
            self.assertFalse(controller.snapshot().headset_connected)
            hardware_targets = [
                target
                for target, command, _payload in transport.calls
                if command == CMD_HARDWARE_MODE
            ]
            self.assertEqual([0x09, RECEIVER_TARGET], hardware_targets)

    def test_rejects_supported_product_from_another_vendor(self) -> None:
        node = HidNode(
            path=Path("/dev/hidraw-test"),
            sysfs_path=Path("/sys/test"),
            interface=3,
            vendor_id=0x1B1C,
            product_id=0x0A6B,
            serial="RECEIVER",
            product="HS80 Receiver",
            readable=True,
            writable=True,
        )

        class OtherVendorTransport(FakeTransport):
            def read_resource(self, _resource: bytes, timeout_ms: int = 1000) -> bytes:
                del timeout_ms
                serial = b"NOT-CORSAIR"
                packet = bytearray(64)
                packet[6] = 1
                packet[7:15] = bytes((0x34, 0x12, 0, 0, 0x69, 0x0A, 1, len(serial)))
                packet[15 : 15 + len(serial)] = serial
                return bytes(packet)

        transport = OtherVendorTransport()
        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FakeMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
                node_finder=lambda: node,
                transport_factory=lambda _node, _callback: transport,  # type: ignore[arg-type]
            )
            controller.start()
            deadline = time.monotonic() + 1
            while controller.snapshot().last_error == "" and time.monotonic() < deadline:
                time.sleep(0.01)
            state = controller.snapshot()
            self.assertTrue(state.receiver_connected)
            self.assertFalse(state.headset_connected)
            self.assertIn("no supported paired HS80", state.last_error)
            controller.stop()

    def test_empty_legacy_list_falls_back_to_active_headset_properties(self) -> None:
        node = HidNode(
            path=Path("/dev/hidraw-test"),
            sysfs_path=Path("/sys/test"),
            interface=3,
            vendor_id=0x1B1C,
            product_id=0x0A6B,
            serial="RECEIVER",
            product="HS80 Receiver",
            readable=True,
            writable=True,
        )

        class PropertyFallbackTransport(FakeTransport):
            def read_resource(self, _resource: bytes, timeout_ms: int = 1000) -> bytes:
                del timeout_ms
                raise DeviceStatusError(RECEIVER_TARGET, bytes((0x08, 0x01)), 0x02)

            def transfer(
                self,
                target: int,
                command: bytes,
                payload: bytes = b"",
                timeout_ms: int = 1000,
            ) -> bytes:
                response = bytearray(super().transfer(target, command, payload, timeout_ms))
                if target == RECEIVER_TARGET and command == CMD_SUBDEVICE_BITFIELD:
                    response[4] = 0x02
                elif target == 0x09 and command == CMD_VENDOR_ID:
                    response[4:6] = (0x1B1C).to_bytes(2, "little")
                elif target == 0x09 and command == CMD_PRODUCT_ID:
                    response[4:6] = (0x0A69).to_bytes(2, "little")
                return bytes(response)

        transport = PropertyFallbackTransport()
        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FakeMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
                node_finder=lambda: node,
                transport_factory=lambda _node, _callback: transport,  # type: ignore[arg-type]
            )
            controller.start()
            deadline = time.monotonic() + 1
            while not controller.snapshot().headset_connected and time.monotonic() < deadline:
                time.sleep(0.01)

            state = controller.snapshot()
            self.assertTrue(state.receiver_connected)
            self.assertTrue(state.headset_connected)
            self.assertEqual("4.5.6", state.firmware)
            self.assertEqual(73, state.battery_percent)
            controller.stop()

    def test_switched_off_headset_reports_an_actionable_reason(self) -> None:
        node = HidNode(
            path=Path("/dev/hidraw-test"),
            sysfs_path=Path("/sys/test"),
            interface=3,
            vendor_id=0x1B1C,
            product_id=0x0A6B,
            serial="RECEIVER",
            product="HS80 Receiver",
            readable=True,
            writable=True,
        )

        class NoHeadsetTransport(FakeTransport):
            """A healthy receiver whose subdevice bitfield stays empty."""

            def read_resource(self, _resource: bytes, timeout_ms: int = 1000) -> bytes:
                del timeout_ms
                raise DeviceStatusError(RECEIVER_TARGET, bytes((0x08, 0x01)), 0x02)

        transport = NoHeadsetTransport()
        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FakeMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
                node_finder=lambda: node,
                transport_factory=lambda _node, _callback: transport,  # type: ignore[arg-type]
            )
            controller.start()
            deadline = time.monotonic() + 1
            while not controller.snapshot().receiver_connected and time.monotonic() < deadline:
                time.sleep(0.01)

            state = controller.snapshot()
            self.assertTrue(state.receiver_connected)
            self.assertFalse(state.headset_connected)
            self.assertEqual(NO_HEADSET_MESSAGE, state.last_error)
            controller.stop()

    def test_active_probe_skips_rejected_channel_and_finds_later_hs80(self) -> None:
        class MultipleEndpointTransport(FakeTransport):
            def transfer(
                self,
                target: int,
                command: bytes,
                payload: bytes = b"",
                timeout_ms: int = 1000,
            ) -> bytes:
                response = bytearray(super().transfer(target, command, payload, timeout_ms))
                if target == RECEIVER_TARGET and command == CMD_SUBDEVICE_BITFIELD:
                    response[4] = 0x06
                elif target == 0x09 and command == CMD_VENDOR_ID:
                    raise DeviceStatusError(target, command, 0x05)
                elif target == 0x0A and command == CMD_VENDOR_ID:
                    response[4:6] = (0x1B1C).to_bytes(2, "little")
                elif target == 0x0A and command == CMD_PRODUCT_ID:
                    response[4:6] = (0x0A69).to_bytes(2, "little")
                return bytes(response)

        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FakeMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
            )
            headset = controller._probe_active_headset(MultipleEndpointTransport())  # type: ignore[arg-type]
            self.assertIsNotNone(headset)
            self.assertEqual(0x0A, headset.endpoint if headset else None)

    def test_mixer_failure_has_separate_state_from_hid_error(self) -> None:
        class FailingMixer(FakeMixer):
            def snapshot(self) -> MixerSnapshot:
                raise MixerError("ALSA card unavailable")

            def set_sidetone(self, enabled: bool, db: float) -> MixerValue:
                del enabled, db
                raise MixerError("ALSA write failed")

        with tempfile.TemporaryDirectory() as directory:
            controller = DeviceController(
                config=ConfigStore(Path(directory) / "config.json"),
                mixer=FailingMixer(),  # type: ignore[arg-type]
                spatial=FakeSpatial(),  # type: ignore[arg-type]
            )
            controller.state.update(last_error="receiver access denied")

            controller._refresh_mixer()
            with self.assertRaisesRegex(MixerError, "ALSA write failed"):
                controller._set_sidetone(True, -20.0)

            state = controller.snapshot()
            self.assertFalse(state.mixer_available)
            self.assertEqual("ALSA write failed", state.audio_error)
            self.assertEqual("receiver access denied", state.last_error)


if __name__ == "__main__":
    unittest.main()
