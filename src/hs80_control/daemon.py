"""hs80d entry point."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict
import json
import logging
import signal
import sys

from dbus_next import BusType
from dbus_next.aio import MessageBus
from dbus_next.constants import NameFlag, RequestNameReply

from . import __version__
from .alsa import AlsaMixer, MixerError
from .controller import DeviceController
from .dbus_service import BUS_NAME, HS80Service, OBJECT_PATH
from .discovery import discover_hid_nodes
from .spatial import SpatialError, SpatialManager


LOG = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corsair HS80 user-session control daemon")
    parser.add_argument("--version", action="version", version=f"hs80d {__version__}")
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    parser.add_argument(
        "--check", action="store_true", help="print local device diagnostics without starting D-Bus"
    )
    return parser


def diagnostics() -> int:
    nodes = discover_hid_nodes()
    result: dict[str, object] = {
        "version": __version__,
        "hid_nodes": [node.to_dict() for node in nodes],
        "sofa_plugin": SpatialManager.plugin_available(),
    }
    try:
        result["alsa"] = asdict(AlsaMixer().snapshot())
    except MixerError as exc:
        result["alsa_error"] = str(exc)
    try:
        result["pipewire_sink"] = SpatialManager.find_hs80_sink()
    except SpatialError as exc:
        result["pipewire_error"] = str(exc)
    print(json.dumps(result, indent=2, sort_keys=True))
    control_nodes = [node for node in nodes if node.interface == 3]
    return 0 if any(node.readable and node.writable for node in control_nodes) else 2


async def run_daemon() -> int:
    loop = asyncio.get_running_loop()
    controller = DeviceController()
    bus: MessageBus | None = None
    service: HS80Service | None = None
    controller_started = False
    stopped = asyncio.Event()
    wait_tasks: list[asyncio.Task[object]] = []

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stopped.set)
        except NotImplementedError:
            pass

    try:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        service = HS80Service(controller, loop)
        bus.export(OBJECT_PATH, service)
        reply = await bus.request_name(BUS_NAME, NameFlag.DO_NOT_QUEUE)
        if reply not in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
            raise RuntimeError(f"could not own D-Bus name {BUS_NAME}: {reply.name}")

        if stopped.is_set():
            return 0
        controller.start()
        controller_started = True
        LOG.info("hs80d %s is ready", __version__)

        stop_task = asyncio.create_task(stopped.wait())
        disconnect_task = asyncio.create_task(bus.wait_for_disconnect())
        wait_tasks = [stop_task, disconnect_task]
        done, _pending = await asyncio.wait(
            wait_tasks, return_when=asyncio.FIRST_COMPLETED
        )
        if disconnect_task in done and not stopped.is_set():
            try:
                disconnect_task.result()
            except Exception as exc:
                LOG.error("session D-Bus connection was lost: %s", exc)
            else:
                LOG.error("session D-Bus connection was closed")
            return 1
        return 0
    finally:
        for task in wait_tasks:
            if not task.done():
                task.cancel()
        for task in wait_tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
        if service is not None:
            service.begin_shutdown()
        if bus is not None:
            bus.unexport(OBJECT_PATH)
        if service is not None:
            await service.wait_idle()
        if controller_started:
            try:
                # The service is no longer exported and all in-flight calls
                # have completed at this point.  Stopping synchronously avoids
                # creating an otherwise unnecessary default executor during
                # shutdown and guarantees that the HID handle is restored
                # before the event loop is closed.
                controller.stop()
            except Exception as exc:
                LOG.error("failed to stop controller cleanly: %s", exc)
        if bus is not None:
            bus.disconnect()


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if arguments.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if arguments.check:
        return diagnostics()
    try:
        return asyncio.run(run_daemon())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        LOG.error("daemon failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
