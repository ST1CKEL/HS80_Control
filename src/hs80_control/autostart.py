"""Login autostart and per-user application preferences.

Packages install the autostart entry system-wide, so the application starts
in the tray by default. Switching that off must not need root: per the XDG
autostart specification a same-named file in the user's directory with
``Hidden=true`` masks the system entry.

The preferences live in their own file on purpose. ``config.json`` belongs
to the daemon, which keeps it in memory and rewrites it; a second writer
would lose changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from .i18n import LANGUAGES, tr as _


AUTOSTART_FILENAME = "io.github.hs80control.App.desktop"
PROFILE_NAME_LENGTH = 40
PROFILE_LIMIT = 50
_PROFILE_MODES = ("off", "static", "pulse", "rainbow", "cycle")
BACKGROUND_FLAG = "--background"

_ENTRY = """[Desktop Entry]
Type=Application
Name=HS80 Control
Name[de]=HS80-Steuerung
Comment=Keep HS80 Control available in the system tray
Comment[de]=HS80-Steuerung im Infobereich bereithalten
Exec={command} {flag}
Icon=io.github.hs80control.App
Terminal=false
StartupNotify=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _config_dirs() -> list[Path]:
    value = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return [Path(entry) for entry in value.split(":") if entry]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _is_hidden(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return True
    group = ""
    for line in lines:
        line = line.strip()
        if line.startswith("["):
            group = line
        elif group == "[Desktop Entry]":
            key, separator, value = line.partition("=")
            if not separator:
                continue
            if key.strip() == "Hidden" and value.strip().lower() == "true":
                return True
            # GNOME Tweaks switches entries off with its own key.
            if (
                key.strip() == "X-GNOME-Autostart-enabled"
                and value.strip().lower() == "false"
            ):
                return True
    return False


class Autostart:
    def __init__(
        self,
        user_dir: Path | None = None,
        system_dirs: list[Path] | None = None,
        command: str | None = None,
    ) -> None:
        self.user_path = (user_dir or _config_home() / "autostart") / AUTOSTART_FILENAME
        self.system_paths = [
            directory / AUTOSTART_FILENAME
            for directory in (
                system_dirs
                if system_dirs is not None
                else [entry / "autostart" for entry in _config_dirs()]
            )
        ]
        self._command = command

    def _system_entry_active(self) -> bool:
        # The first directory that has the file decides, as in the spec.
        for path in self.system_paths:
            if path.is_file():
                return not _is_hidden(path)
        return False

    def is_enabled(self) -> bool:
        if self.user_path.is_file():
            return not _is_hidden(self.user_path)
        return self._system_entry_active()

    def _entry(self) -> str:
        command = self._command or shutil.which("hs80-control") or "hs80-control"
        return _ENTRY.format(command=command, flag=BACKGROUND_FLAG)

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            _atomic_write(self.user_path, self._entry() + "Hidden=true\n")
        elif self._system_entry_active():
            # Dropping the mask is enough; the packaged entry takes over.
            self.user_path.unlink(missing_ok=True)
        else:
            _atomic_write(self.user_path, self._entry())


def _is_color(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def validate_rgb_profile(profile: object) -> dict[str, object]:
    """Return a clean lighting profile or raise ValueError."""

    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    mode = profile.get("mode")
    brightness = profile.get("brightness")
    speed = profile.get("speed", 3)
    if mode not in _PROFILE_MODES:
        raise ValueError(f"unsupported RGB mode: {mode}")
    for name, value, low, high in (
        ("brightness", brightness, 0, 100),
        ("speed", speed, 1, 5),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"profile {name} must be between {low} and {high}")
    clean: dict[str, object] = {"mode": mode, "brightness": brightness, "speed": speed}
    for zone in ("logo", "indicator", "microphone"):
        if not _is_color(profile.get(zone)):
            raise ValueError(f"profile {zone} must be a #RRGGBB colour")
        clean[zone] = str(profile[zone]).lower()
    return clean


class AppSettings:
    """Preferences of the window itself, not of the headset."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _config_home() / "hs80-control" / "app.json"
        self._tray = True
        self._language: str | None = None
        self._update_check = True
        self._profiles: dict[str, dict[str, object]] = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        if not isinstance(loaded, dict):
            return
        if isinstance(loaded.get("tray"), bool):
            self._tray = loaded["tray"]
        if isinstance(loaded.get("update_check"), bool):
            self._update_check = loaded["update_check"]
        if loaded.get("language") in LANGUAGES:
            self._language = loaded["language"]
        profiles = loaded.get("rgb_profiles")
        if isinstance(profiles, dict):
            for name, profile in profiles.items():
                try:
                    self._profiles[self._clean_name(name)] = validate_rgb_profile(
                        profile
                    )
                except ValueError:
                    continue  # Skip a damaged entry, keep the rest.

    @staticmethod
    def _clean_name(name: object) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(_("Profilname darf nicht leer sein"))
        return name.strip()[:PROFILE_NAME_LENGTH]

    def _save(self) -> None:
        data: dict[str, object] = {
            "tray": self._tray,
            "rgb_profiles": self._profiles,
            "update_check": self._update_check,
        }
        if self._language is not None:
            data["language"] = self._language
        _atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    @property
    def tray(self) -> bool:
        return self._tray

    def set_tray(self, enabled: bool) -> None:
        self._tray = bool(enabled)
        self._save()

    @property
    def update_check(self) -> bool:
        """Whether the window looks for a new release when it starts."""

        return self._update_check

    def set_update_check(self, enabled: bool) -> None:
        self._update_check = bool(enabled)
        self._save()

    @property
    def language(self) -> str | None:
        """The chosen interface language; None until the user has picked."""

        return self._language

    def set_language(self, code: str) -> None:
        if code not in LANGUAGES:
            raise ValueError(f"unsupported language: {code}")
        self._language = code
        self._save()

    @property
    def rgb_profiles(self) -> dict[str, dict[str, object]]:
        return {name: dict(profile) for name, profile in self._profiles.items()}

    def save_rgb_profile(self, name: str, profile: dict[str, object]) -> None:
        clean_name = self._clean_name(name)
        clean = validate_rgb_profile(profile)
        if clean_name not in self._profiles and len(self._profiles) >= PROFILE_LIMIT:
            raise ValueError(
                _("Höchstens {limit} Profile möglich").format(limit=PROFILE_LIMIT)
            )
        self._profiles[clean_name] = clean
        self._save()

    def delete_rgb_profile(self, name: str) -> None:
        if self._profiles.pop(name, None) is not None:
            self._save()
