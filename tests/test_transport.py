from __future__ import annotations

import unittest

from hs80_control.protocol import (
    CMD_BATTERY,
    CMD_FIRMWARE,
    RECEIVER_TARGET,
    DeviceEvent,
)
from hs80_control.transport import HidTransport, TransportError


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
        response = report(1, 2, 9, 2, 0x84, 0x03)
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
        other_target = report(1, 2, 8, 2, 0x84, 0x03)
        response = report(1, 2, 9, 2, 0x84, 0x03)
        transport = HidTransport(FakeHandle([media, other_target, response]))
        self.assertEqual(response, transport.transfer(0x09, CMD_BATTERY))

    def test_stale_same_target_response_is_ignored(self) -> None:
        stale_same_target = report(1, 2, 9, 1, 0, 0)
        response = report(1, 2, 9, 2, 0x84, 0x03)
        transport = HidTransport(FakeHandle([stale_same_target, response]))
        self.assertEqual(response, transport.transfer(0x09, CMD_BATTERY))

    def test_receiver_payload_is_not_mistaken_for_an_opcode_echo(self) -> None:
        response = report(1, 2, RECEIVER_TARGET, 4, 5, 0x34, 0x12)
        transport = HidTransport(FakeHandle([response]))
        self.assertEqual(response, transport.transfer(RECEIVER_TARGET, CMD_FIRMWARE))

    def test_short_write_is_rejected(self) -> None:
        class ShortWriteHandle(FakeHandle):
            def write(self, data: bytes) -> int:
                super().write(data)
                return len(data) - 1

        transport = HidTransport(ShortWriteHandle([]))
        with self.assertRaises(TransportError):
            transport.transfer(0x09, CMD_BATTERY)

    def test_close_is_idempotent(self) -> None:
        handle = FakeHandle([])
        transport = HidTransport(handle)
        transport.close()
        transport.close()
        self.assertTrue(handle.closed)


if __name__ == "__main__":
    unittest.main()
