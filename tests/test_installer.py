import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "hs80_installer", ROOT / "installer" / "hs80_installer.py"
)
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)


class InstallerLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_both_languages_cover_the_same_texts(self) -> None:
        self.assertEqual(set(installer.TEXT["de"]), set(installer.TEXT["en"]))
        self.assertEqual(set(installer.LANGUAGES), set(installer.TEXT))

    def test_desktop_detection(self) -> None:
        self.assertEqual("kde", installer.detect_desktop("KDE"))
        self.assertEqual("gnome", installer.detect_desktop("GNOME"))
        self.assertEqual("gnome", installer.detect_desktop("ubuntu:GNOME"))
        self.assertEqual("xfce", installer.detect_desktop("XFCE"))
        self.assertEqual("unknown", installer.detect_desktop(""))
        self.assertEqual("KDE Plasma", installer.desktop_label("kde", "en"))
        self.assertEqual("Andere (xfce)", installer.desktop_label("xfce", "de"))

    def test_language_is_merged_into_existing_preferences(self) -> None:
        path = self.directory / "hs80-control" / "app.json"
        installer.write_language("en", path)
        self.assertEqual({"language": "en"}, json.loads(path.read_text("utf-8")))
        path.write_text(json.dumps({"tray": False, "language": "en"}), "utf-8")
        installer.write_language("de", path)
        self.assertEqual(
            {"tray": False, "language": "de"}, json.loads(path.read_text("utf-8"))
        )
        with self.assertRaises(ValueError):
            installer.write_language("fr", path)

    def test_app_reads_the_language_the_installer_wrote(self) -> None:
        from hs80_control import i18n
        from hs80_control.autostart import AppSettings

        path = self.directory / "app.json"
        installer.write_language("en", path)
        self.assertEqual("en", i18n.stored_language(path))
        self.assertEqual("en", AppSettings(path).language)

    def test_autostart_off_masks_and_on_unmasks_the_packaged_entry(self) -> None:
        from hs80_control.autostart import Autostart

        system = self.directory / "etc" / "autostart"
        system.mkdir(parents=True)
        entry = system / installer.DESKTOP_FILE
        entry.write_text(
            (ROOT / "data" / "autostart" / installer.DESKTOP_FILE).read_text("utf-8"),
            "utf-8",
        )
        user = self.directory / "user"
        autostart = Autostart(user_dir=user, system_dirs=[system])
        self.assertTrue(autostart.is_enabled())
        installer.set_autostart(False, user, entry)
        self.assertFalse(autostart.is_enabled())
        installer.set_autostart(True, user, entry)
        self.assertTrue(autostart.is_enabled())
        self.assertFalse((user / installer.DESKTOP_FILE).exists())

    def test_bundled_package_is_found_next_to_the_installer(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(installer.RPM_VARIABLE, None)
            self.assertIsNone(installer.find_bundled_rpm(self.directory))
            for version in ("0.7.1", "0.8.0"):
                (self.directory / f"hs80-control-{version}-1.fc45.noarch.rpm").touch()
            self.assertEqual(
                "hs80-control-0.8.0-1.fc45.noarch.rpm",
                installer.find_bundled_rpm(self.directory).name,
            )

    def test_release_asset_must_be_our_package_from_github(self) -> None:
        good = {
            "name": "hs80-control-0.8.0-1.fc45.noarch.rpm",
            "browser_download_url": "https://github.com/ST1CKEL/HS80_Control/releases/download/v0.8.0/hs80-control-0.8.0-1.fc45.noarch.rpm",
        }
        self.assertEqual(
            (good["name"], good["browser_download_url"]),
            installer.pick_release_asset({"assets": [{"name": "notes.txt"}, good]}),
        )
        elsewhere = dict(good, browser_download_url="https://example.org/x.rpm")
        self.assertIsNone(installer.pick_release_asset({"assets": [elsewhere]}))
        self.assertIsNone(installer.pick_release_asset({"assets": []}))
        self.assertIsNone(installer.pick_release_asset([]))

    def test_install_command_passes_packages_as_arguments(self) -> None:
        rpm = Path("/tmp/with space/hs80-control-0.8.0-1.fc45.noarch.rpm")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(installer.DRY_RUN_VARIABLE, None)
            command = installer.install_command(rpm, [installer.GNOME_TRAY_PACKAGE])
        self.assertEqual(["pkexec", "/bin/sh", "-c"], command[:3])
        # The path is an argument, never part of the shell script itself.
        self.assertNotIn(str(rpm), command[3])
        self.assertEqual([str(rpm), installer.GNOME_TRAY_PACKAGE], command[5:])
        with mock.patch.dict(os.environ, {installer.DRY_RUN_VARIABLE: "1"}):
            self.assertEqual("/bin/echo", installer.install_command(rpm, [])[0])


if __name__ == "__main__":
    unittest.main()
