# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""One navigation context around the existing native reviewer and graph components."""

from __future__ import annotations

import html
import importlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aqt
from anki.decks import DeckId
from aqt import gui_hooks
from aqt.operations import CollectionOp, QueryOp
from aqt.operations.deck import set_current_deck
from aqt.qt import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTextBrowser,
    QTimer,
    QUrl,
    QVBoxLayout,
    QWidget,
)
from aqt.theme import theme_manager
from aqt.utils import askUser, getSaveFile, showInfo, tooltip
from aqt.webview import AnkiWebView, AnkiWebViewKind

from .deck_select import DeckTreeSelect
from .metrics import collect_snapshot, scope_query, session_summary
from .policy import DAY, application_blocker
from .review_layout import LAYOUT_KEY, ReviewLayout
from .service import (
    analyze,
    apply_confirmed,
    effect_review,
    reconcile,
    report_payload,
    revert_action,
)
from .settings import SettingsDialog, get_key
from .storage import LearningStore


def escaped(value: Any) -> str:
    return html.escape(str(value))


def when(value: int) -> str:
    return datetime.fromtimestamp(value).strftime("%m-%d %H:%M")


def percent(value: float | None) -> str:
    return "数据不足" if value is None else f"{value * 100:.1f}%"


class LearningWorkspace(QWidget):
    def __init__(self, mw: Any):
        super().__init__(mw)
        self.mw = mw
        self.setObjectName("learningWorkspace")
        self.store: LearningStore | None = None
        self.snapshot: dict | None = None
        self.generation = 0
        self.refresh_revision = 0
        self.refreshing = False
        self.analyzing = False
        self.syncing = False
        self.last_sync = 0
        self.sync_quiet_until = 0.0
        self.changing = False
        self.legacy_navigation = False
        self.session: dict | None = None
        self.before_answer_id = 0
        self.paused_timers: list = []
        self.paused_auto_advance: bool | None = None
        self.report_ids: list[str] = []
        self.action_ids: list[str] = []
        self.report_id: str | None = None
        self.graph_search = ""
        self.graph_days = 7
        self._build_ui()
        self._register()
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.daily_tick)
        self.timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName("learningHeader")
        head = QVBoxLayout(self.header)
        row = QHBoxLayout()
        title = QLabel("统计")
        title.setObjectName("learningTitle")
        row.addWidget(title)
        self.deck = DeckTreeSelect()
        self.deck.setAccessibleName("统计牌组")
        self.deck.setMinimumWidth(150)
        row.addWidget(self.deck, 1)
        self.deck_options_button = QPushButton("牌组选项")
        self.deck_options_button.clicked.connect(self.deck_options)
        row.addWidget(self.deck_options_button)
        self.resume_button = QPushButton("继续复习")
        self.resume_button.clicked.connect(self.show_review)
        row.addWidget(self.resume_button)
        self.resume_button.hide()
        head.addLayout(row)
        self.preset_scope = QLabel()
        self.preset_scope.setWordWrap(True)
        head.addWidget(self.preset_scope)
        row = QHBoxLayout()
        self.include_children = QCheckBox("含子牌组")
        self.include_children.setChecked(True)
        row.addWidget(self.include_children)
        self.days = QComboBox()
        self.days.setAccessibleName("统计历史范围")
        for label, value in (
            ("近 7 天", 7),
            ("近 28 天", 28),
            ("近一年", 365),
            ("全部历史", 0),
        ):
            self.days.addItem(label, value)
        row.addWidget(self.days)
        settings = QPushButton("分析设置")
        self.settings_button = settings
        settings.clicked.connect(self.settings)
        row.addWidget(settings)
        row.addStretch()
        head.addLayout(row)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for text in ("概览统计", "AI 建议", "记录"):
            self.tabs.addTab(text)
        head.addWidget(self.tabs)
        self.status = QLabel("实际统计来自本机学习记录；AI 分析另行标注。")
        self.status.setWordWrap(True)
        head.addWidget(self.status)
        layout.addWidget(self.header)
        self._build_review_bar(layout)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)

        self.overview = QWidget()
        overview = QVBoxLayout(self.overview)
        actions = QHBoxLayout()
        for label, callback in (
            ("查看范围内卡片", self.browse_scope),
            ("牌组工具", self.native_overview),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        overview.addLayout(actions)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setObjectName("learningResult")
        overview.addWidget(self.result)
        self.summary = QTextBrowser()
        self.summary.setOpenExternalLinks(False)
        self.summary.setObjectName("learningSummary")
        overview.addWidget(self.summary, 1)
        details = QHBoxLayout()
        for label, callback in (
            ("详细统计", self.show_graphs),
            ("FSRS 扩展统计（原口径）", self.show_legacy_stats),
            ("牌组附加统计", self.show_advanced_stats),
            ("刷新", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            details.addWidget(button)
        overview.addLayout(details)
        self.pages.addWidget(self.overview)

        # Reparent the original WebViews, never clone or replace the card renderer.
        mw_layout = self.mw.mainLayout
        mw_layout.removeWidget(self.mw.web)
        mw_layout.removeWidget(self.mw.bottomWeb)
        self.native = ReviewLayout(
            self.mw.web, self.mw.bottomWeb, self.save_review_layout
        )
        self.reset_layout_button.clicked.connect(self.native.viewport.reset_layout)
        self.pages.addWidget(self.native)

        ai_page = QWidget()
        ai_layout = QVBoxLayout(ai_page)
        ai_buttons = QHBoxLayout()
        self.analyze_button = QPushButton("分析最近完整学习日")
        self.analyze_button.clicked.connect(lambda: self.analyze_now(manual=True))
        self.payload_button = QPushButton("查看将发送的汇总数据")
        self.payload_button.clicked.connect(self.preview_payload)
        self.apply_button = QPushButton("查看并确认应用")
        self.apply_button.clicked.connect(self.confirm_apply)
        for button in (self.analyze_button, self.payload_button, self.apply_button):
            ai_buttons.addWidget(button)
        ai_layout.addLayout(ai_buttons)
        split = QSplitter()
        self.report_list = QListWidget()
        self.report_list.setMaximumWidth(260)
        self.report_list.setMinimumWidth(140)
        self.report_list.setAccessibleName("每日报告")
        self.report_list.currentRowChanged.connect(self.select_report)
        self.ai_text = QTextBrowser()
        split.addWidget(self.report_list)
        split.addWidget(self.ai_text)
        split.setStretchFactor(1, 1)
        split.setSizes([180, 600])
        ai_layout.addWidget(split, 1)
        self.pages.addWidget(ai_page)

        history_page = QWidget()
        history = QVBoxLayout(history_page)
        self.history_text = QTextBrowser()
        history.addWidget(self.history_text, 1)
        self.action_picker = QComboBox()
        history.addWidget(self.action_picker)
        undo = QPushButton("撤销所选参数调整")
        undo.clicked.connect(self.confirm_revert)
        history.addWidget(undo)
        self.pages.addWidget(history_page)

        self._build_graph_page()
        self.pages.setCurrentWidget(self.native)
        self.header.hide()
        mw_layout.addWidget(self)
        self.deck.currentIndexChanged.connect(self.scope_changed)
        self.include_children.toggled.connect(self.scope_changed)
        self.days.currentIndexChanged.connect(self.scope_changed)
        self.tabs.currentChanged.connect(self.open)
        self.update_theme()

    def _build_review_bar(self, layout: QVBoxLayout) -> None:
        from ..passfail2 import mode_selector

        self.review_bar = QWidget()
        review_actions = QHBoxLayout(self.review_bar)
        self.review_label = QLabel()
        self.review_label.setWordWrap(True)
        review_actions.addWidget(self.review_label, 1)
        review_actions.addWidget(mode_selector(self.mw))
        self.reset_layout_button = QPushButton("恢复布局")
        self.reset_layout_button.setToolTip("恢复卡片区域的默认宽度和高度")
        review_actions.addWidget(self.reset_layout_button)
        self.finish_button = QPushButton("结束复习 · 返回牌组")
        self.finish_button.clicked.connect(lambda: self.mw.moveToState("deckBrowser"))
        review_actions.addWidget(self.finish_button)
        layout.addWidget(self.review_bar)
        self.review_bar.hide()

    def _build_graph_page(self) -> None:
        graph_page = QWidget()
        graph_layout = QVBoxLayout(graph_page)
        graph_actions = QHBoxLayout()
        self.graph_scope_label = QLabel()
        self.graph_scope_label.setWordWrap(True)
        graph_actions.addWidget(self.graph_scope_label, 1)
        self.extended_stats = QCheckBox("搜索与扩展统计")
        self.extended_stats.setChecked(
            self.mw.review_tools.config.values["policy"]["search_stats_enabled"]
        )
        self.extended_stats.toggled.connect(self.toggle_extended_stats)
        graph_actions.addWidget(self.extended_stats)
        export = QPushButton("导出 PDF")
        export.clicked.connect(self.export_graphs)
        graph_actions.addWidget(export)
        back = QPushButton("返回概览")
        back.clicked.connect(lambda: self.open(0))
        graph_actions.addWidget(back)
        graph_layout.addLayout(graph_actions)
        self.graph_web = AnkiWebView(self.mw, kind=AnkiWebViewKind.DECK_STATS)
        self.mw.review_tools.search_stats.attach(self.graph_web)
        self.graph_web.set_bridge_command(self.graph_bridge, self)
        graph_layout.addWidget(self.graph_web, 1)
        self.pages.addWidget(graph_page)

    def _register(self) -> None:
        gui_hooks.profile_did_open.append(self.profile_open)
        gui_hooks.profile_will_close.append(self.profile_close)
        gui_hooks.state_did_change.append(self.state_changed)
        gui_hooks.operation_did_execute.append(self.operation_done)
        gui_hooks.reviewer_will_answer_card.append(self.before_answer)
        gui_hooks.reviewer_did_answer_card.append(self.after_answer)
        gui_hooks.sync_will_start.append(self.sync_start)
        gui_hooks.sync_did_finish.append(self.sync_finished)
        gui_hooks.theme_did_change.append(self.update_theme)
        action = QAction("统计", self.mw)
        action.triggered.connect(lambda: self.open(0))
        self.mw.form.menuTools.addAction(action)
        helper = importlib.import_module("aqt.builtin_features.fsrs_helper")
        helper.menu_for_helper.addAction("每日 AI 分析…", lambda: self.open(1))

    def update_theme(self, *args: Any) -> None:
        dark = theme_manager.night_mode
        bg, fg, line, card = (
            ("#202326", "#e5e9e7", "#414a46", "#272d2a")
            if dark
            else ("#f6f8f5", "#243b30", "#d9e2dc", "#ffffff")
        )
        self.setStyleSheet(f"""
            QWidget#learningWorkspace {{ background: {bg}; color: {fg}; }}
            QWidget#learningHeader {{ border-bottom: 1px solid {line}; }}
            QLabel#learningTitle {{ font-size: 22px; font-weight: 600; padding: 4px 12px; }}
            QLabel#learningResult {{ padding: 8px; }}
            QTextBrowser {{ background: {card}; color: {fg}; border: 1px solid {line}; border-radius: 8px; padding: 12px; }}
            QTabBar::tab {{ padding: 10px 22px; border-bottom: 3px solid transparent; }}
            QTabBar::tab:selected {{ border-bottom-color: #478266; font-weight: 600; }}
            QPushButton {{ padding: 7px 12px; }}
        """)

    def profile_open(self) -> None:
        self.generation += 1
        self.native.viewport.load(self.mw.pm.profile.get(LAYOUT_KEY))
        self.store = LearningStore(Path(self.mw.pm.profileFolder()))
        self.snapshot = None
        self.session = None
        self.analyzing = False
        self.last_sync = 0
        self.sync_quiet_until = time.monotonic() + 120
        self.fill_decks()
        self.read_history()
        store = self.store
        QueryOp(
            parent=self,
            op=lambda col: reconcile(col, store),
            success=lambda _: self.read_history(),
        ).failure(self.error).run_in_background()

    def profile_close(self) -> None:
        self.end_session()
        self.generation += 1
        self.store = None
        self.snapshot = None
        self.report_id = None
        self.paused_timers.clear()
        self.paused_auto_advance = None
        self.header.hide()
        self.review_bar.hide()
        self.native.viewport.set_reviewing(False)
        self.pages.setCurrentWidget(self.native)
        self.graph_web.load_url(QUrl("about:blank"))

    def save_review_layout(self, value: dict[str, float]) -> None:
        self.mw.pm.profile[LAYOUT_KEY] = value
        self.mw.pm.save()

    def fill_decks(self) -> None:
        if not self.mw.col:
            return
        current = (
            self.deck.currentData()
            if self.deck.count()
            else int(self.mw.col.decks.selected())
        )
        self.changing = True
        self.deck.set_decks(
            [("全部牌组", 0)]
            + [
                (item.name, int(item.id))
                for item in self.mw.col.decks.all_names_and_ids()
            ],
            current,
        )
        self.changing = False
        self.update_deck_settings()

    def update_deck_settings(self) -> None:
        self.preset_scope.setToolTip("")
        did = self.deck.currentData()
        deck = self.mw.col.decks.get(DeckId(did), default=False) if did else None
        self.deck_options_button.setEnabled(bool(deck))
        if not deck:
            self.preset_scope.setText("选择一个具体牌组后可调整其选项。")
            return
        if deck.get("dyn"):
            self.preset_scope.setText(f"筛选牌组设置：{deck['name']}。")
            return
        preset = self.mw.col.decks.config_dict_for_deck_id(DeckId(did))
        names = [
            item["name"]
            for item in self.mw.col.decks.all()
            if not item.get("dyn") and item.get("conf") == preset["id"]
        ]
        self.preset_scope.setText(
            f"当前牌组：{deck['name']} · 预设「{preset['name']}」由 {len(names)} 个牌组共享。修改预设会影响这些牌组。"
        )
        self.preset_scope.setToolTip("\n".join(names))

    def deck_options(self) -> None:
        from aqt.deckoptions import display_options_for_deck_id

        did = self.deck.currentData()
        if did and self.mw.col.decks.get(DeckId(did), default=False):
            display_options_for_deck_id(DeckId(did))

    def scope_changed(self, *args: Any) -> None:
        if self.changing:
            return
        self.snapshot = None
        self.update_deck_settings()
        self.refresh()
        if self.pages.currentIndex() == 4:
            self.show_graphs()

    def open(self, tab: int = 0) -> None:
        if self.changing or not self.mw.col or not self.store:
            return
        if self.mw.state == "review" and self.mw.reviewer.state == "transition":
            return
        was_visible = self.header.isVisible()
        self.fill_decks()
        if not was_visible:
            self.changing = True
            self.deck.setCurrentIndex(
                max(0, self.deck.findData(int(self.mw.col.decks.selected())))
            )
            self.changing = False
            self.update_deck_settings()
        self.header.show()
        self.review_bar.hide()
        self.resume_button.setVisible(self.mw.state == "review")
        self.changing = True
        self.tabs.setCurrentIndex(tab)
        self.changing = False
        self.pages.setCurrentIndex((0, 2, 3)[tab])
        self.review_visibility(False)
        self.deck.setEnabled(self.mw.state != "review")
        self.include_children.setEnabled(self.mw.state != "review")
        if tab == 0:
            self.refresh()
        elif tab in (1, 2):
            self.read_history()

    def show_review(self) -> None:
        if self.mw.state != "review":
            return
        self.header.hide()
        self.native.viewport.set_reviewing(True)
        self.review_bar.show()
        self.review_label.setText("复习 · " + self.mw.col.decks.current()["name"])
        self.pages.setCurrentWidget(self.native)
        self.review_visibility(True)

    def review_visibility(self, visible: bool) -> None:
        if self.mw.state != "review":
            return
        self.mw.reviewer.shortcuts.invalidate()
        self.mw.bottomWeb.set_review_page_visible(visible)
        self.mw.review_tools.visibility_changed()
        if visible:
            # Reviewer.show() already installs these on entry. Reinstall only
            # after our temporary navigation cleared them, or Qt sees duplicate
            # shortcuts and no longer dispatches the rating key reliably.
            if not self.mw.stateShortcuts:
                self.mw.setStateShortcuts(self.mw.reviewer._shortcutKeys())
            if self.paused_auto_advance is not None:
                self.mw.reviewer.auto_advance_enabled = self.paused_auto_advance
                self.paused_auto_advance = None
            for timer, remaining in self.paused_timers:
                try:
                    timer.start(max(1, remaining))
                except RuntimeError:
                    pass
            self.paused_timers.clear()
            self.mw.web.setFocus()
        else:
            self.mw.clearStateShortcuts()
            if self.paused_auto_advance is None:
                self.paused_auto_advance = self.mw.reviewer.auto_advance_enabled
            self.mw.reviewer.auto_advance_enabled = False
            if not self.paused_timers:
                for name in ("_show_question_timer", "_show_answer_timer"):
                    timer = getattr(self.mw.reviewer, name, None)
                    if timer and timer.isActive():
                        self.paused_timers.append((timer, timer.remainingTime()))
                        timer.stop()

    def state_changed(self, new: str, old: str) -> None:
        if not self.store:
            return
        if old == "review" and new != "review":
            self.end_session()
            self.paused_timers.clear()
            self.paused_auto_advance = None
        if new == "review":
            if old != "review":
                deck = self.mw.col.decks.current()
                self.session = {
                    "id": uuid.uuid4().hex,
                    "started": int(time.time()),
                    "deck_id": deck["id"],
                    "name": deck["name"],
                    "events": [],
                }
                self.changing = True
                self.deck.setCurrentIndex(max(0, self.deck.findData(int(deck["id"]))))
                self.changing = False
            self.show_review()
        elif new in ("deckBrowser", "overview", "resetRequired", "profileManager"):
            self.header.hide()
            self.review_bar.hide()
            self.native.viewport.set_reviewing(False)
            self.pages.setCurrentWidget(self.native)
            if new == "overview" and old == "review" and not self.legacy_navigation:
                QTimer.singleShot(
                    0,
                    lambda: (
                        self.mw.moveToState("deckBrowser")
                        if self.mw.state == "overview"
                        else None
                    ),
                )
        self.legacy_navigation = False

    def operation_done(self, changes: Any, handler: Any) -> None:
        self.sync_quiet_until = time.monotonic() + 10
        if self.store and self.header.isVisible():
            self.fill_decks()
        if self.store and self.pages.currentIndex() == 0 and not self.refreshing:
            QTimer.singleShot(0, self.refresh)

    def before_answer(self, result: tuple, reviewer: Any, card: Any) -> tuple:
        if self.pages.currentWidget() is not self.native and self.header.isVisible():
            return (False, result[1])
        self.before_answer_id = self.mw.col.db.scalar(
            "SELECT COALESCE(MAX(id),0) FROM revlog WHERE cid=?", card.id
        )
        return result

    def after_answer(self, reviewer: Any, card: Any, ease: int) -> None:
        if not self.session or not self.store:
            return
        ids = self.mw.col.db.list(
            "SELECT id FROM revlog WHERE cid=? AND id>? AND ease=? ORDER BY id",
            card.id,
            self.before_answer_id,
            ease,
        )
        if len(ids) == 1 and ids[0] not in self.session["events"]:
            self.session["events"].append(ids[0])
        self.persist_session()

    def persist_session(self, ended: int | None = None) -> None:
        if self.session and self.store:
            item = self.session
            self.store.save_session(
                item["id"],
                item["started"],
                item["deck_id"],
                item["name"],
                item["events"],
                ended,
            )

    def end_session(self) -> None:
        if self.session:
            self.persist_session(int(time.time()))
            self.session = None

    def start_review(self) -> None:
        if self.mw.state == "review":
            self.show_review()
            return
        did = self.deck.currentData()
        if not did:
            self.open(0)
            tooltip("请先选择一个牌组或父牌组")
            return
        if (
            not self.include_children.isChecked()
            and len(self.mw.col.decks.deck_and_child_ids(DeckId(did))) > 1
        ):
            from aqt.filtered_deck import FilteredDeckConfigDialog

            self.open(0)
            FilteredDeckConfigDialog(
                self.mw,
                search=scope_query(self.mw.col, did, False) + " is:due -is:suspended",
            )
            return

        self.mw.deckBrowser.start_review(DeckId(did))

    def native_overview(self) -> None:
        if self.mw.state == "review":
            if not askUser(
                "结束本次复习并打开原牌组工具？未评分的卡片不会生成学习记录。",
                parent=self,
            ):
                return
        did = self.deck.currentData()
        if not did:
            return

        def show(_: Any) -> None:
            self.legacy_navigation = True
            self.mw.moveToState("overview")

        set_current_deck(parent=self, deck_id=DeckId(did)).success(
            show
        ).run_in_background()

    def refresh(self) -> None:
        if not self.store or not self.mw.col or self.refreshing:
            return
        self.refreshing = True
        self.refresh_revision += 1
        revision, generation = self.refresh_revision, self.generation
        did, children, days = (
            int(self.deck.currentData() or 0),
            self.include_children.isChecked(),
            int(self.days.currentData()),
        )
        self.status.setText("正在读取实际学习记录…")

        def ready(snapshot: dict) -> None:
            self.refreshing = False
            if generation != self.generation or revision != self.refresh_revision:
                return
            if (did, children, days) != (
                int(self.deck.currentData() or 0),
                self.include_children.isChecked(),
                int(self.days.currentData()),
            ):
                self.refresh()
                return
            self.snapshot = snapshot
            self.render_summary(snapshot)

        def failed(exc: Exception) -> None:
            self.refreshing = False
            if generation == self.generation:
                self.error(exc)

        QueryOp(
            parent=self,
            op=lambda col: collect_snapshot(
                col, did, children, int(time.time()), complete_day=False, days=days
            ),
            success=ready,
        ).failure(failed).run_in_background()

    def render_summary(self, snapshot: dict) -> None:
        data, cards = snapshot["summary"], snapshot["cards"]
        self.status.setText(
            f"{self.deck.currentText()} · {self.days.currentText()} · 更新于 {when(snapshot['created_at'])}。历史范围不改变今天的原生复习队列。"
        )
        metrics = (
            ("评分记录", f"{data['reviews']} 次"),
            ("不重复卡片", f"{data['unique_cards']} 张"),
            ("记录耗时", f"{data['recorded_seconds'] / 60:.1f} 分钟"),
            ("跨日真实保留率", percent(data["true_retention"])),
        )
        cells = "".join(
            f"<td style='padding:18px'><small>{label}</small><h2>{value}</h2></td>"
            for label, value in metrics
        )
        daily = "".join(
            f"<tr><td>{datetime.fromtimestamp(self.mw.col.sched.day_cutoff + item['day_offset'] * DAY).strftime('%m-%d')}</td><td>{item['reviews']}</td><td>{item['again']}</td><td>{item['recorded_seconds'] / 60:.1f} 分钟</td></tr>"
            for item in data["daily"][-14:]
        )
        future = " · ".join(
            f"{'今天' if day == 0 else '+' + str(day) + '天'} {count}"
            for day, count in enumerate(cards["future_due"][:7])
        )
        self.summary.setHtml(
            f"<table width='100%'><tr>{cells}</tr></table><p>有效跨日样本 {data['long_reviews']} 次，通过 {data['long_passed']} 次。评分是自评；耗时沿用原生计时上限。</p><h3>现在的学习任务</h3><p>当前未学习 {cards['new']} 张 · 逾期 {cards['backlog']} 张 · 今天到期 {cards['future_due'][0]} 张</p><p>到期数量未扣除每日限额；可实际学习数量由原生调度决定。</p><p>{future}</p><h3>实际学习趋势</h3><table width='100%' cellspacing='8'><tr><th align='left'>学习日</th><th>评分次数</th><th>重来次数</th><th>记录耗时</th></tr>{daily or '<tr><td>该范围没有学习记录。</td></tr>'}</table><h3>AI 建议</h3><p>在“AI 建议”页查看每日分析。推断和参数建议独立于这些实际统计，未确认不会改变设置。</p>"
        )
        self.render_session()

    def render_session(self) -> None:
        if not self.store or not self.mw.col:
            return
        sessions = self.store.sessions()
        if not sessions:
            self.result.setText("")
            self.result.hide()
            return
        item = sessions[0]
        result = session_summary(self.mw.col, json.loads(item["events"]))
        self.result.show()
        self.result.setText(
            f"最近一次：{item['deck_name']} · {result['reviews']} 次评分 / {result['unique_cards']} 张卡片 · {result['recorded_seconds'] / 60:.1f} 分钟。\n重来 {result['ratings'][0]} / 困难 {result['ratings'][1]} / 良好 {result['ratings'][2]} / 简单 {result['ratings'][3]}。已撤销的评分不计入。"
        )

    def browse_scope(self) -> None:
        query = scope_query(
            self.mw.col,
            int(self.deck.currentData() or 0),
            self.include_children.isChecked(),
        )
        aqt.dialogs.open("Browser", self.mw).search_for(query)

    def show_graphs(self) -> None:
        if not self.mw.col:
            return
        self.review_visibility(False)
        self.graph_search = scope_query(
            self.mw.col,
            int(self.deck.currentData() or 0),
            self.include_children.isChecked(),
        )
        self.graph_days = int(self.days.currentData())
        self.graph_scope_label.setText(
            f"{self.deck.currentText()} · {self.days.currentText()}。卡片状态及未来到期图反映当前状态；各图保留原有口径。"
        )
        query = urlencode(
            {"learning": "1", "scope": self.graph_search, "days": self.graph_days}
        )
        self.graph_web.load_sveltekit_page("graphs?" + query)
        self.pages.setCurrentIndex(4)

    def toggle_extended_stats(self, enabled: bool) -> None:
        config = self.mw.review_tools.config
        config.save(
            "policy", config.values["policy"] | {"search_stats_enabled": enabled}
        )
        self.show_graphs()

    def show_advanced_stats(self) -> None:
        from ..review_tools.info import overview_report

        overview_report(self.mw, int(self.deck.currentData() or 0))

    def show_legacy_stats(self) -> None:
        self.review_visibility(False)
        did = self.deck.currentData()
        if did and did != self.mw.col.decks.selected() and self.mw.state != "review":
            set_current_deck(parent=self, deck_id=DeckId(did)).success(
                lambda _: self.show_legacy_stats()
            ).run_in_background()
            return
        dialog = aqt.dialogs.open("DeckStats", self.mw)
        dialog.wholeCollection = not self.deck.currentData()
        # Legacy supports month/year/all only. Do not relabel it as a 7-day report.
        dialog.period = (
            2
            if not self.days.currentData()
            else 1
            if self.days.currentData() == 365
            else 0
        )
        dialog.refresh()

    def graph_bridge(self, command: str) -> bool:
        if not command.startswith("browserSearch:"):
            return False
        query = command.split(":", 1)[1].strip()
        dialog = QDialog(self)
        dialog.setWindowTitle("统计对应的卡片范围")
        layout = QVBoxLayout(dialog)
        label = QLabel(
            "以下条件来自所点击的原生统计图。普通复习保持原生调度；筛选复习将在原生窗口中确认。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        editor = QPlainTextEdit(query)
        editor.setReadOnly(True)
        layout.addWidget(editor)
        browse = QPushButton("查看卡片")
        browse.clicked.connect(
            lambda: aqt.dialogs.open("Browser", self.mw).search_for(query)
        )
        layout.addWidget(browse)
        filtered = QPushButton("复习其中已到期的卡片…")

        def study() -> None:
            if self.mw.state == "review":
                showInfo("请先结束当前复习，再建立新的筛选复习范围。", parent=dialog)
                return
            from aqt.filtered_deck import FilteredDeckConfigDialog

            FilteredDeckConfigDialog(self.mw, search=f"({query}) is:due -is:suspended")
            dialog.accept()

        filtered.clicked.connect(study)
        layout.addWidget(filtered)
        dialog.resize(560, 310)
        dialog.exec()
        return True

    def export_graphs(self) -> None:
        picker = QDialog(self)
        path = getSaveFile(
            picker,
            title="导出统计 PDF",
            dir_description="stats",
            key="stats",
            ext=".pdf",
            fname="学习统计.pdf",
        )
        picker.deleteLater()
        if path:
            self.graph_web.page().printToPdf(path)

    def settings(self) -> None:
        if self.store:
            SettingsDialog(self, self.store).exec()
            self.read_history()

    def preview_payload(self) -> None:
        if not self.store:
            return
        settings, generation = self.store.settings(), self.generation

        def show(snapshot: dict) -> None:
            if generation != self.generation:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("待发送数据预览 · 此操作不调用 API")
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(
                json.dumps(
                    report_payload(self.store, snapshot, settings),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            text.setReadOnly(True)
            layout.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.resize(740, 600)
            dialog.exec()

        QueryOp(
            parent=self,
            op=lambda col: collect_snapshot(
                col, settings["deck_id"], settings["include_children"], int(time.time())
            ),
            success=show,
        ).failure(self.error).run_in_background()

    def sync_start(self) -> None:
        self.syncing = True

    def sync_finished(self) -> None:
        self.syncing = False
        self.last_sync = int(time.time())
        self.sync_quiet_until = time.monotonic() + 120

    def daily_tick(self) -> None:
        if (
            not self.store
            or not self.mw.col
            or self.mw.safeMode
            or self.analyzing
            or self.syncing
            or self.mw.state == "review"
            or self.mw.progress.busy()
            or time.monotonic() < self.sync_quiet_until
        ):
            return
        settings = self.store.settings()
        if not settings["daily_enabled"]:
            return
        reports = self.store.reports()
        if reports and reports[0]["status"] == "configuration_error":
            self.status.setText(
                "Key 或余额需要处理；请修复后手动重新分析，期间每日请求已暂停。"
            )
            return
        now = int(time.time())
        if now < int(self.mw.col.sched.day_cutoff) - DAY + 600:
            return
        if (
            self.mw.pm.sync_auth()
            and self.last_sync < int(self.mw.col.sched.day_cutoff) - DAY
        ):
            return
        self.analyze_now(manual=False)

    def analyze_now(self, *, manual: bool) -> None:
        if not self.store or not self.mw.col or self.analyzing:
            return
        if self.mw.state == "review" or self.syncing or self.mw.progress.busy():
            if manual:
                showInfo("请先结束本次复习，并等待同步或其他操作完成。", parent=self)
            return
        settings = self.store.settings()
        if not settings["consent"] or not settings["deck_id"]:
            if manual:
                self.settings()
            return
        try:
            key = get_key(self.store, settings)
            if not key:
                raise ValueError("请先在分析设置中配置 DeepSeek Key")
        except (ValueError, OSError) as exc:
            self.error(exc)
            return
        generation, store = self.generation, self.store
        self.analyzing = True
        self.analyze_button.setEnabled(False)

        def dispatch(snapshot: dict) -> None:
            if generation != self.generation:
                return
            try:
                day_reviews = sum(
                    item["reviews"]
                    for item in snapshot["baseline"]["daily"]
                    if item["day_offset"] == -2
                )
                scope = f"{settings['deck_id']}:{int(settings['include_children'])}:v1"
                report_id = store.claim(
                    snapshot["day"],
                    scope,
                    settings["monthly_budget"],
                    int(time.time()),
                    manual=manual,
                )
                if report_id is None:
                    self.analysis_done(generation)
                    if manual:
                        tooltip("该学习日的任务正在执行或已有应用记录，未重复执行")
                    return
                if not day_reviews:
                    store.finish(
                        report_id,
                        "no_activity",
                        snapshot,
                        error="上一完整学习日没有学习记录；未调用 API",
                        cost=0,
                    )
                    self.analysis_done(generation)
                    return
                attempt = store.report(report_id)["attempts"]
                QueryOp(
                    parent=self,
                    op=lambda _: analyze(
                        store,
                        report_id,
                        snapshot,
                        settings,
                        key,
                        expected_attempt=attempt,
                    ),
                    success=lambda _: self.analysis_done(generation),
                ).without_collection().failure(
                    lambda exc: self.analysis_failed(generation, exc)
                ).run_in_background()
            except Exception as exc:
                self.analysis_failed(generation, exc)

        QueryOp(
            parent=self,
            op=lambda col: collect_snapshot(
                col, settings["deck_id"], settings["include_children"], int(time.time())
            ),
            success=dispatch,
        ).failure(lambda exc: self.analysis_failed(generation, exc)).run_in_background()

    def analysis_done(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.analyzing = False
        self.analyze_button.setEnabled(True)
        self.tabs.setTabText(2, "AI 建议 · 已更新")
        self.read_history()

    def analysis_failed(self, generation: int, exc: Exception) -> None:
        self.analysis_done(generation)
        if generation == self.generation:
            self.error(exc)

    def read_history(self) -> None:
        if not self.store:
            return
        selected = self.report_id
        self.report_list.blockSignals(True)
        self.report_list.clear()
        reports = self.store.reports()
        self.report_ids = [item["id"] for item in reports]
        statuses = {
            "ready": "建议就绪",
            "running": "分析中",
            "failed": "未成功",
            "retry": "等待重试",
            "no_activity": "无学习记录",
            "interrupted": "请求中断",
            "configuration_error": "Key / 余额待处理",
            "cancelled": "已取消",
        }
        for item in reports:
            self.report_list.addItem(
                f"{item['day']} · {statuses.get(item['status'], item['status'])}"
            )
        self.report_list.blockSignals(False)
        self.report_list.setCurrentRow(
            self.report_ids.index(selected) if selected in self.report_ids else 0
        )
        if not reports:
            self.report_id = None
            self.ai_text.setHtml(
                "<h2>每日学习分析</h2><p>尚无报告。先在分析设置中选择牌组、每日时间和数据范围，再生成建议。</p><p>实际数据、AI 推断和调整建议会分开展示。这里没有自动调整开关。</p>"
            )
            self.apply_button.setEnabled(False)
        actions = self.store.actions()
        self.action_picker.clear()
        self.action_ids = []
        action_html = ""
        for item in actions:
            self.action_ids.append(item["id"])
            label = f"{when(item['created'])} · {item['before_value']} → {item['after_value']} · {item['status']}"
            self.action_picker.addItem(label, item["id"])
            action_html += f"<p><b>{escaped(label)}</b><br>{escaped(item['reason'])}<br>{escaped(item['error'])}</p>"
        session_html = ""
        if self.mw.col:
            for item in self.store.sessions()[:20]:
                result = session_summary(self.mw.col, json.loads(item["events"]))
                session_html += f"<p>{escaped(item['deck_name'])} · {when(item['started'])} · {result['reviews']} 次评分 / {result['unique_cards']} 张卡片 · {result['recorded_seconds'] / 60:.1f} 分钟</p>"
        spent = sum(item["cost"] for item in reports)
        effect = "打开同一范围的概览，查看调整后的观察结果。"
        if self.snapshot:
            effect = effect_review(self.store, self.snapshot, self.store.settings())[
                "message"
            ]
        self.history_text.setHtml(
            f"<h2>参数应用记录</h2><p>这里只恢复设置，不改写真实学习记录。null 表示恢复继承原预设。</p>{action_html or '<p>尚未应用过调整。</p>'}<h2>效果观察</h2><p>{escaped(effect)}</p><h2>复习记录</h2>{session_html or '<p>还没有本机记录的复习会话。</p>'}<h2>API 用量</h2><p>最近报告累计估算 {spent:.4f} 元。失败请求用量未知时保留预留额度。</p>"
        )

    def select_report(self, index: int) -> None:
        if not self.store or not 0 <= index < len(self.report_ids):
            return
        self.report_id = self.report_ids[index]
        row = self.store.report(self.report_id)
        snapshot = json.loads(row["snapshot"] or "null")
        result = json.loads(row["report"] or "null")
        self.apply_button.setEnabled(False)
        if not result:
            self.ai_text.setHtml(
                f"<h2>{escaped(row['day'])}</h2><p>{escaped(row['error'] or '分析进行中…')}</p>"
            )
            return
        report = result["content"]
        scope = self.mw.col.decks.get(
            DeckId(snapshot["scope"]["deck_id"]), default=False
        )
        scope_name = scope["name"] if scope else "原牌组已不存在"
        observations = "".join(
            f"<li>{escaped(item)}</li>" for item in report["observations"]
        )
        inferences = "".join(
            f"<li>{escaped(item)}</li>" for item in report["inferences"]
        )
        proposed = "".join(
            f"<p><b>每日新卡：{item['before']} → {item['after']}</b><br>{escaped(item['reason'])}<br>依据：{escaped(', '.join(item['evidence']))}</p>"
            for item in report["changes"]
        )
        blocker = application_blocker(snapshot, self.store.settings(), int(time.time()))
        self.apply_button.setEnabled(
            bool(report["changes"]) and not blocker and self.mw.state != "review"
        )
        actual = snapshot["summary"]
        self.ai_text.setHtml(
            f"<h2>{escaped(row['day'])} · {escaped(scope_name)}</h2><p>固定分析窗口：前一完整学习日、近 7 天与 28 天基线。数据快照 {when(snapshot['created_at'])}。</p><h3>本地实际统计</h3><p>{actual['reviews']} 次评分 · {actual['unique_cards']} 张卡片 · 跨日保留率 {percent(actual['true_retention'])}（{actual['long_reviews']} 个样本）</p><h3>AI 摘要〔推断〕</h3><p>{escaped(report['summary'])}</p><h3>AI 对数据的解读</h3><ul>{observations}</ul><h3>AI 推断与不确定性</h3><ul>{inferences}</ul><h3>调整建议</h3>{proposed or '<p>保持当前设置。</p>'}<p>{escaped(blocker)}</p><small>模型 {escaped(result['model'])} · 本次估算 {result['estimated_cost']:.4f} 元。模型解读不替代原生统计。</small>"
        )

    def confirm_apply(self) -> None:
        if not self.store or not self.report_id or self.mw.state == "review":
            return
        row = self.store.report(self.report_id)
        report = json.loads(row["report"])["content"]
        if not report["changes"]:
            return
        change = report["changes"][0]
        snapshot = json.loads(row["snapshot"])
        deck = self.mw.col.decks.get(
            DeckId(snapshot["scope"]["deck_id"]), default=False
        )
        if not deck:
            self.error(ValueError("该报告的牌组已不存在"))
            return
        if not askUser(
            f"牌组：{deck['name']}\n每日新卡限额：{change['before']} → {change['after']}。\n父牌组限额也会约束其子牌组的实际可学习量。\n不会修改共享预设、评分记录或执行批量排程。\n\n{change['reason']}\n\n确认应用？",
            parent=self,
        ):
            return
        store, key = self.store, self.report_id
        CollectionOp(self, lambda col: apply_confirmed(col, store, key)).success(
            lambda _: self.read_history()
        ).failure(self.error).run_in_background(initiator=self)

    def confirm_revert(self) -> None:
        if (
            not self.store
            or not self.action_picker.currentData()
            or self.mw.state == "review"
        ):
            return
        if not askUser(
            "恢复这次调整之前的新卡限额？之后真实发生的学习记录会保留；后续手动修改不会被覆盖。",
            parent=self,
        ):
            return
        store, key = self.store, self.action_picker.currentData()
        CollectionOp(self, lambda col: revert_action(col, store, key)).success(
            lambda _: self.read_history()
        ).failure(self.error).run_in_background(initiator=self)

    def error(self, exc: Exception) -> None:
        self.status.setText(str(exc))
