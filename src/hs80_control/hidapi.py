"""Minimal ctypes binding to Fedora's hidapi-hidraw runtime library."""

from __future__ import annotations

import ctypes
from ctypes.util import find_library
from pathlib import Path
import threading


class HidApiError(OSError):
    """A hidapi operation failed."""


class HidApi:
    _instance: "HidApi | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "HidApi":
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialize()
                cls._instance = instance
            return cls._instance

    def _initialize(self) -> None:
        library_name = find_library("hidapi-hidraw")
        if not library_name:
            raise HidApiError("libhidapi-hidraw.so was not found")
        self.lib = ctypes.CDLL(library_name)

        self.lib.hid_init.argtypes = []
        self.lib.hid_init.restype = ctypes.c_int
        self.lib.hid_open_path.argtypes = [ctypes.c_char_p]
        self.lib.hid_open_path.restype = ctypes.c_void_p
        self.lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t]
        self.lib.hid_write.restype = ctypes.c_int
        self.lib.hid_read_timeout.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        self.lib.hid_read_timeout.restype = ctypes.c_int
        self.lib.hid_set_nonblocking.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.hid_set_nonblocking.restype = ctypes.c_int
        self.lib.hid_error.argtypes = [ctypes.c_void_p]
        self.lib.hid_error.restype = ctypes.c_wchar_p
        self.lib.hid_close.argtypes = [ctypes.c_void_p]
        self.lib.hid_close.restype = None

        if self.lib.hid_init() != 0:
            raise HidApiError("hidapi initialization failed")

    def open_path(self, path: str | Path) -> "HidHandle":
        encoded = str(path).encode("utf-8")
        pointer = self.lib.hid_open_path(encoded)
        if not pointer:
            raise HidApiError(f"cannot open {path}; install the udev rule or check device permissions")
        return HidHandle(self, pointer, Path(path))


class HidHandle:
    def __init__(self, api: HidApi, pointer: int, path: Path) -> None:
        self._api = api
        self._pointer = ctypes.c_void_p(pointer)
        self.path = path
        self._closed = False

    def _error(self, operation: str) -> HidApiError:
        detail = self._api.lib.hid_error(self._pointer)
        return HidApiError(f"{operation} failed on {self.path}: {detail or 'unknown hidapi error'}")

    def write(self, data: bytes) -> int:
        if self._closed:
            raise HidApiError("attempted to write to a closed HID handle")
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        result = self._api.lib.hid_write(self._pointer, buffer, len(data))
        if result < 0:
            raise self._error("HID write")
        return int(result)

    def read_timeout(self, size: int, timeout_ms: int) -> bytes:
        if self._closed:
            raise HidApiError("attempted to read from a closed HID handle")
        buffer = (ctypes.c_ubyte * size)()
        result = self._api.lib.hid_read_timeout(self._pointer, buffer, size, timeout_ms)
        if result < 0:
            raise self._error("HID read")
        return bytes(buffer[:result])

    def set_nonblocking(self, enabled: bool) -> None:
        if self._api.lib.hid_set_nonblocking(self._pointer, int(enabled)) < 0:
            raise self._error("setting HID nonblocking mode")

    def close(self) -> None:
        if not self._closed:
            self._api.lib.hid_close(self._pointer)
            self._closed = True

    def __enter__(self) -> "HidHandle":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
