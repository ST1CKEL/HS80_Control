from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from hs80_control import cli


class CliValidationTests(unittest.IsolatedAsyncioTestCase):
    async def assert_rejected_before_proxy(
        self, arguments: list[str], message: str
    ) -> None:
        namespace = cli.build_parser().parse_args(arguments)
        proxy = AsyncMock(side_effect=AssertionError("D-Bus must not be contacted"))
        with patch("hs80_control.cli._proxy", proxy):
            with self.assertRaisesRegex(ValueError, message):
                await cli.run(namespace)
        proxy.assert_not_awaited()

    async def test_sidetone_range_is_validated_before_proxy(self) -> None:
        await self.assert_rejected_before_proxy(
            ["sidetone", "on", "--db", "4.1"], "sidetone level"
        )

    async def test_microphone_gain_range_is_validated_before_proxy(self) -> None:
        await self.assert_rejected_before_proxy(
            ["mic-gain", "-36.1"], "microphone gain"
        )

    async def test_each_rgb_color_is_validated_before_proxy(self) -> None:
        for option in ("logo", "indicator", "microphone"):
            with self.subTest(option=option):
                await self.assert_rejected_before_proxy(
                    ["rgb", "static", f"--{option}", "#12xx56"],
                    f"--{option}",
                )

    async def test_sofa_path_is_validated_before_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wrong_extension = Path(directory) / "hrtf.txt"
            wrong_extension.write_bytes(b"SOFA")
            await self.assert_rejected_before_proxy(
                ["spatial", "configure", str(wrong_extension)],
                r"existing \.sofa",
            )

        await self.assert_rejected_before_proxy(
            ["spatial", "configure", "/file/that/does/not/exist.sofa"],
            r"existing \.sofa",
        )


class _FakeBus:
    def __init__(self) -> None:
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


class _FakeInterface:
    def __init__(self) -> None:
        self.rgb_arguments: tuple[object, ...] | None = None
        self.spatial_default: bool | None = None

    async def call_set_spatial_enabled(self, _enabled: bool) -> bool:
        return True

    async def call_set_spatial_make_default(self, enabled: bool) -> bool:
        self.spatial_default = enabled
        return True

    async def call_update_rgb(self, *arguments: object) -> bool:
        self.rgb_arguments = arguments
        return True


class _FakeProperties:
    async def call_get_all(self, _interface: str) -> dict[str, object]:
        return {}


class CliCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_spatial_operation_uses_the_long_timeout(self) -> None:
        bus = _FakeBus()
        timeouts: list[float] = []

        async def observe(
            awaitable: object,
            timeout: float = cli.DBUS_CALL_TIMEOUT_SECONDS,
        ) -> object:
            timeouts.append(timeout)
            return await awaitable  # type: ignore[misc]

        namespace = cli.build_parser().parse_args(["spatial", "on"])
        with (
            patch(
                "hs80_control.cli._proxy",
                AsyncMock(return_value=(bus, _FakeInterface(), _FakeProperties())),
            ),
            patch("hs80_control.cli._dbus_call", side_effect=observe),
            redirect_stdout(StringIO()),
        ):
            result = await cli.run(namespace)

        self.assertEqual(0, result)
        self.assertTrue(bus.disconnected)
        self.assertGreaterEqual(timeouts[0], 45.0)
        self.assertEqual(cli.DBUS_CALL_TIMEOUT_SECONDS, timeouts[1])

    async def test_rgb_uses_daemon_side_partial_update(self) -> None:
        bus = _FakeBus()
        interface = _FakeInterface()
        namespace = cli.build_parser().parse_args(
            ["rgb", "static", "--logo", "#112233"]
        )
        with (
            patch(
                "hs80_control.cli._proxy",
                AsyncMock(return_value=(bus, interface, _FakeProperties())),
            ),
            redirect_stdout(StringIO()),
        ):
            result = await cli.run(namespace)

        self.assertEqual(0, result)
        self.assertEqual(
            ("static", -1, "#112233", "", ""),
            interface.rgb_arguments,
        )

    async def test_spatial_default_preference_is_exposed(self) -> None:
        bus = _FakeBus()
        interface = _FakeInterface()
        namespace = cli.build_parser().parse_args(["spatial", "default", "off"])
        with (
            patch(
                "hs80_control.cli._proxy",
                AsyncMock(return_value=(bus, interface, _FakeProperties())),
            ),
            redirect_stdout(StringIO()),
        ):
            result = await cli.run(namespace)

        self.assertEqual(0, result)
        self.assertFalse(interface.spatial_default)


class CliMainTests(unittest.TestCase):
    def test_json_validation_error_is_machine_readable(self) -> None:
        stderr = StringIO()
        proxy = AsyncMock(side_effect=AssertionError("D-Bus must not be contacted"))
        with (
            patch("hs80_control.cli._proxy", proxy),
            redirect_stderr(stderr),
        ):
            result = cli.main(["--json", "mic-gain", "0.1"])

        self.assertEqual(1, result)
        self.assertEqual(
            {"error": "microphone gain must be between -36 and 0 dB"},
            json.loads(stderr.getvalue()),
        )
        proxy.assert_not_awaited()

    def test_json_flag_is_accepted_after_subcommand(self) -> None:
        stderr = StringIO()
        proxy = AsyncMock(side_effect=AssertionError("D-Bus must not be contacted"))
        with (
            patch("hs80_control.cli._proxy", proxy),
            redirect_stderr(stderr),
        ):
            result = cli.main(["mic-gain", "0.1", "--json"])

        self.assertEqual(1, result)
        self.assertEqual(
            {"error": "microphone gain must be between -36 and 0 dB"},
            json.loads(stderr.getvalue()),
        )
        proxy.assert_not_awaited()

    def test_json_parser_error_is_machine_readable(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            result = cli.main(["mic-gain", "not-a-number", "--json"])

        self.assertEqual(2, result)
        error = json.loads(stderr.getvalue())["error"]
        self.assertIn("invalid float value", error)


if __name__ == "__main__":
    unittest.main()
