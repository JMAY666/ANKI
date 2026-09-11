# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Validated local desktop settings; profile keys retain AnkiPenDown compatibility."""

import math
import re
from typing import Any

from ..storage import FeatureStorage, copy_missing, read_object, write_object

PEN_DEFAULTS: dict[str, Any] = {
    "ts_state_on": False,
    "ts_pen1_color": "#000000",
    "ts_pen2_color": "#ff0000",
    "ts_line_width": 4,
    "ts_auto_hide": True,
    "ts_auto_hide_pointer": True,
    "ts_default_small_canvas": False,
    "ts_zen_mode": False,
    "ts_follow": False,
    "ts_compact_toolbar": False,
    "ts_location": 1,
    "ts_x_offset": 2,
    "ts_y_offset": 2,
    "ts_small_width": 500,
    "ts_small_height": 500,
    "ts_background_color": "#FFFFFF00",
    "ts_orient_vertical": True,
}


def pen_settings(profile: dict[str, Any]) -> dict[str, Any]:
    value = {key: profile.get(key, default) for key, default in PEN_DEFAULTS.items()}
    validate_pen(value)
    return value


def validate_pen(value: dict[str, Any]) -> None:
    for key, default in PEN_DEFAULTS.items():
        actual = value[key]
        if isinstance(default, bool) and type(actual) is not bool:
            raise ValueError("手写设置中的开关必须为布尔值。")
        if "color" in key:
            length = 8 if key == "ts_background_color" else 6
            if not isinstance(actual, str) or not re.fullmatch(
                rf"#[0-9a-fA-F]{{{length}}}", actual
            ):
                raise ValueError("手写设置中的颜色格式无效。")
    for key, low, high in (
        ("ts_line_width", 0.1, 100),
        ("ts_location", 0, 3),
        ("ts_x_offset", 0, 1000),
        ("ts_y_offset", 0, 1000),
        ("ts_small_width", 1, 9999),
        ("ts_small_height", 1, 9999),
    ):
        actual = value[key]
        if (
            type(actual) not in (int, float)
            or not math.isfinite(actual)
            or not low <= actual <= high
            or (key != "ts_line_width" and int(actual) != actual)
        ):
            raise ValueError("手写设置中的尺寸或位置超出有效范围。")


def tray_settings(storage: FeatureStorage) -> dict[str, Any]:
    path = storage.root / "minimize_to_tray.json"
    value: dict[str, Any] = {
        "enabled": False,
        "hide_on_startup": False,
        "debug": False,
    }
    if path.exists():
        value.update(read_object(path))
    else:
        addons = storage.base / "addons21"
        ids = ("85158043",)
        candidates = [addons / key for key in ids if (addons / key).is_dir()]
        for manifest in sorted(addons.glob("*/manifest.json")):
            if read_object(manifest).get("package") in ids:
                if manifest.parent not in candidates:
                    candidates.append(manifest.parent)
        snapshots = []
        for candidate in candidates:
            snapshot: dict[str, Any] = {}
            for name in ("config.json", "meta.json"):
                if (candidate / name).exists():
                    snapshot[name] = read_object(candidate / name)
            snapshots.append(snapshot)
        if snapshots and any(item != snapshots[0] for item in snapshots[1:]):
            raise ValueError("托盘功能存在不同的旧配置，请选择迁移来源；原件未修改。")
        if snapshots:
            value.update(snapshots[0].get("config.json", {}))
            value.update(snapshots[0].get("meta.json", {}).get("config", {}))
            # The user's explicit integration choice governs close behavior.
            value["enabled"] = False
            for candidate in candidates:
                copy_missing(
                    candidate / "user_files",
                    storage.root / "minimize_to_tray/user_files",
                )
    for key in ("enabled", "hide_on_startup", "debug"):
        if type(value[key]) is not bool:
            raise ValueError("托盘设置中的开关必须为布尔值；原配置未覆盖。")
    if not path.exists():
        write_object(path, value)
    return value
