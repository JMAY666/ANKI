# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Six source-integrated tools sharing Anki's existing reviewer and collection."""

from __future__ import annotations

import html
import importlib
import re
from collections import deque
from typing import Any

from aqt import gui_hooks
from aqt.qt import QAction, QMenu, QObject
from aqt.theme import theme_manager

from .config import ToolConfig, get_config, review_is_visible
from .i18n import tr


class ReviewTools(QObject):
    def __init__(self, mw: Any, storage: Any) -> None:
        super().__init__(mw)
        self.mw = mw
        self.config = ToolConfig(storage)
        self.previous: deque[int] = deque(maxlen=100)
        self.skipped: dict[int, int] = {}
        self.closing = False
        self.controls_dirty = False
        self.renderers: tuple[Any, Any] | None = None
        self.renderer_theme: bool | None = None
        self.menu = QMenu("复习与统计扩展", mw)
        mw.form.menuTools.addMenu(self.menu)
        self.add_action("设置…", self.show_settings)
        self.pace_menu = self.menu.addMenu("复习速度图")
        self.add_action("卡片信息侧栏", self.toggle_sidebar)
        self.add_action("搁置当前卡片（本次跳过）", lambda: self.skip(False))
        self.add_action("暂停当前卡片（本次跳过）", lambda: self.skip(True))
        self.add_action("恢复本次跳过的卡片", self.restore_skipped)
        self.menu.addSeparator()
        self.add_action("快速作答后遗忘 · 报告（全部牌组）", self.show_confidence)
        self.add_action("在浏览器查看快速作答后遗忘的卡片", self.browse_confidence)

    def finish_install(self) -> None:
        from .feedback import Feedback
        from .info import CardSidebar
        from .pace_graph import install
        from .search_stats import install as install_stats

        self.feedback = Feedback(self)
        self.sidebar = CardSidebar(self)
        self.pace = install()
        self.search_stats = install_stats(self)
        gui_hooks.reviewer_did_answer_card.append(self.answered)
        gui_hooks.reviewer_did_show_question.append(self.question)
        gui_hooks.reviewer_did_show_answer.append(self.feedback.capture_buttons)
        gui_hooks.reviewer_will_end.append(self.end_review)
        gui_hooks.profile_will_close.append(self.close_profile)
        gui_hooks.profile_did_open.append(self.open_profile)
        gui_hooks.state_did_change.append(lambda *_: self.visibility_changed())

    def add_action(self, text: str, callback: Any) -> QAction:
        action = QAction(text, self.mw)
        action.triggered.connect(callback)
        self.menu.addAction(action)
        return action

    def show_settings(self) -> None:
        from .settings import ToolSettings

        ToolSettings(self).exec()

    def toggle_sidebar(self) -> None:
        self.sidebar.toggle()

    def show_confidence(self) -> None:
        if self.mw.col:
            from .confidence import show_report

            show_report()

    def browse_confidence(self) -> None:
        if self.mw.col:
            from .confidence import browse_them

            browse_them()

    def answered(self, reviewer: Any, card: Any, ease: int) -> None:
        self.previous.appendleft(card.id)
        self.feedback.show_grade(ease)

    def question(self, card: Any) -> None:
        self.refresh_review_controls()
        self.sidebar.update_card()
        self.feedback.show_debug()

    def visibility_changed(self) -> None:
        if not review_is_visible():
            self.feedback.hide()
            self.pace.overlay.hide()
            self.sidebar.dock.hide()
        else:
            self.refresh_review_controls()
            if self.sidebar.requested:
                self.sidebar.update_card()

    def end_review(self) -> None:
        self.feedback.hide()
        self.pace.overlay.hide()
        self.sidebar.dock.hide()
        # Match ARBb's end-of-session unbury, but only for cards actually
        # buried by this tool. Never unbury/rebury the entire collection.
        if not self.closing:
            self.restore_skipped(buried_only=True)

    def close_profile(self) -> None:
        self.closing = True
        self.search_stats.rotate_token()
        # Profile-close hooks run before the collection is closed. Restore
        # only this tool's manually buried cards synchronously at that boundary.
        if self.mw.col:
            ids = [
                cid
                for cid, queue in self.skipped.items()
                if queue == -3
                and self.mw.col.db.scalar("select queue from cards where id = ?", cid)
                == -3
            ]
            if ids:
                self.mw.col.sched.unbury_cards(ids)
        self.previous.clear()
        self.skipped.clear()
        self.feedback.hide()
        self.sidebar.dock.hide()

    def open_profile(self) -> None:
        self.closing = False

    def skip(self, suspend: bool = False) -> None:
        if not review_is_visible():
            return
        from aqt.operations.scheduling import bury_cards, suspend_cards

        card = self.mw.reviewer.card
        cid = card.id
        operation = suspend_cards if suspend else bury_cards
        operation(parent=self.mw, card_ids=[cid]).success(
            lambda _: self.skipped.update({cid: -1 if suspend else -3})
        ).run_in_background()

    def restore_skipped(self, buried_only: bool = False) -> None:
        if not self.mw.col or not self.skipped:
            return
        from aqt.operations import CollectionOp

        selected = {
            cid: queue
            for cid, queue in self.skipped.items()
            if not buried_only or queue == -3
        }
        if not selected:
            return

        def restore(col: Any) -> Any:
            # Queues can change through undo or another native operation.
            ids = [
                cid
                for cid, queue in selected.items()
                if col.db.scalar("select queue from cards where id = ?", cid) == queue
            ]
            return col.sched.unbury_cards(ids)

        def done(_: Any) -> None:
            for cid in selected:
                self.skipped.pop(cid, None)

        CollectionOp(parent=self.mw, op=restore).success(done).run_in_background()

    def changed(self) -> None:
        self.renderers = None
        self.controls_dirty = True
        self.feedback.hide()
        self.visibility_changed()
        workspace = getattr(self.mw, "learning_workspace", None)
        if workspace:
            selector = workspace.extended_stats
            selector.blockSignals(True)
            selector.setChecked(self.config.values["policy"]["search_stats_enabled"])
            selector.blockSignals(False)
            if workspace.pages.currentIndex() == 4:
                workspace.show_graphs()

    def refresh_review_controls(self) -> None:
        if (
            self.controls_dirty
            and review_is_visible()
            and self.mw.reviewer.card
            and self.mw.reviewer.state in ("question", "answer")
        ):
            self.controls_dirty = False
            # Rebuild controls only. Card DOM, face, timer and scheduler states
            # remain owned by the native reviewer.
            reviewer = self.mw.reviewer
            from aqt.reviewer import ReviewerBottomBar

            reviewer.bottom.web.stdHtml(
                reviewer._bottomHTML(),
                css=["css/toolbar-bottom.css", "css/reviewer-bottom.css"],
                js=[
                    "js/vendor/jquery.min.js",
                    "js/reviewer-shortcuts.js",
                    "js/reviewer-bottom.js",
                ],
                context=ReviewerBottomBar(reviewer),
            )
            if reviewer.state == "answer":
                reviewer._showEaseButtons()
            else:
                reviewer._showAnswerButton()
            self.mw.clearStateShortcuts()
            self.mw.setStateShortcuts(reviewer._shortcutKeys())

    def advanced(self) -> tuple[Any, Any]:
        if self.renderers is None or self.renderer_theme != theme_manager.night_mode:
            styles = importlib.import_module(".advanced.styles", __name__)
            importlib.reload(styles)
            bottom = importlib.import_module(".advanced.Bottom_Bar", __name__)
            buttons = importlib.import_module(".advanced.Button_Colors", __name__)
            importlib.reload(bottom)
            importlib.reload(buttons)
            self.renderers = bottom, buttons
            self.renderer_theme = theme_manager.night_mode
        return self.renderers


def install(mw: Any, storage: Any) -> None:
    if getattr(mw, "review_tools", None) is None:
        mw.review_tools = ReviewTools(mw, storage)
        mw.review_tools.finish_install()


def decorate_buttons(buttons: tuple, reviewer: Any) -> tuple:
    owner = getattr(reviewer.mw, "review_tools", None)
    if owner is None:
        return buttons
    mode = get_config("policy")["style"]
    passfail = reviewer.mw.passfail2.value
    if mode == "colours":
        if passfail["enabled"] and passfail["toggle_names_textcolors"] == "1":
            return buttons
        config = get_config("button_colours")
        palette = config["colours-dark" if theme_manager.night_mode else "colours"]
        count = reviewer.mw.col.sched.answerButtons(reviewer.card)
        colors = palette.get(f"{count} answers", [])
        return tuple(
            (
                ease,
                f'<span style="color:{html.escape(str(colors[ease - 1] if ease <= len(colors) else "black"), quote=True)}">{label}</span>',
            )
            for ease, label in buttons
        )
    if mode != "advanced" or passfail["enabled"]:
        return buttons
    conf = get_config("advanced_review")
    if not conf["  Button Colors"]:
        return buttons
    labels = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
    last_type = (
        reviewer.mw.col.db.scalar(
            "select type from revlog where cid = ? order by id desc limit 1",
            reviewer.card.id,
        )
        or 0
    )
    return tuple(
        (ease, html.escape(tr(conf[f"Button Label_ {labels[ease]}"])))
        for ease, _ in buttons
        if ease == 1
        or (
            not conf[f"Button_   Hide {labels[ease]}"]
            and not (
                ease == 4 and conf["  Hide Easy if not in Learning"] and last_type != 0
            )
        )
    )


def render(reviewer: Any, part: str) -> str | bool | None:
    owner = getattr(reviewer.mw, "review_tools", None)
    if owner is None or get_config("policy")["style"] != "advanced":
        return None
    bottom, buttons = owner.advanced()
    if part == "question":
        bottom._showAnswerButton(reviewer)
        return True
    if part == "buttons" and not get_config("advanced_review")["  Button Colors"]:
        return None
    value = (
        bottom._bottomHTML(reviewer)
        if part == "bottom"
        else buttons._answerButtons(reviewer)
    )
    # Keep ARBb's eight visual styles, using actual responsive rows rather than
    # the old fixed-width table. Existing footer lifecycle still measures it.
    value = value.replace("id=good ", "id=defease ")
    for name, ease in (("again", 1), ("hard", 2), ("good", 3), ("easy", 4)):
        value = value.replace(f"#{name}", f'[data-ease="{ease}"]')
    value += """<style>
        html,body{overflow-x:hidden!important} body{padding:0!important}
        #outer{width:100%;max-width:100%} #innertable>tbody>tr{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:4px}
        #innertable>tbody>tr>td{width:auto;max-width:100%} #middle{flex:1 1 auto}
        #middle table{max-width:100%} #middle tr{display:flex;flex-wrap:wrap;justify-content:center}
        button{max-width:100%;white-space:normal!important;overflow-wrap:anywhere}
        .mybuttons,.wide{min-width:0!important;box-sizing:border-box}
        .timer_style{position:static!important;transform:none!important}
    </style>"""
    return value


def command(reviewer: Any, url: str) -> bool:
    if not url.startswith("builtinReview:"):
        return False
    owner = getattr(reviewer.mw, "review_tools", None)
    if owner is not None and review_is_visible():
        action = url.split(":", 1)[1]
        if action == "card_info":
            owner.sidebar.toggle()
        elif action == "skip":
            owner.skip(get_config("advanced_review")["  Skip Method"] == 2)
        elif action == "showSkipped":
            owner.restore_skipped()
        elif action == "undo":
            reviewer.mw.undo()
    return True


def shortcuts(reviewer: Any, original: list) -> list:
    if (
        getattr(reviewer.mw, "review_tools", None) is None
        or get_config("policy")["style"] != "advanced"
    ):
        return original
    for _label, action, sequence in advanced_shortcut_entries(reviewer, original):
        original.append(
            (
                sequence,
                lambda action=action: command(reviewer, "builtinReview:" + action),
            )
        )
    return original


def advanced_shortcut_entries(reviewer: Any, original: list) -> list:
    from aqt.qt import QAction, QKeySequence, QShortcut

    existing = [QKeySequence(key) for key, _ in original]
    existing.extend(QKeySequence(str(key)) for key in (1, 2, 3, 4))
    existing.extend(
        shortcut.key()
        for shortcut in reviewer.mw.findChildren(QShortcut)
        if shortcut not in reviewer.mw.stateShortcuts
    )
    existing.extend(
        key
        for action in reviewer.mw.findChildren(QAction)
        for key in action.shortcuts()
    )
    conf = get_config("advanced_review")
    entries = []
    for key, action in (
        ("Info", "card_info"),
        ("Skip", "skip"),
        ("Show Skipped", "showSkipped"),
        ("Undo", "undo"),
    ):
        sequence = re.sub(r"\s*\+\s*", "+", conf[f"Button_ Shortcut_ {key} Button"])
        canonical = QKeySequence(sequence)
        conflict = any(
            not other.isEmpty()
            and (
                canonical.matches(other) != QKeySequence.SequenceMatch.NoMatch
                or other.matches(canonical) != QKeySequence.SequenceMatch.NoMatch
            )
            for other in existing
        )
        if conf[f"Button_   {key} Button"] and canonical.toString() and not conflict:
            entries.append((key, action, sequence))
            existing.append(canonical)
    return entries


def advanced_shortcut_hint(reviewer: Any, label: str) -> str:
    entries = advanced_shortcut_entries(
        reviewer, list(reviewer._shortcutKeys(include_tools=False))
    )
    return next((sequence for key, _action, sequence in entries if key == label), "")
