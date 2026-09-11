# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Reports propose; native collection transactions apply only confirmed limits."""

from __future__ import annotations

import json
import time
from typing import Any

from anki.collection import Collection, OpChanges
from anki.decks import DeckId, UpdateDeckConfigs

from .metrics import collect_snapshot, parameters, public_payload
from .policy import DAY, application_blocker, evaluate_effect, validate_report
from .provider import ProviderError, request_report
from .storage import LearningStore


def analyze(
    store: LearningStore,
    report_id: str,
    snapshot: dict,
    settings: dict,
    key: str,
    requester: Any = request_report,
    expected_attempt: int | None = None,
) -> None:
    attempt = (
        store.report(report_id)["attempts"]
        if expected_attempt is None
        else expected_attempt
    )
    if store.report(report_id)["attempts"] != attempt:
        return
    if store.settings() != settings:
        store.finish(
            report_id,
            "cancelled",
            snapshot,
            error="设置或数据授权已变化，未发送请求",
            cost=0,
            expected_attempt=attempt,
        )
        return
    try:
        report, metadata = requester(report_payload(store, snapshot, settings), key)
        validated = validate_report(report, snapshot, settings)
        store.finish(
            report_id,
            "ready",
            snapshot,
            {"content": validated, **metadata},
            cost=metadata["estimated_cost"],
            expected_attempt=attempt,
        )
    except (ProviderError, ValueError) as exc:
        status = "failed"
        if isinstance(exc, ProviderError):
            status = (
                "configuration_error"
                if exc.configuration_error
                else "retry"
                if exc.retryable
                else "failed"
            )
        store.finish(
            report_id,
            status,
            snapshot,
            error=str(exc),
            expected_attempt=attempt,
        )


def report_payload(store: LearningStore, snapshot: dict, settings: dict) -> dict:
    payload = public_payload(snapshot, settings)
    payload["recent_adjustments"] = [
        {
            "parameter": "new_per_day",
            "before": json.loads(action["before_value"]),
            "after": json.loads(action["after_value"]),
            "status": action["status"],
            "days_ago": max(0, (snapshot["created_at"] - action["created"]) // DAY),
        }
        for action in store.actions()
        if action["deck_id"] == settings["deck_id"]
        and snapshot["created_at"] - action["created"] <= 28 * DAY
    ][:5]
    payload["effect_review"] = effect_review(store, snapshot, settings)
    return payload


def effect_review(store: LearningStore, current: dict, settings: dict) -> dict:
    for action in store.actions():
        if (
            action["status"] == "applied"
            and action["deck_id"] == current["scope"]["deck_id"]
        ):
            previous = json.loads(store.report(action["report_id"])["snapshot"])
            return evaluate_effect(
                previous,
                current,
                (current["created_at"] - action["created"]) / DAY,
                settings["minutes"],
            )
    return {"blocked": False, "message": "暂无待评估的已应用调整"}


def set_new_override(col: Collection, deck_id: int, value: int | None) -> OpChanges:
    """Preserve every unrelated native setting, including today's and parent limits."""
    data = col.decks.get_deck_configs_for_update(DeckId(deck_id))
    preset = next(
        item.config
        for item in data.all_config
        if item.config.id == data.current_deck.config_id
    )
    request = UpdateDeckConfigs(
        target_deck_id=deck_id,
        configs=[preset],
        limits=data.current_deck.limits,
        fsrs=data.fsrs,
        fsrs_health_check=data.fsrs_health_check,
        fsrs_reschedule=False,
        new_cards_ignore_review_limit=data.new_cards_ignore_review_limit,
        apply_all_parent_limits=data.apply_all_parent_limits,
        card_state_customizer=data.card_state_customizer,
    )
    if value is None:
        request.limits.ClearField("new")
    else:
        setattr(request.limits, "new", value)
    return col.decks.update_deck_configs(request)


def apply_confirmed(
    col: Collection, store: LearningStore, report_id: str, now: int | None = None
) -> OpChanges:
    now = int(time.time()) if now is None else now
    row = store.report(report_id)
    if row["status"] != "ready":
        raise ValueError("报告尚未就绪或已失效")
    snapshot = json.loads(row["snapshot"])
    settings = store.settings()
    report = validate_report(json.loads(row["report"])["content"], snapshot, settings)
    if not report["changes"]:
        raise ValueError("该报告建议保持现状")
    last = max(
        (
            action["created"]
            for action in store.actions()
            if action["deck_id"] == settings["deck_id"] and action["status"] != "failed"
        ),
        default=0,
    )
    if reason := application_blocker(snapshot, settings, now, last):
        raise ValueError(reason)
    current = collect_snapshot(
        col, settings["deck_id"], settings["include_children"], now
    )
    if current["fingerprint"] != snapshot["fingerprint"]:
        raise ValueError("学习数据、日期或设置已变化，请重新分析后再确认")
    effect = effect_review(store, current, settings)
    if effect["blocked"]:
        raise ValueError(effect["message"])
    change = report["changes"][0]
    before = current["parameters"]["override"]
    action = store.pending_action(
        report_id, settings["deck_id"], before, change["after"], change["reason"], now
    )
    try:
        changes = set_new_override(col, settings["deck_id"], change["after"])
    except Exception:
        store.mark_action(action, "failed", "原生设置更新未完成")
        raise
    # If the ledger write fails after the native commit, startup reconciliation
    # sees 'pending' and compares values instead of repeating the mutation.
    store.mark_action(action, "applied")
    return changes


def revert_action(col: Collection, store: LearningStore, action_id: str) -> OpChanges:
    action = next((item for item in store.actions() if item["id"] == action_id), None)
    if not action or action["status"] != "applied":
        raise ValueError("这条调整不能撤销")
    current = parameters(col, action["deck_id"])
    if current["override"] != json.loads(action["after_value"]):
        raise ValueError("设置后来已被修改，未覆盖当前值")
    store.mark_action(action_id, "reverting")
    result = set_new_override(
        col, action["deck_id"], json.loads(action["before_value"])
    )
    store.mark_action(action_id, "reverted")
    return result


def reconcile(col: Collection, store: LearningStore) -> None:
    """Never mutate collection data during recovery."""
    for action in store.actions():
        if action["status"] not in ("pending", "reverting", "applied"):
            continue
        try:
            current = parameters(col, action["deck_id"])["override"]
        except Exception:
            store.mark_action(action["id"], "conflict", "牌组已不存在，请人工核对")
            continue
        before, after = (
            json.loads(action["before_value"]),
            json.loads(action["after_value"]),
        )
        if current == before:
            store.mark_action(
                action["id"],
                "reverted" if action["status"] != "pending" else "failed",
                "当前值为调整前值",
            )
        elif current == after:
            store.mark_action(action["id"], "applied")
        else:
            store.mark_action(
                action["id"], "conflict", "当前值与记录不一致，未自动覆盖"
            )
    with store.connection() as db:
        db.execute(
            "UPDATE reports SET status='interrupted',error='上次请求中断，用量未知；可手动重新分析，设置未改变' WHERE status='running'"
        )
