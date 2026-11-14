"""Spoken announcements played on the headset.

The clips are rendered ahead of time (``tools/render-voice-clips.sh``) and
ship with the package, so no speech synthesiser is needed at runtime. They
are played by ``pw-play`` straight into the headset's own PipeWire sink:
an announcement about the headset belongs on the headset, even while the
desktop's default output is a pair of speakers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Callable

from . import i18n
from .notifications import LowBatteryMonitor
from .state import DeviceState, StateStore


LOG = logging.getLogger(__name__)

CLIP_DIRECTORY = Path(__file__).resolve().parent / "assets" / "voice"

# Language -> clip name -> spoken text. The render script reads this table;
# the files live in assets/voice/<language>/<clip>.wav.
CLIPS: dict[str, dict[str, str]] = {
    "en": {
        "microphone_muted": "Microphone muted",
        "microphone_active": "Microphone activated",
        "charging": "Charging battery",
        "unplugged": "Charging stopped",
        "battery_full": "Battery fully charged",
        "battery_low": "Battery low",
        "battery_critical": "Battery critical",
        "sample": "Voice announcements enabled",
    },
    "de": {
        "microphone_muted": "Mikrofon stumm",
        "microphone_active": "Mikrofon aktiv",
        "charging": "Akku wird geladen",
        "unplugged": "Laden beendet",
        "battery_full": "Akku vollständig geladen",
        "battery_low": "Akku niedrig",
        "battery_critical": "Akku fast leer",
        "sample": "Sprachansagen aktiviert",
    },
}
CLIP_NAMES = frozenset(CLIPS["en"])

_WATCHED = frozenset(
    {
        "battery_percent",
        "charging",
        "microphone_muted",
        "headset_connected",
        "connection_mode",
        "voice_enabled",
        "voice_microphone",
        "voice_charging",
        "voice_battery",
    }
)

# alsa.components of the receiver and of the headset on its own cable.
_SINK_COMPONENTS = {"wireless": "usb1b1c:0a6b", "usb": "usb1b1c:0a69"}


class AnnouncementMonitor:
    """Turn successive device states into the clips worth speaking.

    Only a change seen on a live link is announced. Whatever the headset
    reports while it connects is the baseline, not news: nobody wants to
    hear "Microphone muted" every time the headset is switched on.
    """

    def __init__(self, battery: LowBatteryMonitor | None = None) -> None:
        self._battery = battery or LowBatteryMonitor()
        self._previous: DeviceState | None = None

    def observe(self, state: DeviceState) -> list[str]:
        previous, self._previous = self._previous, state
        if not state.voice_enabled:
            self._battery.reset()
            return []

        clips: list[str] = []
        steady = (
            previous is not None
            and previous.headset_connected
            and state.headset_connected
            and previous.connection_mode == state.connection_mode
        )
        if steady and previous is not None:
            if (
                state.voice_microphone
                and previous.microphone_muted >= 0
                and state.microphone_muted >= 0
                and state.microphone_muted != previous.microphone_muted
            ):
                clips.append(
                    "microphone_muted" if state.microphone_muted else "microphone_active"
                )
            if state.voice_charging:
                if (
                    previous.charging >= 0
                    and state.charging >= 0
                    and state.charging != previous.charging
                ):
                    clips.append("charging" if state.charging == 1 else "unplugged")
                elif (
                    state.charging == 1
                    and state.battery_percent == 100
                    and 0 <= previous.battery_percent < 100
                ):
                    clips.append("battery_full")

        if state.voice_battery:
            charging = state.charging == 1 or state.connection_mode == "usb"
            level = self._battery.evaluate(
                state.battery_percent, charging, state.headset_connected
            )
            if level is not None:
                # Last, so a warning outlasts whatever else just happened.
                clips.append(f"battery_{level}")
        else:
            self._battery.reset()
        return clips


def find_headset_sink(connection_mode: str = "wireless") -> str | None:
    """Name of the headset's physical PipeWire sink, or None without one."""

    wanted = _SINK_COMPONENTS.get(connection_mode, _SINK_COMPONENTS["wireless"])
    try:
        result = subprocess.run(
            ["pw-dump"], capture_output=True, text=True, timeout=5, check=True
        )
        objects = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        LOG.debug("pw-dump failed: %s", exc)
        return None
    if not isinstance(objects, list):
        return None
    for item in objects:
        if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Node":
            continue
        info = item.get("info")
        properties = info.get("props") if isinstance(info, dict) else None
        if not isinstance(properties, dict):
            continue
        if properties.get("media.class") != "Audio/Sink":
            continue
        if wanted in str(properties.get("alsa.components", "")).lower():
            name = properties.get("node.name")
            if isinstance(name, str) and name:
                return name
    return None


class ClipPlayer:
    """Play one clip at a time on a worker thread; the newest request wins."""

    def __init__(
        self,
        directory: Path = CLIP_DIRECTORY,
        sink_finder: Callable[[str], str | None] = find_headset_sink,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        language: Callable[[], str] = i18n.resolve,
    ) -> None:
        self._directory = directory
        # Asked for every clip: the daemon outlives language changes made
        # in the window.
        self._language = language
        self._sink_finder = sink_finder
        self._popen = popen
        self._requests: queue.Queue[tuple[str, int, str] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._closed = False

    def play(self, clip: str, volume: int, connection_mode: str = "wireless") -> None:
        """Queue a clip. Never blocks: this runs on the hardware thread."""

        with self._lock:
            if self._closed:
                return
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="hs80-voice", daemon=True
                )
                self._thread.start()
        self._requests.put((clip, volume, connection_mode))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            self._requests.put(None)
            thread.join(timeout=7)
        self._stop_current()

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            # A flapping microphone arm queues several; only the last counts.
            while request is not None:
                try:
                    request = self._requests.get_nowait()
                except queue.Empty:
                    break
            if request is None:
                return
            try:
                self._start(*request)
            except Exception as exc:  # Sound is a nicety; never take hs80d down.
                LOG.warning("voice announcement failed: %s", exc)

    def _stop_current(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _start(self, clip: str, volume: int, connection_mode: str) -> None:
        language = self._language()
        path = self._directory / (language if language in CLIPS else "en") / f"{clip}.wav"
        if clip not in CLIP_NAMES or not path.is_file():
            raise OSError(f"voice clip is missing: {path}")
        sink = self._sink_finder(connection_mode)
        if sink is None:
            # Without the headset's sink the clip would come out of whatever
            # the default output is. Staying silent is the better failure.
            LOG.debug("no headset sink; skipping announcement %s", clip)
            return
        self._stop_current()
        self._process = self._popen(
            [
                "pw-play",
                "--target",
                sink,
                "--volume",
                f"{max(0, min(100, volume)) / 100:.2f}",
                "--media-role",
                "Notification",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # pw-play parses --volume with the locale's decimal separator.
            env={**os.environ, "LC_ALL": "C"},
        )


class VoiceAnnouncer:
    """Bridge controller state changes to spoken clips."""

    def __init__(
        self,
        state: StateStore,
        monitor: AnnouncementMonitor | None = None,
        player: ClipPlayer | None = None,
    ) -> None:
        self._state = state
        self._monitor = monitor or AnnouncementMonitor()
        self._player = player or ClipPlayer()
        self._lock = threading.Lock()
        self._closed = False
        # The state before the first change is the baseline as well.
        self._monitor.observe(state.snapshot())
        state.add_listener(self._state_changed)

    def _state_changed(self, changed: dict[str, object]) -> None:
        if self._closed or not _WATCHED.intersection(changed):
            return
        # Settings arrive from D-Bus threads, device state from the worker.
        with self._lock:
            snapshot = self._state.snapshot()
            clips = self._monitor.observe(snapshot)
        for clip in clips:
            self._player.play(clip, snapshot.voice_volume, snapshot.connection_mode)

    def play_sample(self) -> bool:
        """Speak a test phrase, e.g. while the user sets the volume."""

        snapshot = self._state.snapshot()
        if self._closed or not snapshot.headset_connected:
            return False
        self._player.play("sample", snapshot.voice_volume, snapshot.connection_mode)
        return True

    def close(self) -> None:
        self._closed = True
        self._player.close()
