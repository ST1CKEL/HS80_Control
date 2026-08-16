from __future__ import annotations

from types import SimpleNamespace
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

    def test_charging_cable_outranks_the_receiver_state(self) -> None:
        # The cable carries no audio either way, so it is the useful label.
        self.assertEqual(
            ("●  Headset am Ladekabel · kein Ton", "status-standby"),
            self.gui._connection_presentation(False, True, True),
        )
        self.assertEqual(
            ("●  Headset am Ladekabel · Receiver fehlt", "status-offline"),
            self.gui._connection_presentation(False, False, True),
        )
        # A live wireless link still wins over a plugged-in cable.
        self.assertEqual(
            ("●  Verbunden", "status-online"),
            self.gui._connection_presentation(True, True, True),
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

    def test_gtk_rgba_is_serialized_for_rgb_dbus_calls(self) -> None:
        self.assertEqual("#12abef", self.gui._hex_color(self.gui._rgba("#12abef")))

    def test_lighting_mute_hint_appears_only_while_muted(self) -> None:
        self.assertEqual("", self.gui._lighting_mute_hint(0))
        self.assertEqual("", self.gui._lighting_mute_hint(-1))
        hint = self.gui._lighting_mute_hint(1)
        self.assertIn("hochgeklappt", hint)
        self.assertIn("Runterklappen", hint)

    def test_rgb_dbus_parameters_use_real_gtk_colors(self) -> None:
        page = SimpleNamespace(
            rgb_brightness=SimpleNamespace(get_value=lambda: 42),
            logo_color=SimpleNamespace(get_rgba=lambda: self.gui._rgba("#123456")),
            indicator_color=SimpleNamespace(
                get_rgba=lambda: self.gui._rgba("#abcdef")
            ),
            microphone_color=SimpleNamespace(
                get_rgba=lambda: self.gui._rgba("#fedcba")
            ),
        )

        parameters = self.gui.HS80Window._rgb_parameters(page, "static")

        self.assertEqual("(sysss)", parameters.get_type_string())
        self.assertEqual(
            ("static", 42, "#123456", "#abcdef", "#fedcba"),
            parameters.unpack(),
        )

    def test_rgb_profile_read_error_does_not_lock_controls(self) -> None:
        class ToastRecorder:
            def __init__(self) -> None:
                self.toasts = []

            def add_toast(self, toast: object) -> None:
                self.toasts.append(toast)

        class BrokenLightingPage:
            _lighting_apply_pending = False
            rgb_mode = SimpleNamespace(get_selected=lambda: 1)
            sleep_spin = SimpleNamespace(get_value=lambda: 15)
            toast_overlay = ToastRecorder()

            @staticmethod
            def _rgb_parameters(_mode: str) -> object:
                raise AttributeError("invalid color")

            @staticmethod
            def _set_lighting_controls_sensitive(_sensitive: bool) -> None:
                raise AssertionError("controls must not be disabled")

        page = BrokenLightingPage()
        self.gui.HS80Window._apply_lighting(page, None)

        self.assertFalse(page._lighting_apply_pending)
        self.assertEqual(1, len(page.toast_overlay.toasts))


if __name__ == "__main__":
    unittest.main()
