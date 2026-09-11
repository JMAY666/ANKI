# Source integration: Ankitects Pty Ltd and contributors
# Derived from ARBb 3.6.1 Card_Info.py; see SOURCE.md for author and license.
"""Card information in a single reusable dock, using current Anki statistics."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from aqt.qt import QDockWidget, Qt, QTextBrowser

from .config import get_config, review_is_visible
from .i18n import tr


def stamp(value: int | float | None) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M") if value else "—"


def card_report(col: Any, cid: int, conf: dict, current_count: int = 0) -> str:
    card = col.get_card(cid)
    note = card.note()
    stats = col.card_stats_data(cid)
    rows = col.db.all(
        "select id,ease,time,ivl,factor,type from revlog where cid = ? order by id desc",
        cid,
    )
    times = [row[2] / 1000 for row in rows]
    answers = [row for row in rows if row[1] > 0 and row[5] < 4]
    memory = card.memory_state
    data = {
        "Created": stamp(stats.added),
        "Edited": stamp(note.mod),
        "First Review": stamp(stats.first_review),
        "Latest Review": stamp(stats.latest_review),
        "Due": stamp(stats.due_date)
        if stats.HasField("due_date")
        else str(stats.due_position),
        "FSRS Stability": f"{memory.stability:.2f}" if memory else "—",
        "FSRS Difficulty": f"{memory.difficulty:.2f}" if memory else "—",
        "FSRS Retrievability": f"{stats.fsrs_retrievability:.2%}"
        if stats.HasField("fsrs_retrievability")
        else "—",
        "Interval": f"{stats.interval} 天",
        "Ease": f"{stats.ease / 10:g}%",
        "Reviews": stats.reviews,
        "Lapses": stats.lapses,
        "Correct Percent": f"{sum(row[1] > 1 for row in answers) / len(answers):.1%}"
        if answers
        else "—",
        "Fastest Review": f"{min(times):g} 秒" if times else "—",
        "Slowest Review": f"{max(times):g} 秒" if times else "—",
        "Average Time": f"{stats.average_secs:.2f} 秒",
        "Total Time": f"{stats.total_secs:.2f} 秒",
        "Card Type": stats.card_type,
        "Note Type": stats.notetype,
        "Deck": stats.original_deck or stats.deck,
        "Tags": " ".join(note.tags),
        "Note ID": note.id,
        "Card ID": cid,
        "Sort Field": note.fields[note.note_type()["sortf"]],
        "Current Review Count": current_count,
    }
    enabled = {
        key.split("_ ", 1)[1].casefold(): value
        for key, value in conf.items()
        if "sidebar_ " in key.casefold()
    }
    body = "".join(
        f"<tr><td>{html.escape(tr(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in data.items()
        if enabled.get(key.casefold(), False)
    )
    limit = conf["Card Info sidebar_ number of reviews to show for a card"]
    shown = rows[:limit] if limit > 0 else rows
    log = "".join(
        f"<tr><td>{stamp(row[0] / 1000)}</td><td>{row[1]}</td><td>{row[2] / 1000:g} 秒</td><td>{row[3]}</td></tr>"
        for row in shown
    )
    warning = (
        f"<p>显示 {len(rows)} 条记录中的前 {len(shown)} 条。</p>"
        if conf["Card Info sidebar_ warning note"] and len(shown) < len(rows)
        else ""
    )
    return f"<h3>卡片 {cid}</h3><table>{body}</table><h4>复习记录</h4>{warning}<table><tr><th>时间</th><th>评分</th><th>耗时</th><th>间隔</th></tr>{log}</table>"


class CardSidebar:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.requested = False
        self.dock = QDockWidget("卡片信息", owner.mw)
        self.dock.setObjectName("builtinAdvancedCardInfo")
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.text = QTextBrowser(self.dock)
        self.text.setMinimumWidth(180)
        self.dock.setWidget(self.text)
        owner.mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        # User closing the dock must stay closed until explicitly opened again.
        self.dock.toggleViewAction().triggered.connect(self.set_requested)

    def set_requested(self, value: bool) -> None:
        self.requested = value

    def toggle(self) -> None:
        self.requested = not self.requested
        self.update_card()

    def update_card(self) -> None:
        conf = get_config("advanced_review")
        active = review_is_visible()
        self.requested = self.requested or (
            active and conf["Card Info sidebar_ Auto Open"]
        )
        if not active or not self.requested:
            self.dock.hide()
            return
        mw = self.owner.mw
        ids = (
            []
            if conf["Card Info sidebar_ Hide Current Card"]
            else [mw.reviewer.card.id]
        )
        ids.extend(
            list(self.owner.previous)[
                : max(
                    0, conf["Card Info sidebar_ Number of previous cards to show"] - 1
                )
            ]
        )
        reports = [
            card_report(mw.col, cid, conf, len(mw.reviewer._answeredIds))
            for cid in ids
            if mw.col.db.scalar("select 1 from cards where id = ?", cid)
        ]
        theme = conf["Card Info sidebar_ theme"]
        colors = (
            "background:#222;color:#eee"
            if theme == 2
            else ("background:white;color:#222" if theme == 1 else "")
        )
        self.text.setStyleSheet(f"QTextBrowser{{{colors}}}")
        self.text.setHtml(
            f'<div style="font-family:{html.escape(conf["Card Info sidebar_ Font"], quote=True)}">'
            + "<hr>".join(reports)
            + "</div>"
        )
        self.dock.show()


def overview_metrics(col: Any, did: int, mode: int) -> dict:
    """ARBb's two original scopes/formulas, without changing the selected deck."""
    import math
    from datetime import date, timedelta

    ids = [did] if mode == 1 else col.decks.deck_and_child_ids(did)
    rows = col.db.all(
        "select queue,type,ivl,due from cards where did in ("
        + ",".join("?" for _ in ids)
        + ")",
        *ids,
    )
    tree = col.sched.deck_due_tree(top_deck_id=did)
    scheduled = (
        [tree.new_count, tree.learn_count, tree.review_count] if tree else [0, 0, 0]
    )
    conf = col.decks.config_dict_for_deck_id(did)
    per_day = conf.get("new", {}).get("perDay", 0)
    counts = {
        "New": sum(q == 0 for q, _, _, _ in rows),
        "Learning": sum(q in (1, 3) for q, _, _, _ in rows),
        "Review": sum(q == 2 for q, _, _, _ in rows),
        "Suspended": sum(q == -1 for q, _, _, _ in rows),
        "Buried": sum(q in (-2, -3) for q, _, _, _ in rows),
    }
    if mode == 1:
        tomorrow = [
            min(per_day, counts["New"]),
            sum(q == 3 and due == col.sched.today + 1 for q, _, _, due in rows),
            sum(q == 2 and due == col.sched.today + 1 for q, _, _, due in rows),
        ]
        return {
            "counts": counts,
            "scheduled": scheduled,
            "tomorrow": tomorrow,
            "total": len(rows),
        }
    mature = sum(q == 2 and ivl >= 21 for q, _, ivl, _ in rows)
    young = sum(q in (1, 3) or (q == 2 and ivl < 21) for q, _, ivl, _ in rows)
    unseen = counts["New"]
    inactive = sum(q < 0 for q, _, _, _ in rows)
    result = {
        "Mature": mature,
        "Young / learning": young,
        "Unseen": unseen,
        "Suspended / buried": inactive,
        "Total": len(rows),
        "Learned": mature + young,
        "Unlearned": len(rows) - mature - young,
        "New today": scheduled[0],
        "Learning today": scheduled[1],
        "Review today": scheduled[2],
    }
    days = math.ceil(unseen / per_day) if per_day else 0
    return {
        "counts": result,
        "total": len(rows),
        "active_total": len(rows) - inactive,
        "days": days,
        "date": str(date.today() + timedelta(days=days)),
        "limit": per_day,
    }


def overview_report(mw: Any, did: int | None = None) -> None:
    from aqt.qt import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

    if not mw.col:
        return
    did = did or mw.col.decks.selected()
    dialog = QDialog(mw)
    dialog.setWindowTitle("牌组附加统计")
    dialog.resize(720, 620)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(mw.col.decks.name(did)))
    selector = QComboBox()
    selector.addItem("关闭附加统计", 0)
    selector.addItem("模式 1：每日数量与本牌组总数", 1)
    selector.addItem("模式 2：本牌组及子牌组的成熟度与预计完成日", 2)
    selector.setCurrentIndex(
        int(get_config("advanced_review")["  More Overview Stats"])
    )
    layout.addWidget(selector)
    text = QTextBrowser()
    layout.addWidget(text, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    def refresh() -> None:
        mode = selector.currentData()
        config = mw.review_tools.config
        config.save(
            "advanced_review",
            config.values["advanced_review"] | {"  More Overview Stats": mode},
        )
        if not mode:
            text.setPlainText(
                "选择模式查看原插件的附加统计。仅查询数据，保留当前主页布局。"
            )
            return
        data = overview_metrics(mw.col, did, mode)
        rows = "".join(
            f"<tr><td>{html.escape(tr(key))}</td><td>{value}</td><td>{value / (data['total'] or 1):.1%}</td>"
            + (
                f"<td>{value / (data['active_total'] or 1):.1%}</td>"
                if mode == 2
                else ""
            )
            + "</tr>"
            for key, value in data["counts"].items()
        )
        if mode == 1:
            extra = f"<p>今天原生可学习：新卡／学习／复习 {data['scheduled']}（包含子牌组和每日限额）。</p><p>明天：{data['tomorrow']}。总数仅计算本牌组，与原模式 1 相同。</p>"
        else:
            extra = f"<p>预计剩余 {data['days']} 天，完成日期 {data['date']}。原公式：未学习卡数 ÷ 预设新卡每日限额 {data['limit']} 后向上取整；不考虑个人未来学习行为。</p><p>第二个百分比列排除暂停和搁置的卡片。原插件的 “暂停”口径包含所有负队列，现明确标注。</p>"
            if not data["limit"]:
                extra += (
                    "<p>限额为 0 时原公式回退为 0 天，此时日期不能用作完成预测。</p>"
                )
        text.setHtml(
            "<table><tr><th>项目</th><th>数量</th><th>占总数</th>"
            + ("<th>占活动总数</th>" if mode == 2 else "")
            + f"</tr>{rows}</table>{extra}"
        )

    selector.currentIndexChanged.connect(refresh)
    refresh()
    dialog.exec()
