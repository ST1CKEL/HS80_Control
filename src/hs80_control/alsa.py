"""ALSA mixer access for controls exposed by the USB Audio Class device."""

from __future__ import annotations

from dataclasses import dataclass
import os
import math
from pathlib import Path
import re
import subprocess

from .protocol import RECEIVER_PRODUCT_ID, VENDOR_ID


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


def parse_amixer_value(output: str) -> MixerValue:
    match = _VALUE_PATTERN.search(output)
    if match is None:
        raise MixerError("could not parse amixer output")
    return MixerValue(
        raw=int(match.group("raw")),
        percent=int(match.group("percent")),
        db=float(match.group("db")),
        enabled=match.group("switch") == "on",
    )


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
        expected = f"{VENDOR_ID:04x}:{RECEIVER_PRODUCT_ID:04x}"
        matches: list[int] = []
        for card in sorted(self.proc_root.glob("card[0-9]*")):
            try:
                usb_id = (card / "usbid").read_text(encoding="ascii").strip().lower()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if usb_id == expected:
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
        card = self.find_card()
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

    def get_control(self, name: str) -> MixerValue:
        if name not in {"Sidetone", "Mic"}:
            raise ValueError("unsupported mixer control")
        return parse_amixer_value(self._run("sget", name))

    def snapshot(self) -> MixerSnapshot:
        return MixerSnapshot(
            sidetone=self.get_control("Sidetone"),
            microphone=self.get_control("Mic"),
        )

    def set_sidetone(self, enabled: bool, db: float) -> MixerValue:
        if not math.isfinite(db):
            raise MixerError("sidetone level must be finite")
        level = max(-42.0, min(4.0, float(db)))
        self._run("sset", "Sidetone", f"{level:.2f}dB")
        self._run("sset", "Sidetone", "unmute" if enabled else "mute")
        return self.get_control("Sidetone")

    def set_microphone_gain(self, db: float) -> MixerValue:
        if not math.isfinite(db):
            raise MixerError("microphone gain must be finite")
        level = max(-36.0, min(0.0, float(db)))
        self._run("sset", "Mic", f"{level:.2f}dB")
        return self.get_control("Mic")

    def set_microphone_muted(self, muted: bool) -> MixerValue:
        self._run("sset", "Mic", "nocap" if muted else "cap")
        return self.get_control("Mic")
