"""Pure protocol helpers for the Corsair HS80 RGB Wireless receiver.

The functions in this module intentionally do not perform I/O. Keeping packet
construction and parsing separate makes malformed receiver data testable and
prevents accidental access to undocumented firmware or pairing commands.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Final, Literal


VENDOR_ID: Final = 0x1B1C
RECEIVER_PRODUCT_ID: Final = 0x0A6B
SUPPORTED_HEADSET_PRODUCT_IDS: Final = frozenset({0x0A69, 0x0A71})
# The headset's own USB ids. Switched off it charges as 0x0a6a with a single
# HID interface and no audio. Switched on it re-enumerates as 0x0a69 with three
# audio interfaces plus control interface 3, carrying the same 0xff42 page as
# the receiver -- and it answers on target 0x08, rejecting 0x09 with 0x06.
WIRED_HEADSET_PRODUCT_ID: Final = 0x0A6A
USB_HEADSET_PRODUCT_ID: Final = 0x0A69
USB_HEADSET_TARGET: Final = 0x08

CONTROL_INTERFACE: Final = 3
VENDOR_USAGE_PAGE: Final = 0xFF42
RECEIVER_TARGET: Final = 0x08
DEFAULT_HEADSET_TARGET: Final = 0x09

WRITE_REPORT_SIZE: Final = 64
READ_REPORT_SIZE: Final = 64
WIRE_REPORT_ID: Final = 0x02
EVENT_REPORT_ID: Final = 0x03

CMD_SOFTWARE_MODE: Final = bytes((0x01, 0x03, 0x00, 0x02))
CMD_HARDWARE_MODE: Final = bytes((0x01, 0x03, 0x00, 0x01))
CMD_SLEEP_NOW: Final = bytes((0x01, 0x03, 0x00, 0x04))
CMD_FIRMWARE: Final = bytes((0x02, 0x13))
CMD_BATTERY: Final = bytes((0x02, 0x0F))
CMD_MIC_STATUS: Final = bytes((0x02, 0xA6))
CMD_HEARTBEAT: Final = bytes((0x12,))
CMD_VENDOR_ID: Final = bytes((0x02, 0x11))
CMD_PRODUCT_ID: Final = bytes((0x02, 0x12))
CMD_SUBDEVICE_BITFIELD: Final = bytes((0x02, 0x36))

CMD_GET_DEVICES: Final = bytes((0x24,))
CMD_RESOURCE_OPEN: Final = bytes((0x0D, 0x01))
CMD_RESOURCE_CLOSE: Final = bytes((0x05, 0x01, 0x01))
CMD_RESOURCE_READ: Final = bytes((0x08, 0x01))
CMD_RESOURCE_PROBE: Final = bytes((0x09, 0x01))

CMD_RGB_CLOSE: Final = bytes((0x05, 0x01, 0x00))
CMD_RGB_OPEN: Final = bytes((0x0D, 0x00, 0x01))
CMD_RGB_WRITE: Final = bytes((0x06, 0x00))
CMD_SLEEP_ENDPOINT: Final = bytes((0x01, 0x0D, 0x00))
CMD_SLEEP_DURATION: Final = bytes((0x01, 0x0E, 0x00))

EventKind = Literal["battery", "charging", "microphone", "connection", "unknown"]


class ProtocolError(ValueError):
    """Raised when a report is malformed or an argument is unsafe."""


@dataclass(frozen=True, slots=True)
class PairedDevice:
    vendor_id: int
    product_id: int
    device_type: int
    endpoint: int
    serial: str


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    kind: EventKind
    value: int | bool | None
    raw: bytes


def build_report(target: int, command: bytes, payload: bytes = b"") -> bytes:
    """Build one hidapi output report.

    Interface 3 exposes report ID 0x02 with 63 data bytes.  hidapi therefore
    receives exactly the descriptor-sized 64-byte report, beginning with the
    report ID itself.
    """

    if not 0 <= target <= 0xFF:
        raise ProtocolError("target must fit in one byte")
    if not command:
        raise ProtocolError("command must not be empty")
    body_length = 2 + len(command) + len(payload)
    if body_length > WRITE_REPORT_SIZE:
        raise ProtocolError("command and payload exceed the 64-byte HID report")

    report = bytearray(WRITE_REPORT_SIZE)
    report[0] = WIRE_REPORT_ID
    report[1] = target
    report[2 : 2 + len(command)] = command
    report[2 + len(command) : body_length] = payload
    return bytes(report)


def _require(report: bytes, size: int, description: str) -> None:
    if len(report) < size:
        raise ProtocolError(f"{description} report is too short: {len(report)} < {size}")


def parse_receiver_firmware(report: bytes) -> str:
    _require(report, 8, "receiver firmware")
    patch = int.from_bytes(report[6:8], "little")
    return f"{report[4]}.{report[5]}.{patch}"


def parse_headset_firmware(report: bytes) -> str:
    _require(report, 7, "headset firmware")
    return f"{report[4]}.{report[5]}.{report[6]}"


def parse_battery_percent(report: bytes) -> int:
    _require(report, 6, "battery")
    tenths = int.from_bytes(report[4:6], "little")
    if tenths > 1000:
        raise ProtocolError(f"invalid battery value: {tenths}")
    return min(100, tenths // 10)


def parse_microphone_muted(report: bytes) -> bool:
    _require(report, 5, "microphone")
    if report[4] not in (0, 1):
        raise ProtocolError(f"invalid microphone state: {report[4]}")
    return report[4] == 1


def parse_device_identifier(report: bytes, description: str) -> int:
    _require(report, 6, description)
    return int.from_bytes(report[4:6], "little")


def parse_subdevice_bitfield(report: bytes) -> int:
    _require(report, 7, "receiver subdevice bitfield")
    # Only channels 1..7 map to paired targets 0x09..0x0f. Ignore the
    # receiver/reserved bit 0 and any firmware-specific upper flag bits.
    return int.from_bytes(report[4:7], "little") & 0xFE


def parse_event(report: bytes) -> DeviceEvent | None:
    """Parse an unsolicited receiver event, returning None for responses."""

    if not report or report[0] != EVENT_REPORT_ID:
        return None

    if len(report) >= 7 and report[3] == 0x0F:
        tenths = int.from_bytes(report[5:7], "little")
        if tenths <= 1000:
            return DeviceEvent("battery", min(100, tenths // 10), bytes(report))

    if len(report) >= 6 and report[3] == 0x10 and report[5] in (0, 1):
        return DeviceEvent("charging", report[5] == 1, bytes(report))

    if len(report) >= 6 and report[1] == 0x00 and report[3] == 0x36:
        return DeviceEvent("connection", report[5], bytes(report))

    if (
        len(report) >= 6
        and report[2] == 0x01
        and report[3] in (0x8E, 0xA6)
        and report[5] in (0, 1)
    ):
        return DeviceEvent("microphone", report[5] == 1, bytes(report))

    return DeviceEvent("unknown", None, bytes(report))


def parse_paired_devices(report: bytes) -> list[PairedDevice]:
    """Parse the receiver's paired-device resource with strict bounds checks."""

    _require(report, 7, "paired-device list")
    channel_count = report[6]
    if channel_count > 7:
        raise ProtocolError(f"invalid paired-device count: {channel_count}")

    data = memoryview(report)[7:]
    position = 0
    devices: list[PairedDevice] = []

    for index in range(channel_count):
        if position + 5 > len(data):
            raise ProtocolError("truncated paired-device entry")

        vendor_id = int.from_bytes(data[position : position + 2], "little")
        typed_format = position + 8 <= len(data) and bytes(data[position + 2 : position + 4]) == b"\x00\x00"

        if typed_format:
            product_id = int.from_bytes(data[position + 4 : position + 6], "little")
            device_type = int(data[position + 6])
            serial_length = int(data[position + 7])
            serial_start = position + 8
        else:
            product_id = int.from_bytes(data[position + 2 : position + 4], "little")
            device_type = index + 1
            serial_length = int(data[position + 4])
            serial_start = position + 5

        serial_end = serial_start + serial_length
        if serial_end > len(data):
            raise ProtocolError("paired-device serial exceeds report length")

        serial_bytes = bytes(data[serial_start:serial_end])
        serial = serial_bytes.replace(b"\x00", b"").decode("ascii", errors="replace")
        if not 1 <= device_type <= 7:
            raise ProtocolError(f"invalid paired-device type: {device_type}")
        endpoint = DEFAULT_HEADSET_TARGET if channel_count == 1 else RECEIVER_TARGET + device_type
        if not 0x09 <= endpoint <= 0x0F:
            raise ProtocolError(f"paired-device endpoint is invalid: 0x{endpoint:02x}")

        devices.append(
            PairedDevice(
                vendor_id=vendor_id,
                product_id=product_id,
                device_type=device_type,
                endpoint=endpoint,
                serial=serial,
            )
        )
        position = serial_end

        # Some firmware revisions count an embedded NUL as part of the serial
        # while placing one additional physical byte after the declared range.
        # Consume that byte only between entries and only for the observed
        # embedded-NUL form.
        if b"\x00" in serial_bytes and position < len(data) and index + 1 < channel_count:
            position += 1

    return devices


def parse_color(value: str) -> tuple[int, int, int]:
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6:
        raise ProtocolError("color must use #RRGGBB format")
    try:
        channels = tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ProtocolError("color must use hexadecimal #RRGGBB format") from exc
    return channels  # type: ignore[return-value]


def format_color(color: tuple[int, int, int]) -> str:
    if len(color) != 3 or any(not 0 <= channel <= 255 for channel in color):
        raise ProtocolError("RGB channels must be between 0 and 255")
    return "#{:02x}{:02x}{:02x}".format(*color)


def scale_color(color: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
    if not 0 <= brightness <= 100:
        raise ProtocolError("brightness must be between 0 and 100")
    return tuple(round(channel * brightness / 100) for channel in color)  # type: ignore[return-value]


def encode_rgb_payload(
    logo: tuple[int, int, int],
    indicator: tuple[int, int, int],
    microphone: tuple[int, int, int],
    brightness: int,
) -> bytes:
    """Encode three logical zones as planar RRR-GGG-BBB data."""

    zones = tuple(scale_color(color, brightness) for color in (logo, indicator, microphone))
    planar = bytes(
        [zones[0][0], zones[1][0], zones[2][0]]
        + [zones[0][1], zones[1][1], zones[2][1]]
        + [zones[0][2], zones[1][2], zones[2][2]]
    )
    return struct.pack("<H", len(planar)) + b"\x00\x00" + planar


def encode_sleep_duration(minutes: int) -> bytes:
    if not 1 <= minutes <= 90:
        raise ProtocolError("sleep timer must be between 1 and 90 minutes")
    return struct.pack("<I", minutes * 60 * 1000)
