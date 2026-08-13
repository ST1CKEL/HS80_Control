"""Session D-Bus API exposed by hs80d."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from dbus_next.constants import PropertyAccess
from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface, dbus_property, method

from . import __version__
from .controller import DeviceController


BUS_NAME = "io.github.hs80control.Daemon"
OBJECT_PATH = "/io/github/hs80control/Daemon"
INTERFACE_NAME = BUS_NAME


_STATE_TO_DBUS = {
    "receiver_connected": "ReceiverConnected",
    "headset_connected": "HeadsetConnected",
    "receiver_serial": "ReceiverSerial",
    "serial": "Serial",
    "receiver_firmware": "ReceiverFirmware",
    "firmware": "Firmware",
    "battery_percent": "BatteryPercent",
    "charging": "Charging",
    "microphone_muted": "MicrophoneMuted",
    "hid_path": "HidPath",
    "last_error": "LastError",
    "rgb_mode": "RgbMode",
    "rgb_brightness": "RgbBrightness",
    "rgb_logo": "RgbLogo",
    "rgb_indicator": "RgbIndicator",
    "rgb_microphone": "RgbMicrophone",
    "sleep_minutes": "SleepMinutes",
    "sidetone_enabled": "SidetoneEnabled",
    "sidetone_db": "SidetoneDb",
    "mic_gain_db": "MicrophoneGainDb",
    "mic_capture_muted": "MicrophoneCaptureMuted",
    "mixer_available": "MixerAvailable",
    "audio_error": "AudioError",
    "spatial_enabled": "SpatialEnabled",
    "spatial_make_default": "SpatialMakeDefault",
    "spatial_sofa_file": "SpatialSofaFile",
    "spatial_error": "SpatialError",
}


class HS80Service(ServiceInterface):
    def __init__(self, controller: DeviceController, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(INTERFACE_NAME)
        self.controller = controller
        self.loop = loop
        # HID/ALSA requests are serialized by the controller worker already,
        # while PipeWire setup can legitimately take several seconds.  Keep
        # the two domains independent so a slow spatial operation does not
        # make status or headset controls appear hung on D-Bus.
        self._hardware_lock = asyncio.Lock()
        self._spatial_lock = asyncio.Lock()
        self._stopping = False
        self.controller.state.add_listener(self._state_changed)

    def begin_shutdown(self) -> None:
        self._stopping = True

    async def wait_idle(self) -> None:
        async with self._hardware_lock:
            async with self._spatial_lock:
                return

    def _state_changed(self, changed: dict[str, object]) -> None:
        if self._stopping:
            return
        properties = {
            _STATE_TO_DBUS[key]: value for key, value in changed.items() if key in _STATE_TO_DBUS
        }
        if not properties:
            return
        try:
            self.loop.call_soon_threadsafe(self.emit_properties_changed, properties)
        except RuntimeError:
            pass

    async def _call(
        self,
        function: Callable[..., Any],
        *arguments: object,
        lock: asyncio.Lock | None = None,
    ) -> Any:
        call_lock = lock or self._hardware_lock
        async with call_lock:
            if self._stopping:
                raise DBusError(
                    "io.github.hs80control.Error.Stopping",
                    "HS80 control service is stopping",
                )
            try:
                return await asyncio.to_thread(function, *arguments)
            except DBusError:
                raise
            except Exception as exc:
                raise DBusError(
                    "io.github.hs80control.Error", str(exc) or type(exc).__name__
                ) from exc

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "s":
        return __version__

    @dbus_property(access=PropertyAccess.READ)
    def ReceiverConnected(self) -> "b":
        return self.controller.snapshot().receiver_connected

    @dbus_property(access=PropertyAccess.READ)
    def HeadsetConnected(self) -> "b":
        return self.controller.snapshot().headset_connected

    @dbus_property(access=PropertyAccess.READ)
    def ReceiverSerial(self) -> "s":
        return self.controller.snapshot().receiver_serial

    @dbus_property(access=PropertyAccess.READ)
    def Serial(self) -> "s":
        return self.controller.snapshot().serial

    @dbus_property(access=PropertyAccess.READ)
    def ReceiverFirmware(self) -> "s":
        return self.controller.snapshot().receiver_firmware

    @dbus_property(access=PropertyAccess.READ)
    def Firmware(self) -> "s":
        return self.controller.snapshot().firmware

    @dbus_property(access=PropertyAccess.READ)
    def BatteryPercent(self) -> "i":
        return self.controller.snapshot().battery_percent

    @dbus_property(access=PropertyAccess.READ)
    def Charging(self) -> "i":
        return self.controller.snapshot().charging

    @dbus_property(access=PropertyAccess.READ)
    def MicrophoneMuted(self) -> "i":
        return self.controller.snapshot().microphone_muted

    @dbus_property(access=PropertyAccess.READ)
    def HidPath(self) -> "s":
        return self.controller.snapshot().hid_path

    @dbus_property(access=PropertyAccess.READ)
    def LastError(self) -> "s":
        return self.controller.snapshot().last_error

    @dbus_property(access=PropertyAccess.READ)
    def RgbMode(self) -> "s":
        return self.controller.snapshot().rgb_mode

    @dbus_property(access=PropertyAccess.READ)
    def RgbBrightness(self) -> "y":
        return self.controller.snapshot().rgb_brightness

    @dbus_property(access=PropertyAccess.READ)
    def RgbLogo(self) -> "s":
        return self.controller.snapshot().rgb_logo

    @dbus_property(access=PropertyAccess.READ)
    def RgbIndicator(self) -> "s":
        return self.controller.snapshot().rgb_indicator

    @dbus_property(access=PropertyAccess.READ)
    def RgbMicrophone(self) -> "s":
        return self.controller.snapshot().rgb_microphone

    @dbus_property(access=PropertyAccess.READ)
    def SleepMinutes(self) -> "q":
        return self.controller.snapshot().sleep_minutes

    @dbus_property(access=PropertyAccess.READ)
    def SidetoneEnabled(self) -> "b":
        return self.controller.snapshot().sidetone_enabled

    @dbus_property(access=PropertyAccess.READ)
    def SidetoneDb(self) -> "d":
        return self.controller.snapshot().sidetone_db

    @dbus_property(access=PropertyAccess.READ)
    def MicrophoneGainDb(self) -> "d":
        return self.controller.snapshot().mic_gain_db

    @dbus_property(access=PropertyAccess.READ)
    def MicrophoneCaptureMuted(self) -> "b":
        return self.controller.snapshot().mic_capture_muted

    @dbus_property(access=PropertyAccess.READ)
    def MixerAvailable(self) -> "b":
        return self.controller.snapshot().mixer_available

    @dbus_property(access=PropertyAccess.READ)
    def AudioError(self) -> "s":
        return self.controller.snapshot().audio_error

    @dbus_property(access=PropertyAccess.READ)
    def SpatialEnabled(self) -> "b":
        return self.controller.snapshot().spatial_enabled

    @dbus_property(access=PropertyAccess.READ)
    def SpatialMakeDefault(self) -> "b":
        return self.controller.snapshot().spatial_make_default

    @dbus_property(access=PropertyAccess.READ)
    def SpatialSofaFile(self) -> "s":
        return self.controller.snapshot().spatial_sofa_file

    @dbus_property(access=PropertyAccess.READ)
    def SpatialError(self) -> "s":
        return self.controller.snapshot().spatial_error

    @method()
    async def Refresh(self) -> "b":
        return bool(await self._call(self.controller.refresh))

    @method()
    async def SetRgb(
        self,
        mode: "s",
        brightness: "y",
        logo: "s",
        indicator: "s",
        microphone: "s",
    ) -> "b":
        return bool(
            await self._call(
                self.controller.set_rgb,
                mode,
                brightness,
                logo,
                indicator,
                microphone,
            )
        )

    @method()
    async def UpdateRgb(
        self,
        mode: "s",
        brightness: "n",
        logo: "s",
        indicator: "s",
        microphone: "s",
    ) -> "b":
        return bool(
            await self._call(
                self.controller.update_rgb,
                mode or None,
                None if brightness < 0 else brightness,
                logo or None,
                indicator or None,
                microphone or None,
            )
        )

    @method()
    async def SetSleepTimer(self, minutes: "q") -> "b":
        return bool(await self._call(self.controller.set_sleep_timer, minutes))

    @method()
    async def SetSidetone(self, enabled: "b", level_db: "d") -> "b":
        return bool(await self._call(self.controller.set_sidetone, enabled, level_db))

    @method()
    async def SetMicrophoneGain(self, level_db: "d") -> "b":
        return bool(await self._call(self.controller.set_microphone_gain, level_db))

    @method()
    async def SetMicrophoneMuted(self, muted: "b") -> "b":
        return bool(await self._call(self.controller.set_microphone_muted, muted))

    @method()
    async def ConfigureSpatial(self, sofa_file: "s") -> "b":
        return bool(
            await self._call(
                self.controller.configure_spatial,
                sofa_file,
                lock=self._spatial_lock,
            )
        )

    @method()
    async def SetSpatialEnabled(self, enabled: "b") -> "b":
        return bool(
            await self._call(
                self.controller.set_spatial_enabled,
                enabled,
                lock=self._spatial_lock,
            )
        )

    @method()
    async def SetSpatialMakeDefault(self, enabled: "b") -> "b":
        return bool(
            await self._call(
                self.controller.set_spatial_make_default,
                enabled,
                lock=self._spatial_lock,
            )
        )
