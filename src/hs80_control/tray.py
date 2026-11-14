"""System tray icon via the StatusNotifierItem protocol.

GTK 4 has no tray API, and the usual helper libraries are GTK 3 only. The
protocol itself is two small D-Bus objects -- the item and its context menu
(com.canonical.dbusmenu) -- so they are implemented here directly on Gio.
KDE Plasma supports this natively; GNOME needs the "AppIndicator and
KStatusNotifierItem Support" extension, whose left click opens the menu.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import os

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .i18n import tr as _  # noqa: E402


LOG = logging.getLogger(__name__)

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

MENU_OPEN = 1
MENU_SEPARATOR = 2
MENU_QUIT = 3

_ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>
"""

_MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" direction="in"/><arg type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/>
      <arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})"/><arg type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
  </interface>
</node>
"""


def is_gnome(desktop: str | None = None) -> bool:
    value = os.environ.get("XDG_CURRENT_DESKTOP", "") if desktop is None else desktop
    return "gnome" in value.lower().split(":")


def icon_name(desktop: str | None = None) -> str:
    # Adwaita ships the headset only as a symbolic icon, and GNOME's top bar
    # expects symbolic icons anyway; Plasma themes carry the plain name.
    return "audio-headset-symbolic" if is_gnome(desktop) else "audio-headset"


def menu_items() -> dict[int, dict[str, GLib.Variant]]:
    return {
        MENU_OPEN: {
            "label": GLib.Variant("s", _("HS80 Control öffnen")),
            "icon-name": GLib.Variant("s", icon_name()),
        },
        MENU_SEPARATOR: {"type": GLib.Variant("s", "separator")},
        MENU_QUIT: {
            "label": GLib.Variant("s", _("Beenden")),
            "icon-name": GLib.Variant("s", "application-exit"),
        },
    }


def menu_layout(parent: int = 0) -> tuple[int, dict[str, GLib.Variant], list[GLib.Variant]]:
    """The (id, properties, children) tree dbusmenu's GetLayout returns."""

    items = menu_items()
    if parent in items:
        return (parent, items[parent], [])
    children = [
        GLib.Variant("(ia{sv}av)", (item_id, properties, []))
        for item_id, properties in items.items()
    ]
    return (0, {"children-display": GLib.Variant("s", "submenu")}, children)


def tooltip_text(connected: bool, battery: int, charging: bool) -> str:
    if not connected:
        return "Headset offline"
    if battery < 0:
        return _("Headset verbunden")
    return _("Akku {percent} %").format(percent=battery) + (
        _(" · lädt") if charging else ""
    )


class TrayIcon:
    """One tray item. ``start`` is safe to call without a tray present."""

    def __init__(
        self,
        app_id: str,
        on_activate: Callable[[], None],
        on_quit: Callable[[], None],
        on_available_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._app_id = app_id
        self._on_activate = on_activate
        self._on_quit = on_quit
        self._on_available_changed = on_available_changed
        self._connection: Gio.DBusConnection | None = None
        self._watch_id = 0
        self._registered = False
        self._tooltip = "HS80 Control"
        self._item_info = Gio.DBusNodeInfo.new_for_xml(_ITEM_XML).interfaces[0]
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]

    @property
    def available(self) -> bool:
        """True while a tray host has accepted the item."""

        return self._registered

    def start(self) -> None:
        if self._connection is not None:
            return
        try:
            # A private connection: closing it is the only reliable way to
            # make the watcher drop the item again when the tray is switched
            # off, because hosts track items by bus name.
            self._connection = Gio.DBusConnection.new_for_address_sync(
                Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None,
                None,
            )
            self._connection.set_exit_on_close(False)
            self._connection.register_object(
                ITEM_PATH, self._item_info, self._item_call, self._item_get, None
            )
            self._connection.register_object(
                MENU_PATH, self._menu_info, self._menu_call, self._menu_get, None
            )
        except GLib.Error as exc:
            LOG.warning("tray icon unavailable: %s", exc.message)
            self._connection = None
            return
        # Registers now if a tray exists and again whenever one (re)appears,
        # e.g. after plasmashell restarts.
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._watcher_appeared,
            self._watcher_vanished,
        )

    def stop(self) -> None:
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close_sync(None)
            except GLib.Error:
                pass
        self._set_registered(False)

    def set_tooltip(self, text: str) -> None:
        if text == self._tooltip:
            return
        self._tooltip = text
        self._emit("NewToolTip", None)

    def _set_registered(self, registered: bool) -> None:
        if registered != self._registered:
            self._registered = registered
            if self._on_available_changed is not None:
                self._on_available_changed(registered)

    def _watcher_appeared(self, connection: Gio.DBusConnection, *_: object) -> None:
        connection.call(
            WATCHER_NAME,
            WATCHER_PATH,
            WATCHER_NAME,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (ITEM_PATH,)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            self._register_finished,
        )

    def _register_finished(
        self, connection: Gio.DBusConnection, result: Gio.AsyncResult
    ) -> None:
        try:
            connection.call_finish(result)
        except GLib.Error as exc:
            LOG.warning("tray registration failed: %s", exc.message)
            self._set_registered(False)
            return
        self._set_registered(self._connection is not None)

    def _watcher_vanished(self, *_: object) -> None:
        self._set_registered(False)

    def _emit(self, signal: str, parameters: GLib.Variant | None) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(
                None, ITEM_PATH, "org.kde.StatusNotifierItem", signal, parameters
            )
        except GLib.Error:
            pass

    # -- org.kde.StatusNotifierItem ------------------------------------

    def _item_get(self, _connection, _sender, _path, _interface, name):
        values = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", self._app_id),
            "Title": GLib.Variant("s", "HS80 Control"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", icon_name()),
            "IconThemePath": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)", (icon_name(), [], "HS80 Control", self._tooltip)
            ),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(name)

    def _item_call(
        self, _connection, _sender, _path, _interface, method, _parameters, invocation
    ) -> None:
        invocation.return_value(None)
        if method in {"Activate", "SecondaryActivate"}:
            # Leave the D-Bus dispatch before touching windows.
            GLib.idle_add(self._run, self._on_activate)

    @staticmethod
    def _run(callback: Callable[[], None]) -> bool:
        callback()
        return GLib.SOURCE_REMOVE

    # -- com.canonical.dbusmenu ----------------------------------------

    def _menu_get(self, _connection, _sender, _path, _interface, name):
        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return values.get(name)

    def _menu_event(self, item_id: int, event: str) -> None:
        if event != "clicked":
            return
        if item_id == MENU_OPEN:
            GLib.idle_add(self._run, self._on_activate)
        elif item_id == MENU_QUIT:
            GLib.idle_add(self._run, self._on_quit)

    def _menu_call(
        self, _connection, _sender, _path, _interface, method, parameters, invocation
    ) -> None:
        arguments = parameters.unpack()
        if method == "GetLayout":
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (1, menu_layout(arguments[0])))
            )
        elif method == "GetGroupProperties":
            items = menu_items()
            wanted = arguments[0] or list(items)
            invocation.return_value(
                GLib.Variant(
                    "(a(ia{sv}))",
                    ([(i, items[i]) for i in wanted if i in items],),
                )
            )
        elif method == "GetProperty":
            value = menu_items().get(arguments[0], {}).get(arguments[1])
            invocation.return_value(
                GLib.Variant("(v)", (value or GLib.Variant("s", ""),))
            )
        elif method == "Event":
            invocation.return_value(None)
            self._menu_event(arguments[0], arguments[1])
        elif method == "EventGroup":
            invocation.return_value(GLib.Variant("(ai)", ([],)))
            for item_id, event, _data, _timestamp in arguments[0]:
                self._menu_event(item_id, event)
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", method
            )
