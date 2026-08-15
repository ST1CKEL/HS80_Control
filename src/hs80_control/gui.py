"""Wayland-native GTK4/libadwaita control application."""

from __future__ import annotations

from collections.abc import Callable
import math
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
.app-shell { background-color: #080d13; }
.app-header {
  background: linear-gradient(180deg, alpha(#1b222c, 0.98), alpha(#121821, 0.98));
  border-bottom: 1px solid alpha(#8ba0b8, 0.12);
  box-shadow: 0 4px 18px alpha(#000000, 0.22);
}
.app-title { font-size: 17px; font-weight: 750; letter-spacing: 0.08em; }
.app-subtitle { color: alpha(#d9e2ee, 0.70); font-size: 0.86em; }
.sidebar {
  background: linear-gradient(145deg, #18212b, #101720);
  border-right: 1px solid alpha(#90a7c0, 0.12);
  padding: 18px 12px;
}
.sidebar-brand { color: alpha(#eaf5ff, 0.86); font-weight: 700; }
.sidebar-device { color: alpha(#d6e1ec, 0.72); font-size: 0.82em; }
.navigation-list { background: transparent; }
.navigation-list > row {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 13px;
  margin: 3px 0;
  padding: 0;
}
.navigation-list > row:hover { background: alpha(#ffffff, 0.045); }
.navigation-list > row:selected {
  background: linear-gradient(105deg, alpha(#00c8f2, 0.17), alpha(#6078ff, 0.10));
  border-color: alpha(#26d8ff, 0.30);
  box-shadow: inset 3px 0 #16c9f4;
}
.navigation-row { padding: 13px 12px; }
.navigation-row image { color: alpha(#e5edf5, 0.80); }
.navigation-list > row:selected .navigation-row image,
.navigation-list > row:selected .navigation-row label { color: #36d7ff; }
.content-background {
  background: linear-gradient(145deg, #080d13, #0a1119 55%, #091019);
}
.dashboard-content { padding: 26px; }
.hero-card {
  background: linear-gradient(118deg, alpha(#0d1822, 0.98), alpha(#0b2635, 0.80) 52%, alpha(#251441, 0.72));
  border: 1px solid alpha(#8ca4bc, 0.22);
  border-radius: 22px;
  padding: 30px;
  box-shadow: 0 14px 32px alpha(#000000, 0.30);
}
.hero-title { font-size: 31px; font-weight: 850; letter-spacing: 0.04em; }
.hero-kicker { color: #29d7ff; font-size: 0.82em; font-weight: 750; letter-spacing: 0.14em; }
.hero-subtitle { color: alpha(#e7eef6, 0.80); }
.battery-value { font-size: 33px; font-weight: 850; font-feature-settings: "tnum"; }
.battery-caption { color: alpha(#d8e3ef, 0.72); font-size: 0.86em; }
.battery-icon { color: #25d9d0; }
.status-online { color: #42dd88; font-weight: 700; }
.status-standby { color: #f2b84b; font-weight: 700; }
.status-offline { color: #f07c82; font-weight: 700; }
.section-title { font-size: 18px; font-weight: 800; }
.status-card {
  background: linear-gradient(135deg, alpha(#1a242f, 0.96), alpha(#111821, 0.96));
  border: 1px solid alpha(#91a7bd, 0.18);
  border-radius: 16px;
  padding: 12px;
  box-shadow: 0 8px 20px alpha(#000000, 0.18);
}
.status-card-icon {
  color: #28d7ff;
  background: alpha(#0b1720, 0.72);
  border: 2px solid alpha(#27d7ff, 0.55);
  border-radius: 999px;
  padding: 8px;
}
.status-card-icon-purple {
  color: #a263ff;
  border-color: alpha(#9b5cff, 0.60);
}
.status-card-title { color: alpha(#eff5fb, 0.94); font-weight: 700; }
.status-card-value { font-size: 15px; font-weight: 800; }
.status-card-detail { color: alpha(#dbe5ef, 0.72); }
.quick-title { font-size: 17px; font-weight: 800; }
.quick-card {
  background: linear-gradient(110deg, alpha(#19232e, 0.96), alpha(#101720, 0.96));
  border: 1px solid alpha(#91a7bd, 0.18);
  border-radius: 16px;
  padding: 20px 24px;
}
.gradient-action {
  background: linear-gradient(100deg, #06bfe8, #337df5 52%, #812fe8);
  color: white;
  border: 0;
  border-radius: 12px;
  padding: 11px 24px;
  font-weight: 800;
  box-shadow: 0 6px 18px alpha(#326fea, 0.30);
}
.gradient-action:hover { background: linear-gradient(100deg, #21d2f7, #4b8dff 52%, #9349f2); }
.settings-page { background-color: #0a1119; }
.section-note { opacity: 0.80; font-size: 0.92em; }
.color-chip { min-width: 54px; min-height: 32px; }
"""


def _connection_presentation(headset: bool, receiver: bool) -> tuple[str, str]:
    if headset:
        return "●  Verbunden", "status-online"
    if receiver:
        return "●  Receiver bereit · Headset offline", "status-standby"
    return "●  Receiver offline", "status-offline"


def _battery_presentation(
    percent: int, charging: int, connected: bool = True
) -> tuple[str, str]:
    if percent < 0:
        return "-- %", "Noch kein Akkureport"
    detail = f"{percent} Prozent"
    if not connected:
        detail += " · letzter Stand"
    elif charging == 1:
        detail += " · lädt"
    return f"{percent} %", detail


def _microphone_presentation(muted: int) -> tuple[str, str]:
    if muted == 1:
        return "Stummgeschaltet", "Arm hochgeklappt"
    if muted == 0:
        return "Aktiv", "Arm heruntergeklappt"
    return "Unbekannt", "Noch kein Hardwarestatus"


class BatteryRing(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.percent = -1
        self.set_content_width(178)
        self.set_content_height(178)
        self.set_draw_func(self._draw)

    def set_percent(self, percent: int) -> None:
        normalized = max(-1, min(100, percent))
        if normalized != self.percent:
            self.percent = normalized
            self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, context: object, width: int, height: int) -> None:
        size = min(width, height)
        center_x = width / 2
        center_y = height / 2
        radius = max(1.0, size / 2 - 10)
        line_width = max(7.0, size * 0.055)
        start = -math.pi / 2

        context.set_line_width(line_width)
        context.set_line_cap(1)
        context.set_source_rgba(0.42, 0.50, 0.60, 0.18)
        context.arc(center_x, center_y, radius, 0, math.tau)
        context.stroke()

        if self.percent < 0:
            return
        end = start + math.tau * self.percent / 100
        context.set_line_width(line_width + 7)
        context.set_source_rgba(0.10, 0.84, 0.98, 0.12)
        context.arc(center_x, center_y, radius, start, end)
        context.stroke()
        midpoint = min(end, start + math.pi)
        context.set_line_width(line_width)
        context.set_source_rgb(0.05, 0.81, 0.95)
        context.arc(center_x, center_y, radius, start, midpoint)
        context.stroke()
        if end > midpoint:
            context.set_source_rgb(0.56, 0.22, 0.96)
            context.arc(center_x, center_y, radius, midpoint, end)
            context.stroke()


class HeadsetArt(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_content_width(260)
        self.set_content_height(250)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_tooltip_text("Stilisierte Darstellung des Corsair HS80")
        self.set_draw_func(self._draw)

    @staticmethod
    def _rounded_rectangle(
        context: object, x: float, y: float, width: float, height: float, radius: float
    ) -> None:
        radius = min(radius, width / 2, height / 2)
        context.new_sub_path()
        context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        context.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        context.close_path()

    def _draw(self, _area: Gtk.DrawingArea, context: object, width: int, height: int) -> None:
        scale = min(width / 300, height / 260)
        context.translate((width - 300 * scale) / 2, (height - 260 * scale) / 2)
        context.scale(scale, scale)
        context.set_line_cap(1)
        context.set_line_join(1)

        for line_width, alpha in ((18, 0.05), (10, 0.10), (4, 0.85)):
            context.set_line_width(line_width)
            context.set_source_rgba(0.10, 0.84, 0.98, alpha)
            context.arc(150, 115, 84, math.pi * 1.04, math.pi * 1.96)
            context.stroke()
        context.set_line_width(18)
        context.set_source_rgba(0.09, 0.11, 0.14, 1)
        context.arc(150, 116, 82, math.pi * 1.04, math.pi * 1.96)
        context.stroke()
        context.set_line_width(6)
        context.set_source_rgba(0.22, 0.27, 0.32, 1)
        context.arc(150, 116, 82, math.pi * 1.04, math.pi * 1.96)
        context.stroke()

        for x, edge in ((63, (0.10, 0.86, 0.97)), (191, (0.61, 0.27, 0.97))):
            context.set_source_rgba(edge[0], edge[1], edge[2], 0.16)
            self._rounded_rectangle(context, x - 7, 97, 60, 124, 27)
            context.fill()
            context.set_source_rgba(0.06, 0.08, 0.11, 1)
            self._rounded_rectangle(context, x, 104, 46, 110, 23)
            context.fill_preserve()
            context.set_line_width(3)
            context.set_source_rgb(*edge)
            context.stroke()
            context.set_source_rgba(0.12, 0.15, 0.18, 1)
            self._rounded_rectangle(context, x + 8, 121, 30, 77, 15)
            context.fill()

        context.set_line_width(7)
        context.set_source_rgba(0.15, 0.18, 0.21, 1)
        context.move_to(88, 190)
        context.curve_to(74, 225, 95, 237, 137, 237)
        context.stroke()
        context.set_line_width(4)
        context.set_source_rgba(0.12, 0.82, 0.96, 0.95)
        context.move_to(87, 188)
        context.curve_to(75, 222, 98, 232, 137, 232)
        context.stroke()
        context.arc(142, 232, 6, 0, math.tau)
        context.set_source_rgba(0.66, 0.31, 0.98, 1)
        context.fill()


def _lighting_mute_hint(microphone: int) -> str:
    # The HS80 firmware suppresses software lighting entirely while the
    # microphone arm is flipped up (muted); verified on firmware 5.8.48.
    if microphone == 1:
        return (
            "Mikrofon ist hochgeklappt (stumm) – "
            "Beleuchtung erscheint erst nach dem Runterklappen"
        )
    return ""


def _rgba(value: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(value):
        color.parse("#000000")
    return color


def _hex_color(color: Gdk.RGBA) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        round(color.red * 255),
        round(color.green * 255),
        round(color.blue * 255),
    )


class HS80Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="HS80 Control")
        self.set_default_size(1280, 820)
        self.set_size_request(680, 560)
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
        toolbar.add_css_class("app-shell")
        header = Adw.HeaderBar()
        header.add_css_class("app-header")
        self.sidebar_button = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        self.sidebar_button.set_tooltip_text("Navigation öffnen")
        self.sidebar_button.set_visible(False)
        self.sidebar_button.connect("clicked", self._toggle_sidebar)
        header.pack_start(self.sidebar_button)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label="HS80 CONTROL")
        title.add_css_class("app-title")
        subtitle = Gtk.Label(label="Fedora · PipeWire")
        subtitle.add_css_class("app-subtitle")
        title_box.append(title)
        title_box.append(subtitle)
        header.set_title_widget(title_box)

        self.stack = Adw.ViewStack()
        self.stack.add_css_class("content-background")
        self.stack.set_enable_transitions(True)
        self.stack.set_transition_duration(180)
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Status aktualisieren")
        self.refresh_button.connect("clicked", self._refresh)
        header.pack_end(self.refresh_button)
        toolbar.add_top_bar(header)

        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_sidebar_width_fraction(0.20)
        self.split_view.set_min_sidebar_width(220)
        self.split_view.set_max_sidebar_width(248)
        self.split_view.set_sidebar(self._build_sidebar())
        self.split_view.set_content(self.stack)
        self.toast_overlay = Adw.ToastOverlay(child=self.split_view)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

        self._build_overview_page()
        self._build_lighting_page()
        self._build_microphone_page()
        self._build_spatial_page()
        self._install_breakpoints()
        first_row = self.navigation.get_row_at_index(0)
        if first_row is not None:
            self.navigation.select_row(first_row)
        self._connect_dbus()
        GLib.timeout_add_seconds(2, self._poll)

    def _build_sidebar(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("sidebar")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        brand.set_margin_start(12)
        brand.set_margin_end(12)
        brand.set_margin_bottom(2)
        brand_title = Gtk.Label(label="HS80 RGB WIRELESS", xalign=0)
        brand_title.add_css_class("sidebar-brand")
        brand_device = Gtk.Label(label="Receiver 1b1c:0a6b", xalign=0)
        brand_device.add_css_class("sidebar-device")
        brand.append(brand_title)
        brand.append(brand_device)
        sidebar.append(brand)

        self.navigation = Gtk.ListBox()
        self.navigation.add_css_class("navigation-list")
        self.navigation.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.navigation.set_activate_on_single_click(True)
        for page, label, icon_name in (
            ("overview", "Übersicht", "go-home-symbolic"),
            ("lighting", "RGB", "preferences-color-symbolic"),
            ("microphone", "Mikrofon", "audio-input-microphone-symbolic"),
            ("spatial", "Spatial", "audio-speakers-symbolic"),
        ):
            row = Gtk.ListBoxRow()
            row.page_name = page
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            content.add_css_class("navigation-row")
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(22)
            content.append(icon)
            text = Gtk.Label(label=label, xalign=0)
            text.set_hexpand(True)
            content.append(text)
            row.set_child(content)
            self.navigation.append(row)
        self.navigation.connect("row-selected", self._navigation_selected)
        sidebar.append(self.navigation)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)
        sidebar.append(Gtk.Separator())
        about = Gtk.Button()
        about_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        about_content.append(Gtk.Image.new_from_icon_name("help-about-symbolic"))
        about_content.append(Gtk.Label(label=f"Über HS80 Control · {__version__}"))
        about.set_child(about_content)
        about.add_css_class("flat")
        about.set_halign(Gtk.Align.FILL)
        about.connect("clicked", self._show_about)
        sidebar.append(about)
        scroll.set_child(sidebar)
        return scroll

    def _install_breakpoints(self) -> None:
        collapsed = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 900sp")
        )
        collapsed.add_setter(self.split_view, "collapsed", True)
        collapsed.add_setter(self.sidebar_button, "visible", True)
        collapsed.add_setter(self.hero_art, "visible", False)
        self.add_breakpoint(collapsed)

        narrow = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 700sp")
        )
        narrow.add_setter(self.split_view, "collapsed", True)
        narrow.add_setter(self.sidebar_button, "visible", True)
        narrow.add_setter(self.hero_art, "visible", False)
        narrow.add_setter(self.quick_action, "orientation", Gtk.Orientation.VERTICAL)
        narrow.add_setter(self.quick_button, "halign", Gtk.Align.FILL)
        self.add_breakpoint(narrow)

    def _toggle_sidebar(self, _button: Gtk.Button) -> None:
        self.split_view.set_show_sidebar(not self.split_view.get_show_sidebar())

    def _navigation_selected(
        self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if row is None:
            return
        self.stack.set_visible_child_name(row.page_name)
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    def _show_about(self, _button: Gtk.Button) -> None:
        dialog = Adw.AboutDialog(
            application_name="HS80 Control",
            application_icon=APP_ID,
            version=__version__,
            developer_name="HS80 Control contributors",
            website="https://github.com/ST1CKEL/HS80_Control",
            issue_url="https://github.com/ST1CKEL/HS80_Control/issues",
            comments=(
                "Linux-Steuerung für das hardwaregetestete Corsair HS80 RGB "
                "Wireless mit Receiver 1b1c:0a6b und Headset-PID 0a69."
            ),
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.present(self)

    @staticmethod
    def _section_title(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("section-title")
        return label

    @staticmethod
    def _status_card(
        icon_name: str, title: str, purple: bool = False
    ) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label, Gtk.Box]:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        card.add_css_class("status-card")
        card.set_size_request(180, 112)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(27)
        icon.add_css_class("status-card-icon")
        if purple:
            icon.add_css_class("status-card-icon-purple")
        icon.set_valign(Gtk.Align.CENTER)
        card.append(icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("status-card-title")
        value = Gtk.Label(label="--", xalign=0)
        value.add_css_class("status-card-value")
        value.set_ellipsize(3)
        value.set_max_width_chars(17)
        detail = Gtk.Label(label="", xalign=0)
        detail.add_css_class("status-card-detail")
        detail.set_ellipsize(3)
        for label in (heading, detail):
            label.set_max_width_chars(15)
        text_box.append(heading)
        text_box.append(value)
        text_box.append(detail)
        card.append(text_box)
        return card, value, detail, text_box

    def _build_overview_page(self) -> None:
        page = Gtk.ScrolledWindow()
        page.add_css_class("content-background")
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=1400, tightening_threshold=1100)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.add_css_class("dashboard-content")
        clamp.set_child(content)
        page.set_child(clamp)

        self.hero = Adw.WrapBox()
        self.hero.set_child_spacing(24)
        self.hero.set_line_spacing(18)
        self.hero.set_natural_line_length(900)
        self.hero.add_css_class("hero-card")
        self.hero.set_hexpand(True)

        self.hero_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.hero_text.set_hexpand(True)
        self.hero_text.set_valign(Gtk.Align.CENTER)
        kicker = Gtk.Label(label="SUPPORTED RECEIVER · 1B1C:0A6B", xalign=0)
        kicker.add_css_class("hero-kicker")
        product = Gtk.Label(label="CORSAIR HS80\nRGB WIRELESS", xalign=0)
        product.set_wrap(True)
        product.add_css_class("hero-title")
        self.connection_label = Gtk.Label(label="Dienst wird verbunden ...", xalign=0)
        self.connection_label.add_css_class("hero-subtitle")
        self.hero_text.append(kicker)
        self.hero_text.append(product)
        self.hero_text.append(self.connection_label)
        self.hero.append(self.hero_text)

        self.hero_art = HeadsetArt()
        self.hero.append(self.hero_art)

        battery_overlay = Gtk.Overlay()
        battery_overlay.set_size_request(180, 180)
        battery_overlay.set_halign(Gtk.Align.CENTER)
        battery_overlay.set_valign(Gtk.Align.CENTER)
        self.battery_ring = BatteryRing()
        battery_overlay.set_child(self.battery_ring)
        battery_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        battery_text.set_halign(Gtk.Align.CENTER)
        battery_text.set_valign(Gtk.Align.CENTER)
        self.battery_label = Gtk.Label(label="-- %")
        self.battery_label.add_css_class("battery-value")
        self.battery_caption = Gtk.Label(label="AKKU")
        self.battery_caption.add_css_class("battery-caption")
        battery_icon = Gtk.Image.new_from_icon_name("battery-good-symbolic")
        battery_icon.set_pixel_size(24)
        battery_icon.add_css_class("battery-icon")
        battery_text.append(self.battery_label)
        battery_text.append(self.battery_caption)
        battery_text.append(battery_icon)
        battery_overlay.add_overlay(battery_text)
        self.hero.append(battery_overlay)
        content.append(self.hero)

        self.error_banner = Adw.Banner()
        self.error_banner.set_revealed(False)
        self.audio_error_banner = Adw.Banner()
        self.audio_error_banner.set_revealed(False)
        self.spatial_error_banner = Adw.Banner()
        self.spatial_error_banner.set_revealed(False)
        content.append(self.error_banner)
        content.append(self.audio_error_banner)
        content.append(self.spatial_error_banner)

        content.append(self._section_title("Gerätestatus"))
        status = Gtk.FlowBox()
        status.set_selection_mode(Gtk.SelectionMode.NONE)
        status.set_activate_on_single_click(False)
        status.set_homogeneous(True)
        status.set_min_children_per_line(1)
        status.set_max_children_per_line(4)
        status.set_column_spacing(8)
        status.set_row_spacing(12)

        battery_card, self.battery_card_value, self.battery_card_detail, battery_box = (
            self._status_card("battery-good-symbolic", "Akku")
        )
        self.battery_progress = Gtk.ProgressBar()
        self.battery_progress.set_size_request(110, -1)
        self.battery_progress.set_margin_top(4)
        battery_box.append(self.battery_progress)
        status.append(battery_card)

        mic_card, self.mic_card_value, self.mic_card_detail, _ = self._status_card(
            "audio-input-microphone-symbolic", "Mikrofonarm", True
        )
        status.append(mic_card)
        firmware_card, self.firmware_card_value, self.firmware_card_detail, _ = (
            self._status_card("computer-symbolic", "Headset-Firmware")
        )
        status.append(firmware_card)
        receiver_card, self.receiver_card_value, self.receiver_card_detail, _ = (
            self._status_card("network-server-symbolic", "Receiver", True)
        )
        status.append(receiver_card)
        content.append(status)

        content.append(self._section_title("Schnellaktionen"))
        self.quick_action = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.quick_action.add_css_class("quick-card")
        quick_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        quick_text.set_hexpand(True)
        quick_title = Gtk.Label(label="Beleuchtung ausschalten", xalign=0)
        quick_title.add_css_class("quick-title")
        quick_detail = Gtk.Label(
            label="Reduziert den Akkuverbrauch des Headsets", xalign=0
        )
        quick_detail.add_css_class("status-card-detail")
        quick_text.append(quick_title)
        quick_text.append(quick_detail)
        self.quick_action.append(quick_text)
        self.quick_button = Gtk.Button(label="RGB ausschalten")
        self.quick_button.set_valign(Gtk.Align.CENTER)
        self.quick_button.add_css_class("gradient-action")
        self.quick_button.connect("clicked", self._quick_rgb_off)
        self.quick_action.append(self.quick_button)
        content.append(self.quick_action)
        self.stack.add_titled(page, "overview", "Übersicht").set_icon_name("view-dashboard-symbolic")

    def _build_lighting_page(self) -> None:
        page = Adw.PreferencesPage()
        page.add_css_class("settings-page")
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
        self.lighting_mute_banner = Adw.Banner(revealed=False)
        lighting_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lighting_wrapper.append(self.lighting_mute_banner)
        page.set_hexpand(True)
        page.set_vexpand(True)
        lighting_wrapper.append(page)
        self.stack.add_titled(lighting_wrapper, "lighting", "RGB").set_icon_name("preferences-color-symbolic")

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
        page.add_css_class("settings-page")
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
        page.add_css_class("settings-page")
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
        charging = int(self._property("Charging", -1))
        error = str(self._property("LastError", ""))
        mixer_available = bool(self._property("MixerAvailable", False))
        audio_error = str(self._property("AudioError", ""))
        spatial_error = str(self._property("SpatialError", ""))
        firmware = str(self._property("Firmware", ""))
        receiver_firmware = str(self._property("ReceiverFirmware", ""))
        microphone = int(self._property("MicrophoneMuted", -1))

        connection_text, connection_class = _connection_presentation(headset, receiver)
        self.connection_label.set_label(connection_text)
        self.connection_label.remove_css_class("status-online")
        self.connection_label.remove_css_class("status-standby")
        self.connection_label.remove_css_class("status-offline")
        self.connection_label.add_css_class(connection_class)
        battery_text, battery_detail = _battery_presentation(
            battery, charging, connected=headset
        )
        self.battery_label.set_label(battery_text)
        if not headset and battery >= 0:
            self.battery_caption.set_label("LETZTER STAND")
        else:
            self.battery_caption.set_label("LÄDT" if charging == 1 else "AKKU")
        self.battery_ring.set_percent(battery)
        self.battery_progress.set_fraction(max(0, battery) / 100 if battery >= 0 else 0)
        self.battery_card_value.set_label(battery_text)
        self.battery_card_detail.set_label(battery_detail)
        microphone_text, microphone_detail = _microphone_presentation(
            microphone if headset else -1
        )
        self.mic_card_value.set_label(microphone_text)
        self.mic_card_detail.set_label(microphone_detail)
        mute_hint = _lighting_mute_hint(microphone if headset else -1)
        self.lighting_mute_banner.set_title(mute_hint)
        self.lighting_mute_banner.set_revealed(bool(mute_hint))
        self.firmware_card_value.set_label(firmware or "--")
        self.firmware_card_detail.set_label(
            "Gerätefirmware" if firmware else "Noch nicht initialisiert"
        )
        self.receiver_card_value.set_label(receiver_firmware or "--")
        self.receiver_card_detail.set_label(
            "Firmware" if receiver_firmware else "Nicht initialisiert"
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
        modes = ["off", "static", "pulse", "rainbow"]
        try:
            mode = modes[self.rgb_mode.get_selected()]
            rgb_parameters = self._rgb_parameters(mode)
            sleep_minutes = round(self.sleep_spin.get_value())
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=f"Beleuchtungsprofil konnte nicht gelesen werden: {exc}",
                    timeout=5,
                )
            )
            return

        self._lighting_apply_pending = True
        self._set_lighting_controls_sensitive(False)

        def finish(success: bool, applied: bool = False) -> None:
            self._lighting_apply_pending = False
            if success:
                self._lighting_dirty.clear()
                mute_hint = _lighting_mute_hint(
                    int(self._property("MicrophoneMuted", -1))
                )
                if mute_hint:
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=f"Profil gespeichert – {mute_hint}", timeout=6)
                    )
                else:
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
                GLib.Variant("(q)", (sleep_minutes,)),
                after_sleep,
                show_result=False,
            )

        self._call("SetRgb", rgb_parameters, after_rgb, show_result=False)

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
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK
        )
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
