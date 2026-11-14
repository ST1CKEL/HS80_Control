from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hs80_control.autostart import AUTOSTART_FILENAME, AppSettings, Autostart


class AutostartTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.user_dir = root / "home" / "autostart"
        self.system_dir = root / "etc" / "autostart"
        self.autostart = Autostart(
            self.user_dir, [self.system_dir], command="/usr/bin/hs80-control"
        )

    def install_system_entry(self) -> Path:
        self.system_dir.mkdir(parents=True)
        path = self.system_dir / AUTOSTART_FILENAME
        path.write_text(
            (Path(__file__).parent.parent / "data/autostart" / AUTOSTART_FILENAME).read_text()
        )
        return path

    def test_packaged_entry_enables_autostart_by_default(self) -> None:
        self.assertFalse(self.autostart.is_enabled())
        self.install_system_entry()
        self.assertTrue(self.autostart.is_enabled())

    def test_switching_off_masks_the_packaged_entry_without_touching_it(self) -> None:
        system = self.install_system_entry()
        before = system.read_text()

        self.autostart.set_enabled(False)

        self.assertFalse(self.autostart.is_enabled())
        self.assertEqual(before, system.read_text())
        self.assertIn("Hidden=true", self.autostart.user_path.read_text())

        self.autostart.set_enabled(True)
        self.assertTrue(self.autostart.is_enabled())
        # The mask is gone; the packaged entry is the single source again.
        self.assertFalse(self.autostart.user_path.exists())

    def test_user_install_writes_its_own_background_entry(self) -> None:
        self.autostart.set_enabled(True)
        content = self.autostart.user_path.read_text()
        self.assertIn("Exec=/usr/bin/hs80-control --background\n", content)
        self.assertNotIn("Hidden", content)
        self.assertTrue(self.autostart.is_enabled())

        self.autostart.set_enabled(False)
        self.assertFalse(self.autostart.is_enabled())

    def test_hidden_only_counts_inside_the_desktop_entry_group(self) -> None:
        self.user_dir.mkdir(parents=True)
        self.autostart.user_path.write_text(
            "[Desktop Entry]\nType=Application\nExec=x\n\n[Other]\nHidden=true\n"
        )
        self.assertTrue(self.autostart.is_enabled())


    def test_gnome_tweaks_switch_is_respected(self) -> None:
        self.install_system_entry()
        self.user_dir.mkdir(parents=True)
        self.autostart.user_path.write_text(
            "[Desktop Entry]\nType=Application\nExec=x\n"
            "X-GNOME-Autostart-enabled=false\n"
        )
        self.assertFalse(self.autostart.is_enabled())


class AppSettingsTests(unittest.TestCase):
    def test_tray_defaults_on_and_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hs80-control" / "app.json"
            settings = AppSettings(path)
            self.assertTrue(settings.tray)
            settings.set_tray(False)
            self.assertFalse(AppSettings(path).tray)

    def test_damaged_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.json"
            for content in ("{broken", '["tray"]', '{"tray": "no"}'):
                path.write_text(content)
                self.assertTrue(AppSettings(path).tray)


if __name__ == "__main__":
    unittest.main()
