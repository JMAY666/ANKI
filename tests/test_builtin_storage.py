"""Migration must be repeatable, preserve originals, and reject corrupt settings."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "feature_storage", ROOT / "qt/aqt/builtin_features/storage.py"
)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.store = storage.FeatureStorage(self.base)

    def test_fsrs_override_and_unknown_fields_survive_restart(self):
        legacy = self.base / "addons21/759844606/meta.json"
        storage.write_object(
            legacy,
            {
                "disabled": False,
                "config": {"days_to_reschedule": 11, "future_option": "keep"},
            },
        )
        original = legacy.read_bytes()
        self.store.migrate_fsrs()
        value = self.store.load_fsrs()
        self.assertEqual(value["days_to_reschedule"], 11)
        self.assertEqual(value["future_option"], "keep")
        self.assertFalse(value["auto_reschedule_after_sync"])
        value["days_to_reschedule"] = 13
        storage.write_object(self.store.fsrs_path, value)
        restarted = storage.FeatureStorage(self.base)
        restarted.migrate_fsrs()
        self.assertEqual(restarted.load_fsrs()["days_to_reschedule"], 13)
        self.assertEqual(legacy.read_bytes(), original)

    def test_profile_settings_and_retired_data_are_not_overwritten(self):
        profile = self.base / "Profile"
        settings = profile / "SynapsePro_Data/addon_settings.json"
        storage.write_object(settings, {"theme_enabled": False})
        retired = profile / "notebook.sqlite"
        retired.write_bytes(b"preserve original notebook")
        legacy = self.base / "addons21/236979321/addon_settings.json"
        storage.write_object(legacy, {"theme_enabled": True})
        self.store.prepare_profile(profile)
        self.store.prepare_profile(profile)
        self.assertEqual(storage.read_object(settings), {"theme_enabled": False})
        self.assertTrue(legacy.exists())
        self.assertEqual(retired.read_bytes(), b"preserve original notebook")
        self.assertTrue((profile / "SynapsePro_Data/themes/medical_theme.css").exists())

    def test_root_settings_and_remedy_history_are_copied(self):
        legacy = self.base / "addons21/236979321/addon_settings.json"
        storage.write_object(legacy, {"custom": "saved"})
        remedy = self.base / "addons21/759844606/user_files/Test_hard_misuse_remedy.csv"
        remedy.parent.mkdir(parents=True)
        remedy.write_text("1,2,3", encoding="utf8")
        self.store.prepare_profile(self.base / "Profile")
        self.store.migrate_fsrs()
        self.assertEqual(
            legacy.read_bytes(),
            (self.base / "Profile/SynapsePro_Data/addon_settings.json").read_bytes(),
        )
        self.assertEqual(
            remedy.read_bytes(),
            (self.store.root / "fsrs_helper/user_files" / remedy.name).read_bytes(),
        )

    def test_corrupt_legacy_settings_abort_without_writing_defaults(self):
        legacy = self.base / "addons21/759844606/meta.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{corrupt", encoding="utf8")
        with self.assertRaises(json.JSONDecodeError):
            self.store.migrate_fsrs()
        self.assertFalse(self.store.fsrs_path.exists())
        self.assertEqual(legacy.read_text(), "{corrupt")
