from __future__ import annotations

import asyncio
import unittest

from dbus_next import Message, MessageType

from hs80_control.notifications import (
    BatteryNotifier,
    LowBatteryMonitor,
    notification_text,
)
from hs80_control.state import StateStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class LowBatteryMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.monitor = LowBatteryMonitor(clock=self.clock)

    def check(self, percent: int, charging: bool = False, connected: bool = True):
        return self.monitor.evaluate(percent, charging, connected)

    def test_each_level_is_announced_once_while_discharging(self) -> None:
        self.assertIsNone(self.check(21))
        self.assertEqual("low", self.check(20))
        self.assertIsNone(self.check(19))
        self.assertIsNone(self.check(11))
        self.assertEqual("critical", self.check(10))
        self.assertIsNone(self.check(9))

    def test_first_reading_below_critical_skips_low(self) -> None:
        self.assertEqual("critical", self.check(4))
        self.assertIsNone(self.check(12))

    def test_unknown_offline_and_charging_never_warn(self) -> None:
        self.assertIsNone(self.check(-1))
        self.assertIsNone(self.check(5, connected=False))
        self.assertIsNone(self.check(5, charging=True))

    def test_wobble_around_threshold_does_not_repeat(self) -> None:
        self.assertEqual("low", self.check(20))
        self.assertIsNone(self.check(21))
        self.assertIsNone(self.check(20))
        self.assertIsNone(self.check(24))
        self.assertIsNone(self.check(20))

    def test_clear_recovery_or_charging_rearms(self) -> None:
        self.assertEqual("low", self.check(20))
        self.clock.now += 3600
        self.assertIsNone(self.check(25))
        self.assertEqual("low", self.check(20))
        self.clock.now += 3600
        self.assertIsNone(self.check(20, charging=True))
        self.assertEqual("low", self.check(20))

    def test_reconnect_rearms_but_flapping_link_is_rate_limited(self) -> None:
        self.assertEqual("low", self.check(15))
        self.assertIsNone(self.check(15, connected=False))
        self.clock.now += 30
        self.assertIsNone(self.check(15))
        self.assertIsNone(self.check(15, connected=False))
        self.clock.now += 600
        self.assertEqual("low", self.check(15))

    def test_failed_delivery_is_retried_on_next_reading(self) -> None:
        self.assertEqual("critical", self.check(8))
        self.monitor.delivery_failed("critical")
        self.assertEqual("critical", self.check(8))

    def test_text_names_the_percentage(self) -> None:
        self.assertIn("17 %", notification_text("low", 17)[1])
        self.assertIn("fast leer", notification_text("critical", 6)[0])


class FakeBus:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[Message] = []

    async def call(self, message: Message) -> Message:
        self.messages.append(message)
        if self.fail:
            return Message(
                message_type=MessageType.ERROR,
                error_name="org.freedesktop.DBus.Error.ServiceUnknown",
                reply_serial=1,
                signature="s",
                body=["no notification daemon"],
            )
        return Message(
            message_type=MessageType.METHOD_RETURN,
            reply_serial=1,
            signature="u",
            body=[41 + len(self.messages)],
        )


class BatteryNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def settle(self, notifier: BatteryNotifier) -> None:
        await asyncio.sleep(0)
        await notifier.wait_idle()

    async def test_state_changes_from_worker_thread_send_notifications(self) -> None:
        bus = FakeBus()
        state = StateStore()
        notifier = BatteryNotifier(bus, state, asyncio.get_running_loop())

        await asyncio.to_thread(
            state.update, headset_connected=True, battery_percent=55
        )
        await self.settle(notifier)
        self.assertEqual([], bus.messages)

        await asyncio.to_thread(state.update, battery_percent=20)
        await self.settle(notifier)
        self.assertEqual(1, len(bus.messages))
        low = bus.messages[0]
        self.assertEqual("org.freedesktop.Notifications", low.destination)
        self.assertEqual("Notify", low.member)
        self.assertEqual(0, low.body[1])
        self.assertEqual("HS80: Akku niedrig", low.body[3])
        self.assertEqual(1, low.body[6]["urgency"].value)

        # Unrelated properties must not cause another look at the battery.
        await asyncio.to_thread(state.update, rgb_brightness=40)
        await self.settle(notifier)
        self.assertEqual(1, len(bus.messages))

        await asyncio.to_thread(state.update, battery_percent=9)
        await self.settle(notifier)
        critical = bus.messages[1]
        self.assertEqual(42, critical.body[1])  # replaces the "low" bubble
        self.assertEqual(2, critical.body[6]["urgency"].value)

    async def test_usb_cable_mode_counts_as_charging(self) -> None:
        bus = FakeBus()
        state = StateStore()
        notifier = BatteryNotifier(bus, state, asyncio.get_running_loop())
        state.update(headset_connected=True, battery_percent=5, connection_mode="usb")
        await self.settle(notifier)
        self.assertEqual([], bus.messages)

    async def test_missing_notification_service_is_retried(self) -> None:
        bus = FakeBus(fail=True)
        state = StateStore()
        notifier = BatteryNotifier(bus, state, asyncio.get_running_loop())
        with self.assertLogs("hs80_control.notifications", "WARNING"):
            state.update(headset_connected=True, battery_percent=18)
            await self.settle(notifier)
        bus.fail = False
        state.update(battery_percent=17)
        await self.settle(notifier)
        self.assertEqual(2, len(bus.messages))

    async def test_closed_notifier_stays_silent(self) -> None:
        bus = FakeBus()
        state = StateStore()
        notifier = BatteryNotifier(bus, state, asyncio.get_running_loop())
        notifier.close()
        state.update(headset_connected=True, battery_percent=3)
        await self.settle(notifier)
        self.assertEqual([], bus.messages)


if __name__ == "__main__":
    unittest.main()
