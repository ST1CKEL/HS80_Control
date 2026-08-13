"""Serialized command/response transport for the shared receiver handle."""

from __future__ import annotations

import threading
import time
from typing import Callable, Protocol

from .protocol import (
    CMD_RESOURCE_CLOSE,
    CMD_RESOURCE_OPEN,
    CMD_RESOURCE_PROBE,
    CMD_RESOURCE_READ,
    READ_REPORT_SIZE,
    RECEIVER_TARGET,
    DeviceEvent,
    ProtocolError,
    build_report,
    parse_event,
)


class Handle(Protocol):
    def write(self, data: bytes) -> int: ...

    def read_timeout(self, size: int, timeout_ms: int) -> bytes: ...

    def close(self) -> None: ...


class TransportError(OSError):
    """A report could not be exchanged with the receiver."""


class TransportTimeout(TransportError):
    """The receiver did not answer before the deadline."""


class DeviceStatusError(TransportError):
    """The receiver returned a matched Bragi response with an error status."""

    def __init__(self, target: int, command: bytes, status: int) -> None:
        self.target = target
        self.command = bytes(command)
        self.status = status
        super().__init__(
            f"device rejected {command.hex(' ')} on target 0x{target:02x} "
            f"with status 0x{status:02x}"
        )


class HidTransport:
    def __init__(
        self,
        handle: Handle,
        event_callback: Callable[[DeviceEvent], None] | None = None,
    ) -> None:
        self._handle = handle
        self._event_callback = event_callback
        self._lock = threading.RLock()
        self._closed = False

    def _dispatch(self, report: bytes) -> bool:
        event = parse_event(report)
        if event is None:
            return False
        if self._event_callback is not None:
            self._event_callback(event)
        return True

    def drain(self) -> None:
        with self._lock:
            for _ in range(128):
                report = self._handle.read_timeout(READ_REPORT_SIZE, 0)
                if not report:
                    return
                self._dispatch(report)
            raise TransportError("receiver input queue did not drain")

    def transfer(
        self,
        target: int,
        command: bytes,
        payload: bytes = b"",
        timeout_ms: int = 1000,
    ) -> bytes:
        if self._closed:
            raise TransportError("transport is closed")
        if timeout_ms <= 0:
            raise ValueError("timeout must be positive")

        with self._lock:
            self.drain()
            report = build_report(target, command, payload)
            written = self._handle.write(report)
            if written != len(report):
                raise TransportError(
                    f"short HID write: receiver accepted {written} of {len(report)} bytes"
                )

            deadline = time.monotonic() + timeout_ms / 1000
            while True:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                if time.monotonic() >= deadline:
                    raise TransportTimeout(
                        f"timeout waiting for response to {command.hex(' ')} on target 0x{target:02x}"
                    )
                response = self._handle.read_timeout(READ_REPORT_SIZE, remaining_ms)
                if not response:
                    raise TransportTimeout(
                        f"timeout waiting for response to {command.hex(' ')} on target 0x{target:02x}"
                    )
                if self._dispatch(response):
                    continue
                # Interface 3 also carries media and vendor reports with IDs
                # 0x0e, 0x0f, 0x11 and 0x58. Command responses are fixed-size
                # report-ID 0x01 packets. Byte 1 is the zero-based target
                # channel (receiver 0x08 -> 0, paired endpoint 0x09 -> 1), byte
                # 2 echoes the command family and byte 3 is status/reserved.
                # The payload starts at byte 4. A timeout makes the controller
                # disconnect and reopen the session so another command in the
                # same family cannot consume a delayed response.
                response_channel = target - RECEIVER_TARGET
                if (
                    len(response) != READ_REPORT_SIZE
                    or not 0 <= response_channel <= 7
                    or response[0] != 0x01
                    or response[1] != response_channel
                    or response[2] != command[0]
                ):
                    continue
                if response[3] != 0:
                    raise DeviceStatusError(target, command, response[3])
                return response

    def poll_event(self, timeout_ms: int = 100) -> DeviceEvent | None:
        with self._lock:
            report = self._handle.read_timeout(READ_REPORT_SIZE, timeout_ms)
            if not report:
                return None
            event = parse_event(report)
            if event and self._event_callback:
                self._event_callback(event)
            return event

    def read_resource(self, resource: bytes, timeout_ms: int = 1000) -> bytes:
        if not resource:
            raise ProtocolError("resource identifier must not be empty")

        opened = False
        active_error: BaseException | None = None
        try:
            # Bragi resource IDs select the resource only while opening the
            # fixed handle 1. Close, probe and read operate on that handle and
            # must not receive the resource ID as an extra payload byte.
            self.transfer(RECEIVER_TARGET, CMD_RESOURCE_CLOSE, b"", timeout_ms)
            try:
                self.transfer(RECEIVER_TARGET, CMD_RESOURCE_OPEN, resource, timeout_ms)
            except DeviceStatusError as exc:
                # Bragi status 0x03 means that the generic handle may still be
                # open. Upstream implementations close it and retry once.
                if exc.status != 0x03:
                    raise
                self.transfer(RECEIVER_TARGET, CMD_RESOURCE_CLOSE, b"", timeout_ms)
                self.transfer(RECEIVER_TARGET, CMD_RESOURCE_OPEN, resource, timeout_ms)
            opened = True
            probe = self.transfer(RECEIVER_TARGET, CMD_RESOURCE_PROBE, b"", timeout_ms)
            resource_length = int.from_bytes(probe[5:9], "little")
            if resource_length == 0:
                return b""
            if resource_length > 4096:
                raise ProtocolError(f"invalid resource length: {resource_length}")

            payload_capacity = READ_REPORT_SIZE - 4
            packet_count = (resource_length + payload_capacity - 1) // payload_capacity
            first = self.transfer(RECEIVER_TARGET, CMD_RESOURCE_READ, b"", timeout_ms)
            result = bytearray(first)
            bytes_remaining = resource_length - payload_capacity
            for _ in range(1, packet_count):
                continuation = self.transfer(
                    RECEIVER_TARGET, CMD_RESOURCE_READ, b"", timeout_ms
                )
                take = min(payload_capacity, bytes_remaining)
                result.extend(continuation[4 : 4 + take])
                bytes_remaining -= take
            return bytes(result)
        except BaseException as exc:
            active_error = exc
            raise
        finally:
            if opened:
                try:
                    self.transfer(RECEIVER_TARGET, CMD_RESOURCE_CLOSE, b"", timeout_ms)
                except OSError:
                    if active_error is None:
                        raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._handle.close()
                self._closed = True
