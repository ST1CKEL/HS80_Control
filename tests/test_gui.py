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

    def test_usb_mode_is_named_in_the_connection_label(self) -> None:
        self.assertEqual(
            ("●  Verbunden · USB-Kabel", "status-online"),
            self.gui._connection_presentation(True, False, False, "usb"),
        )
        self.assertEqual(
            ("●  Verbunden", "status-online"),
            self.gui._connection_presentation(True, True, False, "wireless"),
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

    def test_missing_tray_is_explained_per_desktop(self) -> None:
        normal = "Schließen minimiert das Fenster, statt das Programm zu beenden"
        self.assertEqual(normal, self.gui._tray_subtitle(True, True, False))
        self.assertEqual(normal, self.gui._tray_subtitle(False, False, True))
        self.assertIn("AppIndicator", self.gui._tray_subtitle(True, False, True))
        self.assertIn(
            "Schließen beendet", self.gui._tray_subtitle(True, False, False)
        )

    def test_battery_warning_switch_names_the_thresholds(self) -> None:
        self.assertEqual(
            "Desktop-Benachrichtigung ab 20 %, dringlich ab 10 %",
            self.gui._battery_warning_subtitle(20, 10),
        )

    def test_low_battery_is_called_out_unless_charging(self) -> None:
        self.assertEqual(
            ("20 %", "20 Prozent · niedrig, bitte laden"),
            self.gui._battery_presentation(20, 0),
        )
        self.assertEqual(
            ("21 %", "21 Prozent"), self.gui._battery_presentation(21, -1)
        )
        self.assertEqual(
            ("12 %", "12 Prozent · lädt"), self.gui._battery_presentation(12, 1)
        )
        self.assertEqual(
            ("30 %", "30 Prozent · niedrig, bitte laden"),
            self.gui._battery_presentation(30, 0, low_percent=30),
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
            _lighting_dirty = {"logo"}
            rgb_mode = SimpleNamespace(get_selected=lambda: 1)
            sleep_spin = SimpleNamespace(get_value=lambda: 15)
            toast_overlay = ToastRecorder()

            @staticmethod
            def _rgb_parameters(_mode: str) -> object:
                raise AttributeError("invalid color")

        page = BrokenLightingPage()
        self.gui.HS80Window._apply_lighting(page, None)

        self.assertFalse(page._lighting_apply_pending)
        self.assertEqual(1, len(page.toast_overlay.toasts))

    def test_live_update_sends_only_the_changed_groups(self) -> None:
        sent: list[tuple[str, tuple[object, ...]]] = []

        class Page:
            _lighting_apply_pending = False
            _lighting_timer = 0
            rgb_mode = SimpleNamespace(get_selected=lambda: 4)
            rgb_speed = SimpleNamespace(get_value=lambda: 5)
            sleep_spin = SimpleNamespace(get_value=lambda: 15)
            mute_indicator_switch = SimpleNamespace(get_active=lambda: False)
            battery_saver = SimpleNamespace(get_selected=lambda: 1)
            toast_overlay = SimpleNamespace(add_toast=lambda _toast: None)
            synced = 0

            def __init__(page, gui: object) -> None:
                page._lighting_dirty = {"speed", "battery_saver"}
                page.mute_color = SimpleNamespace(
                    get_rgba=lambda: gui._rgba("#ff8800")
                )
                page._rgb_option_parameters = (
                    lambda: gui.HS80Window._rgb_option_parameters(page)
                )
                page._finish_lighting = (
                    lambda: gui.HS80Window._finish_lighting(page)
                )

            def _rgb_parameters(page, _mode: str) -> object:
                raise AssertionError("colours did not change")

            def _call(page, method, parameters, callback, show_result=True):
                sent.append((method, parameters.unpack()))
                callback(True, True)

            def _sync_state(page) -> None:
                page.synced += 1

        page = Page(self.gui)
        self.gui.HS80Window._apply_lighting(page, None)

        self.assertEqual(
            [("UpdateRgbOptions", (5, 0, "#ff8800", "dim"))], sent
        )
        self.assertEqual(set(), page._lighting_dirty)
        self.assertFalse(page._lighting_apply_pending)
        self.assertEqual(1, page.synced)


if __name__ == "__main__":
    unittest.main()
