"""Assemble one Windows application from this project's wheels and Qt runtime."""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = Path(sys.argv[1]).resolve()
destination = (root / "dist" / sys.argv[2]).resolve()
assert destination.parent == (root / "dist").resolve()
assert not destination.exists(), "Use a new output name; existing builds are preserved"
assert (template / "Anki.exe").is_file()
wheels = sorted((root / "out/wheels").glob("*.whl"))
assert len(wheels) == 2 and {p.name.split("-")[0] for p in wheels} == {"anki", "aqt"}


def ignore_replaced_packages(directory, names):
    if Path(directory).resolve() == template / "app_packages":
        return [
            n for n in names
            if n in ("aqt", "_aqt", "anki")
            or (n.startswith(("anki-", "aqt-")) and n.endswith(".dist-info"))
        ]
    return [n for n in names if n == "__pycache__"]


shutil.copytree(template, destination, ignore=ignore_replaced_packages)
packages = destination / "app_packages"
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            target = (packages / member.filename).resolve()
            assert target.is_relative_to(packages)
        archive.extractall(packages)
required = [
    "aqt/main.py", "aqt/builtin_features/__init__.py",
    "aqt/builtin_features/synapsepro/chat_ui.html",
    "aqt/builtin_features/fsrs_helper/locale/zh_CN.json",
    "aqt/builtin_features/fsrs_helper/python_i18n/i18n/__init__.py",
    "aqt/builtin_features/learning/workspace.py",
    "aqt/builtin_features/learning/provider.py",
    "aqt/builtin_features/protected_secrets.py",
]
for name in required:
    assert (packages / name).is_file(), name
from verify_web_runtime import verify

verify(packages / "_aqt/data/web/sveltekit")
assert not (destination / "addons21").exists()
manifest = {
    "edition": "Anki 26.8.1 with built-in SynapsePro and FSRS Helper",
    "synapsepro": "1.6.0-local, d7b6c5e20 (DeepSeek changes from 4eed59734)",
    "fsrs_helper": "26.05.08, prepared checkout 85ad582; runtime c7219f5",
    "learning_workspace": "1: native review, scoped statistics and confirmed daily DeepSeek suggestions",
    "wheels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels},
    "runtime": "Existing Anki 26.8.1 Windows Python/Qt launcher and dependencies",
}
(destination / "INTEGRATED-BUILD.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
print(destination, flush=True)
