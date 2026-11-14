#!/usr/bin/python3
"""Graphical installer for HS80 Control on Fedora (KDE Plasma and GNOME).

The installer is one self-contained file next to its two logos and,
optionally, the RPM. Without a bundled RPM it fetches the newest release
from GitHub. Everything that needs root goes through one ``pkexec`` call, so
the password prompt is the desktop's own, on Plasma as well as on GNOME.

The logic that touches the user's files is kept free of GTK so the test
suite can exercise it without a display.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import urllib.request


APP_ID = "io.github.hs80control.Installer"
PACKAGE = "hs80-control"
DESKTOP_FILE = "io.github.hs80control.App.desktop"
RELEASE_API = "https://api.github.com/repos/ST1CKEL/HS80_Control/releases/latest"
DEVELOPER_NAME = "Stickelbroeck Labs"
DEVELOPER_URL = "https://stickelbroeck.com/"
GNOME_TRAY_PACKAGE = "gnome-shell-extension-appindicator"
GNOME_TRAY_EXTENSION = "appindicatorsupport@rgcjonas.gmail.com"
DRY_RUN_VARIABLE = "HS80_INSTALLER_DRY_RUN"
RPM_VARIABLE = "HS80_INSTALLER_RPM"
HERE = Path(__file__).resolve().parent

LANGUAGES = {"de": "Deutsch", "en": "English"}

TEXT: dict[str, dict[str, str]] = {
    "de": {
        "window": "HS80 Control – Installation",
        "tagline": "Linux-Steuerung für das Corsair HS80 RGB Wireless",
        "developed_by": "Entwickelt von",
        "options_title": "Installation einrichten",
        "desktop": "Erkannte Arbeitsumgebung",
        "desktop_other": "Andere ({name})",
        "source": "Paket",
        "source_bundled": "Beiliegend: {name}",
        "source_download": "Neueste Version wird von GitHub geladen",
        "language": "Sprache der App",
        "autostart": "Beim Anmelden automatisch starten",
        "autostart_hint": "Startet minimiert im Infobereich",
        "tray": "Infobereich für GNOME einrichten",
        "tray_hint": (
            "Installiert die Erweiterung „AppIndicator and KStatusNotifierItem "
            "Support“ – GNOME hat sonst keinen Infobereich"
        ),
        "launch": "HS80 Control nach der Installation starten",
        "install": "Installieren",
        "back": "Zurück",
        "password_note": (
            "Für die Installation wird das Administratorpasswort abgefragt."
        ),
        "progress_title": "HS80 Control wird installiert",
        "details": "Details",
        "step_download": "Paket wird heruntergeladen …",
        "step_install": "Paket wird installiert – bitte Passwort bestätigen …",
        "step_setup": "Einstellungen werden übernommen …",
        "step_service": "Hintergrunddienst wird gestartet …",
        "done_title": "Installation abgeschlossen",
        "done_body": "HS80 Control ist eingerichtet und im Anwendungsmenü zu finden.",
        "done_gnome": (
            "Bitte einmal ab- und wieder anmelden, damit GNOME das Symbol im "
            "Infobereich anzeigt."
        ),
        "failed_title": "Installation fehlgeschlagen",
        "cancelled": "Die Passwortabfrage wurde abgebrochen.",
        "failed_step": "Schritt fehlgeschlagen: {step}",
        "retry": "Erneut versuchen",
        "close": "Schließen",
        "finish": "Fertig",
        "not_fedora": (
            "Dieser Installer ist für Fedora gebaut. Auf diesem System fehlt "
            "dnf – die Installation kann nicht fortgesetzt werden."
        ),
        "no_package": "Im neuesten Release wurde kein RPM-Paket gefunden.",
    },
    "en": {
        "window": "HS80 Control – Installation",
        "tagline": "Linux control for the Corsair HS80 RGB Wireless",
        "developed_by": "Developed by",
        "options_title": "Set up the installation",
        "desktop": "Detected desktop",
        "desktop_other": "Other ({name})",
        "source": "Package",
        "source_bundled": "Bundled: {name}",
        "source_download": "The latest version is downloaded from GitHub",
        "language": "App language",
        "autostart": "Start automatically at login",
        "autostart_hint": "Starts minimised in the system tray",
        "tray": "Set up a system tray for GNOME",
        "tray_hint": (
            "Installs the extension “AppIndicator and KStatusNotifierItem "
            "Support” – GNOME has no system tray otherwise"
        ),
        "launch": "Start HS80 Control after the installation",
        "install": "Install",
        "back": "Back",
        "password_note": "The installation asks for the administrator password.",
        "progress_title": "Installing HS80 Control",
        "details": "Details",
        "step_download": "Downloading the package …",
        "step_install": "Installing the package – please confirm your password …",
        "step_setup": "Applying your settings …",
        "step_service": "Starting the background service …",
        "done_title": "Installation complete",
        "done_body": "HS80 Control is set up and listed in the application menu.",
        "done_gnome": (
            "Please log out and back in once so GNOME shows the icon in the "
            "system tray."
        ),
        "failed_title": "Installation failed",
        "cancelled": "The password prompt was cancelled.",
        "failed_step": "Step failed: {step}",
        "retry": "Try again",
        "close": "Close",
        "finish": "Finish",
        "not_fedora": (
            "This installer is built for Fedora. This system has no dnf – the "
            "installation cannot continue."
        ),
        "no_package": "The latest release contains no RPM package.",
    },
}


# --- logic without GTK --------------------------------------------------


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def system_language() -> str:
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(variable, "")
        if value and value not in ("C", "POSIX"):
            return "de" if value.lower().startswith("de") else "en"
    return "en"


def detect_desktop(value: str | None = None) -> str:
    """Return ``kde``, ``gnome`` or the lowercase name of anything else."""

    if value is None:
        value = os.environ.get("XDG_CURRENT_DESKTOP", "")
    names = [name.strip().lower() for name in value.split(":") if name.strip()]
    if "kde" in names:
        return "kde"
    if "gnome" in names:
        return "gnome"
    return names[0] if names else "unknown"


def desktop_label(desktop: str, language: str) -> str:
    if desktop == "kde":
        return "KDE Plasma"
    if desktop == "gnome":
        return "GNOME"
    return TEXT[language]["desktop_other"].format(name=desktop)


def find_bundled_rpm(directory: Path | None = None) -> Path | None:
    override = os.environ.get(RPM_VARIABLE, "")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    candidates = sorted((directory or HERE).glob(f"{PACKAGE}-*.noarch.rpm"))
    return candidates[-1] if candidates else None


def pick_release_asset(release: object) -> tuple[str, str] | None:
    """(name, download URL) of the RPM in a GitHub release description."""

    if not isinstance(release, dict):
        return None
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if (
            name.startswith(f"{PACKAGE}-")
            and name.endswith(".noarch.rpm")
            and url.startswith("https://github.com/")
        ):
            return name, url
    return None


def download_latest_rpm(target_dir: Path) -> Path:
    def fetch(url: str) -> bytes:
        request = urllib.request.Request(
            url, headers={"User-Agent": "hs80-control-installer"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()

    asset = pick_release_asset(json.loads(fetch(RELEASE_API)))
    if asset is None:
        raise LookupError("no RPM asset in the latest release")
    name, url = asset
    path = target_dir / Path(name).name
    path.write_bytes(fetch(url))
    return path


def install_command(rpm: Path, extra_packages: list[str]) -> list[str]:
    """One privileged call: install, then let udev re-tag a plugged receiver."""

    script = (
        'dnf install -y "$@" || exit $?; '
        "udevadm control --reload-rules; "
        "udevadm trigger --subsystem-match=hidraw --subsystem-match=usb "
        "--action=change; exit 0"
    )
    command = ["/bin/sh", "-c", script, "hs80-install", str(rpm), *extra_packages]
    if os.environ.get(DRY_RUN_VARIABLE):
        return ["/bin/echo", "[dry run] pkexec", *command]
    return ["pkexec", *command]


def write_language(language: str, path: Path | None = None) -> None:
    """Store the choice where the app reads it, keeping what is there."""

    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    path = path or config_home() / "hs80-control" / "app.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["language"] = language
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def set_autostart(
    enabled: bool,
    user_dir: Path | None = None,
    system_entry: Path | None = None,
) -> None:
    """Mirror the app's own switch: a user-level ``Hidden=true`` masks the
    packaged autostart entry, and removing that mask re-enables it."""

    user_path = (user_dir or config_home() / "autostart") / DESKTOP_FILE
    system_entry = system_entry or Path("/etc/xdg/autostart") / DESKTOP_FILE
    if enabled:
        if system_entry.is_file():
            user_path.unlink(missing_ok=True)
        return
    try:
        lines = system_entry.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = ["[Desktop Entry]", "Type=Application", "Name=HS80 Control"]
    lines = [line for line in lines if not line.startswith("Hidden=")]
    _atomic_write(user_path, "\n".join(lines) + "\nHidden=true\n")


def service_commands() -> list[list[str]]:
    return [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "hs80d.service"],
        ["systemctl", "--user", "restart", "hs80d.service"],
    ]


def _asset(bundled: str, in_repository: str) -> Path:
    """A logo next to the installer (bundle) or in the source tree."""

    path = HERE / bundled
    return path if path.is_file() else HERE.parent / in_repository


# --- window -------------------------------------------------------------


def run_gui(argv: list[str]) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk

    hs80_logo = _asset("hs80-control.svg", "data/icons/io.github.hs80control.App.svg")
    developer_logo = _asset(
        "stickelbroeck-labs.png", "src/hs80_control/assets/stickelbroeck-labs.png"
    )

    class Installer(Adw.ApplicationWindow):
        def __init__(self, application: Adw.Application) -> None:
            super().__init__(application=application)
            self.set_default_size(620, 640)
            self.set_size_request(420, 520)
            self.language = system_language()
            self.desktop = detect_desktop()
            self.rpm = find_bundled_rpm()
            self.autostart = True
            self.tray = self.desktop == "gnome"
            self.launch = True
            self.temporary: tempfile.TemporaryDirectory[str] | None = None
            self.busy = False
            self.connect("close-request", lambda *_: self.busy)

            toolbar = Adw.ToolbarView()
            self.title_widget = Adw.WindowTitle(title="HS80 Control")
            toolbar.add_top_bar(Adw.HeaderBar(title_widget=self.title_widget))

            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            brand.set_margin_top(12)
            brand.set_margin_bottom(12)
            if hs80_logo.is_file():
                picture = Gtk.Image.new_from_file(str(hs80_logo))
                picture.set_pixel_size(88)
                picture.set_halign(Gtk.Align.CENTER)
                picture.set_tooltip_text("HS80 Control")
                brand.append(picture)
            name = Gtk.Label(label="HS80 Control")
            name.add_css_class("title-1")
            brand.append(name)
            self.tagline = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
            self.tagline.add_css_class("dim-label")
            brand.append(self.tagline)
            body.append(brand)

            self.stack = Gtk.Stack(
                transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                vexpand=True,
            )
            body.append(self.stack)

            footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            footer.set_halign(Gtk.Align.CENTER)
            footer.set_margin_top(10)
            footer.set_margin_bottom(10)
            if developer_logo.is_file():
                logo = Gtk.Image.new_from_file(str(developer_logo))
                logo.set_pixel_size(44)
                logo.set_tooltip_text(DEVELOPER_NAME)
                footer.append(logo)
            credit = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            credit.set_valign(Gtk.Align.CENTER)
            self.credit_caption = Gtk.Label(xalign=0)
            self.credit_caption.add_css_class("caption")
            self.credit_caption.add_css_class("dim-label")
            credit.append(self.credit_caption)
            link = Gtk.LinkButton(uri=DEVELOPER_URL, label=DEVELOPER_NAME)
            link.set_halign(Gtk.Align.START)
            link.add_css_class("flat")
            link.set_tooltip_text(DEVELOPER_URL)
            credit.append(link)
            footer.append(credit)
            body.append(Gtk.Separator())
            body.append(footer)

            toolbar.set_content(body)
            self.set_content(toolbar)

            self.stack.add_named(self._language_page(), "language")
            self._retranslate()
            if shutil.which("dnf") is None and not os.environ.get(DRY_RUN_VARIABLE):
                self._show_result(False, self.t("not_fedora"), retry=False)

        def t(self, key: str) -> str:
            return TEXT[self.language][key]

        def _retranslate(self) -> None:
            self.set_title(self.t("window"))
            self.title_widget.set_title(self.t("window"))
            self.tagline.set_label(self.t("tagline"))
            self.credit_caption.set_label(self.t("developed_by"))

        def _replace_page(self, name: str, page: Gtk.Widget) -> None:
            old = self.stack.get_child_by_name(name)
            if old is not None:
                self.stack.remove(old)
            self.stack.add_named(page, name)
            self.stack.set_visible_child_name(name)

        @staticmethod
        def _clamped(child: Gtk.Widget) -> Gtk.Widget:
            clamp = Adw.Clamp(child=child, maximum_size=480)
            clamp.set_margin_start(18)
            clamp.set_margin_end(18)
            return Gtk.ScrolledWindow(
                hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp
            )

        # -- page 1: language ---------------------------------------------

        def _language_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_valign(Gtk.Align.CENTER)
            heading = Gtk.Label(label="Sprache wählen · Choose language")
            heading.add_css_class("title-3")
            box.append(heading)
            note = Gtk.Label(
                label=(
                    "Gilt für den Installer und die App.\n"
                    "Applies to the installer and the app."
                ),
                justify=Gtk.Justification.CENTER,
            )
            note.add_css_class("dim-label")
            note.set_margin_bottom(6)
            box.append(note)
            for code, label in LANGUAGES.items():
                button = Gtk.Button(label=label)
                button.add_css_class("pill")
                if code == self.language:
                    button.add_css_class("suggested-action")
                button.set_halign(Gtk.Align.CENTER)
                button.set_size_request(220, -1)
                button.connect("clicked", self._language_chosen, code)
                box.append(button)
            return self._clamped(box)

        def _language_chosen(self, _button: Gtk.Button, code: str) -> None:
            self.language = code
            self._retranslate()
            self._replace_page("options", self._options_page())

        # -- page 2: options ----------------------------------------------

        def _options_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            box.set_margin_top(6)
            box.set_margin_bottom(12)
            heading = Gtk.Label(label=self.t("options_title"), xalign=0)
            heading.add_css_class("title-3")
            box.append(heading)

            facts = Adw.PreferencesGroup()
            facts.add(
                Adw.ActionRow(
                    title=self.t("desktop"),
                    subtitle=desktop_label(self.desktop, self.language),
                )
            )
            facts.add(
                Adw.ActionRow(
                    title=self.t("source"),
                    subtitle=(
                        self.t("source_bundled").format(name=self.rpm.name)
                        if self.rpm is not None
                        else self.t("source_download")
                    ),
                )
            )
            facts.add(
                Adw.ActionRow(
                    title=self.t("language"), subtitle=LANGUAGES[self.language]
                )
            )
            box.append(facts)

            choices = Adw.PreferencesGroup()
            autostart = Adw.SwitchRow(
                title=self.t("autostart"), subtitle=self.t("autostart_hint")
            )
            autostart.set_active(self.autostart)
            autostart.connect(
                "notify::active",
                lambda row, _p: setattr(self, "autostart", row.get_active()),
            )
            choices.add(autostart)
            if self.desktop == "gnome":
                tray = Adw.SwitchRow(title=self.t("tray"), subtitle=self.t("tray_hint"))
                tray.set_active(self.tray)
                tray.connect(
                    "notify::active",
                    lambda row, _p: setattr(self, "tray", row.get_active()),
                )
                choices.add(tray)
            launch = Adw.SwitchRow(title=self.t("launch"))
            launch.set_active(self.launch)
            launch.connect(
                "notify::active",
                lambda row, _p: setattr(self, "launch", row.get_active()),
            )
            choices.add(launch)
            box.append(choices)

            note = Gtk.Label(label=self.t("password_note"), wrap=True, xalign=0)
            note.add_css_class("caption")
            note.add_css_class("dim-label")
            box.append(note)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            buttons.set_halign(Gtk.Align.END)
            back = Gtk.Button(label=self.t("back"))
            back.connect(
                "clicked", lambda *_: self.stack.set_visible_child_name("language")
            )
            buttons.append(back)
            install = Gtk.Button(label=self.t("install"))
            install.add_css_class("suggested-action")
            install.connect("clicked", lambda *_: self._start())
            buttons.append(install)
            box.append(buttons)
            return self._clamped(box)

        # -- page 3: progress ---------------------------------------------

        def _progress_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_margin_top(6)
            box.set_margin_bottom(12)
            heading = Gtk.Label(label=self.t("progress_title"), xalign=0)
            heading.add_css_class("title-3")
            box.append(heading)
            self.step_label = Gtk.Label(xalign=0, wrap=True)
            box.append(self.step_label)
            self.progress = Gtk.ProgressBar()
            box.append(self.progress)
            self.log = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
            self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.log.set_top_margin(8)
            self.log.set_left_margin(8)
            scrolled = Gtk.ScrolledWindow(child=self.log, min_content_height=170)
            scrolled.add_css_class("card")
            expander = Gtk.Expander(label=self.t("details"), child=scrolled)
            box.append(expander)
            return self._clamped(box)

        def _log(self, text: str) -> None:
            buffer = self.log.get_buffer()
            buffer.insert(buffer.get_end_iter(), text.rstrip("\n") + "\n")
            self.log.scroll_to_mark(buffer.get_insert(), 0.0, False, 0.0, 1.0)

        def _start(self) -> None:
            self.busy = True
            self._replace_page("progress", self._progress_page())
            steps: list[tuple[str, object]] = []
            if self.rpm is None:
                steps.append(("step_download", self._step_download))
            steps.append(("step_install", self._step_install))
            steps.append(("step_setup", self._step_setup))
            steps.append(("step_service", self._step_service))
            self._steps = steps
            self._total = len(steps)
            self._pulse = GLib.timeout_add(120, self._pulse_tick)
            self._next_step()

        def _pulse_tick(self) -> bool:
            if not self.busy:
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        def _next_step(self) -> None:
            if not self._steps:
                self._show_result(True, "")
                return
            key, action = self._steps.pop(0)
            self._current = key
            self.step_label.set_label(self.t(key))
            self.progress.set_fraction((self._total - len(self._steps) - 1) / self._total)
            action()  # type: ignore[operator]

        def _step_done(self, success: bool, detail: str = "") -> None:
            if success:
                self._next_step()
                return
            self._show_result(
                False,
                detail or self.t("failed_step").format(step=self.t(self._current)),
            )

        def _run(self, argv: list[str], done: object, fatal: bool = True) -> None:
            self._log("$ " + " ".join(argv))
            try:
                process = Gio.Subprocess.new(
                    argv,
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE,
                )
            except GLib.Error as exc:
                self._log(exc.message)
                done(not fatal, -1)  # type: ignore[operator]
                return
            stream = Gio.DataInputStream.new(process.get_stdout_pipe())

            def read(source: Gio.DataInputStream, result: Gio.AsyncResult) -> None:
                try:
                    line, _length = source.read_line_finish_utf8(result)
                except GLib.Error:
                    line = None
                if line is None:
                    process.wait_async(None, finished)
                    return
                self._log(line)
                source.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

            def finished(proc: Gio.Subprocess, result: Gio.AsyncResult) -> None:
                try:
                    proc.wait_finish(result)
                    status = proc.get_exit_status() if proc.get_if_exited() else -1
                except GLib.Error as exc:
                    self._log(exc.message)
                    status = -1
                done(status == 0 or not fatal, status)  # type: ignore[operator]

            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

        def _step_download(self) -> None:
            self.temporary = tempfile.TemporaryDirectory(prefix="hs80-installer-")
            target = Path(self.temporary.name)
            self._log(RELEASE_API)

            def work() -> None:
                try:
                    path = download_latest_rpm(target)
                except LookupError:
                    GLib.idle_add(self._step_done, False, self.t("no_package"))
                except Exception as exc:  # network errors come in many shapes
                    GLib.idle_add(self._log, str(exc))
                    GLib.idle_add(self._step_done, False, "")
                else:
                    self.rpm = path
                    GLib.idle_add(self._log, path.name)
                    GLib.idle_add(self._step_done, True, "")

            threading.Thread(target=work, daemon=True).start()

        def _step_install(self) -> None:
            extra = [GNOME_TRAY_PACKAGE] if self.desktop == "gnome" and self.tray else []
            assert self.rpm is not None

            def done(success: bool, status: int) -> None:
                # pkexec: 126 = dismissed, 127 = not authorised.
                if status in (126, 127):
                    self._step_done(False, self.t("cancelled"))
                else:
                    self._step_done(success)

            self._run(install_command(self.rpm, extra), done)

        def _step_setup(self) -> None:
            try:
                write_language(self.language)
                set_autostart(self.autostart)
            except OSError as exc:
                self._log(str(exc))
                self._step_done(False)
                return
            if self.desktop == "gnome" and self.tray and shutil.which("gnome-extensions"):
                # Fails until the next login, when the shell first sees the
                # freshly installed extension; that is expected.
                self._run(
                    ["gnome-extensions", "enable", GNOME_TRAY_EXTENSION],
                    lambda *_: self._step_done(True),
                    fatal=False,
                )
            else:
                self._step_done(True)

        def _step_service(self) -> None:
            commands = service_commands()
            if os.environ.get(DRY_RUN_VARIABLE):
                commands = [["/bin/echo", "[dry run]", *command] for command in commands]

            def advance(success: bool = True, _status: int = 0) -> None:
                if not commands:
                    self._step_done(True)
                    return
                # A session without the user manager must not fail the
                # installation; the service is D-Bus activated anyway.
                self._run(commands.pop(0), advance, fatal=False)

            advance()

        # -- page 4: result -----------------------------------------------

        def _show_result(self, success: bool, detail: str, retry: bool = True) -> None:
            self.busy = False
            if success:
                description = self.t("done_body")
                if self.desktop == "gnome" and self.tray:
                    description += "\n\n" + self.t("done_gnome")
                page = Adw.StatusPage(
                    icon_name="emblem-ok-symbolic",
                    title=self.t("done_title"),
                    description=description,
                )
                button = Gtk.Button(label=self.t("finish"))
                button.add_css_class("suggested-action")
                button.connect("clicked", lambda *_: self._finish())
            else:
                page = Adw.StatusPage(
                    icon_name="dialog-error-symbolic",
                    title=self.t("failed_title"),
                    description=detail,
                )
                button = Gtk.Button(label=self.t("retry") if retry else self.t("close"))
                button.connect(
                    "clicked",
                    (lambda *_: self.stack.set_visible_child_name("options"))
                    if retry
                    else (lambda *_: self.close()),
                )
            page.add_css_class("compact")
            button.add_css_class("pill")
            button.set_halign(Gtk.Align.CENTER)
            page.set_child(button)
            self._replace_page("result", page)

        def _finish(self) -> None:
            if self.launch and not os.environ.get(DRY_RUN_VARIABLE):
                try:
                    Gio.Subprocess.new(["hs80-control"], Gio.SubprocessFlags.NONE)
                except GLib.Error:
                    pass
            self.close()

    application = Adw.Application(
        application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
    )
    application.connect("activate", lambda app: Installer(app).present())
    return application.run(argv)


if __name__ == "__main__":
    sys.exit(run_gui(sys.argv))
