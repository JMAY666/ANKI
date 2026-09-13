# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two native review surfaces, one collection, scheduler and undo history."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from typing import Any

from anki.cards import Card
from anki.scheduler_pb2 import ReviewCardAnswer
from aqt import gui_hooks
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QEvent,
    QFrame,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QObject,
    QPalette,
    QPushButton,
    QSplitter,
    Qt,
    QTabBar,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from aqt.reviewer import Reviewer, ReviewerBottomBar, V3CardInfo
from aqt.toolbar import BottomWebView
from aqt.utils import showWarning
from aqt.webview import AnkiWebView, AnkiWebViewKind

from .learning.deck_select import DeckTreeSelect
from .learning.review_layout import ReviewLayout

FOCUS_SCRIPT = """(() => {
  if (window.ankiDualReviewFocusInstalled) return;
  window.ankiDualReviewFocusInstalled = true;
  for (const event of ['pointerdown', 'focusin']) {
    document.addEventListener(event, () => pycmd('dualReviewFocus'), true);
  }
  const attached = new WeakSet();
  function attach(doc) {
    if(attached.has(doc)) return;
    attached.add(doc);
    doc.addEventListener('keydown', event => {
      if(event.repeat || event.isComposing || event.keyCode===229 ||
          typeof window.ankiReviewShortcutAllowed!=='function' || !window.ankiReviewShortcutAllowed()) return;
      let key = ({' ':'Space', 'Enter':'Return', 'Escape':'Esc'})[event.key] || event.key;
      const parts=[];
      if(event.ctrlKey) parts.push('Ctrl');
      if(event.altKey) parts.push('Alt');
      if(event.shiftKey) parts.push('Shift');
      if(event.metaKey) parts.push('Meta');
      parts.push(key);
      const canonical=parts.join('+').toLowerCase();
      const index=(window.ankiDualReviewKeys || []).findIndex(k=>k.toLowerCase()===canonical);
      if(index>=0){event.preventDefault();event.stopImmediatePropagation();pycmd('dualReviewKey:'+window.ankiDualReviewKeyEpoch+':'+index);}
    }, true);
    const frames=()=>doc.querySelectorAll('iframe').forEach(frame=>{
      try {if(frame.contentDocument) attach(frame.contentDocument);} catch(_) {}
    });
    new MutationObserver(frames).observe(doc,{childList:true,subtree:true});
    doc.addEventListener('load',frames,true);
    frames();
  }
  attach(document);
})();
"""


class ReviewPanel(QFrame):
    def __init__(
        self, owner: DualReview, index: int, reviewer: Reviewer, native: ReviewLayout
    ) -> None:
        super().__init__()
        self.setObjectName("dualReviewPanel")
        self.owner, self.index, self.reviewer, self.native = (
            owner,
            index,
            reviewer,
            native,
        )
        self.session_id = uuid.uuid4().hex
        self.deck_id = 0
        self.token = 0
        self.revision = 0
        self.pending = False
        self.stale = False
        self.elapsed = 0.0
        self.fresh_on_refresh = False
        self.cached_signature = None
        self.started: float | None = None
        self.paused_timers: list[tuple[str, int]] = []
        layout = QVBoxLayout(self)
        self.content_layout = layout
        layout.setContentsMargins(6, 6, 6, 6)
        self.heading = QWidget()
        head = QVBoxLayout(self.heading)
        head.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.activate_button = QPushButton(self.name)
        self.activate_button.clicked.connect(lambda: owner.activate(self, focus=True))
        row.addWidget(self.activate_button)
        row.addStretch()
        self.mode_label = QLabel("正式复习")
        row.addWidget(self.mode_label)
        head.addLayout(row)
        self.deck = DeckTreeSelect()
        self.deck.setAccessibleName(self.name + "牌组")
        self.deck.currentIndexChanged.connect(self.deck_changed)
        head.addWidget(self.deck)
        layout.addWidget(self.heading)
        warning_row = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        warning_row.addWidget(self.message, 1)
        self.refresh = QPushButton("刷新本栏")
        self.refresh.clicked.connect(
            lambda: self.next_card(keep=not self.fresh_on_refresh)
        )
        warning_row.addWidget(self.refresh)
        layout.addLayout(warning_row)
        self.message.hide()
        self.refresh.hide()
        if index:
            layout.addWidget(native, 1)
        self.setAccessibleName(self.name + "复习")

    @property
    def name(self) -> str:
        return "左栏" if self.index == 0 else "右栏"

    def signature(self):
        reviewer = self.reviewer
        if not reviewer.card or not reviewer._v3:
            return None
        note = reviewer.card.note()
        return (
            reviewer._v3.top_card().card.SerializeToString(),
            tuple(note.fields),
            tuple(note.tags),
            json.dumps(reviewer.card.note_type(), sort_keys=True),
            json.dumps(
                self.owner.mw.col.decks.config_dict_for_deck_id(
                    reviewer.card.current_deck_id()
                ),
                sort_keys=True,
            ),
        )

    def can_act(self) -> bool:
        return bool(
            self.owner.visible()
            and (self.owner.enabled or not self.index)
            and self.reviewer.card
            and not self.stale
            and not self.pending
            and not self.owner.submitting
        )

    def fill_decks(self) -> None:
        self.deck.blockSignals(True)
        self.deck.set_decks(
            [("请选择牌组", 0)]
            + [(d.name, d.id) for d in self.owner.mw.col.decks.all_names_and_ids()],
            self.deck_id,
        )
        self.deck.blockSignals(False)

    def deck_changed(self, _index: int) -> None:
        if not self.owner.managed:
            return
        if self.owner.submitting:
            self.fill_decks()
            return
        self.owner.activate(self)
        self.deck_id = self.deck.currentData()
        self.next_card()

    def next_card(
        self,
        keep: bool = False,
        preserve: bool = False,
        card_id: int = 0,
        face: str | None = None,
    ) -> None:
        if not self.owner.managed or self.owner.submitting:
            return
        self.revision += 1
        revision = self.revision
        self.pending = True
        self.stale = False
        reviewer = self.reviewer
        reviewer.shortcuts.invalidate()
        if not preserve:
            reviewer._cancel_pending_audio()
            self.paused_timers.clear()
            self.started = None
        held = card_id or (reviewer.card.id if keep and reviewer.card else 0)
        old_face = face or (reviewer.state if held else "question")
        self.message.setText("正在取卡…")
        self.message.show()
        self.refresh.hide()
        did = self.deck_id
        expected = (self.cached_signature or self.signature()) if preserve else None

        def fetch(col):
            if not did:
                col._backend.release_review_card(self.session_id)
                return None
            response = col._backend.get_review_card(
                session_id=self.session_id,
                deck_id=did,
                keep_card_id=held,
                validate_only=False,
            )
            signature = None
            if preserve and response.queued_cards.cards:
                card = response.queued_cards.cards[0].card
                note = col.get_note(card.note_id)
                signature = (
                    card.SerializeToString(),
                    tuple(note.fields),
                    tuple(note.tags),
                    json.dumps(col.models.get(note.mid), sort_keys=True),
                    json.dumps(
                        col.decks.config_dict_for_deck_id(
                            card.original_deck_id or card.deck_id
                        ),
                        sort_keys=True,
                    ),
                )
            return response, signature

        def received(payload):
            if revision != self.revision or not self.owner.managed:
                return
            self.pending = False
            output, actual = payload if payload is not None else (None, None)
            if output is not None and output.stale:
                self.mark_stale("原卡片已不在可复习范围内，请重新取卡。")
                self.fresh_on_refresh = True
                return
            if output is None or not output.queued_cards.cards:
                reviewer.card = None
                reviewer.state = None
                reviewer._v3 = None
                reviewer._reps = None
                self.token = 0
                reviewer.web.stdHtml(
                    '<div style="padding:28px;line-height:1.8"><h2>请选择牌组</h2><p>另一栏可以继续复习。</p></div>'
                    if not did
                    else '<div style="padding:28px;line-height:1.8"><h2>暂时没有可取出的卡片</h2><p>可能已完成、学习卡尚未到期，或卡片与限额正在另一栏使用。</p></div>',
                    context=reviewer,
                )
                reviewer.bottom.web.clear()
                self.message.hide()
                self.refresh.setVisible(bool(did))
                self.owner.update_ui()
                self.owner.refresh_peers(self)
                return
            self.token = output.token
            self.fresh_on_refresh = False
            preview = output.queued_cards.cards[0].states.current.filtered.HasField(
                "preview"
            )
            self.mode_label.setText("筛选预览 · 原计划不变" if preview else "正式复习")
            if preserve and expected != actual:
                self.mark_stale()
                return
            if not preserve:
                reviewer.previous_card = reviewer.card
                reviewer._v3 = V3CardInfo.from_queue(output.queued_cards)
                reviewer.card = Card(
                    self.owner.mw.col, backend_card=reviewer._v3.top_card().card
                )
                reviewer.card.start_timer()
                self.elapsed = 0.0
                self.started = time.monotonic() if self.owner.active is self else None
                reviewer._card_info.set_card(reviewer.card)
                reviewer._previous_card_info.set_card(reviewer.previous_card)
                reviewer.web.set_bridge_command(reviewer._linkHandler, reviewer)
                reviewer.bottom.web.set_bridge_command(
                    reviewer._linkHandler, ReviewerBottomBar(reviewer)
                )
                reviewer._state_mutation_js = self.owner.mw.col.get_config(
                    "cardStateCustomizer"
                )
                if (
                    reviewer._reps is None
                    or reviewer.bottom.web._content_state != "review"
                ):
                    reviewer._initWeb()
                reviewer._showQuestion()
                if old_face == "answer":
                    reviewer._showAnswer()
            self.native.viewport.set_reviewing(True)
            self.message.hide()
            self.refresh.hide()
            self.install_focus()
            self.cached_signature = self.signature()
            self.owner.update_ui()
            self.owner.refresh_peers(self)

        QueryOp(parent=self.owner.mw, op=fetch, success=received).failure(
            lambda exc: self.failed(exc, revision)
        ).run_in_background()

    def install_focus(self) -> None:
        for web in (self.reviewer.web, self.reviewer.bottom.web):
            web.eval(FOCUS_SCRIPT)
        self.owner.install_shortcuts()

    def failed(self, exc: Exception, revision: int) -> None:
        if revision == self.revision:
            self.pending = False
            self.mark_stale("操作未完成，请刷新本栏以核对当前状态。")
            showWarning(str(exc), parent=self.owner.mw)

    def mark_stale(self, message: str = "卡片已更新，请刷新后继续评分。") -> None:
        self.stale = True
        self.reviewer.shortcuts.invalidate()
        self.reviewer._cancel_pending_audio()
        self.message.setText(message)
        self.message.show()
        self.refresh.show()

    def validate(self) -> None:
        if not self.token or self.pending or self.stale:
            return
        revision = self.revision

        def received(result):
            if revision != self.revision:
                return
            if result.stale:
                self.mark_stale()
                return
            if self.reviewer._v3:
                current = self.reviewer._v3.queued_cards
                updated = result.queued_cards
                current.new_count = updated.new_count
                current.learning_count = updated.learning_count
                current.review_count = updated.review_count
                counts = json.dumps(
                    [updated.new_count, updated.learning_count, updated.review_count]
                )
                self.reviewer.bottom.web.eval(
                    "(() => {const values="
                    + counts
                    + ";['new-count','learn-count','review-count'].forEach((name,index)=>document.querySelectorAll('.'+name).forEach(node=>{(node.querySelector('u')||node).textContent=values[index]}));})();"
                )

        QueryOp(
            parent=self.owner.mw,
            op=lambda col: col._backend.get_review_card(
                session_id=self.session_id,
                deck_id=self.deck_id,
                keep_card_id=0,
                validate_only=True,
            ),
            success=received,
        ).failure(lambda exc: self.failed(exc, revision)).run_in_background()

    def pause(self) -> None:
        if self.started is not None:
            self.elapsed += time.monotonic() - self.started
            self.started = None
        self.paused_timers.clear()
        for name in ("_show_question_timer", "_show_answer_timer"):
            timer = getattr(self.reviewer, name, None)
            if timer and timer.isActive():
                self.paused_timers.append((name, max(1, timer.remainingTime())))
        self.reviewer._cancel_pending_audio()
        self.reviewer.bottom.web.eval(
            "if(typeof timerStopped !== 'undefined') timerStopped=true;"
        )
        self.reviewer.web.eval(
            "document.querySelectorAll('audio,video').forEach(m=>m.pause());"
        )
        self.reviewer.web.page().setAudioMuted(True)

    def resume(self) -> None:
        self.reviewer.web.page().setAudioMuted(False)
        if self.reviewer.card:
            self.reviewer.web.setPlaybackRequiresGesture(
                not self.reviewer.card.autoplay()
            )
        if self.reviewer.card and self.started is None:
            self.started = time.monotonic()
            self.reviewer.card.timer_started = time.time() - self.elapsed
        for name, remaining in self.paused_timers:
            if self.reviewer.auto_advance_enabled:
                callback = (
                    self.reviewer._on_show_question_timeout
                    if name == "_show_question_timer"
                    else self.reviewer._on_show_answer_timeout
                )
                setattr(
                    self.reviewer,
                    name,
                    self.owner.mw.progress.timer(remaining, callback, repeat=False),
                )
        self.paused_timers.clear()
        pending = self.reviewer._pending_visible_audio
        if pending:
            self.reviewer._play_visible_audio(str(pending[0]), acknowledged=False)

    def submit(self, answer, callback) -> None:
        if self.owner.submitting or self.pending or self.stale:
            self.reviewer.state = "answer"
            return
        self.owner.submitting = True
        self.owner.update_ui()
        revision = self.revision
        card_id = answer.card_id
        deck_id = self.deck_id
        token = self.token
        answer.milliseconds_taken = int(
            (self.elapsed + (time.monotonic() - self.started if self.started else 0))
            * 1000
        )

        def done(changes):
            self.owner.submitting = False
            counter = self.owner.mw.col.undo_status().last_step
            self.owner.history[counter] = (self.index, deck_id, card_id)
            if self.revision == revision:
                with self.owner.render_context(self.reviewer):
                    callback(changes)
            self.owner.update_ui()

        def failed(exc):
            self.owner.submitting = False
            self.reviewer.state = "answer"
            self.failed(exc, revision)

        CollectionOp(
            parent=self.owner.mw,
            op=lambda col: col._backend.answer_review_card(
                ReviewCardAnswer(session_id=self.session_id, token=token, answer=answer)
            ),
        ).success(done).failure(failed).run_in_background(initiator=self.reviewer)


class DualReview(QObject):
    def __init__(self, mw: Any) -> None:
        super().__init__(mw)
        self.mw = mw
        self.managed = False
        self.enabled = False
        self.submitting = False
        self.audio_owner: Reviewer | None = None
        self.panels: list[ReviewPanel] = []
        self.history: dict[int, tuple[int, int, int]] = {}
        self.undo_labels: dict[int, str] = {}
        self.active: ReviewPanel | None = None
        self.page: QWidget | None = None
        self.original_reviewer = mw.reviewer
        self.compact = False
        self.paused = False
        self.key_epoch = 0
        self.web_keys: list[str] = []
        self.web_actions: list = []
        self.context_depth = 0
        self.single_layout: dict = {}
        mw.app.installEventFilter(self)
        gui_hooks.state_will_change.append(self.state_change)
        gui_hooks.profile_will_close.append(self.stop)
        gui_hooks.state_did_undo.append(self.did_undo)
        gui_hooks.theme_did_change.append(self.update_ui)
        mw.passfail2.changed.connect(self.refresh_controls)
        mw.app.focusChanged.connect(self.focus_changed)

    def build(self) -> None:
        if self.page:
            return
        workspace = self.mw.learning_workspace
        self.native_index = workspace.pages.indexOf(workspace.native)
        self.placeholder = QWidget()
        self.page = QWidget()
        self.page.setObjectName("dualReviewWorkspace")
        layout = QVBoxLayout(self.page)
        layout.setContentsMargins(8, 6, 8, 6)
        row = QHBoxLayout()
        row.addWidget(QLabel("双栏复习"))
        row.addStretch()
        self.undo_button = QPushButton("撤销上次操作")
        self.undo_button.clicked.connect(self.mw.undo)
        row.addWidget(self.undo_button)
        close = QPushButton("退出双栏")
        close.clicked.connect(self.toggle)
        row.addWidget(close)
        layout.addLayout(row)
        self.tabs = QTabBar()
        self.tabs.addTab("左栏")
        self.tabs.addTab("右栏")
        self.tabs.currentChanged.connect(
            lambda index: self.activate(self.panels[index])
        )
        layout.addWidget(self.tabs)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.splitterMoved.connect(self.save_sizes)
        layout.addWidget(self.splitter, 1)
        left = ReviewPanel(self, 0, self.original_reviewer, workspace.native)
        web = AnkiWebView(self.mw, kind=AnkiWebViewKind.MAIN)
        web.setMinimumWidth(0)
        gui_hooks.card_review_webview_did_init(web, AnkiWebViewKind.MAIN)
        bottom = BottomWebView(self.mw)
        reviewer = Reviewer(self.mw, web, bottom)
        native = ReviewLayout(
            web, bottom, lambda value: self.save_card_size("right", value)
        )
        right = ReviewPanel(self, 1, reviewer, native)
        self.panels = [left, right]
        self.active = left
        for panel in self.panels:
            self.splitter.addWidget(panel)
            panel.setMinimumWidth(280)
        self.splitter.handle(1).setAccessibleName("双栏分隔线")
        self.splitter.handle(1).setToolTip(
            "拖动调整双栏宽度；卡片边缘用于调整单张卡片尺寸"
        )
        workspace.pages.addWidget(self.page)

    def panel_for(self, reviewer: Reviewer) -> ReviewPanel | None:
        return next((p for p in self.panels if p.reviewer is reviewer), None)

    @contextmanager
    def render_context(self, reviewer: Reviewer):
        previous = self.mw.reviewer
        self.context_depth += 1
        self.mw.reviewer = reviewer
        try:
            yield
        finally:
            self.context_depth -= 1
            self.mw.reviewer = (
                previous
                if self.context_depth
                else (
                    self.active.reviewer
                    if self.managed and self.active
                    else self.original_reviewer
                )
            )

    def visible(self) -> bool:
        workspace = self.mw.learning_workspace
        return bool(
            self.managed
            and not self.paused
            and self.mw.state == "review"
            and workspace.pages.currentWidget()
            is (self.page if self.enabled else workspace.native)
        )

    def toggle(self) -> None:
        if not self.mw.col or self.submitting:
            return
        self.build()
        workspace = self.mw.learning_workspace
        if self.enabled:
            self.activate(self.panels[0])
            self.panels[1].pause()
            self.enabled = False
            self.panels[1].revision += 1
            self.panels[1].pending = False
            QueryOp(
                parent=self.mw,
                op=lambda col: col._backend.release_review_card(
                    self.panels[1].session_id
                ),
                success=lambda _: None,
            ).run_in_background()
            self.restore_native()
            workspace.native.viewport.load(self.single_layout)
            workspace.native.viewport.minimum_card_width = 400
            workspace.native.viewport.setMinimumWidth(416)
            workspace.show_review()
            self.update_ui()
            return
        entering = not self.managed
        self.managed = self.enabled = True
        self.single_layout = self.mw.pm.profile.get("reviewViewportLayout", {})
        workspace.pages.removeWidget(workspace.native)
        workspace.pages.insertWidget(self.native_index, self.placeholder)
        self.panels[0].content_layout.addWidget(workspace.native, 1)
        for panel in self.panels:
            panel.native.viewport.minimum_card_width = 280
            panel.native.viewport.setMinimumWidth(280)
            panel.native.viewport.load(
                self.mw.pm.profile.get("dualReviewLayout", {}).get(
                    "left" if panel.index == 0 else "right", {}
                )
            )
            panel.fill_decks()
        self.active = self.panels[0]
        self.mw.reviewer = self.original_reviewer
        if entering:
            self.history.clear()
            self.panels[0].deck_id = int(self.mw.col.decks.selected())
            self.panels[0].fill_decks()
        was_reviewing = (
            self.mw.state == "review" and self.original_reviewer.card is not None
        )
        if entering and was_reviewing:
            assert self.original_reviewer.card is not None
            self.panels[0].elapsed = (
                self.original_reviewer.card.time_taken(capped=False) / 1000
            )
            self.panels[0].started = time.monotonic()
        if self.mw.state != "review":
            self.mw.moveToState("review")
        else:
            self.show_review()
        self.audio_owner = self.original_reviewer if was_reviewing else None
        if entering:
            panel = self.panels[0]
            panel.started = time.monotonic()
            panel.elapsed = (
                panel.reviewer.card.time_taken(capped=False) / 1000
                if was_reviewing
                else 0
            )
            panel.next_card(keep=was_reviewing, preserve=was_reviewing)
        self.panels[1].next_card(
            keep=bool(self.panels[1].reviewer.card),
            preserve=bool(self.panels[1].reviewer.card),
        )
        self.panels[1].reviewer.web.page().setAudioMuted(True)
        sizes = self.mw.pm.profile.get("dualReviewLayout", {}).get("sizes", [1, 1])
        if (
            isinstance(sizes, list)
            and len(sizes) == 2
            and all(isinstance(n, int) and n > 0 for n in sizes)
        ):
            self.splitter.setSizes(sizes)
        self.update_ui()

    def show_review(self) -> None:
        workspace = self.mw.learning_workspace
        workspace.header.hide()
        workspace.review_bar.setVisible(
            not self.enabled and workspace.review_toolbar_visible()
        )
        workspace.pages.setCurrentWidget(
            self.page if self.enabled else workspace.native
        )
        workspace.native.show()
        if self.active:
            workspace.review_label.setText("复习 · " + self.active.deck.currentText())
        self.visibility(True)
        self.update_ui()

    def activate(self, panel: ReviewPanel, focus: bool = False) -> None:
        if not self.managed or (panel.index and not self.enabled):
            return
        changed = self.active is not panel
        if changed:
            if self.active:
                self.active.pause()
                self.active.reviewer.shortcuts.invalidate()
            self.active = panel
            self.mw.reviewer = panel.reviewer
            panel.resume()
            if panel.reviewer.card:
                self.mw.review_tools.sidebar.update_card()
        if changed:
            self.install_shortcuts()
        self.update_ui()
        if focus:
            panel.reviewer.web.setFocus()

    def install_shortcuts(self) -> None:
        if self.active and self.visible():
            self.mw.clearStateShortcuts()
            shortcuts = self.active.reviewer._shortcutKeys()
            self.mw.setStateShortcuts(shortcuts)
            self.web_keys = [QKeySequence(key).toString() for key, _ in shortcuts]
            self.web_actions = [action for _, action in shortcuts]
            self.key_epoch += 1
            code = f"window.ankiDualReviewKeys={json.dumps(self.web_keys)};window.ankiDualReviewKeyEpoch={self.key_epoch};"
            for panel in self.panels:
                for web in (panel.reviewer.web, panel.reviewer.bottom.web):
                    web.eval(code)

    def web_shortcut(self, reviewer, command: str) -> None:
        if not self.active or self.active.reviewer is not reviewer:
            return
        try:
            _, epoch, index = command.split(":")
            if int(epoch) == self.key_epoch and 0 <= int(index) < len(self.web_actions):
                reviewer.shortcuts.run(self.web_actions[int(index)])
        except (ValueError, IndexError):
            return

    def focus_changed(self, _old, new) -> None:
        if not self.managed or new is None:
            return
        for panel in self.panels:
            if (
                panel is new
                or panel.isAncestorOf(new)
                or panel.reviewer.web is new
                or panel.reviewer.bottom.web is new
            ):
                self.activate(panel)
                return

    def eventFilter(self, obj, event) -> bool:
        if (
            self.managed
            and event.type() == QEvent.Type.Resize
            and obj in (self.mw, self.page)
        ):
            QTimer.singleShot(0, self.update_ui)
        return False

    def visibility(self, visible: bool) -> None:
        self.paused = not visible
        for panel in self.panels:
            panel.reviewer.shortcuts.invalidate()
            panel.reviewer.bottom.web.set_review_page_visible(
                visible and (self.enabled or not panel.index)
            )
        if visible:
            if self.active:
                self.active.resume()
            self.install_shortcuts()
        else:
            if self.active:
                self.active.pause()
            self.mw.clearStateShortcuts()

    def changed(self, changes, handler) -> None:
        if not self.managed:
            return
        if changes.note_text and handler is not None:
            origin = getattr(handler, "_dual_review_origin", None)
            if origin is not None:
                self.undo_labels[self.mw.col.undo_status().last_step] = (
                    self.panels[origin].name + "编辑"
                )
        for panel in self.panels:
            if (self.enabled or not panel.index) and panel.reviewer is not handler:
                panel.validate()
            elif panel.reviewer is handler and not panel.pending:
                panel.validate()
        self.update_ui()

    def refresh_peers(self, source: ReviewPanel) -> None:
        if self.enabled:
            for panel in self.panels:
                if panel is not source:
                    panel.validate()

    def update_ui(self, *_args) -> None:
        if not self.page or not self.managed:
            return
        self.compact = self.page.width() < 840
        self.tabs.setVisible(self.enabled and self.compact)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(self.active.index)
        self.tabs.blockSignals(False)
        for panel in self.panels:
            panel.setVisible(
                self.enabled and (not self.compact or panel is self.active)
            )
            color = (
                self.mw.palette()
                .color(
                    QPalette.ColorRole.Highlight
                    if panel is self.active
                    else QPalette.ColorRole.Mid
                )
                .name()
            )
            panel.setStyleSheet(
                f"QFrame#dualReviewPanel{{border:1px solid {color};border-radius:6px;}}"
            )
            panel.activate_button.setText(
                panel.name + (" · 当前操作" if panel is self.active else " · 点击激活")
            )
            panel.activate_button.setCheckable(True)
            panel.activate_button.setChecked(panel is self.active)
            panel.deck.setEnabled(not self.submitting)
        if self.mw.col:
            undo = self.mw.col.undo_status()
            entry = self.history.get(undo.last_step)
            self.undo_button.setEnabled(bool(undo.undo) and not self.submitting)
            self.undo_button.setText(
                "撤销："
                + (
                    self.panels[entry[0]].name + "评分"
                    if entry
                    else self.undo_labels.get(undo.last_step, undo.undo)
                )
                if undo.undo
                else "撤销上次操作"
            )

    def did_undo(self, output) -> None:
        if not self.managed:
            return
        entry = self.history.pop(output.counter, None)
        if entry:
            index, deck_id, card_id = entry
            panel = self.panels[index if self.enabled else 0]
            panel.deck_id = deck_id
            panel.fill_decks()
            self.activate(panel)
            panel.next_card(card_id=card_id, face="answer")

    def save_sizes(self, *_args) -> None:
        if self.enabled and not self.compact:
            value = dict(self.mw.pm.profile.get("dualReviewLayout", {}))
            value["sizes"] = self.splitter.sizes()
            self.mw.pm.profile["dualReviewLayout"] = value
            self.mw.pm.save()

    def save_card_size(self, side: str, value: dict) -> None:
        config = dict(self.mw.pm.profile.get("dualReviewLayout", {}))
        config[side] = value
        self.mw.pm.profile["dualReviewLayout"] = config
        self.mw.pm.save()

    def refresh_controls(self) -> None:
        if not self.managed:
            return
        for panel in self.panels:
            reviewer = panel.reviewer
            reviewer.shortcuts.invalidate()
            if reviewer.card and not panel.stale and not panel.pending:
                if reviewer.state == "answer":
                    reviewer._showEaseButtons()
                elif reviewer.state == "question":
                    reviewer._showAnswerButton()
        self.install_shortcuts()

    def state_change(self, new: str, _old: str) -> None:
        if self.managed and new not in ("review", "resetRequired"):
            self.stop()

    def restore_native(self) -> None:
        workspace = self.mw.learning_workspace
        if workspace.pages.indexOf(self.placeholder) >= 0:
            workspace.pages.removeWidget(self.placeholder)
        if workspace.pages.indexOf(workspace.native) < 0:
            self.panels[0].layout().removeWidget(workspace.native)
            workspace.pages.insertWidget(self.native_index, workspace.native)

    def stop(self) -> None:
        if not self.managed:
            return
        self.visibility(False)
        for panel in self.panels:
            panel.revision += 1
            panel.pending = False
            panel.cached_signature = None
            panel.reviewer.cleanup()
            if self.mw.col:
                self.mw.col._backend.release_review_card(panel.session_id)
        self.restore_native()
        self.mw.learning_workspace.native.viewport.minimum_card_width = 400
        self.mw.learning_workspace.native.viewport.load(self.single_layout)
        self.enabled = self.managed = False
        self.mw.reviewer = self.original_reviewer
        self.history.clear()
        self.undo_labels.clear()
