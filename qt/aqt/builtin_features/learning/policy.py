# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Versioned, deterministic limits. Model confidence never authorizes a write."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

VERSION = 1
DAY = 86400
MIN_REVIEWS = 200
MIN_ACTIVE_DAYS = 14
COOLDOWN_DAYS = 7
MAX_INPUT_BYTES = 60000
MAX_OUTPUT_TOKENS = 1800
# Worst-case peak pricing, without cache discounts, CNY per million tokens.
INPUT_PRICE = 2.0
OUTPUT_PRICE = 8.0
REQUEST_RESERVE = 0.15

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": VERSION,
    "daily_enabled": False,
    "consent": False,
    "primary_device": False,
    "deck_id": 0,
    "include_children": True,
    "mode": "confirm",
    "minutes": 0,
    "new_limit": 0,
    "monthly_budget": 5.0,
    "enabled_since": 0,
    "model": "deepseek-flash",
    "use_existing_key": True,
}


def digest(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def validate_settings(value: dict[str, Any]) -> dict[str, Any]:
    result = DEFAULT_SETTINGS | value
    for key in (
        "daily_enabled",
        "consent",
        "primary_device",
        "include_children",
        "use_existing_key",
    ):
        if type(result[key]) is not bool:
            raise ValueError(f"{key}: 必须为开关值")
    for key, low, high in (
        ("deck_id", 0, 2**63 - 1),
        ("minutes", 0, 480),
        ("new_limit", 0, 9999),
        ("enabled_since", 0, 2**53),
    ):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key}: 超出允许范围")
    budget = result["monthly_budget"]
    if (
        type(budget) not in (int, float)
        or not math.isfinite(budget)
        or not 0.15 <= budget <= 100
    ):
        raise ValueError("月预算必须在 0.15～100 元之间")
    if result["mode"] not in ("suggest", "confirm"):
        raise ValueError("本版本只支持只生成建议或确认后应用")
    if result["model"] != "deepseek-flash":
        raise ValueError("本版本使用 deepseek-flash")
    if result["daily_enabled"] and not (result["consent"] and result["primary_device"]):
        raise ValueError("每日分析需要同意发送汇总数据，并指定本机执行")
    return result


def validate_report(
    value: Any, snapshot: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "snapshot_id",
        "decision",
        "summary",
        "observations",
        "inferences",
        "changes",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("模型报告字段不完整或包含未知字段")
    if value["snapshot_id"] != snapshot["snapshot_id"]:
        raise ValueError("模型返回了错误的数据快照")
    if value["decision"] not in ("keep", "propose"):
        raise ValueError("模型返回了未知决策")
    if not isinstance(value["summary"], str) or not 1 <= len(value["summary"]) <= 3000:
        raise ValueError("报告摘要无效")
    for key in ("observations", "inferences"):
        if not isinstance(value[key], list) or len(value[key]) > 12:
            raise ValueError("报告条目无效")
        if any(not isinstance(item, str) or len(item) > 1200 for item in value[key]):
            raise ValueError("报告条目必须为有长度限制的文字")
    changes = value["changes"]
    if not isinstance(changes, list) or len(changes) > 1:
        raise ValueError("每份报告最多调整一个参数")
    if bool(changes) != (value["decision"] == "propose"):
        raise ValueError("建议与决策不一致")
    for change in changes:
        if not isinstance(change, dict) or set(change) != {
            "parameter",
            "before",
            "after",
            "reason",
            "evidence",
        }:
            raise ValueError("调整字段无效")
        if change["parameter"] != "new_per_day":
            raise ValueError("只允许建议每日新卡量；不允许模型修改排程或评分")
        before, after = change["before"], change["after"]
        if type(before) is not int or type(after) is not int:
            raise ValueError("新卡限额必须是整数")
        if before != snapshot["parameters"]["new_per_day"]:
            raise ValueError("调整前的值与快照不一致")
        delta = min(2, before // 10)
        if (
            before == after
            or abs(after - before) > delta
            or not 0 <= after <= settings["new_limit"]
        ):
            raise ValueError("建议超出单次变化上限或已批准的新卡范围")
        if (
            not isinstance(change["reason"], str)
            or not 1 <= len(change["reason"]) <= 1500
        ):
            raise ValueError("缺少调整理由")
        evidence = change["evidence"]
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(key not in snapshot["evidence"] for key in evidence)
        ):
            raise ValueError("建议引用了未提供的指标")
    return value


def application_blocker(
    snapshot: dict[str, Any], settings: dict[str, Any], now: int, last_applied: int = 0
) -> str:
    if settings["mode"] != "confirm":
        return "当前为只生成建议模式"
    if (
        not settings["consent"]
        or not settings["deck_id"]
        or not settings["minutes"]
        or not settings["new_limit"]
    ):
        return "请先设置分析牌组、每日可用时间及新卡上限，并确认汇总数据范围"
    if now - settings["enabled_since"] < MIN_ACTIVE_DAYS * DAY:
        return "首次启用后的 14 天为观察期，暂不应用调整"
    if now - snapshot["created_at"] > DAY:
        return "报告超过 24 小时，请重新分析"
    if not snapshot["quality"]["eligible"]:
        return "数据不足或存在质量问题，仅供观察"
    if snapshot["scope"]["deck_id"] != settings["deck_id"]:
        return "报告牌组与当前批准的范围不同"
    if snapshot["parameters"]["has_today_override"]:
        return "存在今日新卡限额覆盖，请先在原生牌组选项中处理"
    if last_applied and now - last_applied < COOLDOWN_DAYS * DAY:
        return "距上次调整未满 7 天"
    return ""


def evaluate_effect(before: dict, current: dict, age_days: float, minutes: int) -> dict:
    """A review flag, not a causal claim or an instruction to reschedule cards."""
    previous, recent = before["summary"], current["summary"]
    if age_days < 14:
        return {"blocked": False, "message": "调整后观察未满 14 天，暂不判断长期效果"}
    if min(previous["long_reviews"], recent["long_reviews"]) < 200:
        return {
            "blocked": False,
            "message": "跨日样本不足，继续观察；不将短期波动视为效果",
        }
    p0, p1 = previous["true_retention"], recent["true_retention"]
    if p0 is None or p1 is None:
        return {"blocked": False, "message": "缺少可比较的保留率"}
    uncertainty = 1.96 * math.sqrt(
        p0 * (1 - p0) / previous["long_reviews"]
        + p1 * (1 - p1) / recent["long_reviews"]
    )
    if p0 - p1 >= max(0.03, uncertainty):
        return {
            "blocked": True,
            "message": "保留率下降达到复核阈值，暂停新的建议应用。卡片构成和重复评分也会影响结果，请核查后决定是否撤销；这不证明因果关系",
        }
    per_day_minutes = recent["recorded_seconds"] / 60 / max(1, recent["active_days"])
    if (
        minutes
        and per_day_minutes > minutes * 1.2
        and current["cards"]["backlog"] > before["cards"]["backlog"]
    ):
        return {
            "blocked": True,
            "message": "记录耗时持续超过预算且积压增加，暂停新的建议应用，请复核学习负担或撤销上一项调整",
        }
    return {
        "blocked": False,
        "message": "尚未发现达到停止阈值的变化；继续比较相同范围，不能仅据前后对比认定改善",
    }
