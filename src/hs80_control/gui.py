"""Wayland-native GTK4/libadwaita control application."""

from __future__ import annotations

from collections.abc import Callable
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__
from .config import ConfigStore
from .dbus_service import BUS_NAME, INTERFACE_NAME, OBJECT_PATH


APP_ID = "io.github.hs80control.App"
DBUS_CALL_TIMEOUT_MS = 30_000
SPATIAL_DBUS_CALL_TIMEOUT_MS = 60_000

_CSS = b"""
.hero-card {
  background: linear-gradient(125deg, alpha(@accent_bg_color, 0.26), alpha(#102c3b, 0.20));
  border: 1px solid alpha(@accent_color, 0.28);
  border-radius: 18px;
  padding: 22px;
}
.hero-title { font-size: 26px; font-weight: 800; }
.hero-subtitle { opacity: 0.72; }
.battery-value { font-size: 34px; font-weight: 800; font-feature-settings: "tnum"; }
.status-online { color: #45d483; font-weight: 700; }
.status-offline { color: #f07c82; font-weight: 700; }
.section-note { opacity: 0.68; font-size: 0.92em; }
.color-chip { min-width: 54px; min-height: 32px; }
"""


def _rgba(value: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(value):
        color.parse("#000000")
    return color


def _hex_color(color: Gdk.RGBA) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        round(color.get_red() * 255),
        round(color.get_green() * 255),
        round(color.get_blue() * 255),
    )


class HS80Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="HS80 Control")
        self.set_default_size(940, 720)
        self.set_size_request(700, 560)
        self.config = ConfigStore()
        self.proxy: Gio.DBusProxy | None = None
        self._syncing = False
        self._lighting_dirty: set[str] = set()
        self._lighting_apply_pending = False
        self._microphone_dirty: set[str] = set()
        self._microphone_apply_pending = False

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label="HS80 CONTROL", xalign=0)
        title.add_css_class("heading")
        subtitle = Gtk.Label(label="Fedora / PipeWire", xalign=0)
        subtitle.add_css_class("caption")
        title_box.append(title)
        title_box.append(subtitle)
        header.set_title_widget(title_box)

        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.pack_start(switcher)
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Status aktualisieren")
        self.refresh_button.connect("clicked", self._refresh)
        header.pack_end(self.refresh_button)
        toolbar.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay(child=self.stack)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

        self._build_overview_page()
        self._build_lighting_page()
        self._build_microphone_page()
        self._build_spatial_page()
        self._connect_dbus()
        GLib.timeout_add_seconds(2, self._poll)

    def _build_overview_page(self) -> None:
        page = Adw.PreferencesPage()
        hero_group = Adw.PreferencesGroup()
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        hero.add_css_class("hero-card")
        hero.set_hexpand(True)

        icon = Gtk.Image.new_from_icon_name("audio-headphones-symbolic")
        icon.set_pixel_size(76)
        hero.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_hexpand(True)
        product = Gtk.Label(label="CORSAIR HS80 RGB WIRELESS", xalign=0)
        product.add_css_class("hero-title")
        self.connection_label = Gtk.Label(label="Dienst wird verbunden ...", xalign=0)
        self.connection_label.add_css_class("hero-subtitle")
        text.append(product)
        text.append(self.connection_label)
        hero.append(text)
        self.battery_label = Gtk.Label(label="-- %")
        self.battery_label.add_css_class("battery-value")
        hero.append(self.battery_label)
        hero_group.add(hero)
        page.add(hero_group)

        self.error_banner = Adw.Banner()
        self.error_banner.set_revealed(False)
        self.audio_error_banner = Adw.Banner()
        self.audio_error_banner.set_revealed(False)
        self.spatial_error_banner = Adw.Banner()
        self.spatial_error_banner.set_revealed(False)
        banner_group = Adw.PreferencesGroup()
        banner_group.add(self.error_banner)
        banner_group.add(self.audio_error_banner)
        banner_group.add(self.spatial_error_banner)
        page.add(banner_group)

        status = Adw.PreferencesGroup(title="Gerätestatus")
        self.battery_row = Adw.ActionRow(title="Akku")
        self.battery_progress = Gtk.ProgressBar()
        self.battery_progress.set_size_request(180, -1)
        self.battery_progress.set_valign(Gtk.Align.CENTER)
        self.battery_row.add_suffix(self.battery_progress)
        status.add(self.battery_row)
        self.mic_state_row = Adw.ActionRow(title="Mikrofonarm")
        status.add(self.mic_state_row)
        self.firmware_row = Adw.ActionRow(title="Headset-Firmware")
        status.add(self.firmware_row)
        self.receiver_row = Adw.ActionRow(title="Receiver")
        status.add(self.receiver_row)
        page.add(status)

        quick = Adw.PreferencesGroup(title="Schnellaktionen")
        rgb_off = Adw.ActionRow(
            title="Beleuchtung ausschalten",
            subtitle="Reduziert den Akkuverbrauch des Headsets",
        )
        rgb_button = Gtk.Button(label="RGB aus")
        rgb_button.set_valign(Gtk.Align.CENTER)
        rgb_button.add_css_class("suggested-action")
        rgb_button.connect("clicked", self._quick_rgb_off)
        rgb_off.add_suffix(rgb_button)
        rgb_off.set_activatable_widget(rgb_button)
        quick.add(rgb_off)
        page.add(quick)
        self.stack.add_titled(page, "overview", "Übersicht").set_icon_name("view-dashboard-symbolic")

    def _build_lighting_page(self) -> None:
        page = Adw.PreferencesPage()
        settings = self.config.snapshot()["rgb"]

        group = Adw.PreferencesGroup(
            title="Beleuchtung",
            description="Die Effekte werden vom Daemon erzeugt; statische Farben sparen Akku.",
        )
        mode_row = Adw.ActionRow(title="Modus")
        self.rgb_mode = Gtk.DropDown.new_from_strings(
            ["Aus", "Statisch", "Pulsieren", "Regenbogen"]
        )
        self.rgb_mode.set_valign(Gtk.Align.CENTER)
        modes = ["off", "static", "pulse", "rainbow"]
        self.rgb_mode.set_selected(modes.index(settings["mode"]))
        self.rgb_mode.connect(
            "notify::selected", lambda *_: self._lighting_changed("mode")
        )
        mode_row.add_suffix(self.rgb_mode)
        mode_row.set_activatable_widget(self.rgb_mode)
        group.add(mode_row)

        brightness_row = Adw.ActionRow(title="Helligkeit")
        self.rgb_brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.rgb_brightness.set_value(settings["brightness"])
        self.rgb_brightness.set_draw_value(True)
        self.rgb_brightness.set_digits(0)
        self.rgb_brightness.set_size_request(260, -1)
        self.rgb_brightness.set_valign(Gtk.Align.CENTER)
        self.rgb_brightness.connect(
            "value-changed", lambda *_: self._lighting_changed("brightness")
        )
        brightness_row.add_suffix(self.rgb_brightness)
        group.add(brightness_row)

        self.logo_color = self._color_row(group, "Logo", settings["logo"], "logo")
        self.indicator_color = self._color_row(
            group, "Statusanzeige", settings["indicator"], "indicator"
        )
        self.microphone_color = self._color_row(
            group, "Mikrofon-LED", settings["microphone"], "microphone"
        )
        page.add(group)

        power = Adw.PreferencesGroup(title="Energie")
        sleep_row = Adw.ActionRow(
            title="Automatisch ausschalten",
            subtitle="0 deaktiviert den Timer; maximal 90 Minuten",
        )
        self.sleep_spin = Gtk.SpinButton.new_with_range(0, 90, 1)
        self.sleep_spin.set_value(self.config.snapshot()["sleep"]["minutes"])
        self.sleep_spin.set_valign(Gtk.Align.CENTER)
        self.sleep_spin.connect(
            "value-changed", lambda *_: self._lighting_changed("sleep")
        )
        sleep_row.add_suffix(self.sleep_spin)
        power.add(sleep_row)
        page.add(power)

        actions = Adw.PreferencesGroup()
        apply_row = Adw.ActionRow(title="Profil anwenden")
        apply = Gtk.Button(label="Anwenden")
        self.lighting_apply_button = apply
        apply.add_css_class("suggested-action")
        apply.set_valign(Gtk.Align.CENTER)
        apply.connect("clicked", self._apply_lighting)
        apply_row.add_suffix(apply)
        apply_row.set_activatable_widget(apply)
        actions.add(apply_row)
        page.add(actions)
        self.stack.add_titled(page, "lighting", "RGB").set_icon_name("preferences-color-symbolic")

    def _color_row(
        self,
        group: Adw.PreferencesGroup,
        title: str,
        value: str,
        setting: str,
    ) -> Gtk.ColorDialogButton:
        row = Adw.ActionRow(title=title)
        dialog = Gtk.ColorDialog(title=f"{title} auswählen", with_alpha=False)
        button = Gtk.ColorDialogButton(dialog=dialog)
        button.set_rgba(_rgba(value))
        button.connect(
            "notify::rgba", lambda *_: self._lighting_changed(setting)
        )
        button.add_css_class("color-chip")
        button.set_valign(Gtk.Align.CENTER)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        group.add(row)
        return button

    def _build_microphone_page(self) -> None:
        page = Adw.PreferencesPage()
        monitoring = Adw.PreferencesGroup(
            title="Hardware-Sidetone",
            description="Direktes Mikrofon-Monitoring ohne PipeWire-Latenz.",
        )
        self.sidetone_switch = Adw.SwitchRow(title="Sidetone aktivieren")
        self.sidetone_switch.connect(
            "notify::active", lambda *_: self._microphone_changed("sidetone_enabled")
        )
        monitoring.add(self.sidetone_switch)
        sidetone_level = Adw.ActionRow(title="Sidetone-Pegel", subtitle="-42 bis +4 dB")
        self.sidetone_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -42, 4, 2)
        self.sidetone_scale.set_draw_value(True)
        self.sidetone_scale.set_digits(0)
        self.sidetone_scale.set_size_request(280, -1)
        self.sidetone_scale.connect(
            "value-changed", lambda *_: self._microphone_changed("sidetone_db")
        )
        sidetone_level.add_suffix(self.sidetone_scale)
        monitoring.add(sidetone_level)
        page.add(monitoring)

        microphone = Adw.PreferencesGroup(title="Mikrofon")
        gain_row = Adw.ActionRow(title="Hardware-Verstärkung", subtitle="-36 bis 0 dB")
        self.mic_gain_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -36, 0, 1)
        self.mic_gain_scale.set_draw_value(True)
        self.mic_gain_scale.set_digits(0)
        self.mic_gain_scale.set_size_request(280, -1)
        self.mic_gain_scale.connect(
            "value-changed", lambda *_: self._microphone_changed("mic_gain")
        )
        gain_row.add_suffix(self.mic_gain_scale)
        microphone.add(gain_row)
        self.mic_mute_switch = Adw.SwitchRow(
            title="Aufnahme stummschalten",
            subtitle="Schaltet den ALSA-Capture-Kanal, unabhängig vom Mikrofonarm",
        )
        self.mic_mute_switch.connect(
            "notify::active", lambda *_: self._microphone_changed("mic_mute")
        )
        microphone.add(self.mic_mute_switch)
        page.add(microphone)

        processing = Adw.PreferencesGroup(
            title="Sprachbearbeitung",
            description="RNNoise, Gate und Kompressor werden über EasyEffects konfiguriert.",
        )
        effects_row = Adw.ActionRow(title="EasyEffects öffnen")
        effects_button = Gtk.Button(label="Öffnen")
        effects_button.set_valign(Gtk.Align.CENTER)
        effects_button.connect("clicked", self._open_easyeffects)
        effects_row.add_suffix(effects_button)
        effects_row.set_activatable_widget(effects_button)
        processing.add(effects_row)
        page.add(processing)

        actions = Adw.PreferencesGroup()
        apply_row = Adw.ActionRow(title="Mikrofoneinstellungen anwenden")
        apply = Gtk.Button(label="Anwenden")
        self.microphone_apply_button = apply
        apply.add_css_class("suggested-action")
        apply.set_valign(Gtk.Align.CENTER)
        apply.connect("clicked", self._apply_microphone)
        apply_row.add_suffix(apply)
        actions.add(apply_row)
        page.add(actions)
        self.stack.add_titled(page, "microphone", "Mikrofon").set_icon_name(
            "audio-input-microphone-symbolic"
        )

    def _build_spatial_page(self) -> None:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Binaurales 7.1",
            description=(
                "PipeWire faltet acht Lautsprecherpositionen mit einer SOFA-HRTF auf Stereo. "
                "Dies ist kein Dolby-Atmos-Decoder."
            ),
        )
        self.spatial_switch = Adw.SwitchRow(
            title="HS80 Spatial 7.1",
            subtitle="Erzeugt ein virtuelles 8-Kanal-Ausgabegerät",
        )
        self.spatial_switch.connect("notify::active", self._spatial_toggled)
        group.add(self.spatial_switch)

        self.spatial_default_switch = Adw.SwitchRow(
            title="Als Standardausgabe verwenden",
            subtitle="Gilt ab der nächsten Aktivierung von Spatial Audio",
        )
        self.spatial_default_switch.connect(
            "notify::active", self._spatial_default_toggled
        )
        group.add(self.spatial_default_switch)

        hrtf_row = Adw.ActionRow(title="SOFA-HRTF", subtitle="Keine Datei ausgewählt")
        self.hrtf_row = hrtf_row
        choose = Gtk.Button(label="Auswählen")
        choose.set_valign(Gtk.Align.CENTER)
        choose.connect("clicked", self._choose_sofa)
        hrtf_row.add_suffix(choose)
        hrtf_row.set_activatable_widget(choose)
        group.add(hrtf_row)
        page.add(group)

        note = Adw.PreferencesGroup(title="Wiedergabehinweis")
        note_row = Adw.ActionRow(
            title="Für echtes Surround muss das Spiel 5.1 oder 7.1 PCM ausgeben.",
            subtitle="Stereo wird absichtlich nicht künstlich hochgemischt.",
        )
        note.add(note_row)
        page.add(note)
        self.stack.add_titled(page, "spatial", "Spatial").set_icon_name("audio-speakers-symbolic")

        sofa = self.config.snapshot()["spatial"]["sofa_file"]
        if sofa:
            self.hrtf_row.set_subtitle(sofa)

    def _connect_dbus(self) -> None:
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                BUS_NAME,
                OBJECT_PATH,
                INTERFACE_NAME,
                None,
            )
            self.proxy.connect("g-properties-changed", lambda *_: self._sync_state())
            self._sync_state()
        except GLib.Error as exc:
            self.proxy = None
            self.error_banner.set_title(f"Steuerdienst nicht erreichbar: {exc.message}")
            self.error_banner.set_revealed(True)
            self.audio_error_banner.set_title(
                "Audio: Status ohne Steuerdienst nicht verfügbar"
            )
            self.audio_error_banner.set_revealed(True)
            self.spatial_error_banner.set_title(
                "Spatial: Status ohne Steuerdienst nicht verfügbar"
            )
            self.spatial_error_banner.set_revealed(True)
            self._set_microphone_controls_sensitive(False)

    def _property(self, name: str, default: object) -> object:
        if self.proxy is None:
            return default
        value = self.proxy.get_cached_property(name)
        return value.unpack() if value is not None else default

    def _microphone_changed(self, setting: str) -> None:
        if not self._syncing:
            self._microphone_dirty.add(setting)

    def _lighting_changed(self, setting: str) -> None:
        if not self._syncing:
            self._lighting_dirty.add(setting)

    def _set_lighting_controls_sensitive(self, sensitive: bool) -> None:
        self.rgb_mode.set_sensitive(sensitive)
        self.rgb_brightness.set_sensitive(sensitive)
        self.logo_color.set_sensitive(sensitive)
        self.indicator_color.set_sensitive(sensitive)
        self.microphone_color.set_sensitive(sensitive)
        self.sleep_spin.set_sensitive(sensitive)
        self.lighting_apply_button.set_sensitive(sensitive)

    def _set_microphone_controls_sensitive(self, sensitive: bool) -> None:
        self.sidetone_switch.set_sensitive(sensitive)
        self.sidetone_scale.set_sensitive(sensitive)
        self.mic_gain_scale.set_sensitive(sensitive)
        self.mic_mute_switch.set_sensitive(sensitive)
        self.microphone_apply_button.set_sensitive(sensitive)

    def _sync_state(self) -> None:
        headset = bool(self._property("HeadsetConnected", False))
        receiver = bool(self._property("ReceiverConnected", False))
        battery = int(self._property("BatteryPercent", -1))
        error = str(self._property("LastError", ""))
        mixer_available = bool(self._property("MixerAvailable", False))
        audio_error = str(self._property("AudioError", ""))
        spatial_error = str(self._property("SpatialError", ""))
        firmware = str(self._property("Firmware", ""))
        receiver_firmware = str(self._property("ReceiverFirmware", ""))
        microphone = int(self._property("MicrophoneMuted", -1))

        self.connection_label.set_label(
            "Headset verbunden" if headset else ("Receiver bereit, Headset offline" if receiver else "Offline")
        )
        self.connection_label.remove_css_class("status-online")
        self.connection_label.remove_css_class("status-offline")
        self.connection_label.add_css_class("status-online" if headset else "status-offline")
        self.battery_label.set_label(f"{battery} %" if battery >= 0 else "-- %")
        self.battery_progress.set_fraction(max(0, battery) / 100 if battery >= 0 else 0)
        self.battery_row.set_subtitle(f"{battery} Prozent" if battery >= 0 else "Noch kein Akkureport")
        self.mic_state_row.set_subtitle(
            "Stummgeschaltet" if microphone == 1 else ("Aktiv" if microphone == 0 else "Unbekannt")
        )
        self.firmware_row.set_subtitle(firmware or "Unbekannt")
        self.receiver_row.set_subtitle(
            f"Firmware {receiver_firmware}" if receiver_firmware else "Nicht initialisiert"
        )
        self.error_banner.set_title(error)
        self.error_banner.set_revealed(bool(error))
        self.audio_error_banner.set_title(
            f"Audio: {audio_error}"
            if audio_error
            else "Audio: ALSA-Mixer nicht verfügbar"
        )
        self.audio_error_banner.set_revealed(bool(audio_error) or not mixer_available)
        self.spatial_error_banner.set_title(f"Spatial: {spatial_error}")
        self.spatial_error_banner.set_revealed(bool(spatial_error))

        self._syncing = True
        self.spatial_switch.set_active(bool(self._property("SpatialEnabled", False)))
        self.spatial_default_switch.set_active(
            bool(self._property("SpatialMakeDefault", True))
        )
        sofa_file = str(self._property("SpatialSofaFile", ""))
        self.hrtf_row.set_subtitle(sofa_file or "Keine Datei ausgewählt")
        if not self._lighting_apply_pending:
            modes = ["off", "static", "pulse", "rainbow"]
            if "mode" not in self._lighting_dirty:
                mode = str(self._property("RgbMode", "static"))
                self.rgb_mode.set_selected(modes.index(mode) if mode in modes else 1)
            if "brightness" not in self._lighting_dirty:
                self.rgb_brightness.set_value(
                    float(self._property("RgbBrightness", 100))
                )
            if "logo" not in self._lighting_dirty:
                self.logo_color.set_rgba(
                    _rgba(str(self._property("RgbLogo", "#00bfff")))
                )
            if "indicator" not in self._lighting_dirty:
                self.indicator_color.set_rgba(
                    _rgba(str(self._property("RgbIndicator", "#00bfff")))
                )
            if "microphone" not in self._lighting_dirty:
                self.microphone_color.set_rgba(
                    _rgba(str(self._property("RgbMicrophone", "#00ffff")))
                )
            if "sleep" not in self._lighting_dirty:
                self.sleep_spin.set_value(
                    float(self._property("SleepMinutes", 15))
                )
        if not self._microphone_apply_pending:
            if "sidetone_enabled" not in self._microphone_dirty:
                self.sidetone_switch.set_active(
                    bool(self._property("SidetoneEnabled", False))
                )
            if "sidetone_db" not in self._microphone_dirty:
                self.sidetone_scale.set_value(
                    float(self._property("SidetoneDb", -42.0))
                )
            if "mic_gain" not in self._microphone_dirty:
                self.mic_gain_scale.set_value(
                    float(self._property("MicrophoneGainDb", 0.0))
                )
            if "mic_mute" not in self._microphone_dirty:
                self.mic_mute_switch.set_active(
                    bool(self._property("MicrophoneCaptureMuted", False))
                )
        self._set_microphone_controls_sensitive(
            mixer_available and not self._microphone_apply_pending
        )
        self._set_lighting_controls_sensitive(not self._lighting_apply_pending)
        self._syncing = False

    def _poll(self) -> bool:
        if self.proxy is None or not self.proxy.get_name_owner():
            self._connect_dbus()
        else:
            self._sync_state()
        return GLib.SOURCE_CONTINUE

    def _call(
        self,
        method: str,
        parameters: GLib.Variant | None,
        callback: Callable[[bool, bool], None] | None = None,
        show_result: bool = True,
        always: Callable[[], None] | None = None,
        timeout_ms: int = DBUS_CALL_TIMEOUT_MS,
    ) -> None:
        def complete(success: bool, applied: bool) -> None:
            try:
                if callback is not None:
                    callback(success, applied)
            finally:
                if always is not None:
                    always()

        if self.proxy is None:
            try:
                self.toast_overlay.add_toast(
                    Adw.Toast(title="Steuerdienst ist nicht erreichbar")
                )
            finally:
                complete(False, False)
            return

        def finished(proxy: Gio.DBusProxy, result: Gio.AsyncResult) -> None:
            success = False
            applied = False
            try:
                value = proxy.call_finish(result)
                unpacked = value.unpack() if value is not None else ()
                applied = bool(unpacked[0]) if unpacked else True
                if show_result:
                    message = (
                        "Einstellung angewendet"
                        if applied
                        else "Profil für nächste Verbindung gespeichert"
                    )
                    self.toast_overlay.add_toast(Adw.Toast(title=message))
                self._sync_state()
                success = True
            except GLib.Error as exc:
                self.toast_overlay.add_toast(Adw.Toast(title=exc.message, timeout=5))
            finally:
                complete(success, applied)

        try:
            self.proxy.call(
                method,
                parameters,
                Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
                finished,
            )
        except GLib.Error as exc:
            self.toast_overlay.add_toast(Adw.Toast(title=exc.message, timeout=5))
            complete(False, False)

    def _refresh(self, _button: Gtk.Button) -> None:
        self.refresh_button.set_sensitive(False)
        self._call(
            "Refresh",
            None,
            show_result=False,
            always=lambda: self.refresh_button.set_sensitive(True),
        )

    def _quick_rgb_off(self, _button: Gtk.Button) -> None:
        self._call(
            "UpdateRgb",
            GLib.Variant("(snsss)", ("off", -1, "", "", "")),
        )

    def _rgb_parameters(self, mode: str) -> GLib.Variant:
        return GLib.Variant(
            "(sysss)",
            (
                mode,
                round(self.rgb_brightness.get_value()),
                _hex_color(self.logo_color.get_rgba()),
                _hex_color(self.indicator_color.get_rgba()),
                _hex_color(self.microphone_color.get_rgba()),
            ),
        )

    def _show_apply_result(self, applied: bool) -> None:
        message = (
            "Einstellung angewendet"
            if applied
            else "Profil für nächste Verbindung gespeichert"
        )
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    def _apply_lighting(self, _button: Gtk.Button | None) -> None:
        if self._lighting_apply_pending:
            return
        self._lighting_apply_pending = True
        self._set_lighting_controls_sensitive(False)
        modes = ["off", "static", "pulse", "rainbow"]
        mode = modes[self.rgb_mode.get_selected()]

        def finish(success: bool, applied: bool = False) -> None:
            self._lighting_apply_pending = False
            if success:
                self._lighting_dirty.clear()
                self._show_apply_result(applied)
            self._sync_state()

        def after_rgb(success: bool, rgb_applied: bool) -> None:
            if not success:
                finish(False)
                return

            def after_sleep(sleep_success: bool, sleep_applied: bool) -> None:
                finish(sleep_success, rgb_applied and sleep_applied)

            self._call(
                "SetSleepTimer",
                GLib.Variant("(q)", (round(self.sleep_spin.get_value()),)),
                after_sleep,
                show_result=False,
            )

        self._call("SetRgb", self._rgb_parameters(mode), after_rgb, show_result=False)

    def _apply_microphone(self, _button: Gtk.Button) -> None:
        if self._microphone_apply_pending:
            return
        self._microphone_apply_pending = True
        self._set_microphone_controls_sensitive(False)

        def finish(success: bool, applied: bool = False) -> None:
            self._microphone_apply_pending = False
            if success:
                self._microphone_dirty.clear()
                self._show_apply_result(applied)
            self._sync_state()

        def after_sidetone(success: bool, sidetone_applied: bool) -> None:
            if not success:
                finish(False)
                return

            def after_gain(gain_success: bool, gain_applied: bool) -> None:
                if not gain_success:
                    finish(False)
                    return

                def after_mute(mute_success: bool, mute_applied: bool) -> None:
                    finish(
                        mute_success,
                        sidetone_applied and gain_applied and mute_applied,
                    )

                self._call(
                    "SetMicrophoneMuted",
                    GLib.Variant("(b)", (self.mic_mute_switch.get_active(),)),
                    after_mute,
                    show_result=False,
                )

            self._call(
                "SetMicrophoneGain",
                GLib.Variant("(d)", (self.mic_gain_scale.get_value(),)),
                after_gain,
                show_result=False,
            )

        self._call(
            "SetSidetone",
            GLib.Variant(
                "(bd)", (self.sidetone_switch.get_active(), self.sidetone_scale.get_value())
            ),
            after_sidetone,
            show_result=False,
        )

    def _spatial_toggled(self, row: Adw.SwitchRow, _property: object) -> None:
        if self._syncing:
            return
        self._call(
            "SetSpatialEnabled",
            GLib.Variant("(b)", (row.get_active(),)),
            timeout_ms=SPATIAL_DBUS_CALL_TIMEOUT_MS,
        )

    def _spatial_default_toggled(
        self, row: Adw.SwitchRow, _property: object
    ) -> None:
        if self._syncing:
            return
        self._call(
            "SetSpatialMakeDefault",
            GLib.Variant("(b)", (row.get_active(),)),
        )

    def _choose_sofa(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="SOFA-HRTF auswählen", modal=True)
        file_filter = Gtk.FileFilter(name="SOFA HRTF")
        file_filter.add_pattern("*.sofa")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)

        def selected(file_dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                selected_file = file_dialog.open_finish(result)
            except GLib.Error:
                return
            path = selected_file.get_path()
            if path:
                def configured(success: bool, applied: bool) -> None:
                    if success and applied:
                        self.hrtf_row.set_subtitle(path)

                self._call(
                    "ConfigureSpatial",
                    GLib.Variant("(s)", (path,)),
                    configured,
                    timeout_ms=SPATIAL_DBUS_CALL_TIMEOUT_MS,
                )

        dialog.open(self, None, selected)

    def _open_easyeffects(self, _button: Gtk.Button) -> None:
        try:
            Gio.Subprocess.new(["easyeffects"], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.toast_overlay.add_toast(Adw.Toast(title=exc.message))


class HS80Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = HS80Window(self)
        window.present()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    if "--version" in arguments:
        print(f"hs80-control {__version__}")
        return 0
    return HS80Application().run(arguments)


if __name__ == "__main__":
    sys.exit(main())
