"""Validated, atomic per-user configuration storage."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from .protocol import ProtocolError, parse_color


RGB_MODES = frozenset({"off", "static", "pulse", "rainbow"})

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "rgb": {
        "mode": "static",
        "brightness": 100,
        "logo": "#00bfff",
        "indicator": "#00bfff",
        "microphone": "#00ffff",
        "mute_indicator": True,
        "apply_on_connect": False,
    },
    "sleep": {"minutes": 15, "apply_on_connect": False},
    "spatial": {
        "enabled": False,
        "sofa_file": "",
        "make_default": True,
        "previous_default": "",
    },
}


def default_config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "hs80-control" / "config.json"


def _merge(default: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(default)
    for key, value in loaded.items():
        if key not in result:
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_config(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProtocolError("configuration root must be an object")
    normalized = _merge(DEFAULT_CONFIG, data)
    if not isinstance(normalized.get("rgb"), dict):
        raise ProtocolError("rgb configuration must be an object")
    if not isinstance(normalized.get("sleep"), dict):
        raise ProtocolError("sleep configuration must be an object")
    if not isinstance(normalized.get("spatial"), dict):
        raise ProtocolError("spatial configuration must be an object")

    rgb = normalized["rgb"]
    if not isinstance(rgb.get("mode"), str) or rgb["mode"] not in RGB_MODES:
        raise ProtocolError(f"unsupported RGB mode: {rgb['mode']}")
    if isinstance(rgb.get("brightness"), bool) or not isinstance(rgb.get("brightness"), int):
        raise ProtocolError("RGB brightness must be an integer")
    brightness = rgb["brightness"]
    if not 0 <= brightness <= 100:
        raise ProtocolError("RGB brightness must be between 0 and 100")
    rgb["brightness"] = brightness
    for key in ("logo", "indicator", "microphone"):
        if not isinstance(rgb.get(key), str):
            raise ProtocolError(f"RGB {key} must be a string")
        parse_color(rgb[key])
        rgb[key] = rgb[key].lower()
    for key in ("mute_indicator", "apply_on_connect"):
        if not isinstance(rgb.get(key), bool):
            raise ProtocolError(f"RGB {key} must be a boolean")

    if isinstance(normalized["sleep"].get("minutes"), bool) or not isinstance(
        normalized["sleep"].get("minutes"), int
    ):
        raise ProtocolError("sleep timer must be an integer")
    minutes = normalized["sleep"]["minutes"]
    if not 0 <= minutes <= 90:
        raise ProtocolError("sleep timer must be between 0 and 90 minutes")
    normalized["sleep"]["minutes"] = minutes
    if not isinstance(normalized["sleep"].get("apply_on_connect"), bool):
        raise ProtocolError("sleep apply_on_connect must be a boolean")
    for key in ("enabled", "make_default"):
        if not isinstance(normalized["spatial"].get(key), bool):
            raise ProtocolError(f"spatial {key} must be a boolean")
    for key in ("sofa_file", "previous_default"):
        if not isinstance(normalized["spatial"].get(key), str):
            raise ProtocolError(f"spatial {key} must be a string")
    normalized["version"] = 1
    return normalized


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ProtocolError("configuration root must be an object")
            return validate_config(loaded)
        except FileNotFoundError:
            return deepcopy(DEFAULT_CONFIG)
        except (json.JSONDecodeError, OSError, ProtocolError, TypeError, ValueError, OverflowError):
            # Preserve a bad file for diagnosis instead of silently replacing it.
            return deepcopy(DEFAULT_CONFIG)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def replace(self, data: dict[str, Any]) -> None:
        validated = validate_config(data)
        with self._lock:
            self._save_locked(validated)
            self._data = validated

    def update_rgb(
        self,
        mode: str,
        brightness: int,
        logo: str,
        indicator: str,
        microphone: str,
        apply_on_connect: bool = True,
    ) -> dict[str, Any]:
        return self.patch_rgb(
            mode=mode,
            brightness=brightness,
            logo=logo,
            indicator=indicator,
            microphone=microphone,
            apply_on_connect=apply_on_connect,
        )

    def patch_rgb(
        self,
        *,
        mode: str | None = None,
        brightness: int | None = None,
        logo: str | None = None,
        indicator: str | None = None,
        microphone: str | None = None,
        apply_on_connect: bool = True,
    ) -> dict[str, Any]:
        """Atomically merge an RGB update with the daemon's current profile."""

        with self._lock:
            candidate = deepcopy(self._data)
            updates: dict[str, Any] = {"apply_on_connect": apply_on_connect}
            for key, value in (
                ("mode", mode),
                ("brightness", brightness),
                ("logo", logo),
                ("indicator", indicator),
                ("microphone", microphone),
            ):
                if value is not None:
                    updates[key] = value
            candidate["rgb"].update(updates)
            validated = validate_config(candidate)
            self._save_locked(validated)
            self._data = validated
            return deepcopy(self._data["rgb"])

    def update_sleep(self, minutes: int, apply_on_connect: bool = True) -> None:
        with self._lock:
            candidate = deepcopy(self._data)
            candidate["sleep"] = {
                "minutes": minutes,
                "apply_on_connect": apply_on_connect,
            }
            validated = validate_config(candidate)
            self._save_locked(validated)
            self._data = validated

    def update_spatial(
        self,
        *,
        enabled: bool | None = None,
        sofa_file: str | None = None,
        make_default: bool | None = None,
        previous_default: str | None = None,
    ) -> None:
        with self._lock:
            candidate = deepcopy(self._data)
            if enabled is not None:
                candidate["spatial"]["enabled"] = enabled
            if sofa_file is not None:
                candidate["spatial"]["sofa_file"] = sofa_file
            if make_default is not None:
                candidate["spatial"]["make_default"] = make_default
            if previous_default is not None:
                candidate["spatial"]["previous_default"] = previous_default
            validated = validate_config(candidate)
            self._save_locked(validated)
            self._data = validated

    def _save_locked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
