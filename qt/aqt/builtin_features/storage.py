# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Local settings and copy-only migration for Anki's built-in study tools."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

LEGACY_IDS = {
    "236979321": "synapsepro",
    "SynapsePro1": "synapsepro",
    "759844606": "fsrs_helper",
}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def copy_missing(source: Path, destination: Path) -> None:
    """Never overwrite migrated data or delete its source."""
    if source.is_dir():
        for path in source.rglob("*"):
            if path.is_file():
                copy_missing(path, destination / path.relative_to(source))
    elif source.is_file() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


class FeatureStorage:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = base / "builtin_features"
        self.fsrs_path = self.root / "fsrs_helper.json"
        self.defaults = read_object(Path(__file__).parent / "fsrs_helper/config.json")

    def migrate_fsrs(self) -> None:
        if not self.fsrs_path.exists():
            settings = dict(self.defaults)
            legacy = self.base / "addons21/759844606"
            if (legacy / "config.json").exists():
                settings.update(read_object(legacy / "config.json"))
            if (legacy / "meta.json").exists():
                override = read_object(legacy / "meta.json").get("config", {})
                if not isinstance(override, dict):
                    raise ValueError("FSRS Helper legacy config must be an object")
                settings.update(override)
            write_object(self.fsrs_path, settings)
        copy_missing(
            self.base / "addons21/759844606/user_files",
            self.root / "fsrs_helper/user_files",
        )

    def load_fsrs(self) -> dict[str, Any]:
        settings = dict(self.defaults)
        settings.update(read_object(self.fsrs_path))
        return settings

    def prepare_profile(self, profile: Path) -> None:
        data = profile / "SynapsePro_Data"
        data.mkdir(parents=True, exist_ok=True)
        for addon_id in ("236979321", "SynapsePro1"):
            legacy = self.base / "addons21" / addon_id
            for name in ("addon_settings.json", "study_plan_config.json"):
                copy_missing(legacy / name, data / name)
            copy_missing(legacy / "theme/user_files", data / "themes")
        copy_missing(
            Path(__file__).parent / "synapsepro/theme/user_files", data / "themes"
        )
