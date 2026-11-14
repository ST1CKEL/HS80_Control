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


AUTOSTART_FILENAME = "io.github.hs80control.App.desktop"
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


class AppSettings:
    """Preferences of the window itself, not of the headset."""

    DEFAULTS: dict[str, bool] = {"tray": True}

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _config_home() / "hs80-control" / "app.json"
        self._data = dict(self.DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            for key in self.DEFAULTS:
                if isinstance(loaded.get(key), bool):
                    self._data[key] = loaded[key]

    @property
    def tray(self) -> bool:
        return self._data["tray"]

    def set_tray(self, enabled: bool) -> None:
        self._data["tray"] = bool(enabled)
        _atomic_write(
            self.path, json.dumps(self._data, indent=2, sort_keys=True) + "\n"
        )
