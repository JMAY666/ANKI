# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from anki.collection import UndoStatus
from aqt import tr
from aqt.reviewer import Reviewer


@pytest.fixture(autouse=True)
def translated_rating_action(monkeypatch):
    monkeypatch.setattr(tr, "actions_answer_card", lambda: "Answer Card")


def make_reviewer():
    reviewer = Reviewer.__new__(Reviewer)
    reviewer.mw = SimpleNamespace(
        state="review", col=Mock(), _background_op_count=0, undo=Mock()
    )
    reviewer.state = "question"
    reviewer.controls_active = Mock(return_value=True)
    reviewer._cancel_pending_audio = Mock()
    reviewer.shortcuts = Mock()
    reviewer._pending_typed_answer = object()
    reviewer.mw.col.undo_status.return_value = UndoStatus(
        undo=tr.actions_answer_card(), last_step=12
    )
    return reviewer


@pytest.mark.parametrize("face", ["question", "answer"])
def test_previous_card_undoes_the_displayed_rating_and_cancels_pending_input(face):
    reviewer = make_reviewer()
    reviewer.state = face

    reviewer._undo_previous_card("12")

    reviewer.mw.undo.assert_called_once()
    reviewer._cancel_pending_audio.assert_called_once()
    reviewer.shortcuts.invalidate.assert_called_once()
    assert reviewer._pending_typed_answer is None


@pytest.mark.parametrize(
    "blocked",
    ["empty", "edit", "stale", "invalid", "busy", "transition", "hidden", "outside"],
)
def test_previous_card_cannot_undo_an_unrelated_or_stale_operation(blocked):
    reviewer = make_reviewer()
    token = "12"
    if blocked == "empty":
        reviewer.mw.col.undo_status.return_value = UndoStatus()
    elif blocked == "edit":
        reviewer.mw.col.undo_status.return_value = UndoStatus(
            undo="Edit Note", last_step=12
        )
    elif blocked == "stale":
        token = "11"
    elif blocked == "invalid":
        token = "not-a-step"
    elif blocked == "busy":
        reviewer.mw._background_op_count = 1
    elif blocked == "transition":
        reviewer.state = "transition"
    elif blocked == "hidden":
        reviewer.controls_active.return_value = False
    elif blocked == "outside":
        reviewer.mw.state = "deckBrowser"

    reviewer._undo_previous_card(token)

    reviewer.mw.undo.assert_not_called()
    reviewer._cancel_pending_audio.assert_not_called()
