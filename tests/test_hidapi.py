from __future__ import annotations

import ctypes
import errno as errno_module
import os
import unittest

from hs80_control.hidapi import HidApiError, HidHandle


class FakeLib:
    def __init__(self, detail: str | None) -> None:
        self.detail = detail

    def hid_error(self, _pointer: object) -> str | None:
        return self.detail

    def hid_close(self, _pointer: object) -> None:
        return None


class FakeApi:
    def __init__(self, detail: str | None) -> None:
        self.lib = FakeLib(detail)


def _message(detail: str | None, errno: int) -> str:
    handle = HidHandle(FakeApi(detail), 1, "/dev/hidraw-test")  # type: ignore[arg-type]
    ctypes.set_errno(errno)
    try:
        return str(handle._error("HID read"))
    finally:
        ctypes.set_errno(0)


class HidApiErrorMessageTests(unittest.TestCase):
    def test_real_hidapi_detail_is_kept(self) -> None:
        message = _message("hid_read_timeout: Broken pipe", errno_module.EPIPE)
        self.assertEqual(
            "HID read failed on /dev/hidraw-test: hid_read_timeout: Broken pipe",
            message,
        )

    def test_strerror_zero_detail_is_replaced_by_the_real_errno(self) -> None:
        # hidapi renders errno 0 as "Success", which reads like the call worked.
        message = _message("Success", errno_module.ENODEV)
        self.assertNotIn("Success", message)
        # strerror is localized, so compare against the platform's own text.
        self.assertIn(os.strerror(errno_module.ENODEV), message)
        self.assertIn(f"errno {errno_module.ENODEV}", message)

    def test_useless_detail_without_errno_says_so(self) -> None:
        message = _message("Success", 0)
        self.assertNotIn("Success", message)
        self.assertIn("no detail reported", message)

    def test_missing_detail_is_handled(self) -> None:
        self.assertIn("no detail reported", _message(None, 0))
        self.assertIn(
            os.strerror(errno_module.ENODEV), _message(None, errno_module.ENODEV)
        )

    def test_error_is_an_oserror(self) -> None:
        handle = HidHandle(FakeApi("Success"), 1, "/dev/hidraw-test")  # type: ignore[arg-type]
        self.assertIsInstance(handle._error("HID write"), HidApiError)
        self.assertIsInstance(handle._error("HID write"), OSError)


if __name__ == "__main__":
    unittest.main()
