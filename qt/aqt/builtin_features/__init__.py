# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Built-in study tools, initialized by AnkiQt before third-party add-ons."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .storage import LEGACY_IDS, FeatureStorage, read_object, write_object

if TYPE_CHECKING:
    from aqt.main import AnkiQt

_instance: BuiltinFeatures | None = None


class BuiltinFeatures:
    def __init__(self, mw: AnkiQt) -> None:
        self.mw = mw
        self.ready = False
        self.storage = FeatureStorage(Path(mw.pm.base))
        self.config_callbacks: list[Callable[[], None]] = []
        self.storage.migrate_fsrs()

    def open_profile(self) -> None:
        self.storage.prepare_profile(Path(self.mw.pm.profileFolder()))


def initialize(mw: AnkiQt) -> None:
    global _instance
    if _instance is not None:
        if _instance.mw is not mw:
            raise RuntimeError("Built-in tools already belong to another Anki window")
        return
    from aqt import gui_hooks

    _instance = BuiltinFeatures(mw)
    gui_hooks.profile_did_open.append(_instance.open_profile)
    synapse = importlib.import_module(".synapsepro", __name__)
    if not synapse.modules_loaded:
        raise RuntimeError("The built-in SynapsePro modules failed to initialize")
    importlib.import_module(".fsrs_helper", __name__)
    _instance.ready = True
    if os.environ.get("ANKI_BUILTIN_DIAGNOSTICS") == "1":
        gui_hooks.profile_did_open.append(
            lambda: mw.progress.single_shot(2000, write_startup_diagnostics, False)
        )


def instance() -> BuiltinFeatures:
    if _instance is None:
        raise RuntimeError("Built-in features have not been initialized")
    return _instance


def replaces_addon(folder: str, addons_root: str) -> bool:
    if _instance is None or not _instance.ready:
        return False
    if folder in LEGACY_IDS:
        return True
    manifest = Path(addons_root) / folder / "manifest.json"
    try:
        return read_object(manifest).get("package") in LEGACY_IDS
    except (OSError, ValueError):
        return False


def load_fsrs_config() -> dict[str, Any]:
    return instance().storage.load_fsrs()


def save_fsrs_config(value: dict[str, Any]) -> None:
    owner = instance()
    write_object(owner.storage.fsrs_path, value)
    for callback in owner.config_callbacks:
        callback()


def on_fsrs_config_change(callback: Callable[[], None]) -> None:
    callbacks = instance().config_callbacks
    if callback not in callbacks:
        callbacks.append(callback)


def fsrs_user_files() -> Path:
    path = instance().storage.root / "fsrs_helper/user_files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def theme_dir() -> Path:
    if _instance is not None and _instance.mw.col:
        return Path(_instance.mw.pm.profileFolder()) / "SynapsePro_Data/themes"
    return Path(__file__).parent / "synapsepro/theme/user_files"


def asset_url(path: str) -> str:
    return f"/_anki/builtin/synapsepro/{path}"


def asset_request(path: str) -> tuple[Path, str] | None:
    """Only public media/CSS can be served; never expose Python or settings."""
    prefix = "_anki/builtin/synapsepro/"
    if not path.startswith(prefix):
        return None
    relative = path[len(prefix) :]
    parts = relative.split("/")
    if len(parts) != 2 or parts[1] in ("", ".", "..") or "\\" in relative:
        return None
    if parts[0] == "themes" and parts[1].endswith(".css"):
        return theme_dir(), parts[1]
    if parts[0] == "media" and Path(parts[1]).suffix.lower() in {
        ".css",
        ".js",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".woff2",
    }:
        return Path(__file__).parent / "synapsepro/media", parts[1]
    return None


def show_fsrs_settings() -> None:
    import json

    from aqt.qt import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

    owner = instance()
    dialog = QDialog(owner.mw)
    dialog.setWindowTitle("FSRS Helper · 内置功能设置")
    dialog.resize(650, 560)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("设置保存在本机 Anki 配置目录，适用于所有账户。"))
    editor = QPlainTextEdit(
        json.dumps(load_fsrs_config(), ensure_ascii=False, indent=2)
    )
    layout.addWidget(editor)
    error = QLabel()
    error.setWordWrap(True)
    layout.addWidget(error)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )

    def save() -> None:
        try:
            value = json.loads(editor.toPlainText())
            if not isinstance(value, dict):
                raise ValueError("请输入 JSON 对象")
            for key, default in owner.storage.defaults.items():
                if key == "reschedule_threshold":
                    threshold = value.get(key)
                    if type(threshold) not in (int, float) or not 0 <= threshold < 1:
                        raise ValueError(
                            "reschedule_threshold: 请输入 0 到 1 之间的数值（不含 1）"
                        )
                    continue
                if key not in value or type(value[key]) is not type(default):
                    raise ValueError(f"{key}: 设置缺失或类型不正确")
                if (
                    isinstance(default, int)
                    and not isinstance(default, bool)
                    and value[key] < 0
                ):
                    raise ValueError(f"{key}: 不能小于 0")
            save_fsrs_config(value)
        except (OSError, ValueError) as exc:
            error.setText(str(exc))
            return
        dialog.accept()

    buttons.accepted.connect(save)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()


def write_startup_diagnostics() -> None:
    """Opt-in support report; no credentials or card content are recorded."""
    import sys

    from anki.utils import version_with_build

    owner = instance()
    mw = owner.mw
    synapse = importlib.import_module(".synapsepro", __name__)
    fsrs = importlib.import_module(".fsrs_helper", __name__)
    report = {
        "anki": version_with_build(),
        "ready": owner.ready,
        "state": mw.state,
        "collection_open": mw.col is not None,
        "synapsepro_source": synapse.__file__,
        "fsrs_helper_source": fsrs.__file__,
        "synapsepro_menu_count": sum(
            a.text() == "SynapsePro" for a in mw.form.menuTools.actions()
        ),
        "fsrs_menu_count": sum(
            a.menu() == fsrs.menu_for_helper for a in mw.form.menuTools.actions()
        ),
        "legacy_modules_loaded": [key for key in LEGACY_IDS if key in sys.modules],
        "developer_mode": bool(os.environ.get("ANKIDEV")),
    }
    write_object(owner.storage.root / "startup-diagnostics.json", report)
    # Automated executable checks can only exit a marked synthetic profile.
    if (owner.storage.base / ".builtin-test").is_file():
        mw.grab().save(str(owner.storage.base / "executable-main.png"))
        if os.environ.get("ANKI_BUILTIN_DIAGNOSTICS_EXIT") == "1":
            mw.close()
