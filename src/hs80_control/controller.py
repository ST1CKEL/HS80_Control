"""Long-running HS80 hardware controller with one serialized I/O worker."""

from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
import colorsys
import logging
import math
import queue
import threading
import time
from typing import Callable

from .alsa import AlsaMixer, MixerError
from .config import ConfigStore, RGB_MODES
from .discovery import HidNode, find_control_node, find_wired_headset
from .hidapi import HidApi
from .protocol import (
    CMD_BATTERY,
    CMD_FIRMWARE,
    CMD_GET_DEVICES,
    CMD_HARDWARE_MODE,
    CMD_HEARTBEAT,
    CMD_MIC_STATUS,
    CMD_PRODUCT_ID,
    CMD_RGB_CLOSE,
    CMD_RGB_OPEN,
    CMD_RGB_WRITE,
    CMD_SLEEP_DURATION,
    CMD_SLEEP_ENDPOINT,
    CMD_SOFTWARE_MODE,
    CMD_SUBDEVICE_BITFIELD,
    CMD_VENDOR_ID,
    RECEIVER_TARGET,
    SUPPORTED_HEADSET_PRODUCT_IDS,
    USB_HEADSET_PRODUCT_ID,
    USB_HEADSET_TARGET,
    VENDOR_ID,
    DeviceEvent,
    PairedDevice,
    ProtocolError,
    encode_rgb_payload,
    encode_sleep_duration,
    parse_battery_percent,
    parse_color,
    parse_device_identifier,
    parse_headset_firmware,
    parse_microphone_muted,
    parse_paired_devices,
    parse_receiver_firmware,
    parse_subdevice_bitfield,
)
from .spatial import SpatialManager
from .state import DeviceState, StateStore
from .transport import DeviceStatusError, HidTransport


LOG = logging.getLogger(__name__)

# A healthy receiver that reports an empty subdevice bitfield is the normal
# picture for a headset that is switched off. Saying so beats leaving the
# status blank, which reads like the software simply gave up.
NO_HEADSET_MESSAGE = (
    "receiver reports no connected headset; switch the HS80 on, "
    "charge it, or move it closer to the receiver"
)

# The cable carries power, the volume keys and a firmware-update endpoint --
# no audio class interface and no 0xff42 control page. Telling the user that
# beats repeating "switch it on" at a headset that is plainly powered.
WIRED_HEADSET_MESSAGE = (
    "headset is charging on its USB cable; sound and controls run over the "
    "receiver only, so unplug the cable once it has charged"
)

RECEIVER_MISSING_MESSAGE = "HS80 receiver not found"
RECEIVER_MISSING_WIRED_MESSAGE = (
    "HS80 receiver not found; the headset is on its USB cable, which charges "
    "it but carries no audio -- plug the wireless receiver back in"
)


class ControllerError(RuntimeError):
    """The requested device operation could not be completed."""


@dataclass(slots=True)
class _Request:
    operation: str
    arguments: tuple[object, ...]
    future: Future[object]


TransportFactory = Callable[[HidNode, Callable[[DeviceEvent], None]], HidTransport]
NodeFinder = Callable[[], HidNode | None]


def _default_transport_factory(
    node: HidNode, callback: Callable[[DeviceEvent], None]
) -> HidTransport:
    return HidTransport(HidApi().open_path(node.path), callback)


class DeviceController:
    """Owns the receiver handle and exposes thread-safe high-level methods."""

    def __init__(
        self,
        config: ConfigStore | None = None,
        mixer: AlsaMixer | None = None,
        spatial: SpatialManager | None = None,
        state: StateStore | None = None,
        node_finder: NodeFinder = find_control_node,
        transport_factory: TransportFactory = _default_transport_factory,
        wired_finder: NodeFinder = find_wired_headset,
    ) -> None:
        self.config = config or ConfigStore()
        settings = self.config.snapshot()
        initial = DeviceState(
            rgb_mode=settings["rgb"]["mode"],
            rgb_brightness=settings["rgb"]["brightness"],
            rgb_logo=settings["rgb"]["logo"],
            rgb_indicator=settings["rgb"]["indicator"],
            rgb_microphone=settings["rgb"]["microphone"],
            sleep_minutes=settings["sleep"]["minutes"],
            # Persisted intent is not proof that the user service is running.
            spatial_enabled=False,
            spatial_make_default=settings["spatial"]["make_default"],
            spatial_sofa_file=settings["spatial"]["sofa_file"],
        )
        self.state = state or StateStore(initial)
        self.mixer = mixer or AlsaMixer()
        self.spatial = spatial or SpatialManager(self.config)
        self._node_finder = node_finder
        self._transport_factory = transport_factory
        self._wired_finder = wired_finder
        self._transport: HidTransport | None = None
        self._node: HidNode | None = None
        self._headset: PairedDevice | None = None
        self._receiver_software_mode = False
        self._headset_software_mode = False
        self._rgb_endpoint_open = False
        self._requests: queue.Queue[_Request] = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._accepting = threading.Event()
        self._thread: threading.Thread | None = None
        self._spatial_lock = threading.RLock()
        self._next_discovery = 0.0
        self._next_heartbeat = 0.0
        self._next_animation = 0.0
        self._rgb_dirty = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._accepting.set()
        self._thread = threading.Thread(target=self._run, name="hs80-io", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 25.0) -> None:
        self._accepting.clear()
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)
        if self._thread and self._thread.is_alive():
            raise ControllerError("HS80 worker did not stop in time")

    def snapshot(self) -> DeviceState:
        return self.state.snapshot()

    def _submit(self, operation: str, *arguments: object, timeout: float = 15.0) -> object:
        if (
            not self._accepting.is_set()
            or not self._thread
            or not self._thread.is_alive()
        ):
            raise ControllerError("HS80 controller is not running")
        future: Future[object] = Future()
        try:
            self._requests.put(_Request(operation, arguments, future), timeout=1.0)
        except queue.Full as exc:
            raise ControllerError("HS80 operation queue is full") from exc
        if not self._accepting.is_set():
            future.cancel()
            raise ControllerError("HS80 controller is stopping")
        try:
            return future.result(timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise ControllerError(f"operation {operation} timed out") from exc

    def refresh(self) -> bool:
        return bool(self._submit("refresh"))

    def reconnect(self) -> bool:
        return bool(self._submit("reconnect"))

    def set_rgb(
        self,
        mode: str,
        brightness: int,
        logo: str,
        indicator: str,
        microphone: str,
    ) -> bool:
        return bool(
            self._submit("rgb", mode, brightness, logo, indicator, microphone)
        )

    def update_rgb(
        self,
        mode: str | None,
        brightness: int | None,
        logo: str | None,
        indicator: str | None,
        microphone: str | None,
    ) -> bool:
        return bool(
            self._submit(
                "rgb_patch", mode, brightness, logo, indicator, microphone
            )
        )

    def set_sleep_timer(self, minutes: int) -> bool:
        return bool(self._submit("sleep", minutes))

    def set_sidetone(self, enabled: bool, db: float) -> bool:
        return bool(self._submit("sidetone", enabled, db))

    def set_microphone_gain(self, db: float) -> bool:
        return bool(self._submit("mic_gain", db))

    def set_microphone_muted(self, muted: bool) -> bool:
        return bool(self._submit("mic_mute", muted))

    def configure_spatial(self, sofa_file: str) -> bool:
        with self._spatial_lock:
            try:
                self.spatial.configure(sofa_file)
            except Exception as exc:
                self._refresh_spatial(exc)
                raise
            self.state.update(
                spatial_sofa_file=self.config.snapshot()["spatial"]["sofa_file"]
            )
            self._refresh_spatial()
        return True

    def set_spatial_enabled(self, enabled: bool) -> bool:
        with self._spatial_lock:
            try:
                result = self.spatial.set_enabled(enabled)
            except Exception as exc:
                self._refresh_spatial(exc)
                raise
            self._refresh_spatial()
        return result

    def set_spatial_make_default(self, enabled: bool) -> bool:
        with self._spatial_lock:
            self.config.update_spatial(make_default=enabled)
            self.state.update(spatial_make_default=enabled)
        return True

    def _run(self) -> None:
        try:
            self._refresh_mixer()
            self._refresh_spatial()
            while not self._stop.is_set():
                try:
                    self._tick()
                except Exception as exc:
                    # A malformed device report must never leave D-Bus alive
                    # with a dead controller thread.
                    self._record_error(exc)
                    self._disconnect(graceful=True)
                    self._stop.wait(0.2)
        finally:
            self._accepting.clear()
            self._fail_pending_requests("controller stopped")
            self._disconnect(graceful=True)

    def _tick(self) -> None:
        now = time.monotonic()
        if self._transport is None and now >= self._next_discovery:
            self._try_connect()
            self._next_discovery = now + 2.0

        self._process_one_request()
        now = time.monotonic()

        if self._transport is not None and now >= self._next_heartbeat:
            self._heartbeat()
            self._next_heartbeat = now + 10.0

        online = self.state.snapshot().headset_connected
        if self._transport is not None and self._animation_active() and now >= self._next_animation:
            try:
                self._write_rgb(now)
            except (OSError, ProtocolError, ControllerError) as exc:
                self._rgb_write_failed(exc)
            self._next_animation = now + 0.04
        elif self._transport is not None and online and self._rgb_dirty:
            try:
                self._write_rgb(now)
            except (OSError, ProtocolError, ControllerError) as exc:
                self._rgb_write_failed(exc)

        if self._transport is not None:
            try:
                self._transport.poll_event(20)
            except OSError as exc:
                self._record_error(exc)
                self._disconnect(graceful=False)
        else:
            self._stop.wait(0.05)

    def _rgb_write_failed(self, error: BaseException) -> None:
        self._record_error(error)
        self._rgb_endpoint_open = False
        self.state.update(headset_connected=False)

    def _process_one_request(self) -> None:
        try:
            request = self._requests.get_nowait()
        except queue.Empty:
            return

        if not request.future.set_running_or_notify_cancel():
            return
        try:
            result = self._execute(request.operation, request.arguments)
        except Exception as exc:  # Propagate typed device errors to the caller.
            if request.operation in {"sidetone", "mic_gain", "mic_mute"}:
                # ALSA has its own availability/error state.  A mixer failure
                # must not overwrite an unrelated receiver/HID diagnosis.
                LOG.warning("%s", str(exc) or type(exc).__name__)
            else:
                self._record_error(exc)
            if not request.future.done():
                request.future.set_exception(exc)
        else:
            if not request.future.done():
                request.future.set_result(result)

    def _execute(self, operation: str, arguments: tuple[object, ...]) -> object:
        if operation == "refresh":
            return self._refresh_all()
        if operation == "reconnect":
            return self._reconnect()
        if operation == "rgb":
            return self._set_rgb(*arguments)
        if operation == "rgb_patch":
            return self._update_rgb(*arguments)
        if operation == "sleep":
            return self._set_sleep_timer(int(arguments[0]))
        if operation == "sidetone":
            return self._set_sidetone(bool(arguments[0]), float(arguments[1]))
        if operation == "mic_gain":
            return self._set_microphone_gain(float(arguments[0]))
        if operation == "mic_mute":
            return self._set_microphone_muted(bool(arguments[0]))
        raise ControllerError(f"unsupported operation: {operation}")

    def _reconnect(self) -> bool:
        # The receiver only reports a headset that is awake on its radio, and
        # it caches that answer until the next probe. Dropping the whole HID
        # session forces a fresh link negotiation instead of waiting out the
        # heartbeat, which is what a user wants right after switching the
        # headset on. Rediscovery is rescheduled exactly as _tick would.
        self._disconnect(graceful=True)
        self._try_connect()
        self._next_discovery = time.monotonic() + 2.0
        return self.state.snapshot().headset_connected

    def _is_usb_mode(self) -> bool:
        return self.state.snapshot().connection_mode == "usb"

    def _connect_usb_headset(self, node: HidNode) -> None:
        # Plugged in and switched on, the headset is the whole device: it
        # answers on the receiver target and rejects 0x09, so there is no
        # paired-device list to walk and no receiver to report.
        self._headset = PairedDevice(
            vendor_id=VENDOR_ID,
            product_id=USB_HEADSET_PRODUCT_ID,
            device_type=0,
            endpoint=USB_HEADSET_TARGET,
            serial=node.serial,
        )
        self._headset_software_mode = False
        self._receiver_software_mode = False
        self.state.update(
            connection_mode="usb",
            receiver_connected=False,
            receiver_firmware="",
            serial=node.serial,
            last_error="",
        )
        if hasattr(self.mixer, "bind_serial"):
            self.mixer.bind_serial(node.serial)
            self._refresh_mixer()
        try:
            self._initialize_headset()
        except (DeviceStatusError, ProtocolError, ControllerError) as exc:
            self.state.update(headset_connected=False, last_error=str(exc))
        self._next_heartbeat = time.monotonic() + 10.0

    def _refresh_wired_state(self) -> bool:
        try:
            present = self._wired_finder() is not None
        except OSError:
            # sysfs went away mid-scan; keep the previous answer rather than
            # claiming the cable was pulled.
            return self.state.snapshot().wired_headset_present
        self.state.update(wired_headset_present=present)
        return present

    def _headset_absence_message(self) -> str:
        if self.state.snapshot().wired_headset_present:
            return WIRED_HEADSET_MESSAGE
        return NO_HEADSET_MESSAGE

    def _try_connect(self) -> None:
        wired = self._refresh_wired_state()
        node = self._node_finder()
        if node is None:
            self.state.update(
                receiver_connected=False,
                headset_connected=False,
                hid_path="",
                last_error=(
                    RECEIVER_MISSING_WIRED_MESSAGE
                    if wired
                    else RECEIVER_MISSING_MESSAGE
                ),
            )
            return
        self.state.update(
            receiver_serial=node.serial,
            hid_path=str(node.path),
        )
        if not node.readable or not node.writable:
            self.state.update(
                receiver_connected=False,
                headset_connected=False,
                last_error=(
                    f"No access to {node.path}; install 70-hs80-control.rules and reconnect the receiver"
                ),
            )
            return

        try:
            transport = self._transport_factory(node, self._handle_event)
            self._transport = transport
            self._node = node
            if node.product_id == USB_HEADSET_PRODUCT_ID:
                self._connect_usb_headset(node)
                return
            receiver_fw = transport.transfer(RECEIVER_TARGET, CMD_FIRMWARE)
            self.state.update(
                connection_mode="wireless",
                receiver_connected=True,
                receiver_firmware=parse_receiver_firmware(receiver_fw),
                last_error="",
            )
            transport.transfer(RECEIVER_TARGET, CMD_SOFTWARE_MODE)
            self._receiver_software_mode = True
            if hasattr(self.mixer, "bind_serial"):
                self.mixer.bind_serial(node.serial)
                self._refresh_mixer()
            try:
                resource = transport.read_resource(CMD_GET_DEVICES)
                paired = parse_paired_devices(resource)
            except (DeviceStatusError, ProtocolError) as exc:
                # Some 0a6b firmware accepts the legacy 0x24 resource but
                # rejects its read. A matched device error or malformed legacy
                # content is safe to replace with the property-based fallback;
                # timeouts and other I/O errors still rebuild the HID session.
                LOG.debug("legacy paired-device list unavailable: %s", exc)
                paired = []
            headset = next(
                (
                    device
                    for device in paired
                    if device.vendor_id == 0x1B1C
                    and device.product_id in SUPPORTED_HEADSET_PRODUCT_IDS
                ),
                None,
            )
            if headset is None:
                headset = self._probe_active_headset(transport)
            if headset is None:
                product_ids = ", ".join(f"0x{device.product_id:04x}" for device in paired)
                self.state.update(
                    headset_connected=False,
                    last_error=(
                        f"no supported paired HS80 found (reported: {product_ids})"
                        if product_ids
                        else self._headset_absence_message()
                    ),
                )
                self._next_heartbeat = time.monotonic() + 2.0
                return
            self._headset = headset
            self._headset_software_mode = False
            self.state.update(serial=headset.serial)
            try:
                self._initialize_headset()
            except (DeviceStatusError, ProtocolError, ControllerError) as exc:
                # A powered-off wireless headset is normal. Keep the healthy
                # receiver open and probe only the paired endpoint later.
                self.state.update(headset_connected=False, last_error=str(exc))
            self._next_heartbeat = time.monotonic() + 10.0
        except Exception as exc:
            self._record_error(exc)
            self._disconnect(graceful=False)

    def _probe_active_headset(self, transport: HidTransport) -> PairedDevice | None:
        mapping = transport.transfer(RECEIVER_TARGET, CMD_SUBDEVICE_BITFIELD)
        active = parse_subdevice_bitfield(mapping)
        for device_type in range(1, 8):
            if not active & (1 << device_type):
                continue
            endpoint = RECEIVER_TARGET + device_type
            try:
                vendor = parse_device_identifier(
                    transport.transfer(endpoint, CMD_VENDOR_ID), "headset vendor ID"
                )
                if vendor != VENDOR_ID:
                    continue
                product = parse_device_identifier(
                    transport.transfer(endpoint, CMD_PRODUCT_ID), "headset product ID"
                )
            except DeviceStatusError:
                # The connection bitfield can briefly contain an endpoint that
                # is going offline. A matched status error leaves the session
                # synchronized, so later active channels remain safe to probe.
                continue
            if vendor == VENDOR_ID and product in SUPPORTED_HEADSET_PRODUCT_IDS:
                return PairedDevice(
                    vendor_id=vendor,
                    product_id=product,
                    device_type=device_type,
                    endpoint=endpoint,
                    serial="",
                )
        return None

    def _initialize_headset(self) -> None:
        transport, headset = self._require_transport_and_headset(require_online=False)
        try:
            # The directly attached headset does not implement the wireless
            # keep-alive: 0x12 goes unanswered there and was observed to reset
            # the device, taking the control interface down with it. Firmware
            # is the liveness probe in that mode.
            if not self._is_usb_mode():
                transport.transfer(headset.endpoint, CMD_HEARTBEAT)
            firmware = transport.transfer(headset.endpoint, CMD_FIRMWARE)
            transport.transfer(headset.endpoint, CMD_SOFTWARE_MODE)
            self._headset_software_mode = True
            battery = transport.transfer(headset.endpoint, CMD_BATTERY)
            microphone = transport.transfer(headset.endpoint, CMD_MIC_STATUS)
            self._open_rgb_endpoint(transport, headset.endpoint)
            self.state.update(
                headset_connected=True,
                firmware=parse_headset_firmware(firmware),
                battery_percent=parse_battery_percent(battery),
                microphone_muted=int(parse_microphone_muted(microphone)),
                last_error="",
            )

            settings = self.config.snapshot()
            if settings["sleep"]["apply_on_connect"]:
                self._apply_sleep_timer(settings["sleep"]["minutes"])
            if settings["rgb"]["apply_on_connect"]:
                self._rgb_dirty = True
                self._write_rgb(time.monotonic())
        except Exception:
            if self._rgb_endpoint_open:
                try:
                    transport.transfer(headset.endpoint, CMD_RGB_CLOSE, timeout_ms=400)
                except Exception:
                    pass
                self._rgb_endpoint_open = False
            self.state.update(headset_connected=False)
            if self._headset_software_mode:
                try:
                    transport.transfer(headset.endpoint, CMD_HARDWARE_MODE, timeout_ms=400)
                except Exception:
                    pass
                else:
                    self._headset_software_mode = False
            raise

    def _usb_heartbeat(self) -> None:
        # No 0x12 in this mode. Reading the battery keeps the session honest
        # and refreshes a value the user actually sees.
        transport, headset = self._transport, self._headset
        if transport is None or headset is None:
            return
        try:
            battery = transport.transfer(headset.endpoint, CMD_BATTERY)
            microphone = transport.transfer(headset.endpoint, CMD_MIC_STATUS)
        except (OSError, ProtocolError, ControllerError) as exc:
            self._record_error(exc)
            self._disconnect(graceful=False)
            return
        self.state.update(
            battery_percent=parse_battery_percent(battery),
            microphone_muted=int(parse_microphone_muted(microphone)),
        )

    def _heartbeat(self) -> None:
        if self._transport is None:
            return
        if self._is_usb_mode():
            self._usb_heartbeat()
            return
        try:
            self._transport.transfer(RECEIVER_TARGET, CMD_HEARTBEAT)
        except (OSError, ProtocolError, ControllerError) as exc:
            self._record_error(exc)
            self._disconnect(graceful=False)
            return

        if self._headset is None:
            try:
                self._headset = self._probe_active_headset(self._transport)
            except (OSError, ProtocolError, ControllerError) as exc:
                self._record_error(exc)
                self._disconnect(graceful=False)
                return
            if self._headset is None:
                self._refresh_wired_state()
                self.state.update(
                    headset_connected=False,
                    last_error=self._headset_absence_message(),
                )
                return
            self._headset_software_mode = False
            self.state.update(serial=self._headset.serial)
        try:
            self._transport.transfer(self._headset.endpoint, CMD_HEARTBEAT)
            if not self.state.snapshot().headset_connected:
                self._initialize_headset()
        except DeviceStatusError as exc:
            self._rgb_endpoint_open = False
            self._headset_software_mode = False
            self._headset = None
            self.state.update(headset_connected=False, serial="", last_error=str(exc))
        except (OSError, ProtocolError, ControllerError) as exc:
            self._record_error(exc)
            self._disconnect(graceful=False)

    def _refresh_all(self) -> bool:
        if self._transport is None:
            self._next_discovery = 0.0
            self._try_connect()
        if (
            self._transport is not None
            and self._headset is not None
            and self.state.snapshot().headset_connected
        ):
            try:
                battery = self._transport.transfer(self._headset.endpoint, CMD_BATTERY)
                microphone = self._transport.transfer(self._headset.endpoint, CMD_MIC_STATUS)
                self.state.update(
                    battery_percent=parse_battery_percent(battery),
                    microphone_muted=int(parse_microphone_muted(microphone)),
                    last_error="",
                )
            except (OSError, ProtocolError, ControllerError) as exc:
                self._rgb_endpoint_open = False
                self.state.update(headset_connected=False)
                self._record_error(exc)
        self._refresh_mixer()
        self._refresh_spatial()
        return self.state.snapshot().receiver_connected

    def _refresh_mixer(self) -> None:
        try:
            snapshot = self.mixer.snapshot()
            self.state.update(
                sidetone_enabled=snapshot.sidetone.enabled,
                sidetone_db=snapshot.sidetone.db,
                mic_gain_db=snapshot.microphone.db,
                mic_capture_muted=not snapshot.microphone.enabled,
                mixer_available=True,
                audio_error="",
            )
        except MixerError as exc:
            LOG.debug("ALSA state unavailable: %s", exc)
            self.state.update(mixer_available=False, audio_error=str(exc))

    def _set_rgb(self, *arguments: object) -> bool:
        mode, brightness, logo, indicator, microphone = arguments
        if str(mode) not in RGB_MODES:
            raise ProtocolError(f"unsupported RGB mode: {mode}")
        settings = self.config.update_rgb(
            str(mode), int(brightness), str(logo), str(indicator), str(microphone)
        )
        self._update_rgb_state(settings)
        return self._apply_current_rgb()

    def _update_rgb(self, *arguments: object) -> bool:
        mode, brightness, logo, indicator, microphone = arguments
        settings = self.config.patch_rgb(
            mode=None if mode is None else str(mode),
            brightness=None if brightness is None else int(brightness),
            logo=None if logo is None else str(logo),
            indicator=None if indicator is None else str(indicator),
            microphone=None if microphone is None else str(microphone),
        )
        self._update_rgb_state(settings)
        return self._apply_current_rgb()

    def _update_rgb_state(self, settings: dict[str, object]) -> None:
        self.state.update(
            rgb_mode=settings["mode"],
            rgb_brightness=settings["brightness"],
            rgb_logo=settings["logo"],
            rgb_indicator=settings["indicator"],
            rgb_microphone=settings["microphone"],
        )

    def _apply_current_rgb(self) -> bool:
        self._rgb_dirty = True
        if self.state.snapshot().headset_connected:
            try:
                self._write_rgb(time.monotonic())
            except (OSError, ProtocolError, ControllerError) as exc:
                self._rgb_write_failed(exc)
                raise
        else:
            return False
        return True

    def _animation_active(self) -> bool:
        return (
            self.state.snapshot().headset_connected
            and self.config.snapshot()["rgb"]["mode"] in {"pulse", "rainbow"}
        )

    def _write_rgb(self, now: float) -> None:
        transport, headset = self._require_transport_and_headset()
        settings = self.config.snapshot()["rgb"]
        mode = settings["mode"]
        brightness = settings["brightness"]
        logo = parse_color(settings["logo"])
        indicator = parse_color(settings["indicator"])
        microphone = parse_color(settings["microphone"])

        if mode == "off":
            logo = indicator = microphone = (0, 0, 0)
            brightness = 100
        elif mode == "pulse":
            pulse = 0.15 + 0.85 * ((math.sin(now * math.pi) + 1.0) / 2.0)
            brightness = round(brightness * pulse)
        elif mode == "rainbow":
            phase = (now % 6.0) / 6.0
            logo = tuple(round(value * 255) for value in colorsys.hsv_to_rgb(phase, 1.0, 1.0))
            indicator = tuple(
                round(value * 255) for value in colorsys.hsv_to_rgb((phase + 0.5) % 1.0, 1.0, 1.0)
            )

        state = self.state.snapshot()
        if state.microphone_muted == 1 and settings["mute_indicator"]:
            microphone = (255, 0, 0)

        if not self._rgb_endpoint_open:
            self._open_rgb_endpoint(transport, headset.endpoint)
        payload = encode_rgb_payload(logo, indicator, microphone, brightness)
        transport.transfer(headset.endpoint, CMD_RGB_WRITE, payload)
        self._rgb_dirty = False

    def _open_rgb_endpoint(self, transport: HidTransport, endpoint: int) -> None:
        # Lighting handle 0 can survive a mode switch or an unclean client
        # exit. Closing it is idempotent and prevents open status 0x03 on the
        # next daemon start.
        transport.transfer(endpoint, CMD_RGB_CLOSE)
        transport.transfer(endpoint, CMD_RGB_OPEN)
        self._rgb_endpoint_open = True

    def _set_sleep_timer(self, minutes: int) -> bool:
        if not 0 <= minutes <= 90:
            raise ProtocolError("sleep timer must be between 0 and 90 minutes")
        self.config.update_sleep(minutes)
        self.state.update(sleep_minutes=minutes)
        if not self.state.snapshot().headset_connected:
            return False
        try:
            self._apply_sleep_timer(minutes)
        except (OSError, ProtocolError, ControllerError) as exc:
            self._rgb_write_failed(exc)
            raise
        return True

    def _apply_sleep_timer(self, minutes: int) -> None:
        transport, headset = self._require_transport_and_headset()
        transport.transfer(headset.endpoint, CMD_SLEEP_ENDPOINT, bytes((1 if minutes else 0,)))
        if minutes:
            transport.transfer(headset.endpoint, CMD_SLEEP_DURATION, encode_sleep_duration(minutes))

    def _set_sidetone(self, enabled: bool, db: float) -> bool:
        try:
            value = self.mixer.set_sidetone(enabled, db)
        except MixerError as exc:
            self.state.update(mixer_available=False, audio_error=str(exc))
            raise
        self.state.update(
            sidetone_enabled=value.enabled,
            sidetone_db=value.db,
            mixer_available=True,
            audio_error="",
        )
        return True

    def _set_microphone_gain(self, db: float) -> bool:
        try:
            value = self.mixer.set_microphone_gain(db)
        except MixerError as exc:
            self.state.update(mixer_available=False, audio_error=str(exc))
            raise
        self.state.update(
            mic_gain_db=value.db,
            mic_capture_muted=not value.enabled,
            mixer_available=True,
            audio_error="",
        )
        return True

    def _set_microphone_muted(self, muted: bool) -> bool:
        try:
            value = self.mixer.set_microphone_muted(muted)
        except MixerError as exc:
            self.state.update(mixer_available=False, audio_error=str(exc))
            raise
        self.state.update(
            mic_gain_db=value.db,
            mic_capture_muted=not value.enabled,
            mixer_available=True,
            audio_error="",
        )
        return True

    def _refresh_spatial(self, operation_error: BaseException | None = None) -> None:
        try:
            enabled = self.spatial.is_enabled()
        except OSError as exc:
            error = operation_error or exc
            self.state.update(
                spatial_enabled=False,
                spatial_error=str(error) or type(error).__name__,
            )
            return
        self.state.update(
            spatial_enabled=enabled,
            spatial_error=(
                str(operation_error) or type(operation_error).__name__
                if operation_error is not None
                else ""
            ),
        )

    def _handle_event(self, event: DeviceEvent) -> None:
        if event.kind == "battery" and isinstance(event.value, int):
            self.state.update(battery_percent=event.value)
        elif event.kind == "charging" and isinstance(event.value, bool):
            self.state.update(charging=int(event.value))
        elif event.kind == "microphone" and isinstance(event.value, bool):
            self.state.update(microphone_muted=int(event.value))
            self._rgb_dirty = True
        elif event.kind == "connection" and isinstance(event.value, int):
            if event.value == 0:
                self._rgb_endpoint_open = False
                self._headset_software_mode = False
                self._headset = None
                self.state.update(headset_connected=False, serial="")
            elif event.value == 2:
                self._next_heartbeat = 0.0

    def _require_transport_and_headset(
        self, require_online: bool = True
    ) -> tuple[HidTransport, PairedDevice]:
        if self._transport is None or self._headset is None:
            raise ControllerError("HS80 transport is not initialized")
        if require_online and not self.state.snapshot().headset_connected:
            raise ControllerError("HS80 headset is offline")
        return self._transport, self._headset

    def _disconnect(self, graceful: bool) -> None:
        # Software-mode ownership is independent of the public connection
        # state: an I/O error marks a device offline before teardown, but it
        # can still accept the best-effort hardware-mode command.
        del graceful
        transport = self._transport
        headset = self._headset
        if transport is not None:
            if headset is not None and self._rgb_endpoint_open:
                try:
                    transport.transfer(headset.endpoint, CMD_RGB_CLOSE, timeout_ms=400)
                except Exception:
                    pass
                self._rgb_endpoint_open = False
            if headset is not None and self._headset_software_mode:
                try:
                    transport.transfer(headset.endpoint, CMD_HARDWARE_MODE, timeout_ms=400)
                except Exception:
                    pass
                else:
                    self._headset_software_mode = False
            if self._receiver_software_mode:
                try:
                    transport.transfer(RECEIVER_TARGET, CMD_HARDWARE_MODE, timeout_ms=400)
                except Exception:
                    pass
                else:
                    self._receiver_software_mode = False
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass
        self._transport = None
        self._node = None
        self._headset = None
        self._receiver_software_mode = False
        self._headset_software_mode = False
        self._rgb_endpoint_open = False
        self.state.update(
            connection_mode="", receiver_connected=False, headset_connected=False
        )

    def _record_error(self, error: BaseException) -> None:
        message = str(error) or type(error).__name__
        LOG.warning("%s", message)
        self.state.update(last_error=message)

    def _fail_pending_requests(self, message: str) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                return
            if not request.future.done():
                request.future.set_exception(ControllerError(message))
