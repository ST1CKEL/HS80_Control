from __future__ import annotations

import unittest


def _gio_available() -> bool:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


@unittest.skipUnless(_gio_available(), "PyGObject is not installed")
class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from gi.repository import GLib

        from hs80_control import tray

        cls.tray = tray
        cls.GLib = GLib

    def test_menu_layout_matches_the_dbusmenu_signature(self) -> None:
        layout = self.tray.menu_layout(0)
        # Raises if the nested structure does not fit the wire type.
        variant = self.GLib.Variant("(u(ia{sv}av))", (1, layout))
        _revision, (root_id, properties, children) = variant.unpack()
        self.assertEqual(0, root_id)
        self.assertEqual("submenu", properties["children-display"])
        self.assertEqual(
            [self.tray.MENU_OPEN, self.tray.MENU_SEPARATOR, self.tray.MENU_QUIT],
            [child[0] for child in children],
        )
        self.assertEqual("Beenden", children[2][1]["label"])

    def test_single_item_layout_has_no_children(self) -> None:
        item_id, properties, children = self.tray.menu_layout(self.tray.MENU_QUIT)
        self.assertEqual(self.tray.MENU_QUIT, item_id)
        self.assertEqual("Beenden", properties["label"].unpack())
        self.assertEqual([], children)

    def test_gnome_gets_a_symbolic_icon(self) -> None:
        self.assertEqual("audio-headset", self.tray.icon_name("KDE"))
        self.assertEqual("audio-headset", self.tray.icon_name(""))
        self.assertEqual("audio-headset-symbolic", self.tray.icon_name("GNOME"))
        self.assertEqual(
            "audio-headset-symbolic", self.tray.icon_name("ubuntu:GNOME")
        )
        self.assertFalse(self.tray.is_gnome("GNOME-Flashback-Not"))

    def test_tooltip_reflects_headset_state(self) -> None:
        self.assertEqual("Headset offline", self.tray.tooltip_text(False, 80, False))
        self.assertEqual("Headset verbunden", self.tray.tooltip_text(True, -1, False))
        self.assertEqual("Akku 80 %", self.tray.tooltip_text(True, 80, False))
        self.assertEqual("Akku 80 % · lädt", self.tray.tooltip_text(True, 80, True))

    def test_menu_clicks_reach_the_callbacks_and_unstarted_icon_is_inert(self) -> None:
        calls: list[str] = []
        icon = self.tray.TrayIcon(
            "test.App", lambda: calls.append("open"), lambda: calls.append("quit")
        )
        self.assertFalse(icon.available)
        icon.set_tooltip("Akku 5 %")  # no connection: must not raise
        icon.stop()

        icon._menu_event(self.tray.MENU_OPEN, "hovered")
        icon._menu_event(self.tray.MENU_OPEN, "clicked")
        icon._menu_event(self.tray.MENU_QUIT, "clicked")
        context = self.GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        self.assertEqual(["open", "quit"], calls)


if __name__ == "__main__":
    unittest.main()
