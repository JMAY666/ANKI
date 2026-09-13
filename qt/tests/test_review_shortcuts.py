# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aqt import gui_hooks
from aqt.builtin_features.passfail2 import answer_key_hint, answer_shortcut_keys
from aqt.qt import (
    QApplication,
    QComboBox,
    QKeySequence,
    QLineEdit,
    QMainWindow,
    QShortcut,
    QTextEdit,
)
from aqt.review_shortcuts import ReviewShortcutGuard, answer_key_errors
from aqt.reviewer import Reviewer


@pytest.fixture
def guard():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.app = app
    window.state = "review"
    window.stateShortcuts = []
    window.bottomWeb = SimpleNamespace(
        _page_epoch=1, review_controls_active=lambda: True
    )
    window.passfail2 = SimpleNamespace(value={"enabled": False})
    reviewer = SimpleNamespace(
        mw=window,
        card=SimpleNamespace(id=1),
        state="question",
        web=Mock(),
        bottom=SimpleNamespace(web=window.bottomWeb),
        controls_active=lambda: True,
    )
    value = ReviewShortcutGuard(reviewer)
    reviewer.shortcuts = value
    yield value
    gui_hooks.state_will_change.remove(value.invalidate)
    app.removeEventFilter(value)
    window.close()


def test_pending_key_is_consumed_only_once(guard):
    guard.available = Mock(return_value=True)
    guard.focus_web = Mock(return_value=guard.reviewer.web)
    action = Mock()
    guard.run(action)
    guard.run(action)
    guard.reviewer.web.evalWithCallback.assert_called_once()
    callback = guard.reviewer.web.evalWithCallback.call_args.args[1]
    callback(True)
    callback(True)
    action.assert_called_once()


@pytest.mark.parametrize("change", ["card", "side", "page", "mode", "generation"])
def test_delayed_key_cannot_act_on_a_different_context(guard, change):
    guard.available = Mock(return_value=True)
    guard.focus_web = Mock(return_value=guard.reviewer.web)
    action = Mock()
    guard.run(action)
    callback = guard.reviewer.web.evalWithCallback.call_args.args[1]
    if change == "card":
        guard.reviewer.card.id += 1
    elif change == "side":
        guard.reviewer.state = "answer"
    elif change == "page":
        guard.mw.bottomWeb._page_epoch += 1
    elif change == "mode":
        guard.mw.passfail2.value["enabled"] = True
    else:
        guard.invalidate()
    callback(True)
    action.assert_not_called()


@pytest.mark.parametrize("response", [False, None, "true"])
def test_editor_or_missing_web_guard_cannot_dispatch(guard, response):
    guard.available = Mock(return_value=True)
    guard.focus_web = Mock(return_value=guard.reviewer.web)
    action = Mock()
    guard.run(action)
    guard.reviewer.web.evalWithCallback.call_args.args[1](response)
    action.assert_not_called()


@pytest.mark.parametrize("widget", [QLineEdit, QTextEdit, QComboBox])
def test_native_editors_keep_their_keyboard_input(guard, widget):
    assert guard.editing(widget(guard.mw))


@pytest.mark.parametrize("side", ["question", "answer", "transition"])
def test_space_and_enter_only_request_the_question_answer(side):
    reviewer = SimpleNamespace(state=side, _getTypedAnswer=Mock())
    Reviewer.onEnterKey(reviewer)
    assert reviewer._getTypedAnswer.call_count == int(side == "question")


def test_two_grade_keys_keep_the_original_scheduler_rating():
    reviewer = SimpleNamespace(
        mw=SimpleNamespace(passfail2=SimpleNamespace(value={"enabled": True})),
        _defaultEase=lambda: 3,
    )
    assert answer_shortcut_keys(reviewer) == {1: "1", 3: "2"}
    assert answer_key_hint(reviewer, 1, "A") == "1"
    assert answer_key_hint(reviewer, 3, "B") == "2"


def test_duplicate_and_reserved_rating_keys_are_rejected(guard):
    reviewer = guard.reviewer
    reviewer._shortcutKeys = lambda *_: [
        ("Space", Mock()),
        ("Return", Mock()),
        ("E", Mock()),
    ]
    navigation = QShortcut(QKeySequence("D"), guard.mw)
    assert answer_key_errors(reviewer, {1: "1", 2: "2", 3: "3", 4: "4"}) == set()
    assert answer_key_errors(reviewer, {1: "Space", 2: "D", 3: "3", 4: "3"}) == {
        1,
        2,
        3,
        4,
    }
    assert navigation.key().toString() == "D"


def test_typed_answer_callback_is_discarded_after_navigation(guard):
    reviewer = guard.reviewer
    reviewer._pending_typed_answer = None
    reviewer._onTypedAnswer = Mock()
    Reviewer._getTypedAnswer(reviewer)
    Reviewer._getTypedAnswer(reviewer)
    reviewer.web.evalWithCallback.assert_called_once()
    callback = reviewer.web.evalWithCallback.call_args.args[1]
    guard.invalidate()
    callback("text")
    reviewer._onTypedAnswer.assert_not_called()


@pytest.mark.parametrize("key", ["Not a valid key", "Ctrl+", "Shift+"])
def test_invalid_key_names_are_rejected(guard, key):
    guard.reviewer._shortcutKeys = lambda *_: []
    assert answer_key_errors(guard.reviewer, {1: key}) == {1}
