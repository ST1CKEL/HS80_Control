from __future__ import annotations

import unittest

from hs80_control.protocol import (
    CMD_BATTERY,
    EVENT_REPORT_ID,
    ProtocolError,
    build_report,
    encode_rgb_payload,
    encode_sleep_duration,
    parse_battery_percent,
    parse_color,
    parse_event,
    parse_headset_firmware,
    parse_paired_devices,
    parse_receiver_firmware,
)


class ProtocolTests(unittest.TestCase):
    def test_build_report_matches_descriptor_framing(self) -> None:
        report = build_report(0x09, CMD_BATTERY)
        self.assertEqual(64, len(report))
        self.assertEqual(bytes((0x02, 0x09, 0x02, 0x0F)), report[:4])
        self.assertEqual(bytes(60), report[4:])

    def test_build_report_rejects_oversized_payload(self) -> None:
        with self.assertRaises(ProtocolError):
            build_report(0x09, b"\x01", bytes(63))

    def test_firmware_and_battery_parsing(self) -> None:
        receiver = bytes((1, 2, 3, 4, 5, 0x34, 0x12))
        headset = bytes((1, 2, 3, 4, 5, 6, 7))
        battery = bytes((1, 2, 3, 4, 0xB2, 0x02))
        self.assertEqual("4.5.4660", parse_receiver_firmware(receiver))
        self.assertEqual("5.6.7", parse_headset_firmware(headset))
        self.assertEqual(69, parse_battery_percent(battery))

    def test_event_parsing(self) -> None:
        battery = bytes((EVENT_REPORT_ID, 1, 1, 0x0F, 0, 0xB2, 0x02))
        charging = bytes((EVENT_REPORT_ID, 1, 1, 0x10, 0, 1))
        microphone = bytes((EVENT_REPORT_ID, 0, 1, 0xA6, 0, 1))
        self.assertEqual(("battery", 69), (parse_event(battery).kind, parse_event(battery).value))
        self.assertEqual(("charging", True), (parse_event(charging).kind, parse_event(charging).value))
        self.assertEqual(
            ("microphone", True),
            (parse_event(microphone).kind, parse_event(microphone).value),
        )
        self.assertIsNone(parse_event(bytes((1, 2, 3, 4))))

    def test_typed_device_list(self) -> None:
        serial = b"HS80SERIAL"
        report = bytearray(64)
        report[6] = 1
        report[7:15] = bytes((0x1C, 0x1B, 0, 0, 0x69, 0x0A, 1, len(serial)))
        report[15 : 15 + len(serial)] = serial
        devices = parse_paired_devices(bytes(report))
        self.assertEqual(1, len(devices))
        self.assertEqual(0x1B1C, devices[0].vendor_id)
        self.assertEqual(0x0A69, devices[0].product_id)
        self.assertEqual(0x09, devices[0].endpoint)
        self.assertEqual("HS80SERIAL", devices[0].serial)

    def test_legacy_device_list(self) -> None:
        serial = b"LEGACY"
        report = bytearray(64)
        report[6] = 1
        report[7:12] = bytes((0x1C, 0x1B, 0x69, 0x0A, len(serial)))
        report[12 : 12 + len(serial)] = serial
        device = parse_paired_devices(bytes(report))[0]
        self.assertEqual(0x0A69, device.product_id)
        self.assertEqual("LEGACY", device.serial)

    def test_rgb_is_planar_and_brightness_scaled(self) -> None:
        payload = encode_rgb_payload((255, 0, 0), (0, 255, 0), (0, 0, 255), 50)
        self.assertEqual(bytes((9, 0, 0, 0)), payload[:4])
        self.assertEqual(bytes((128, 0, 0, 0, 128, 0, 0, 0, 128)), payload[4:])

    def test_color_and_sleep_validation(self) -> None:
        self.assertEqual((0, 191, 255), parse_color("#00bfff"))
        self.assertEqual((0x60, 0xEA, 0, 0), tuple(encode_sleep_duration(1)))
        with self.assertRaises(ProtocolError):
            parse_color("blue")
        with self.assertRaises(ProtocolError):
            encode_sleep_duration(0)


if __name__ == "__main__":
    unittest.main()
