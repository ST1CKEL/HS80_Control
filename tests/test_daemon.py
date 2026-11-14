from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from dbus_next.constants import NameFlag, RequestNameReply

from hs80_control.daemon import run_daemon


class FakeConfig:
    def snapshot(self) -> dict[str, dict[str, object]]:
        return {"battery": {"notify": True, "low_percent": 20, "critical_percent": 10}}


class FakeNotifier:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.events.append("notifier.create")

    def close(self) -> None:
        self.events.append("notifier.close")

    async def wait_idle(self) -> None:
        self.events.append("notifier.idle")


class FakeAnnouncer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.events.append("announcer.create")

    def close(self) -> None:
        self.events.append("announcer.close")


class FakeController:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.config = FakeConfig()
        self.state = object()

    def start(self) -> None:
        self.events.append("controller.start")

    def stop(self) -> None:
        self.events.append("controller.stop")


class FakeService:
    def __init__(self, _controller: FakeController, _loop: asyncio.AbstractEventLoop, events: list[str]) -> None:
        self.events = events
        self.events.append("service.create")

    def begin_shutdown(self) -> None:
        self.events.append("service.shutdown")

    async def wait_idle(self) -> None:
        self.events.append("service.idle")


class FakeBus:
    def __init__(self, events: list[str], name_reply: RequestNameReply) -> None:
        self.events = events
        self.name_reply = name_reply

    async def connect(self) -> FakeBus:
        self.events.append("bus.connect")
        return self

    def export(self, _path: str, _service: FakeService) -> None:
        self.events.append("bus.export")

    async def request_name(self, _name: str, flags: NameFlag) -> RequestNameReply:
        self.events.append(f"bus.request_name:{int(flags)}")
        return self.name_reply

    async def wait_for_disconnect(self) -> None:
        self.events.append("bus.wait_disconnect")

    def unexport(self, _path: str) -> None:
        self.events.append("bus.unexport")

    def disconnect(self) -> None:
        self.events.append("bus.disconnect")


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_is_owned_before_controller_starts(self) -> None:
        events: list[str] = []
        controller = FakeController(events)
        bus = FakeBus(events, RequestNameReply.PRIMARY_OWNER)
        loop = asyncio.get_running_loop()

        with (
            patch("hs80_control.daemon.DeviceController", return_value=controller),
            patch("hs80_control.daemon.MessageBus", return_value=bus),
            patch(
                "hs80_control.daemon.HS80Service",
                side_effect=lambda controller, service_loop: FakeService(
                    controller, service_loop, events
                ),
            ),
            patch(
                "hs80_control.daemon.BatteryNotifier",
                side_effect=lambda *_arguments: FakeNotifier(events),
            ),
            patch(
                "hs80_control.daemon.VoiceAnnouncer",
                side_effect=lambda *_arguments: FakeAnnouncer(events),
            ),
            patch.object(loop, "add_signal_handler"),
            patch("hs80_control.daemon.LOG.error"),
        ):
            result = await run_daemon()

        request = f"bus.request_name:{int(NameFlag.DO_NOT_QUEUE)}"
        self.assertEqual(1, result)
        self.assertLess(events.index(request), events.index("controller.start"))
        self.assertLess(events.index("service.shutdown"), events.index("controller.stop"))
        # The notifier must exist before the worker can report a battery
        # level, and be quiet before the bus goes away.
        self.assertLess(events.index("notifier.create"), events.index("controller.start"))
        self.assertLess(events.index("notifier.close"), events.index("bus.disconnect"))
        # Same for the spoken announcements; the player thread must be gone
        # before the process exits.
        self.assertLess(events.index("announcer.create"), events.index("controller.start"))
        self.assertIn("announcer.close", events)
        self.assertIn("controller.stop", events)

    async def test_name_conflict_never_starts_controller(self) -> None:
        events: list[str] = []
        controller = FakeController(events)
        bus = FakeBus(events, RequestNameReply.EXISTS)
        loop = asyncio.get_running_loop()

        with (
            patch("hs80_control.daemon.DeviceController", return_value=controller),
            patch("hs80_control.daemon.MessageBus", return_value=bus),
            patch(
                "hs80_control.daemon.HS80Service",
                side_effect=lambda controller, service_loop: FakeService(
                    controller, service_loop, events
                ),
            ),
            patch.object(loop, "add_signal_handler"),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not own D-Bus name"):
                await run_daemon()

        self.assertNotIn("controller.start", events)
        self.assertNotIn("controller.stop", events)
        self.assertIn("bus.disconnect", events)


if __name__ == "__main__":
    unittest.main()
