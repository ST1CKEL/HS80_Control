"""ALSA mixer access for controls exposed by the USB Audio Class device."""

from __future__ import annotations

from dataclasses import dataclass
import os
import math
from pathlib import Path
import re
import subprocess

from .protocol import RECEIVER_PRODUCT_ID, USB_HEADSET_PRODUCT_ID, VENDOR_ID


class MixerError(OSError):
    """An ALSA card or mixer operation failed."""


@dataclass(frozen=True, slots=True)
class MixerValue:
    raw: int
    percent: int
    db: float
    enabled: bool


@dataclass(frozen=True, slots=True)
class MixerSnapshot:
    sidetone: MixerValue
    microphone: MixerValue


_VALUE_PATTERN = re.compile(
    r"^\s*(?:Mono|Front Left):\s+(?:Playback|Capture)\s+"
    r"(?P<raw>\d+)\s+\[(?P<percent>\d+)%\]\s+"
    r"\[(?P<db>-?\d+(?:\.\d+)?)dB\]\s+\[(?P<switch>on|off)\]",
    re.MULTILINE,
)

# On the directly attached headset both directions share one simple control,
# printed on a single line as "Mono: Playback ... [on] Capture ... [on]".
# The direction keyword therefore has to be part of the match.
_DIRECTED_VALUE_PATTERN = re.compile(
    r"(?P<direction>Playback|Capture)\s+"
    r"(?P<raw>\d+)\s+\[(?P<percent>\d+)%\]\s+"
    r"\[(?P<db>-?\d+(?:\.\d+)?)dB\]\s+\[(?P<switch>on|off)\]"
)


def _value_from_match(match: re.Match[str]) -> MixerValue:
    return MixerValue(
        raw=int(match.group("raw")),
        percent=int(match.group("percent")),
        db=float(match.group("db")),
        enabled=match.group("switch") == "on",
    )


def parse_amixer_value(output: str, direction: str | None = None) -> MixerValue:
    if direction is not None:
        for match in _DIRECTED_VALUE_PATTERN.finditer(output):
            if match.group("direction") == direction:
                return _value_from_match(match)
        raise MixerError(f"could not parse {direction.lower()} values from amixer output")
    match = _VALUE_PATTERN.search(output)
    if match is None:
        raise MixerError("could not parse amixer output")
    return _value_from_match(match)


# (amixer simple control, direction keyword). The receiver publishes dedicated
# Sidetone and Mic controls; the directly attached headset folds both onto
# 'Headset',0 and puts the headphone volume on 'Headset',1, which PipeWire owns.
_ControlSpec = tuple[str, str | None]

_WIRELESS_SCHEME: dict[str, _ControlSpec] = {
    "Sidetone": ("Sidetone", None),
    "Mic": ("Mic", None),
}
_USB_SCHEME: dict[str, _ControlSpec] = {
    "Sidetone": ("Headset,0", "Playback"),
    "Mic": ("Headset,0", "Capture"),
}


class AlsaMixer:
    def __init__(
        self,
        proc_root: Path = Path("/proc/asound"),
        executable: str = "amixer",
        sound_class: Path = Path("/sys/class/sound"),
    ) -> None:
        self.proc_root = proc_root
        self.executable = executable
        self.sound_class = sound_class
        self.serial: str | None = None
        self._scheme_cache: dict[str, _ControlSpec] = _WIRELESS_SCHEME
        self._scheme_card: int | None = None

    def bind_serial(self, serial: str) -> None:
        self.serial = serial or None

    def _card_serial(self, card_number: int) -> str:
        try:
            device = (self.sound_class / f"card{card_number}" / "device").resolve(strict=True)
        except (FileNotFoundError, OSError):
            return ""
        for parent in (device, *device.parents):
            try:
                return (parent / "serial").read_text(encoding="utf-8").strip()
            except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
                continue
        return ""

    def find_card(self) -> int:
        # Wireless audio arrives through the receiver; a headset switched on
        # while plugged in brings its own card under a different product id.
        expected = {
            f"{VENDOR_ID:04x}:{RECEIVER_PRODUCT_ID:04x}",
            f"{VENDOR_ID:04x}:{USB_HEADSET_PRODUCT_ID:04x}",
        }
        matches: list[int] = []
        for card in sorted(self.proc_root.glob("card[0-9]*")):
            try:
                usb_id = (card / "usbid").read_text(encoding="ascii").strip().lower()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if usb_id in expected:
                card_number = int(card.name.removeprefix("card"))
                if self.serial and self._card_serial(card_number) != self.serial:
                    continue
                matches.append(card_number)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MixerError("multiple HS80 ALSA cards found; select a receiver serial")
        raise MixerError("HS80 ALSA card was not found")

    def _run(self, *arguments: str) -> str:
        return self._run_on(self.find_card(), *arguments)

    def _run_on(self, card: int, *arguments: str) -> str:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        try:
            result = subprocess.run(
                [self.executable, "-c", str(card), *arguments],
                check=False,
                text=True,
                capture_output=True,
                timeout=3,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MixerError(f"could not execute {self.executable}: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown ALSA error"
            raise MixerError(detail)
        return result.stdout

    def _scheme(self, card: int) -> dict[str, _ControlSpec]:
        if self._scheme_card != card:
            output = self._run_on(card, "scontrols")
            self._scheme_cache = (
                _WIRELESS_SCHEME if "'Sidetone'" in output else _USB_SCHEME
            )
            self._scheme_card = card
        return self._scheme_cache

    def _argv(self, card: int, name: str) -> list[str]:
        control, direction = self._scheme(card)[name]
        return [control] if direction is None else [control, direction.lower()]

    def get_control(self, name: str) -> MixerValue:
        if name not in {"Sidetone", "Mic"}:
            raise ValueError("unsupported mixer control")
        card = self.find_card()
        control, direction = self._scheme(card)[name]
        return parse_amixer_value(self._run_on(card, "sget", control), direction)

    def snapshot(self) -> MixerSnapshot:
        return MixerSnapshot(
            sidetone=self.get_control("Sidetone"),
            microphone=self.get_control("Mic"),
        )

    def set_sidetone(self, enabled: bool, db: float) -> MixerValue:
        if not math.isfinite(db):
            raise MixerError("sidetone level must be finite")
        level = max(-42.0, min(4.0, float(db)))
        card = self.find_card()
        argv = self._argv(card, "Sidetone")
        self._run_on(card, "sset", *argv, f"{level:.2f}dB")
        self._run_on(card, "sset", *argv, "unmute" if enabled else "mute")
        return self.get_control("Sidetone")

    def set_microphone_gain(self, db: float) -> MixerValue:
        if not math.isfinite(db):
            raise MixerError("microphone gain must be finite")
        level = max(-36.0, min(0.0, float(db)))
        card = self.find_card()
        self._run_on(card, "sset", *self._argv(card, "Mic"), f"{level:.2f}dB")
        return self.get_control("Mic")

    def set_microphone_muted(self, muted: bool) -> MixerValue:
        card = self.find_card()
        self._run_on(
            card, "sset", *self._argv(card, "Mic"), "nocap" if muted else "cap"
        )
        return self.get_control("Mic")
