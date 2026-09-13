# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Copy-only migration and validation for the six built-in review tools."""

from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any

from ..storage import FeatureStorage, copy_missing, read_object, write_object
from .i18n import caption, tr

FEATURES = {
    "pace_graph": ("1323545382", "pace_graph"),
    "button_colours": ("2494384865",),
    "search_stats": ("1613056169",),
    "advanced_review": ("1136455830",),
    "answer_feedback": ("2060144143",),
    "confident_wrong": ("1659223841",),
}
POLICY = {
    "style": "current",
    "feedback": "off",
    "pace_enabled": True,
    "search_stats_enabled": True,
}


def merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def defaults(feature: str) -> dict[str, Any]:
    if feature == "policy":
        return dict(POLICY)
    if feature not in FEATURES:
        raise ValueError("未知内置功能")
    return read_object(Path(__file__).parent / "defaults" / f"{feature}.json")


class ToolConfig:
    def __init__(self, storage: FeatureStorage) -> None:
        self.root = storage.root / "review_tools"
        self.values: dict[str, dict[str, Any]] = {}
        for feature in (*FEATURES, "policy"):
            path = self.path(feature)
            value = defaults(feature)
            if path.exists():
                value = merge(value, read_object(path))
            else:
                if feature in FEATURES:
                    legacy = self.find_legacy(storage.base / "addons21", feature)
                    if legacy:
                        if (legacy / "config.json").exists():
                            value = merge(value, read_object(legacy / "config.json"))
                        meta = (
                            read_object(legacy / "meta.json")
                            if (legacy / "meta.json").exists()
                            else {}
                        )
                        override = meta.get("config", {})
                        if not isinstance(override, dict):
                            raise ValueError(f"{tr(feature)}：旧设置必须是对象")
                        value = merge(value, override)
                        copy_missing(
                            legacy / "user_files", self.root / feature / "user_files"
                        )
                        # Keep original activation as evidence; explicit integration
                        # choices, stored separately, control overlapping features.
                        value["_legacy_disabled"] = bool(meta.get("disabled", False))
                elif feature == "policy":
                    for name in ("pace", "search_stats"):
                        source_name = "pace_graph" if name == "pace" else name
                        if self.values[source_name].get("_legacy_disabled"):
                            value[f"{name}_enabled"] = False
                write_object(path, value)
            self.values[feature] = value

    @staticmethod
    def find_legacy(addons: Path, feature: str) -> Path | None:
        ids = FEATURES[feature]
        candidates = [addons / key for key in ids if (addons / key).is_dir()]
        for manifest in sorted(addons.glob("*/manifest.json")):
            try:
                package = read_object(manifest).get("package")
            except (OSError, ValueError):
                continue
            if manifest.parent not in candidates and package in ids:
                candidates.append(manifest.parent)
        # Conflicting copies require a choice; never merge two different setups.
        if len(candidates) > 1:
            snapshots = []
            for candidate in candidates:
                value = {}
                for name in ("config.json", "meta.json"):
                    if (candidate / name).exists():
                        value[name] = read_object(candidate / name)
                snapshots.append(value)
            if any(value != snapshots[0] for value in snapshots[1:]):
                raise ValueError(
                    f"{tr(feature)}：发现多个不同的旧配置；请保留原件并选择迁移来源"
                )
        return candidates[0] if candidates else None

    def path(self, feature: str) -> Path:
        if feature not in (*FEATURES, "policy"):
            raise ValueError("未知内置功能")
        return self.root / f"{feature}.json"

    def save(self, feature: str, value: dict[str, Any]) -> None:
        validate(feature, value)
        write_object(self.path(feature), value)
        self.values[feature] = copy.deepcopy(value)


def validate(feature: str, value: dict[str, Any]) -> None:
    for key, default in defaults(feature).items():
        if key not in value:
            if feature == "pace_graph" and default is None:
                continue
            raise ValueError(f"缺少设置：{caption(key)}")
        item = value[key]
        if default is not None and type(item) is not type(default):
            if not (
                (
                    type(default) is float
                    or feature == "pace_graph"
                    or key == "  More Overview Stats"
                )
                and type(item) in (int, float)
            ):
                raise ValueError(f"设置类型不正确：{caption(key)}")
        if isinstance(item, (int, float)) and not math.isfinite(item):
            raise ValueError(f"数值无效：{caption(key)}")
        if isinstance(default, str) and default.startswith("#"):
            if not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", item):
                raise ValueError(f"颜色无效：{caption(key)}")
    if feature == "policy":
        if value["style"] not in ("current", "colours", "advanced") or value[
            "feedback"
        ] not in ("off", "badge", "advanced"):
            raise ValueError("复习模式无效")
    if feature == "confident_wrong":
        if any(
            type(value[k]) not in (int, float) or not 0 < value[k] <= 100000
            for k in defaults(feature)
        ):
            raise ValueError("分析参数必须为正数")
    if feature == "answer_feedback":
        if not 0 <= value["hide_duration_ms"] <= 60000 or not isinstance(
            value["custom_labels"], dict
        ):
            raise ValueError("评分提示时长或标签无效")
    if feature == "button_colours":
        for theme in ("colours", "colours-dark"):
            if not isinstance(value[theme], dict):
                raise ValueError("配色设置无效")
            for colors in value[theme].values():
                if not isinstance(colors, list) or any(
                    not isinstance(color, str)
                    or not re.fullmatch(
                        r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|[a-zA-Z]+", color
                    )
                    for color in colors
                ):
                    raise ValueError("按钮颜色列表无效")
    if feature == "advanced_review":
        ranges = {
            " Review_ Buttons Style": (0, 7),
            " Review_ Bottombar Buttons Style": (0, 4),
            " Review_ Hover Effect": (0, 3),
            " Review_ Active Button Indicator": (0, 2),
            "Button_ Font Weight": (0, 8),
            " Review_ Cursor Style": (0, 1),
            " Review_ Interval Style": (0, 2),
            "Tooltip Style": (0, 1),
            "ShowAnswer_ Border Color Style": (0, 3),
            "  Skip Method": (0, 2),
            "  More Overview Stats": (0, 2),
            "Card Info sidebar_ Hide Current Card": (0, 1),
            "Card Info sidebar_ Number of previous cards to show": (0, 4),
        }
        for key, (low, high) in ranges.items():
            if not low <= value[key] <= high:
                raise ValueError(f"{caption(key)}：请输入 {low}～{high} 之间的数值")
        for key, item in value.items():
            if key.startswith("Button_ Position_") and item not in (
                "left",
                "middle left",
                "middle right",
                "right",
            ):
                raise ValueError(f"按钮位置无效：{caption(key)}")
            if (
                key.startswith(("Button_ Width_", "Button_ Height_"))
                and not 10 <= item <= 2000
            ):
                raise ValueError(f"按钮尺寸无效：{caption(key)}")
        for key in ("Tooltip Position", "Tooltip Offset"):
            if (
                not isinstance(value[key], list)
                or len(value[key]) != 2
                or any(type(n) is not int or abs(n) > 10000 for n in value[key])
            ):
                raise ValueError(f"提示位置无效：{caption(key)}")


def get_config(feature: str) -> dict[str, Any]:
    from aqt import mw

    return getattr(mw, "review_tools").config.values[feature]


def save_config(feature: str, value: dict[str, Any]) -> None:
    from aqt import mw

    getattr(mw, "review_tools").config.save(feature, value)


def review_is_visible() -> bool:
    from aqt import mw

    return bool(
        mw and mw.col and mw.state == "review" and mw.reviewer.controls_active()
    )
