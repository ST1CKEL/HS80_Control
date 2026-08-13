from __future__ import annotations

import unittest

from hs80_control.protocol import (
    CMD_BATTERY,
    CMD_FIRMWARE,
    CMD_GET_DEVICES,
    RECEIVER_TARGET,
    DeviceEvent,
)
from hs80_control.transport import DeviceStatusError, HidTransport, TransportError


class FakeHandle:
    def __init__(self, reports: list[bytes]) -> None:
        self.reports = list(reports)
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def read_timeout(self, _size: int, timeout_ms: int) -> bytes:
        # Zero-timeout reads are transport drains. Test responses become
        # available only after the corresponding write.
        if timeout_ms == 0 or not self.writes or not self.reports:
            return b""
        return self.reports.pop(0)

    def close(self) -> None:
        self.closed = True


def report(*values: int) -> bytes:
    packet = bytearray(64)
    packet[: len(values)] = bytes(values)
    return bytes(packet)


class TransportTests(unittest.TestCase):
    def test_event_before_response_is_dispatched(self) -> None:
        event = report(3, 1, 1, 0x0F, 0, 0x20, 0x03)
        response = report(1, 1, 2, 0, 0x84, 0x03)
        handle = FakeHandle([event, response])
        events: list[DeviceEvent] = []
        transport = HidTransport(handle, events.append)
        result = transport.transfer(0x09, CMD_BATTERY)
        self.assertEqual(response, result)
        self.assertEqual(1, len(events))
        self.assertEqual("battery", events[0].kind)
        self.assertEqual(80, events[0].value)
        self.assertEqual(bytes((2, 9, 2, 0x0F)), handle.writes[0][:4])

    def test_unrelated_reports_are_ignored(self) -> None:
        media = report(0x0E, 0, 0, 0)
        other_channel = report(1, 0, 2, 0, 0x84, 0x03)
        other_command = report(1, 1, 1, 0, 0x84, 0x03)
        response = report(1, 1, 2, 0, 0x84, 0x03)
        transport = HidTransport(FakeHandle([media, other_channel, other_command, response]))
        self.assertEqual(response, transport.transfer(0x09, CMD_BATTERY))

    def test_stale_same_target_response_is_ignored(self) -> None:
        stale_same_target = report(1, 1, 1, 0, 0, 0)
        response = report(1, 1, 2, 0, 0x84, 0x03)
        transport = HidTransport(FakeHandle([stale_same_target, response]))
        self.assertEqual(response, transport.transfer(0x09, CMD_BATTERY))

    def test_real_receiver_firmware_response_is_accepted(self) -> None:
        response = report(1, 0, 2, 0, 5, 9, 0x82, 0x00)
        transport = HidTransport(FakeHandle([response]))
        self.assertEqual(response, transport.transfer(RECEIVER_TARGET, CMD_FIRMWARE))

    def test_matched_nonzero_device_status_is_rejected(self) -> None:
        transport = HidTransport(FakeHandle([report(1, 1, 2, 5)]))
        with self.assertRaises(DeviceStatusError) as raised:
            transport.transfer(0x09, CMD_BATTERY)
        self.assertEqual(0x05, raised.exception.status)

    def test_short_write_is_rejected(self) -> None:
        class ShortWriteHandle(FakeHandle):
            def write(self, data: bytes) -> int:
                super().write(data)
                return len(data) - 1

        transport = HidTransport(ShortWriteHandle([]))
        with self.assertRaises(TransportError):
            transport.transfer(0x09, CMD_BATTERY)

    def test_resource_id_is_sent_only_when_opening_handle(self) -> None:
        responses = [
            report(1, 0, 5, 0),
            report(1, 0, 0x0D, 0),
            report(1, 0, 9, 0, 0, 14, 0, 0),
            report(1, 0, 8, 0, 0, 0, 0),
            report(1, 0, 5, 0),
        ]
        handle = FakeHandle(responses)
        result = HidTransport(handle).read_resource(CMD_GET_DEVICES)
        self.assertEqual(64, len(result))
        self.assertEqual(bytes((2, 8, 5, 1, 1, 0)), handle.writes[0][:6])
        self.assertEqual(bytes((2, 8, 0x0D, 1, 0x24, 0)), handle.writes[1][:6])
        self.assertEqual(bytes((2, 8, 9, 1, 0)), handle.writes[2][:5])
        self.assertEqual(bytes((2, 8, 8, 1, 0)), handle.writes[3][:5])
        self.assertEqual(bytes((2, 8, 5, 1, 1, 0)), handle.writes[4][:6])

    def test_multi_packet_resource_uses_probe_length_and_strips_headers(self) -> None:
        payload = bytes(range(75))
        first = bytearray(report(1, 0, 8, 0))
        first[4:] = payload[:60]
        second = bytearray(report(1, 0, 8, 0))
        second[4 : 4 + 15] = payload[60:]
        responses = [
            report(1, 0, 5, 0),
            report(1, 0, 0x0D, 0),
            report(1, 0, 9, 0, 0, 75, 0, 0, 0),
            bytes(first),
            bytes(second),
            report(1, 0, 5, 0),
        ]
        result = HidTransport(FakeHandle(responses)).read_resource(CMD_GET_DEVICES)
        self.assertEqual(payload, result[4:])

    def test_close_is_idempotent(self) -> None:
        handle = FakeHandle([])
        transport = HidTransport(handle)
        transport.close()
        transport.close()
        self.assertTrue(handle.closed)


if __name__ == "__main__":
    unittest.main()
