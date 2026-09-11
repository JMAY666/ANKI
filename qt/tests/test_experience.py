# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from aqt.reviewer import Reviewer


def pending_reviewer():
    reviewer = Reviewer.__new__(Reviewer)
    reviewer.card = object()
    reviewer.state = "question"
    reviewer.web = Mock()
    reviewer.web.isVisible.return_value = True
    reviewer.mw = SimpleNamespace(state="review", bottomWeb=Mock())
    reviewer.mw.bottomWeb.review_controls_active.return_value = True
    reviewer._audio_revision = 7
    reviewer._pending_visible_audio = (7, reviewer.card, "question", ["sound"])
    reviewer._auto_advance_to_answer_if_enabled = Mock()
    reviewer._auto_advance_to_question_if_enabled = Mock()
    return reviewer


def test_audio_starts_once_only_after_matching_visible_acknowledgment():
    reviewer = pending_reviewer()
    with patch("aqt.reviewer.av_player") as player:
        reviewer._play_visible_audio("6")
        player.play_tags.assert_not_called()
        reviewer._play_visible_audio("7")
        reviewer._play_visible_audio("7")
        player.play_tags.assert_called_once_with(["sound"])
        reviewer._auto_advance_to_answer_if_enabled.assert_called_once()


@pytest.mark.parametrize("change", ["card", "side", "page", "hidden", "controls"])
def test_late_audio_cannot_play_after_navigation(change):
    reviewer = pending_reviewer()
    if change == "card":
        reviewer.card = object()
    elif change == "side":
        reviewer.state = "answer"
    elif change == "page":
        reviewer.mw.state = "deckBrowser"
    elif change == "hidden":
        reviewer.web.isVisible.return_value = False
    else:
        reviewer.mw.bottomWeb.review_controls_active.return_value = False
    with patch("aqt.reviewer.av_player") as player:
        reviewer._play_visible_audio("7")
        player.play_tags.assert_not_called()


def test_cancel_invalidates_pending_audio_and_stops_old_queue():
    reviewer = pending_reviewer()
    reviewer._clear_auto_advance_timers = Mock()
    with patch("aqt.reviewer.av_player") as player:
        reviewer._cancel_pending_audio()
        reviewer._play_visible_audio("7")
        player.stop_and_clear_queue.assert_called_once()
        player.play_tags.assert_not_called()
    assert reviewer._audio_revision == 8


def test_quick_setting_failure_restores_memory():
    from aqt.builtin_features import synapsepro
    from aqt.builtin_features.synapsepro.quick_switches import save_setting

    with (
        patch.object(
            synapsepro, "addon_settings", {"gamification_popups_enabled": True}
        ),
        patch.object(synapsepro, "save_addon_settings", return_value=False),
    ):
        with pytest.raises(OSError):
            save_setting("gamification_popups_enabled", False)
        assert synapsepro.addon_settings["gamification_popups_enabled"] is True
