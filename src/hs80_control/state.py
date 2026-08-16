"""Thread-safe state shared by the hardware worker and D-Bus service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
import threading
from typing import Callable


@dataclass(slots=True)
class DeviceState:
    receiver_connected: bool = False
    headset_connected: bool = False
    receiver_serial: str = ""
    serial: str = ""
    receiver_firmware: str = ""
    firmware: str = ""
    battery_percent: int = -1
    charging: int = -1
    microphone_muted: int = -1
    hid_path: str = ""
    # "wireless" over the receiver, "usb" for a headset switched on while
    # plugged in, "" while nothing is connected.
    connection_mode: str = ""
    # True while the headset sits on USB switched off. It only charges there
    # and offers no audio or control protocol, so this just explains the state.
    wired_headset_present: bool = False
    last_error: str = ""
    rgb_mode: str = "static"
    rgb_brightness: int = 100
    rgb_logo: str = "#00bfff"
    rgb_indicator: str = "#00bfff"
    rgb_microphone: str = "#00ffff"
    sleep_minutes: int = 15
    sidetone_enabled: bool = False
    sidetone_db: float = -42.0
    mic_gain_db: float = 0.0
    mic_capture_muted: bool = False
    mixer_available: bool = False
    audio_error: str = ""
    spatial_enabled: bool = False
    spatial_make_default: bool = True
    spatial_sofa_file: str = ""
    spatial_error: str = ""


StateListener = Callable[[dict[str, object]], None]
LOG = logging.getLogger(__name__)


class StateStore:
    def __init__(self, initial: DeviceState | None = None) -> None:
        self._state = initial or DeviceState()
        self._lock = threading.RLock()
        self._listeners: list[StateListener] = []

    def snapshot(self) -> DeviceState:
        with self._lock:
            return DeviceState(**asdict(self._state))

    def as_dict(self) -> dict[str, object]:
        return asdict(self.snapshot())

    def add_listener(self, listener: StateListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def update(self, **values: object) -> dict[str, object]:
        changed: dict[str, object] = {}
        with self._lock:
            for key, value in values.items():
                if not hasattr(self._state, key):
                    raise AttributeError(f"unknown state property: {key}")
                if getattr(self._state, key) != value:
                    setattr(self._state, key, value)
                    changed[key] = value
            listeners = tuple(self._listeners)
        if changed:
            for listener in listeners:
                try:
                    listener(changed)
                except Exception:
                    LOG.exception("state listener failed")
        return changed
