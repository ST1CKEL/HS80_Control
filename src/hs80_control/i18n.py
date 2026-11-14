"""Interface language: German source strings with an English catalogue.

The German text in the code is the message key. That keeps every call site
readable and makes a missing translation fall back to German instead of
failing. The choice is stored in the application preferences (``app.json``)
so the window, the tray, ``hs80ctl`` and the daemon's notifications agree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


LANGUAGES: dict[str, str] = {"de": "Deutsch", "en": "English"}
DEFAULT_LANGUAGE = "de"
# Overrides the stored choice, e.g. for scripts and the test suite.
ENVIRONMENT_VARIABLE = "HS80_CONTROL_LANGUAGE"

_current = DEFAULT_LANGUAGE


def settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "hs80-control" / "app.json"


def system_language() -> str:
    """German for a German desktop session, English for everyone else."""

    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(variable, "")
        if value and value not in ("C", "POSIX"):
            return "de" if value.lower().startswith("de") else "en"
    return "en"


def stored_language(path: Path | None = None) -> str | None:
    """The language the user picked, or None before the first choice."""

    try:
        loaded = json.loads((path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = loaded.get("language") if isinstance(loaded, dict) else None
    return value if value in LANGUAGES else None


def resolve(path: Path | None = None) -> str:
    override = os.environ.get(ENVIRONMENT_VARIABLE, "")
    if override in LANGUAGES:
        return override
    return stored_language(path) or system_language()


def language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language: {code}")
    _current = code


def init(path: Path | None = None) -> str:
    """Load the effective language. Cheap enough to call before each use."""

    set_language(resolve(path))
    return _current


def tr(text: str) -> str:
    if _current == "de":
        return text
    return _ENGLISH.get(text, text)


_ENGLISH: dict[str, str] = {
    # --- language choice -------------------------------------------------
    "Sprache": "Language",
    "Sprache der Oberfläche": "Interface language",
    "Gilt für Fenster, Infobereich, Benachrichtigungen und hs80ctl":
        "Applies to the window, tray, notifications and hs80ctl",
    # --- lighting --------------------------------------------------------
    "Aus": "Off",
    "Statisch": "Static",
    "Pulsieren": "Pulse",
    "Regenbogen": "Rainbow",
    "Farbwechsel": "Colour cycle",
    "Unverändert": "Unchanged",
    "Dimmen": "Dim",
    "Ausschalten": "Switch off",
    # --- connection and status -------------------------------------------
    "●  Verbunden · USB-Kabel": "●  Connected · USB cable",
    "●  Verbunden": "●  Connected",
    "●  Headset am Ladekabel · kein Ton": "●  Headset on charging cable · no sound",
    "●  Headset am Ladekabel · Receiver fehlt":
        "●  Headset on charging cable · receiver missing",
    "●  Receiver bereit · Headset offline": "●  Receiver ready · headset offline",
    "Noch kein Akkureport": "No battery report yet",
    "{percent} Prozent": "{percent} percent",
    " · letzter Stand": " · last known",
    " · lädt": " · charging",
    " · niedrig, bitte laden": " · low, please charge",
    "Desktop-Benachrichtigung ab {low} %, dringlich ab {critical} %":
        "Desktop notification from {low} %, urgent from {critical} %",
    "Schließen minimiert das Fenster, statt das Programm zu beenden":
        "Closing minimises the window instead of quitting",
    "Kein Infobereich gefunden – unter GNOME die Erweiterung "
    "„AppIndicator and KStatusNotifierItem Support“ installieren "
    "und aktivieren":
        "No system tray found – on GNOME, install and enable the extension "
        "“AppIndicator and KStatusNotifierItem Support”",
    "Kein Infobereich gefunden – Schließen beendet das Programm":
        "No system tray found – closing quits the application",
    "Stummgeschaltet": "Muted",
    "Arm hochgeklappt": "Boom flipped up",
    "Aktiv": "Active",
    "Arm heruntergeklappt": "Boom flipped down",
    "Unbekannt": "Unknown",
    "Noch kein Hardwarestatus": "No hardware status yet",
    "Mikrofon ist hochgeklappt (stumm) – "
    "Beleuchtung erscheint erst nach dem Runterklappen":
        "Microphone is flipped up (muted) – "
        "lighting only shows after flipping it down",
    # --- header and menu -------------------------------------------------
    "Status aktualisieren": "Refresh status",
    "Funkverbindung neu aufbauen und Headset suchen":
        "Rebuild the wireless link and search for the headset",
    "Über HS80 Control": "About HS80 Control",
    "Beenden": "Quit",
    "Hauptmenü": "Main menu",
    # --- about -----------------------------------------------------------
    "Linux-Steuerung für das hardwaregetestete Corsair HS80 RGB "
    "Wireless mit Receiver 1b1c:0a6b und Headset-PID 0a69.":
        "Linux control for the hardware-tested Corsair HS80 RGB "
        "Wireless with receiver 1b1c:0a6b and headset PID 0a69.",
    "Entwickelt von": "Developed by",
    "Logo von {name}": "{name} logo",
    "Projekt": "Project",
    "Quellcode": "Source code",
    "Fehler melden": "Report an issue",
    "Lizenz": "Licence",
    "GNU General Public License 3.0 oder neuer":
        "GNU General Public License 3.0 or later",
    "Dieses Programm wird ohne jegliche Gewährleistung bereitgestellt.":
        "This program comes with absolutely no warranty.",
    # --- overview --------------------------------------------------------
    "Dienst wird verbunden ...": "Connecting to the service ...",
    "AKKU": "BATTERY",
    "LÄDT": "CHARGING",
    "LETZTER STAND": "LAST KNOWN",
    "Gerätestatus": "Device status",
    "Akku": "Battery",
    "Mikrofonarm": "Microphone boom",
    "Headset-Firmware": "Headset firmware",
    "Benachrichtigungen": "Notifications",
    "Warnung bei niedrigem Akkustand": "Low-battery warning",
    "Programmstart": "Startup",
    "Im Infobereich der Taskleiste weiterlaufen": "Keep running in the system tray",
    "Beim Anmelden automatisch starten": "Start automatically at login",
    "Startet minimiert im Infobereich": "Starts minimised in the system tray",
    "Schnellaktionen": "Quick actions",
    "Beleuchtung ausschalten": "Switch lighting off",
    "Reduziert den Akkuverbrauch des Headsets": "Reduces the headset's battery drain",
    "RGB ausschalten": "Switch RGB off",
    "Übersicht": "Overview",
    # --- lighting page ---------------------------------------------------
    "Profile": "Profiles",
    "Gespeicherte Kombinationen aus Modus, Helligkeit, Tempo und Farben.":
        "Saved combinations of mode, brightness, tempo and colours.",
    "Profil laden": "Load profile",
    "Ausgewähltes Profil löschen": "Delete the selected profile",
    "Aktuelle Beleuchtung als Profil speichern": "Save the current lighting as a profile",
    "Speichern …": "Save …",
    "Beleuchtung": "Lighting",
    "Änderungen wirken sofort. Die Effekte erzeugt der Daemon; "
    "statische Farben sparen Akku.":
        "Changes apply immediately. The daemon generates the effects; "
        "static colours save battery.",
    "Modus": "Mode",
    "Helligkeit": "Brightness",
    "Für Pulsieren, Regenbogen und Farbwechsel": "For pulse, rainbow and colour cycle",
    "langsam": "slow",
    "schnell": "fast",
    "Statusanzeige": "Status indicator",
    "Mikrofon-LED": "Microphone LED",
    "Stummanzeige": "Mute indicator",
    "Zeigt an der Mikrofon-LED, dass das Mikrofon stumm ist.":
        "Shows on the microphone LED that the microphone is muted.",
    "Mikrofon-LED bei Stummschaltung umfärben": "Recolour the microphone LED while muted",
    "Farbe bei Stummschaltung": "Colour while muted",
    "Energie": "Power",
    "Beleuchtung bei niedrigem Akkustand": "Lighting at low battery",
    "Ab {percent} %, nicht während des Ladens": "From {percent} %, not while charging",
    "Automatisch ausschalten": "Power off automatically",
    "0 deaktiviert den Timer; maximal 90 Minuten":
        "0 disables the timer; 90 minutes at most",
    "{title} auswählen": "Choose {title}",
    # --- microphone page -------------------------------------------------
    "Hardware-Sidetone": "Hardware sidetone",
    "Direktes Mikrofon-Monitoring ohne PipeWire-Latenz.":
        "Direct microphone monitoring without PipeWire latency.",
    "Sidetone aktivieren": "Enable sidetone",
    "Sidetone-Pegel": "Sidetone level",
    "-42 bis +4 dB": "-42 to +4 dB",
    "Mikrofon": "Microphone",
    "Hardware-Verstärkung": "Hardware gain",
    "-36 bis 0 dB": "-36 to 0 dB",
    "Aufnahme stummschalten": "Mute capture",
    "Schaltet den ALSA-Capture-Kanal, unabhängig vom Mikrofonarm":
        "Switches the ALSA capture channel, independent of the microphone boom",
    "Sprachbearbeitung": "Voice processing",
    "RNNoise, Gate und Kompressor werden über EasyEffects konfiguriert.":
        "RNNoise, gate and compressor are configured in EasyEffects.",
    "EasyEffects öffnen": "Open EasyEffects",
    "Öffnen": "Open",
    "Mikrofoneinstellungen anwenden": "Apply microphone settings",
    "Anwenden": "Apply",
    # --- spatial page ----------------------------------------------------
    "Binaurales 7.1": "Binaural 7.1",
    "PipeWire faltet acht Lautsprecherpositionen mit einer SOFA-HRTF auf Stereo. "
    "Dies ist kein Dolby-Atmos-Decoder.":
        "PipeWire convolves eight speaker positions with a SOFA HRTF down to "
        "stereo. This is not a Dolby Atmos decoder.",
    "Erzeugt ein virtuelles 8-Kanal-Ausgabegerät": "Creates a virtual 8-channel output device",
    "Als Standardausgabe verwenden": "Use as default output",
    "Gilt ab der nächsten Aktivierung von Spatial Audio":
        "Takes effect the next time spatial audio is enabled",
    "Keine Datei ausgewählt": "No file selected",
    "Auswählen": "Choose",
    "Wiedergabehinweis": "Playback note",
    "Für echtes Surround muss das Spiel 5.1 oder 7.1 PCM ausgeben.":
        "For real surround the game must output 5.1 or 7.1 PCM.",
    "Stereo wird absichtlich nicht künstlich hochgemischt.":
        "Stereo is deliberately not upmixed artificially.",
    "SOFA-HRTF auswählen": "Choose SOFA HRTF",
    # --- messages --------------------------------------------------------
    "Steuerdienst nicht erreichbar: {error}": "Control service unreachable: {error}",
    "Audio: Status ohne Steuerdienst nicht verfügbar":
        "Audio: status unavailable without the control service",
    "Spatial: Status ohne Steuerdienst nicht verfügbar":
        "Spatial: status unavailable without the control service",
    "Profil speichern": "Save profile",
    "Ein vorhandenes Profil gleichen Namens wird überschrieben.":
        "An existing profile with the same name is overwritten.",
    "Abbrechen": "Cancel",
    "Speichern": "Save",
    "Profil „{name}“ gespeichert": "Profile “{name}” saved",
    "Profil „{name}“ gelöscht": "Profile “{name}” deleted",
    "Profilname darf nicht leer sein": "The profile name must not be empty",
    "Höchstens {limit} Profile möglich": "No more than {limit} profiles",
    "Gerätefirmware": "Device firmware",
    "Noch nicht initialisiert": "Not initialised yet",
    "Nicht verwendet · USB-Kabel": "Not in use · USB cable",
    "Nicht initialisiert": "Not initialised",
    "Audio: ALSA-Mixer nicht verfügbar": "Audio: ALSA mixer unavailable",
    "Steuerdienst ist nicht erreichbar": "The control service is unreachable",
    "Einstellung angewendet": "Setting applied",
    "Profil für nächste Verbindung gespeichert": "Saved for the next connection",
    "Headset verbunden": "Headset connected",
    "Kein Headset gefunden - eingeschaltet und in Reichweite?":
        "No headset found - switched on and in range?",
    "Beleuchtungsprofil konnte nicht gelesen werden: {error}":
        "Could not read the lighting profile: {error}",
    "Autostart konnte nicht geändert werden: {error}":
        "Could not change autostart: {error}",
    "Sprache konnte nicht gespeichert werden: {error}":
        "Could not save the language: {error}",
    # --- updates ---------------------------------------------------------
    "Updates": "Updates",
    "Version {version}": "Version {version}",
    "Neue Versionen kommen von der GitHub-Seite des Projekts":
        "New versions come from the project's GitHub page",
    "Nach Updates suchen": "Check for updates",
    "Beim Start nach Updates suchen": "Check for updates at startup",
    "Fragt einmal pro Programmstart bei GitHub nach":
        "Asks GitHub once per program start",
    "Version {version} ist verfügbar": "Version {version} is available",
    "Installieren": "Install",
    "Zur Download-Seite": "Open download page",
    "Suche fehlgeschlagen: {error}": "Check failed: {error}",
    "HS80 Control ist aktuell": "HS80 Control is up to date",
    "Version {version} wird geladen …": "Downloading version {version} …",
    "Update fehlgeschlagen: {error}": "Update failed: {error}",
    "Passwortabfrage abgebrochen": "password prompt cancelled",
    "dnf meldet Fehler {status}": "dnf reported error {status}",
    "Version {version} wird installiert – bitte Passwort bestätigen":
        "Installing version {version} – please confirm your password",
    "Version {version} ist installiert – Neustart nötig":
        "Version {version} is installed – restart required",
    "Update installiert": "Update installed",
    "Version {version} ist installiert. HS80 Control muss neu "
    "gestartet werden, damit sie aktiv wird.":
        "Version {version} is installed. HS80 Control has to be restarted "
        "for it to take effect.",
    "Später": "Later",
    "Jetzt neu starten": "Restart now",
    # --- tray ------------------------------------------------------------
    "HS80 Control öffnen": "Open HS80 Control",
    "Akku {percent} %": "Battery {percent} %",
    # --- notifications ---------------------------------------------------
    "HS80: Akku fast leer": "HS80: battery almost empty",
    "Noch {percent} %. Das Headset schaltet sich bald ab – jetzt laden.":
        "{percent} % left. The headset will switch off soon – charge it now.",
    "HS80: Akku niedrig": "HS80: battery low",
    "Noch {percent} %. Bitte bald an das Ladekabel anschließen.":
        "{percent} % left. Please plug in the charging cable soon.",
    # --- hs80ctl ---------------------------------------------------------
    "verbunden": "connected",
    " (am USB-Ladekabel)": " (on the USB charging cable)",
    "Verbindung: USB-Kabel (Direktbetrieb, ohne Receiver)":
        "Connection: USB cable (direct mode, no receiver)",
    "unbekannt": "unknown",
    " (niedrig, bitte laden)": " (low, please charge)",
    "Akkuwarnung": "Battery warning",
    "Sprachansagen": "Voice announcements",
    "Ansagen im Headset": "Announcements on the headset",
    "Gesprochene Hinweise in der Sprache der App, direkt auf dem Headset":
        "Spoken notices in the app's language, played straight on the headset",
    "Beim Hoch- und Herunterklappen": "When it is flipped up or down",
    "Ladekabel": "Charging cable",
    "Beim Anstecken, Abziehen und bei vollem Akku":
        "When it is plugged in, pulled, and when the battery is full",
    "Niedriger Akkustand": "Low battery",
    "Bei niedrigem und bei fast leerem Akku":
        "When the battery is low and when it is almost empty",
    "Lautstärke der Ansagen": "Announcement volume",
    "Probe hören": "Play sample",
    "an": "on",
    "aus": "off",
    "Laden": "Charging",
    "ja": "yes",
    "nein": "no",
    "stumm": "muted",
    "aktiv": "active",
    "Spatial als Standard": "Spatial as default",
    "Hinweis": "Note",
    "Audio-Hinweis": "Audio note",
    "Spatial-Hinweis": "Spatial note",
    "Headset verbunden.": "Headset connected.",
    "Kein Headset gefunden; Receiver-Verbindung neu aufgebaut.":
        "No headset found; receiver link rebuilt.",
    "Einstellung angewendet.": "Setting applied.",
    "Einstellung gespeichert; das Headset ist derzeit offline.":
        "Setting saved; the headset is currently offline.",
    "der laufende Daemon kennt diese Funktion nicht (ältere Version); "
    "bitte neu starten: systemctl --user restart hs80d.service":
        "the running daemon does not know this function (older version); "
        "please restart it: systemctl --user restart hs80d.service",
}
