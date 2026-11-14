import ast
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from hs80_control import i18n
from hs80_control.autostart import AppSettings
from hs80_control.notifications import notification_text


SOURCES = Path(i18n.__file__).resolve().parent
LABEL_TUPLES = ("RGB_MODE_LABELS", "BATTERY_SAVER_LABELS")


def _translated_keys() -> set[str]:
    keys: set[str] = set()
    for path in SOURCES.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                keys.add(node.args[0].value)
            elif isinstance(node, ast.Assign) and any(
                getattr(target, "id", "") in LABEL_TUPLES for target in node.targets
            ):
                keys.update(element.value for element in node.value.elts)
    return keys


class LanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())

    def test_german_is_returned_unchanged(self) -> None:
        i18n.set_language("de")
        self.assertEqual("Beenden", i18n.tr("Beenden"))

    def test_english_translates_and_falls_back(self) -> None:
        i18n.set_language("en")
        self.assertEqual("Quit", i18n.tr("Beenden"))
        self.assertEqual("nicht im Katalog", i18n.tr("nicht im Katalog"))

    def test_unknown_language_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            i18n.set_language("fr")

    def test_every_marked_text_has_an_english_translation(self) -> None:
        self.assertEqual(set(), _translated_keys() - set(i18n._ENGLISH))

    def test_catalogue_has_no_stale_entries(self) -> None:
        self.assertEqual(set(), set(i18n._ENGLISH) - _translated_keys())

    def test_placeholders_survive_translation(self) -> None:
        for german, english in i18n._ENGLISH.items():
            self.assertEqual(
                sorted(re.findall(r"\{\w+\}", german)),
                sorted(re.findall(r"\{\w+\}", english)),
                german,
            )

    def test_notification_follows_the_language(self) -> None:
        i18n.set_language("en")
        summary, body = notification_text("critical", 7)
        self.assertEqual("HS80: battery almost empty", summary)
        self.assertIn("7 % left", body)
        i18n.set_language("de")
        self.assertEqual("HS80: Akku niedrig", notification_text("low", 18)[0])


class LanguageResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "app.json"

    def _environment(self, **values: str) -> mock._patch_dict:
        clean = {
            key: value
            for key, value in os.environ.items()
            if key
            not in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG", i18n.ENVIRONMENT_VARIABLE)
        }
        clean.update(values)
        return mock.patch.dict(os.environ, clean, clear=True)

    def test_system_language_decides_before_the_first_choice(self) -> None:
        with self._environment(LANG="de_DE.UTF-8"):
            self.assertEqual("de", i18n.resolve(self.path))
        with self._environment(LANG="fr_FR.UTF-8"):
            self.assertEqual("en", i18n.resolve(self.path))
        with self._environment(LANG="C"):
            self.assertEqual("en", i18n.resolve(self.path))

    def test_stored_choice_outranks_the_system_language(self) -> None:
        self.path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        with self._environment(LANG="de_DE.UTF-8"):
            self.assertEqual("en", i18n.init(self.path))
            self.assertEqual("en", i18n.language())

    def test_environment_override_outranks_the_stored_choice(self) -> None:
        self.path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        with self._environment(HS80_CONTROL_LANGUAGE="de"):
            self.assertEqual("de", i18n.resolve(self.path))

    def test_damaged_or_foreign_value_counts_as_no_choice(self) -> None:
        self.path.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
        self.assertIsNone(i18n.stored_language(self.path))
        self.path.write_text("{", encoding="utf-8")
        self.assertIsNone(i18n.stored_language(self.path))

    def test_settings_store_the_language_next_to_the_rest(self) -> None:
        settings = AppSettings(self.path)
        self.assertIsNone(settings.language)
        settings.set_tray(False)
        self.assertNotIn("language", json.loads(self.path.read_text("utf-8")))
        settings.set_language("en")
        reloaded = AppSettings(self.path)
        self.assertEqual("en", reloaded.language)
        self.assertFalse(reloaded.tray)
        self.assertEqual("en", i18n.stored_language(self.path))
        with self.assertRaises(ValueError):
            settings.set_language("fr")


if __name__ == "__main__":
    unittest.main()
