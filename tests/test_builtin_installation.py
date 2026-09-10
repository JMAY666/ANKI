"""Exercise installation and recovery on disposable files, never real Anki data."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows installer")
class InstallationTests(unittest.TestCase):
    def test_install_and_restore_preserve_old_program_config_and_new_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image, install, data, backup = (root / name for name in ("image", "Anki", "Anki2", "backup"))
            for path in (image, install, backup, data / "addons21/759844606"):
                path.mkdir(parents=True)
            (image / "Anki.exe").write_bytes(b"integrated program fixture")
            (image / "INTEGRATED-BUILD.json").write_text("{}")
            (install / "Anki.exe").write_bytes(b"original program fixture")
            (backup / "sha256-manifest.json").write_text("{}")
            meta = data / "addons21/759844606/meta.json"
            original = {"disabled": False, "config": {"days_to_reschedule": 9}, "custom": "keep"}
            meta.write_text(json.dumps(original))
            (data / "prefs21.db").write_bytes(b"original preferences")
            shutil.copytree(data, backup / "Anki2")
            subprocess.run([
                "pwsh", "-NoProfile", "-File", str(ROOT / "scripts/install_builtin.ps1"),
                "-ImagePath", str(image), "-InstallPath", str(install),
                "-BackupPath", str(backup), "-DataPath", str(data),
            ], check=True, capture_output=True)
            self.assertEqual((install / "Anki.exe").read_bytes(), b"integrated program fixture")
            migrated = json.loads(meta.read_text(encoding="utf8"))
            self.assertTrue(migrated["disabled"])
            self.assertEqual(migrated["config"], original["config"])
            new_data = data / "new-learning-record"
            new_data.write_bytes(b"preserve learning since installation")
            subprocess.run([
                "pwsh", "-NoProfile", "-File", str(ROOT / "scripts/remove_legacy_addons.ps1"),
                "-DataPath", str(data), "-BackupPath", str(backup),
            ], check=True, capture_output=True)
            self.assertFalse(meta.parent.exists())
            subprocess.run([
                "pwsh", "-NoProfile", "-File", str(ROOT / "scripts/restore_builtin.ps1"),
                "-BackupPath", str(backup),
            ], check=True, capture_output=True)
            self.assertEqual((install / "Anki.exe").read_bytes(), b"original program fixture")
            self.assertEqual(json.loads(meta.read_text(encoding="utf8")), original)
            self.assertEqual(new_data.read_bytes(), b"preserve learning since installation")
            subprocess.run([
                "pwsh", "-NoProfile", "-File", str(ROOT / "scripts/restore_builtin.ps1"),
                "-BackupPath", str(backup), "-RestoreUserData",
            ], check=True, capture_output=True)
            self.assertFalse(new_data.exists())
            retained = list(root.glob("Anki2.before-restore-*/new-learning-record"))
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].read_bytes(), b"preserve learning since installation")
