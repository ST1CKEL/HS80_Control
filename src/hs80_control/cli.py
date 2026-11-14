"""Command-line client for the hs80d D-Bus service."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, TypeVar

from dbus_next import BusType
from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError

from . import __version__
from .config import DEFAULT_CONFIG, RGB_BATTERY_SAVERS, RGB_MODES
from .daemon import diagnostics
from .dbus_service import BUS_NAME, INTERFACE_NAME, OBJECT_PATH
from . import i18n
from .i18n import tr as _
from .protocol import parse_color


DBUS_CALL_TIMEOUT_SECONDS = 30.0
SPATIAL_DBUS_CALL_TIMEOUT_SECONDS = 60.0
LOW_BATTERY_PERCENT = DEFAULT_CONFIG["battery"]["low_percent"]
T = TypeVar("T")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the Corsair HS80 RGB Wireless")
    parser.add_argument("--version", action="version", version=f"hs80ctl {__version__}")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="show headset state")
    subparsers.add_parser("refresh", help="refresh battery and mixer state")
    subparsers.add_parser(
        "reconnect", help="rebuild the receiver link and search for the headset"
    )
    subparsers.add_parser("doctor", help="inspect local USB, ALSA and PipeWire support")

    rgb = subparsers.add_parser("rgb", help="set RGB mode and colors")
    rgb.add_argument("mode", choices=sorted(RGB_MODES))
    rgb.add_argument("--brightness", type=int, choices=range(0, 101), metavar="0..100")
    rgb.add_argument("--logo", metavar="#RRGGBB")
    rgb.add_argument("--indicator", metavar="#RRGGBB")
    rgb.add_argument("--microphone", metavar="#RRGGBB")
    rgb.add_argument(
        "--speed", type=int, choices=range(1, 6), metavar="1..5",
        help="tempo of pulse, rainbow and cycle",
    )
    rgb.add_argument(
        "--mute-indicator", choices=("on", "off"),
        help="colour the microphone LED while the microphone is muted",
    )
    rgb.add_argument("--mute-color", metavar="#RRGGBB")
    rgb.add_argument(
        "--battery-saver", choices=sorted(RGB_BATTERY_SAVERS),
        help="lighting at low battery: unchanged, dimmed or off",
    )

    battery_warning = subparsers.add_parser(
        "battery-warning", help="switch the low-battery desktop notification"
    )
    battery_warning.add_argument("state", choices=("on", "off"))

    sleep = subparsers.add_parser("sleep", help="set automatic power-off timer")
    sleep.add_argument("minutes", type=int, choices=range(0, 91), metavar="0..90")

    sidetone = subparsers.add_parser("sidetone", help="control zero-latency microphone monitoring")
    sidetone.add_argument("state", choices=("on", "off"))
    sidetone.add_argument("--db", type=float, choices=None, default=None, metavar="-42..4")

    mic_gain = subparsers.add_parser("mic-gain", help="set hardware microphone gain")
    mic_gain.add_argument("db", type=float, metavar="-36..0")

    mic_mute = subparsers.add_parser("mic-mute", help="mute the ALSA capture channel")
    mic_mute.add_argument("state", choices=("on", "off"))

    spatial = subparsers.add_parser("spatial", help="configure binaural 7.1 processing")
    spatial_sub = spatial.add_subparsers(dest="spatial_command", required=True)
    spatial_sub.add_parser("on")
    spatial_sub.add_parser("off")
    configure = spatial_sub.add_parser("configure")
    configure.add_argument("sofa_file", type=Path)
    make_default = spatial_sub.add_parser(
        "default", help="choose whether Spatial becomes the default output"
    )
    make_default.add_argument("state", choices=("on", "off"))
    return parser


async def _dbus_call(
    awaitable: Awaitable[T], timeout: float = DBUS_CALL_TIMEOUT_SECONDS
) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except TimeoutError as exc:
        raise OSError(f"D-Bus call timed out after {timeout:g} seconds") from exc


async def _proxy() -> tuple[MessageBus, Any, Any]:
    bus = await _dbus_call(MessageBus(bus_type=BusType.SESSION).connect())
    try:
        introspection = await _dbus_call(bus.introspect(BUS_NAME, OBJECT_PATH))
    except Exception:
        bus.disconnect()
        raise
    proxy_object = bus.get_proxy_object(BUS_NAME, OBJECT_PATH, introspection)
    return (
        bus,
        proxy_object.get_interface(INTERFACE_NAME),
        proxy_object.get_interface("org.freedesktop.DBus.Properties"),
    )


async def _status(properties: Any) -> dict[str, object]:
    variants = await _dbus_call(properties.call_get_all(INTERFACE_NAME))
    return {name: variant.value for name, variant in variants.items()}


def _validate_arguments(arguments: argparse.Namespace) -> None:
    if arguments.command == "rgb":
        for option in ("logo", "indicator", "microphone", "mute_color"):
            value = getattr(arguments, option)
            if value is None:
                continue
            try:
                parse_color(value)
            except ValueError as exc:
                raise ValueError(f"--{option.replace('_', '-')}: {exc}") from exc
    elif arguments.command == "sidetone":
        if arguments.db is not None and not -42.0 <= arguments.db <= 4.0:
            raise ValueError("sidetone level must be between -42 and +4 dB")
    elif arguments.command == "mic-gain":
        if not -36.0 <= arguments.db <= 0.0:
            raise ValueError("microphone gain must be between -36 and 0 dB")
    elif (
        arguments.command == "spatial"
        and arguments.spatial_command == "configure"
    ):
        sofa_file = arguments.sofa_file.expanduser().resolve()
        if not sofa_file.is_file() or sofa_file.suffix.lower() != ".sofa":
            raise ValueError("select an existing .sofa HRTF file")
        arguments.sofa_file = sofa_file


def _print_status(status: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return

    connected = bool(status.get("HeadsetConnected"))
    battery = int(status.get("BatteryPercent", -1))
    charging = int(status.get("Charging", -1))
    microphone = int(status.get("MicrophoneMuted", -1))
    wired = bool(status.get("WiredHeadsetPresent"))
    mode = str(status.get("ConnectionMode", ""))
    unknown = _("unbekannt")

    def on_off(value: object) -> str:
        return _("an") if value else _("aus")

    def yes_no(value: object) -> str:
        return _("ja") if value else _("nein")

    offline_detail = _(" (am USB-Ladekabel)") if wired else ""
    print(f"HS80: {_('verbunden') if connected else f'offline{offline_detail}'}")
    if mode == "usb":
        print(_("Verbindung: USB-Kabel (Direktbetrieb, ohne Receiver)"))
    else:
        print(
            "Receiver: "
            f"{_('verbunden') if status.get('ReceiverConnected') else 'offline'}"
        )
    low = connected and 0 <= battery <= LOW_BATTERY_PERCENT and charging != 1
    print(
        f"{_('Akku')}: {f'{battery} %' if battery >= 0 else unknown}"
        f"{_(' (niedrig, bitte laden)') if low else ''}"
    )
    print(f"{_('Akkuwarnung')}: {on_off(status.get('BatteryNotify', True))}")
    print(f"{_('Laden')}: {yes_no(charging) if charging >= 0 else unknown}")
    microphone_text = _("stumm") if microphone else _("aktiv")
    print(f"{_('Mikrofonarm')}: {microphone_text if microphone >= 0 else unknown}")
    print(f"Firmware: {status.get('Firmware') or unknown}")
    print(
        f"RGB: {status.get('RgbMode', unknown)} / "
        f"{status.get('RgbBrightness', 0)} %"
    )
    print(
        f"Sidetone: {on_off(status.get('SidetoneEnabled'))} / "
        f"{float(status.get('SidetoneDb', 0.0)):.1f} dB"
    )
    print(f"Spatial 7.1: {on_off(status.get('SpatialEnabled'))}")
    print(
        f"{_('Spatial als Standard')}: "
        f"{yes_no(status.get('SpatialMakeDefault', True))}"
    )
    if status.get("LastError"):
        print(f"{_('Hinweis')}: {status['LastError']}")
    if status.get("AudioError"):
        print(f"{_('Audio-Hinweis')}: {status['AudioError']}")
    if status.get("SpatialError"):
        print(f"{_('Spatial-Hinweis')}: {status['SpatialError']}")


async def run(arguments: argparse.Namespace) -> int:
    _validate_arguments(arguments)

    if arguments.command == "doctor":
        return diagnostics()

    bus, interface, properties = await _proxy()
    try:
        command = arguments.command or "status"
        applied: bool | None = None
        if command == "refresh":
            applied = await _dbus_call(interface.call_refresh())
        elif command == "reconnect":
            applied = await _dbus_call(interface.call_reconnect())
        elif command == "rgb":
            applied = await _dbus_call(
                interface.call_update_rgb(
                    arguments.mode,
                    arguments.brightness if arguments.brightness is not None else -1,
                    arguments.logo or "",
                    arguments.indicator or "",
                    arguments.microphone or "",
                )
            )
            if (
                arguments.speed is not None
                or arguments.mute_indicator is not None
                or arguments.mute_color is not None
                or arguments.battery_saver is not None
            ):
                applied = await _dbus_call(
                    interface.call_update_rgb_options(
                        -1 if arguments.speed is None else arguments.speed,
                        -1
                        if arguments.mute_indicator is None
                        else int(arguments.mute_indicator == "on"),
                        arguments.mute_color or "",
                        arguments.battery_saver or "",
                    )
                )
        elif command == "battery-warning":
            applied = await _dbus_call(
                interface.call_set_battery_notify(arguments.state == "on")
            )
        elif command == "sleep":
            applied = await _dbus_call(
                interface.call_set_sleep_timer(arguments.minutes)
            )
        elif command == "sidetone":
            current = await _status(properties)
            level = (
                arguments.db
                if arguments.db is not None
                else float(current.get("SidetoneDb", -42.0))
            )
            applied = await _dbus_call(
                interface.call_set_sidetone(arguments.state == "on", level)
            )
        elif command == "mic-gain":
            applied = await _dbus_call(
                interface.call_set_microphone_gain(arguments.db)
            )
        elif command == "mic-mute":
            applied = await _dbus_call(
                interface.call_set_microphone_muted(arguments.state == "on")
            )
        elif command == "spatial":
            if arguments.spatial_command == "configure":
                applied = await _dbus_call(
                    interface.call_configure_spatial(str(arguments.sofa_file)),
                    SPATIAL_DBUS_CALL_TIMEOUT_SECONDS,
                )
            elif arguments.spatial_command in {"on", "off"}:
                applied = await _dbus_call(
                    interface.call_set_spatial_enabled(
                        arguments.spatial_command == "on"
                    ),
                    SPATIAL_DBUS_CALL_TIMEOUT_SECONDS,
                )
            else:
                applied = await _dbus_call(
                    interface.call_set_spatial_make_default(
                        arguments.state == "on"
                    )
                )

        status = await _status(properties)
        if command == "reconnect" and not arguments.json:
            # The generic "applied" wording says nothing useful here; the
            # interesting answer is whether a headset turned up.
            print(
                _("Headset verbunden.")
                if applied
                else _("Kein Headset gefunden; Receiver-Verbindung neu aufgebaut.")
            )
            _print_status(status, False)
        elif command == "status" or command == "refresh":
            _print_status(status, arguments.json)
        elif arguments.json:
            print(
                json.dumps(
                    {"applied": bool(applied), "status": status},
                    indent=2,
                    sort_keys=True,
                )
            )
        elif applied:
            print(_("Einstellung angewendet."))
        else:
            print(_("Einstellung gespeichert; das Headset ist derzeit offline."))
        return 0
    finally:
        bus.disconnect()


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    # argparse normally accepts global flags only before the subcommand.  The
    # JSON contract is easier to automate when `--json` works in either
    # position, so normalize it before parsing.
    if "--json" in raw_arguments:
        raw_arguments = [value for value in raw_arguments if value != "--json"]
        raw_arguments.insert(0, "--json")
    if raw_arguments and raw_arguments[0] == "--json":
        parser_stderr = StringIO()
        try:
            with redirect_stderr(parser_stderr):
                arguments = build_parser().parse_args(raw_arguments)
        except SystemExit as exc:
            if not exc.code:
                raise
            detail = parser_stderr.getvalue().strip().splitlines()
            message = (
                detail[-1].partition("error:")[2].strip()
                if detail
                else "invalid arguments"
            )
            print(
                json.dumps(
                    {"error": message or "invalid arguments"}, sort_keys=True
                ),
                file=sys.stderr,
            )
            return int(exc.code)
    else:
        arguments = build_parser().parse_args(raw_arguments)
    i18n.init()
    try:
        return asyncio.run(run(arguments))
    except AttributeError as exc:
        # dbus-next builds the proxy from the daemon's introspection, so a
        # method the running daemon lacks surfaces as a missing attribute.
        if "call_" not in str(exc):
            raise
        message = (
            _("der laufende Daemon kennt diese Funktion nicht (ältere Version); "
            "bitte neu starten: systemctl --user restart hs80d.service")
        )
        if arguments.json:
            print(json.dumps({"error": message}, sort_keys=True), file=sys.stderr)
        else:
            print(f"hs80ctl: {message}", file=sys.stderr)
        return 1
    except (DBusError, OSError, ValueError) as exc:
        if arguments.json:
            print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        else:
            print(f"hs80ctl: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
