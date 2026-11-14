"""Low-battery desktop notifications sent by the daemon.

The daemon is the only process that is always running, so the warning lives
here rather than in the GTK application: it has to arrive while a game is in
the foreground and the control window is closed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Literal

from dbus_next import Message, MessageType, Variant

from .state import DeviceState, StateStore


LOG = logging.getLogger(__name__)

BatteryLevel = Literal["low", "critical"]

_RANK: dict[BatteryLevel, int] = {"low": 1, "critical": 2}
_WATCHED = frozenset(
    {"battery_percent", "charging", "headset_connected", "connection_mode"}
)

NOTIFICATIONS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
DESKTOP_ENTRY = "io.github.hs80control.App"


class LowBatteryMonitor:
    """Decide when a battery reading deserves a warning.

    Each level is announced once per discharge. It is re-armed by charging,
    by a reading clearly above the threshold, or by the headset going away
    and coming back -- switching it on the next day at 15 % should warn
    again. ``min_interval`` keeps a flapping radio link from repeating it.
    """

    def __init__(
        self,
        low_percent: int = 20,
        critical_percent: int = 10,
        rearm_margin: int = 5,
        min_interval: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.low_percent = low_percent
        self.critical_percent = critical_percent
        self.rearm_margin = rearm_margin
        self.min_interval = min_interval
        self._clock = clock
        self._announced = 0
        self._last_sent: dict[BatteryLevel, float] = {}

    def evaluate(
        self, percent: int, charging: bool, connected: bool
    ) -> BatteryLevel | None:
        if not connected or percent < 0 or charging:
            self._announced = 0
            return None
        if percent > self.low_percent:
            # Readings wobble by a percent; only a clear recovery re-arms.
            if percent >= self.low_percent + self.rearm_margin:
                self._announced = 0
            return None

        level: BatteryLevel = (
            "critical" if percent <= self.critical_percent else "low"
        )
        if _RANK[level] <= self._announced:
            return None
        self._announced = _RANK[level]
        now = self._clock()
        last = self._last_sent.get(level)
        if last is not None and now - last < self.min_interval:
            return None
        self._last_sent[level] = now
        return level

    def delivery_failed(self, level: BatteryLevel) -> None:
        """Forget an announcement nobody saw so the next reading retries."""

        self._announced = min(self._announced, _RANK[level] - 1)
        self._last_sent.pop(level, None)


def notification_text(level: BatteryLevel, percent: int) -> tuple[str, str]:
    if level == "critical":
        return (
            "HS80: Akku fast leer",
            f"Noch {percent} %. Das Headset schaltet sich bald ab – jetzt laden.",
        )
    return (
        "HS80: Akku niedrig",
        f"Noch {percent} %. Bitte bald an das Ladekabel anschließen.",
    )


class BatteryNotifier:
    """Bridge controller state changes to org.freedesktop.Notifications."""

    def __init__(
        self,
        bus: Any,
        state: StateStore,
        loop: asyncio.AbstractEventLoop,
        monitor: LowBatteryMonitor | None = None,
    ) -> None:
        self._bus = bus
        self._state = state
        self._loop = loop
        self._monitor = monitor or LowBatteryMonitor()
        self._notification_id = 0
        self._stopping = False
        self._tasks: set[asyncio.Task[None]] = set()
        state.add_listener(self._state_changed)

    def close(self) -> None:
        self._stopping = True

    async def wait_idle(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _state_changed(self, changed: dict[str, object]) -> None:
        # Runs on the hardware worker thread; hop to the event loop.
        if self._stopping or not _WATCHED.intersection(changed):
            return
        try:
            self._loop.call_soon_threadsafe(self._schedule)
        except RuntimeError:
            pass

    def _schedule(self) -> None:
        if self._stopping:
            return
        task = self._loop.create_task(self.check())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def check(self) -> None:
        snapshot: DeviceState = self._state.snapshot()
        # On its own cable the headset is charging by definition, even when
        # no charging event has been seen yet.
        charging = snapshot.charging == 1 or snapshot.connection_mode == "usb"
        level = self._monitor.evaluate(
            snapshot.battery_percent, charging, snapshot.headset_connected
        )
        if level is None:
            return
        try:
            await self._send(level, snapshot.battery_percent)
        except Exception as exc:  # No notification server is not fatal.
            LOG.warning("low-battery notification failed: %s", exc)
            self._monitor.delivery_failed(level)
        else:
            LOG.info("battery %s at %d %%", level, snapshot.battery_percent)

    async def _send(self, level: BatteryLevel, percent: int) -> None:
        summary, body = notification_text(level, percent)
        critical = level == "critical"
        reply = await asyncio.wait_for(
            self._bus.call(
                Message(
                    destination=NOTIFICATIONS_NAME,
                    path=NOTIFICATIONS_PATH,
                    interface=NOTIFICATIONS_NAME,
                    member="Notify",
                    signature="susssasa{sv}i",
                    body=[
                        "HS80 Control",
                        # Replace the "low" bubble instead of stacking.
                        self._notification_id,
                        "battery-empty-symbolic"
                        if critical
                        else "battery-caution-symbolic",
                        summary,
                        body,
                        [],
                        {
                            "urgency": Variant("y", 2 if critical else 1),
                            "category": Variant("s", "device"),
                            "desktop-entry": Variant("s", DESKTOP_ENTRY),
                        },
                        -1,
                    ],
                )
            ),
            timeout=5.0,
        )
        if reply is None:
            raise OSError("notification service sent no reply")
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise OSError(str(detail))
        if reply.body and isinstance(reply.body[0], int):
            self._notification_id = reply.body[0]
