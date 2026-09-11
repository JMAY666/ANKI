# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Scope keyboard actions to the visible card and its current input context."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from aqt import gui_hooks
from aqt.qt import (
    QAbstractSpinBox,
    QAction,
    QApplication,
    QComboBox,
    QEvent,
    QInputMethodEvent,
    QKeyEvent,
    QKeySequence,
    QKeySequenceEdit,
    QLineEdit,
    QObject,
    QPlainTextEdit,
    QShortcut,
    Qt,
    QTextEdit,
    QWidget,
)
from aqt.webview import AnkiWebView


def answer_key_errors(reviewer: Any, values: Mapping[int, str | None]) -> set[int]:
    mw = reviewer.mw
    reserved = [QKeySequence(key) for key, _ in reviewer._shortcutKeys(False, False)]
    reserved.extend(
        shortcut.key()
        for shortcut in mw.findChildren(QShortcut)
        if shortcut not in mw.stateShortcuts
    )
    reserved.extend(
        key for action in mw.findChildren(QAction) for key in action.shortcuts()
    )
    sequences = {ease: QKeySequence(key) for ease, key in values.items() if key}

    def conflicts(left: QKeySequence, right: QKeySequence) -> bool:
        return not right.isEmpty() and (
            left.matches(right) != QKeySequence.SequenceMatch.NoMatch
            or right.matches(left) != QKeySequence.SequenceMatch.NoMatch
        )

    return {
        ease
        for ease, key in sequences.items()
        if key.isEmpty()
        or not key.toString()
        or any(conflicts(key, other) for other in reserved)
        or any(
            conflicts(key, other) for index, other in sequences.items() if index != ease
        )
    }


class ReviewShortcutGuard(QObject):
    def __init__(self, reviewer: Any) -> None:
        super().__init__(reviewer.mw)
        self.reviewer = reviewer
        self.mw = reviewer.mw
        self.generation = 0
        self.pending: object | None = None
        self.composing = False
        self.mw.app.installEventFilter(self)
        gui_hooks.state_will_change.append(self.invalidate)

    def invalidate(self, *_args: Any) -> None:
        self.generation += 1
        self.pending = None

    def snapshot(self) -> tuple:
        card = self.reviewer.card
        control = getattr(self.mw, "passfail2", None)
        return (
            self.generation,
            self.mw.bottomWeb._page_epoch,
            card.id if card else None,
            self.reviewer.state,
            bool(control and control.value["enabled"]),
        )

    def focus_web(self, focus: QWidget | None) -> AnkiWebView | None:
        while focus is not None:
            if isinstance(focus, AnkiWebView):
                return focus
            focus = focus.parentWidget()
        return None

    def editing(self, focus: QWidget | None) -> bool:
        while focus is not None:
            if isinstance(
                focus,
                (
                    QLineEdit,
                    QTextEdit,
                    QPlainTextEdit,
                    QAbstractSpinBox,
                    QComboBox,
                    QKeySequenceEdit,
                ),
            ):
                return True
            focus = focus.parentWidget()
        return False

    def available(self) -> bool:
        focus = self.mw.app.focusWidget()
        return bool(
            self.mw.state == "review"
            and self.mw.bottomWeb.review_controls_active()
            and self.reviewer.card
            and self.reviewer.state in ("question", "answer")
            and QApplication.activeWindow() is self.mw
            and not QApplication.activeModalWidget()
            and not QApplication.activePopupWidget()
            and not self.composing
            and focus
            and focus.window() is self.mw
            and not self.editing(focus)
        )

    def run(self, action: Callable[[], Any]) -> None:
        if self.pending is not None or not self.available():
            return
        focus = self.mw.app.focusWidget()
        web = self.focus_web(focus)
        if web is not None and web not in (self.reviewer.web, self.mw.bottomWeb):
            return
        ticket = self.pending = object()
        snapshot = self.snapshot()

        def finish(allowed: Any) -> None:
            if self.pending is not ticket:
                return
            self.pending = None
            if (
                allowed is True
                and self.available()
                and self.snapshot() == snapshot
                and self.mw.app.focusWidget() is focus
            ):
                action()

        if web is None:
            finish(True)
        else:
            web.evalWithCallback(
                "typeof ankiReviewShortcutAllowed === 'function' && ankiReviewShortcutAllowed()",
                finish,
            )

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if isinstance(event, QInputMethodEvent):
            self.composing = bool(event.preeditString())
        elif event and event.type() == QEvent.Type.FocusOut:
            self.composing = False
        if not isinstance(event, QKeyEvent) or self.mw.state != "review":
            return False
        focus = self.mw.app.focusWidget()
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and focus is not None
            and focus.window() is self.mw
            and not QApplication.activeModalWidget()
            and not QApplication.activePopupWidget()
            and (self.composing or self.editing(focus))
        ):
            # Let Qt editors and the input method handle the original key.
            event.accept()
            return True
        if (
            event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers()
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
            and self.available()
            and self.focus_web(focus) is None
            and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
        ):
            # Native buttons can accept ShortcutOverride themselves. Their
            # default activation must obey the same rule as the review WebView.
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.run(self.reviewer.onEnterKey)
            event.accept()
            return True
        return False
