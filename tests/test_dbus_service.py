from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from hs80_control.dbus_service import HS80Service
from hs80_control.state import DeviceState, StateStore


class _FakeController:
    def __init__(self) -> None:
        self.state = StateStore()

    def snapshot(self) -> DeviceState:
        return self.state.snapshot()


class DbusServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_spatial_call_does_not_block_hardware_domain(self) -> None:
        loop = asyncio.get_running_loop()
        service = HS80Service(_FakeController(), loop)  # type: ignore[arg-type]
        spatial_started = asyncio.Event()
        release_spatial = asyncio.Event()

        def spatial_operation() -> str:
            return "spatial"

        def hardware_operation() -> str:
            return "hardware"

        async def controlled_to_thread(function, *arguments):
            if function is spatial_operation:
                spatial_started.set()
                await release_spatial.wait()
            return function(*arguments)

        with patch(
            "hs80_control.dbus_service.asyncio.to_thread",
            new=controlled_to_thread,
        ):
            spatial_task = asyncio.create_task(
                service._call(
                    spatial_operation,
                    lock=service._spatial_lock,
                )
            )
            await asyncio.wait_for(spatial_started.wait(), timeout=0.5)

            hardware_result = await asyncio.wait_for(
                service._call(hardware_operation), timeout=0.5
            )
            self.assertEqual("hardware", hardware_result)
            self.assertFalse(spatial_task.done())

            release_spatial.set()
            self.assertEqual("spatial", await spatial_task)


if __name__ == "__main__":
    unittest.main()
