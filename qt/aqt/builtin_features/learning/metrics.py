# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Explicit statistical scopes; collection data is only read by this module."""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from anki.collection import Collection
from anki.decks import DeckId

from .policy import DAY, MIN_ACTIVE_DAYS, MIN_REVIEWS, VERSION, digest


def scope_ids(col: Collection, deck_id: int, children: bool) -> list[int]:
    if not deck_id:
        return []
    if not col.decks.get(DeckId(deck_id), default=False):
        raise ValueError("所选牌组已不存在")
    return (
        list(col.decks.deck_and_child_ids(DeckId(deck_id))) if children else [deck_id]
    )


def scope_query(col: Collection, deck_id: int, children: bool) -> str:
    ids = scope_ids(col, deck_id, children)
    return "(" + " OR ".join(f"did:{did}" for did in ids) + ")" if ids else ""


def card_limit(ids: list[int]) -> str:
    joined = ",".join(str(int(did)) for did in ids)
    return f"(did IN ({joined}) OR odid IN ({joined}))" if ids else "1"


def parameters(col: Collection, deck_id: int) -> dict[str, Any]:
    if not deck_id or col.decks.get(DeckId(deck_id), default=False).get("dyn"):
        return {
            "new_per_day": 0,
            "override": None,
            "has_today_override": False,
            "fingerprint": "global",
            "fsrs": bool(col.get_config("fsrs", False)),
        }
    data = col.decks.get_deck_configs_for_update(DeckId(deck_id))
    current = data.current_deck
    preset = next(
        item.config for item in data.all_config if item.config.id == current.config_id
    )
    limits = current.limits
    override = getattr(limits, "new") if limits.HasField("new") else None
    limit = override if override is not None else preset.config.new_per_day
    parents = [
        item.config
        for item in data.all_config
        if item.config.id in current.parent_config_ids
    ]
    return {
        "new_per_day": limit,
        "override": override,
        "has_today_override": limits.new_today_active,
        "desired_retention": limits.desired_retention
        if limits.HasField("desired_retention")
        else preset.config.desired_retention,
        "maximum_interval": preset.config.maximum_review_interval,
        "review_limit": limits.review
        if limits.HasField("review")
        else preset.config.reviews_per_day,
        "fsrs": data.fsrs,
        "preset_id": preset.id,
        "shared_decks": next(
            item.use_count
            for item in data.all_config
            if item.config.id == current.config_id
        ),
        "fingerprint": digest(
            [
                preset.SerializeToString().hex(),
                limits.SerializeToString().hex(),
                [item.SerializeToString().hex() for item in parents],
                data.fsrs,
                data.apply_all_parent_limits,
                data.new_cards_ignore_review_limit,
            ]
        ),
    }


def summarize(rows: list, cutoff: int) -> dict[str, Any]:
    """rows: id,cid,ease,ivl,lastIvl,factor,time,type, sorted by id."""
    valid = [
        row for row in rows if 1 <= row[2] <= 4 and not (row[7] == 3 and row[5] == 0)
    ]
    long_reviews = [
        row for row in valid if row[7] == 1 or row[4] >= 1 or row[4] <= -DAY
    ]
    daily: dict[int, dict[str, Any]] = {}
    for row in valid:
        offset = int((row[0] / 1000 - cutoff) // DAY)
        entry = daily.setdefault(
            offset,
            {
                "day_offset": offset,
                "reviews": 0,
                "again": 0,
                "recorded_seconds": 0,
                "cards": set(),
            },
        )
        entry["reviews"] += 1
        entry["again"] += row[2] == 1
        entry["recorded_seconds"] += row[6] / 1000
        entry["cards"].add(row[1])
    for entry in daily.values():
        entry["unique_cards"] = len(entry.pop("cards"))
    return {
        "reviews": len(valid),
        "unique_cards": len({row[1] for row in valid}),
        "ratings": [sum(row[2] == rating for row in valid) for rating in (1, 2, 3, 4)],
        "stages": [sum(row[7] == stage for row in valid) for stage in (0, 1, 2, 3)],
        "recorded_seconds": round(sum(row[6] for row in valid) / 1000, 2),
        "median_seconds": statistics.median([row[6] / 1000 for row in valid])
        if valid
        else None,
        "long_reviews": len(long_reviews),
        "long_passed": sum(row[2] > 1 for row in long_reviews),
        "true_retention": sum(row[2] > 1 for row in long_reviews) / len(long_reviews)
        if long_reviews
        else None,
        "active_days": len(daily),
        "daily": list(daily.values()),
        "invalid_rows": sum(
            not (0 <= row[2] <= 4 and 0 <= row[7] <= 5 and row[6] >= 0) for row in rows
        ),
    }


def collect_snapshot(
    col: Collection,
    deck_id: int,
    children: bool,
    now: int,
    *,
    complete_day: bool = True,
    days: int = 7,
) -> dict[str, Any]:
    ids = scope_ids(col, deck_id, children)
    condition = card_limit(ids)
    cutoff = int(col.sched.day_cutoff)
    end = cutoff - DAY if complete_day else min(now, cutoff)
    start28 = (cutoff - DAY if complete_day else cutoff) - 28 * DAY
    rev_condition = f"cid IN (SELECT id FROM cards WHERE {condition})" if ids else "1"
    rows = col.db.all(
        f"SELECT id,cid,ease,ivl,lastIvl,factor,time,type FROM revlog WHERE id>=? AND id<? AND {rev_condition} ORDER BY id",
        start28 * 1000,
        end * 1000,
    )
    window_start = (cutoff - DAY if complete_day else cutoff) - max(1, days) * DAY
    window = [row for row in rows if row[0] >= window_start * 1000]
    if days > 28 or days == 0:
        earliest = 0 if days == 0 else (cutoff - days * DAY) * 1000
        window_start = earliest // 1000
        window = col.db.all(
            f"SELECT id,cid,ease,ivl,lastIvl,factor,time,type FROM revlog WHERE id>=? AND id<? AND {rev_condition} ORDER BY id",
            earliest,
            end * 1000,
        )
    previous = [row for row in rows if end - 14 * DAY <= row[0] / 1000 < end - 7 * DAY]
    cards = col.db.all(
        f"SELECT id,queue,type,due,ivl,odue,odid,data,reps,lapses,mod FROM cards WHERE {condition} ORDER BY id"
    )

    def due(row: Sequence[Any]) -> int:
        return row[5] if row[6] else row[3]

    today = col.sched.today
    backlog = sum(row[1] == 2 and due(row) < today for row in cards)
    next_due = [
        sum(row[1] == 2 and due(row) == today + offset for row in cards)
        for offset in range(14)
    ]
    summary = summarize(window, cutoff)
    baseline = summarize(rows, cutoff)
    params = parameters(col, deck_id)
    live_tail = col.db.all(
        f"SELECT id,cid,ease,ivl,lastIvl,factor,time,type FROM revlog WHERE id>=? AND {rev_condition} ORDER BY id",
        end * 1000,
    )
    available_states = 0
    for row in cards:
        try:
            available_states += json.loads(row[7] or "{}").get("s") is not None
        except (ValueError, TypeError):
            pass
    evidence = {
        "recent_reviews": summary["reviews"],
        "recent_true_retention": summary["true_retention"],
        "recent_recorded_seconds": summary["recorded_seconds"],
        "previous_week_true_retention": summarize(previous, cutoff)["true_retention"],
        "backlog": backlog,
        "baseline_reviews": baseline["reviews"],
        "baseline_active_days": baseline["active_days"],
    }
    data = {
        "version": VERSION,
        "scope": {
            "deck_id": deck_id,
            "include_children": children,
            "deck_count": len(ids),
        },
        "created_at": now,
        "day": datetime.fromtimestamp(
            cutoff - (2 if complete_day else 1) * DAY
        ).strftime("%Y-%m-%d"),
        "window": {
            "start": window_start,
            "end": end,
            "complete_day": complete_day,
            "days": days,
        },
        "summary": summary,
        "baseline": baseline,
        "evidence": evidence,
        "cards": {
            "total": len(cards),
            "new": sum(row[1] == 0 for row in cards),
            "backlog": backlog,
            "future_due": next_due,
            "memory_states": available_states,
        },
        "parameters": params,
        "quality": {
            "eligible": baseline["reviews"] >= MIN_REVIEWS
            and baseline["unique_cards"] >= 50
            and baseline["active_days"] >= MIN_ACTIVE_DAYS
            and not baseline["invalid_rows"]
            and params["fsrs"]
        },
        "fingerprint": digest(
            [cards, rows, live_tail, params["fingerprint"], ids, cutoff]
        ),
    }
    data["snapshot_id"] = digest(data)
    return data


def public_payload(
    snapshot: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    """Allowlist only aggregates. No card/deck IDs, names, text or individual timestamps."""
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "scope": "approved_deck_group",
        "window_days": snapshot["window"]["days"],
        "complete_learning_day": snapshot["window"]["complete_day"],
        "summary": snapshot["summary"],
        "baseline_28_days": snapshot["baseline"],
        "cards": snapshot["cards"],
        "evidence": snapshot["evidence"],
        "quality": snapshot["quality"],
        "parameters": {
            key: snapshot["parameters"][key]
            for key in (
                "new_per_day",
                "desired_retention",
                "maximum_interval",
                "review_limit",
                "fsrs",
            )
            if key in snapshot["parameters"]
        },
        "approved_limits": {
            "minutes_per_day": settings["minutes"],
            "new_cards_max": settings["new_limit"],
            "max_change": min(2, snapshot["parameters"]["new_per_day"] // 10),
        },
        "caveats": [
            "评分为自评，不是客观考试成绩",
            "耗时已被原生计时上限截断",
            "积压为当前快照，历史积压未知",
            "过去牌组归属按当前卡片关系统计",
            "样本不足时保持原设置",
        ],
    }


def session_summary(col: Collection, event_ids: list[int]) -> dict[str, Any]:
    if not event_ids:
        return summarize([], int(col.sched.day_cutoff))
    rows = col.db.all(
        "SELECT id,cid,ease,ivl,lastIvl,factor,time,type FROM revlog WHERE id IN ("
        + ",".join(str(int(rid)) for rid in set(event_ids))
        + ") ORDER BY id"
    )
    return summarize(rows, int(col.sched.day_cutoff))
