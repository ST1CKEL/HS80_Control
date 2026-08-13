from __future__ import annotations

import unittest


def _gui_dependencies_available() -> bool:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


GUI_DEPENDENCIES_AVAILABLE = _gui_dependencies_available()


@unittest.skipUnless(
    GUI_DEPENDENCIES_AVAILABLE,
    "PyGObject, GTK 4 or libadwaita is not installed",
)
class GuiPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from hs80_control import gui

        cls.gui = gui

    def test_connection_states_are_distinct(self) -> None:
        self.assertEqual(
            ("●  Verbunden", "status-online"),
            self.gui._connection_presentation(True, True),
        )
        self.assertEqual(
            ("●  Receiver bereit · Headset offline", "status-standby"),
            self.gui._connection_presentation(False, True),
        )
        self.assertEqual(
            ("●  Receiver offline", "status-offline"),
            self.gui._connection_presentation(False, False),
        )

    def test_battery_state_handles_unknown_and_charging(self) -> None:
        self.assertEqual(
            ("-- %", "Noch kein Akkureport"),
            self.gui._battery_presentation(-1, -1),
        )
        self.assertEqual(
            ("97 %", "97 Prozent · lädt"),
            self.gui._battery_presentation(97, 1),
        )
        self.assertEqual(
            ("97 %", "97 Prozent · letzter Stand"),
            self.gui._battery_presentation(97, 1, connected=False),
        )

    def test_physical_microphone_arm_state_is_explained(self) -> None:
        self.assertEqual(
            ("Stummgeschaltet", "Arm hochgeklappt"),
            self.gui._microphone_presentation(1),
        )
        self.assertEqual(
            ("Aktiv", "Arm heruntergeklappt"),
            self.gui._microphone_presentation(0),
        )
        self.assertEqual(
            ("Unbekannt", "Noch kein Hardwarestatus"),
            self.gui._microphone_presentation(-1),
        )


if __name__ == "__main__":
    unittest.main()
