# Source integration: Ankitects Pty Ltd and contributors
# Confident But Wrong — find cards you answered Good/Easy unusually fast, then failed next time.
# Read-only (SELECT on revlog/cards). Never touches due/ivl/reps of any card.

from __future__ import annotations

import html
import statistics
from collections import defaultdict

import aqt
from aqt import mw
from .config import get_config
from aqt.qt import QAction
from aqt.utils import showText, tooltip

DEFAULTS = {
    # "Fast" = answered in less than this fraction of the deck's median answer time.
    "fast_factor": 0.6,
    # How many days of review history to scan.
    "lookback_days": 120,
    # Two reviews closer together than this (hours) are not counted as a pair —
    # they are learning steps within one day, not recall across days.
    "min_gap_hours": 12,
    # How many cards to list in the per-card table.
    "max_rows": 60,
    # Truncate the card preview to this many characters.
    "preview_chars": 60,
}

PREVIEW_CHARS = DEFAULTS["preview_chars"]


def _conf() -> dict:
    """Read config.json, falling back to defaults for anything missing or invalid."""
    global PREVIEW_CHARS
    raw = get_config("confident_wrong") or {}
    conf = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            conf[key] = value
    PREVIEW_CHARS = int(conf["preview_chars"])
    return conf


def _scan(conf: dict, collection=None) -> tuple[list[tuple[int, str, int, int]], dict[str, tuple[int, int, int, int]]]:
    """Return (per-card rows, per-deck summary).

    per-card = [(cid, deck name, times "fast then failed", times answered fast)]
    per-deck = {deck name: (fast+failed, fast total, slow+failed, slow total)}
    """
    col = collection if collection is not None else mw.col
    cutoff_ms = (col.sched.day_cutoff - int(conf["lookback_days"]) * 86400) * 1000

    # ease = 0 and type = 4 are manual reschedules, not real answers -> excluded.
    # New cards are still in learning (type 0); dropping them would hide any deck
    # you only just started, so the real confounder is handled by min_gap_hours below.
    # odid != 0 means the card is borrowed by a filtered deck -> count it under its home deck.
    rows = col.db.all(
        """
        select r.cid, r.ease, r.time,
               case when c.odid != 0 then c.odid else c.did end as deck_id,
               r.id
        from revlog r join cards c on c.id = r.cid
        where r.id >= ? and r.ease > 0 and r.type in (0, 1, 2, 3)
        order by r.cid, r.id
        """,
        cutoff_ms,
    )
    gap_ms = int(conf["min_gap_hours"]) * 3600 * 1000
    fast_factor = float(conf["fast_factor"])

    # Median answer time per deck, over correct answers only.
    times_by_deck: dict[int, list[int]] = defaultdict(list)
    for _cid, ease, time_ms, deck_id, _rid in rows:
        if ease >= 2:
            times_by_deck[deck_id].append(time_ms)
    median = {d: statistics.median(t) for d, t in times_by_deck.items() if t}

    per_card: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # [fast+failed, fast total]
    per_deck: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    deck_of: dict[int, int] = {}

    for cur, nxt in zip(rows, rows[1:]):
        if cur[0] != nxt[0]:  # different card, not a consecutive pair
            continue
        if nxt[4] - cur[4] < gap_ms:  # same-day repeat = learning step, not recall
            continue
        cid, ease, time_ms, deck_id, _rid = cur
        if ease < 3:  # only interested in Good/Easy answers
            continue
        med = median.get(deck_id)
        if not med:
            continue
        deck_of[cid] = deck_id
        failed_next = nxt[1] == 1
        fast = time_ms < fast_factor * med
        bucket = per_deck[deck_id]
        if fast:
            bucket[1] += 1
            per_card[cid][1] += 1
            if failed_next:
                bucket[0] += 1
                per_card[cid][0] += 1
        else:
            bucket[3] += 1
            if failed_next:
                bucket[2] += 1

    cards = [
        (cid, col.decks.name(deck_of[cid]), hits, total)
        for cid, (hits, total) in per_card.items()
        if hits
    ]
    cards.sort(key=lambda r: (-r[2], -r[3]))
    summary = {col.decks.name(d): tuple(v) for d, v in per_deck.items() if v[1] or v[3]}
    return cards, summary


def _preview(cid: int) -> str:
    try:
        note = mw.col.get_card(cid).note()
        text = mw.col.media.strip(note.fields[0]) if note.fields else ""
        text = " ".join(text.split())
    except Exception:
        return "?"
    return text[:PREVIEW_CHARS] + ("…" if len(text) > PREVIEW_CHARS else "")


def _render(cards, summary, conf: dict) -> str:
    def rate(bad: int, total: int) -> str:
        return f"{100.0 * bad / total:.1f}%" if total else "—"

    max_rows = int(conf["max_rows"])
    head = "".join(
        f"<tr><td class=l>{html.escape(name)}</td>"
        f"<td>{rate(fb, ft)}</td><td class=d>({fb}/{ft})</td>"
        f"<td>{rate(sb, st)}</td><td class=d>({sb}/{st})</td></tr>"
        for name, (fb, ft, sb, st) in sorted(
            summary.items(), key=lambda kv: -(kv[1][1] + kv[1][3])
        )
    )
    body = "".join(
        f"<tr><td class=l>{html.escape(_preview(cid))}</td>"
        f"<td class=d>{html.escape(deck)}</td>"
        f"<td>{hits}</td><td class=d>/ {total}</td></tr>"
        for cid, deck, hits, total in cards[:max_rows]
    )
    more = (
        f"<p class=d>共 {len(cards)} 张卡片，显示前 {max_rows} 张。</p>"
        if len(cards) > max_rows
        else ""
    )
    return f"""<style>
 body {{ font-family: -apple-system, sans-serif; font-size: 13px; }}
 table {{ border-collapse: collapse; margin-bottom: 1.2em; }}
 td, th {{ padding: 2px 10px; text-align: right; white-space: nowrap; }}
 td.l, th.l {{ text-align: left; white-space: normal; }}
 td.d {{ opacity: 0.55; }}
 th {{ border-bottom: 1px solid currentColor; }}
 h3 {{ margin: 0.2em 0; }}
 p.d {{ opacity: 0.6; }}
</style>
<h3>快速与较慢作答后的遗忘情况对比</h3>
<p class=d>“快速作答”指耗时少于该牌组中位作答时间的 {float(conf["fast_factor"]):g} 倍。
统计最近 {int(conf["lookback_days"])} 天，且只比较间隔至少 {int(conf["min_gap_hours"])} 小时的连续两次复习。<br>
两列接近：未观察到明显的速度差异；左列更高：快速作答后更容易遗忘；右列更高：需要较长思考的卡片更容易遗忘。</p>
<table>
 <tr><th class=l>牌组</th><th colspan=2>快速作答后遗忘</th><th colspan=2>较慢作答后遗忘</th></tr>
 {head}
</table>
<h3>最常出现此情况的卡片</h3>
<p class=d>次数＝“快速作答后遗忘”的次数／快速作答次数。</p>
<table>
 <tr><th class=l>卡片正面</th><th class=d>牌组</th><th colspan=2>次数</th></tr>
 {body}
</table>
{more}"""


def show_report() -> None:
    conf = _conf()
    cards, summary = _scan(conf)
    if not summary:
        tooltip("复习记录不足，暂时无法分析。")
        return
    showText(_render(cards, summary, conf), parent=mw, type="html", title="快速作答后遗忘分析")


def browse_them() -> None:
    cards, _ = _scan(_conf())
    if not cards:
        tooltip("没有找到符合条件的卡片。")
        return
    query = "cid:" + ",".join(str(c[0]) for c in cards)
    browser = aqt.dialogs.open("Browser", mw)
    browser.search_for(query)
