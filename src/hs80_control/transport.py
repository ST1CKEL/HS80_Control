"""Serialized command/response transport for the shared receiver handle."""

from __future__ import annotations

import threading
import time
from typing import Callable, Protocol

from .protocol import (
    CMD_RESOURCE_CLOSE,
    CMD_RESOURCE_OPEN,
    CMD_RESOURCE_READ,
    CMD_RESOURCE_WRITE,
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
                # report-ID 0x01 packets and echo the protocol marker/target.
                # Paired-device responses additionally echo the first command
                # byte at offset 3.  Receiver payloads start at that offset
                # (notably firmware), so they cannot use the same check; a
                # receiver timeout makes the controller disconnect and reopen
                # the entire session instead of continuing desynchronized.
                if (
                    len(response) != READ_REPORT_SIZE
                    or response[0] != 0x01
                    or response[1] != 0x02
                    or response[2] != target
                    or (target != RECEIVER_TARGET and response[3] != command[0])
                ):
                    continue
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
            self.transfer(RECEIVER_TARGET, CMD_RESOURCE_CLOSE, resource, timeout_ms)
            self.transfer(RECEIVER_TARGET, CMD_RESOURCE_OPEN, resource, timeout_ms)
            opened = True
            self.transfer(RECEIVER_TARGET, CMD_RESOURCE_WRITE, resource, timeout_ms)
            first = self.transfer(RECEIVER_TARGET, CMD_RESOURCE_READ, resource, timeout_ms)

            packet_count = first[6]
            if packet_count == 0:
                packet_count = 1
            if packet_count > 16:
                raise ProtocolError(f"invalid resource packet count: {packet_count}")

            result = bytearray(first)
            for _ in range(1, packet_count):
                continuation = self.transfer(
                    RECEIVER_TARGET, CMD_RESOURCE_READ, resource, timeout_ms
                )
                result.extend(continuation[3:])
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
