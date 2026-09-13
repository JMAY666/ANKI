# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from aqt.reviewer import Reviewer
from aqt.toolbar import BottomWebView, TopWebView
from aqt.webview import AnkiWebView


def make_top_web_view(state: str) -> TopWebView:
    web = cast(TopWebView, MagicMock(spec=TopWebView))
    web.mw = MagicMock()
    web.mw.state = state
    return web


@patch.object(AnkiWebView, "on_theme_did_change")
def test_theme_change_refreshes_review_background(
    super_on_theme_did_change: MagicMock,
) -> None:
    web = make_top_web_view("review")

    TopWebView.on_theme_did_change(web)

    super_on_theme_did_change.assert_called_once_with()
    web.eval.assert_called_once()
    script = web.eval.call_args.args[0]
    assert 'document.body.style.removeProperty("background")' in script
    delay, callback = web.mw.progress.single_shot.call_args.args
    assert delay == 0
    callback()
    web.update_background_image.assert_called_once_with()


@patch.object(AnkiWebView, "on_theme_did_change")
def test_theme_change_does_not_copy_background_outside_review(
    super_on_theme_did_change: MagicMock,
) -> None:
    web = make_top_web_view("deckBrowser")

    TopWebView.on_theme_did_change(web)

    super_on_theme_did_change.assert_called_once_with()
    web.eval.assert_not_called()
    web.mw.progress.single_shot.assert_not_called()


def test_bottom_measurement_does_not_reopen_an_auto_hidden_review_bar() -> None:
    web = cast(BottomWebView, MagicMock(spec=BottomWebView))
    web.mw = MagicMock(state="review")
    web.hidden = True
    BottomWebView._onHeight(web, 74)
    assert web.web_height == 74
    web.setFixedHeight.assert_not_called()


def test_bottom_measurement_replaces_a_stale_expansion_height() -> None:
    web = cast(BottomWebView, MagicMock(spec=BottomWebView))
    web.mw = MagicMock(state="review")
    web.hidden = False
    web.animation = MagicMock()
    BottomWebView._onHeight(web, 74)
    web.animation.stop.assert_called_once()
    web.setFixedHeight.assert_called_once_with(74)


def test_bottom_measurement_does_not_restore_a_hidden_home_footer() -> None:
    web = cast(BottomWebView, MagicMock(spec=BottomWebView))
    web.mw = MagicMock(state="deckBrowser")
    web.hidden = True
    BottomWebView._onHeight(web, 74)
    web.setFixedHeight.assert_not_called()


def test_bottom_measurement_from_a_previous_page_is_discarded() -> None:
    web = cast(BottomWebView, MagicMock(spec=BottomWebView))
    web.hidden = False
    web._page_epoch = 1
    BottomWebView.adjustHeightToFit(web)
    measured = web.evalWithCallback.call_args.args[1]
    web._page_epoch = 2
    measured(74)
    web._onHeight.assert_not_called()


def test_bottom_animation_from_a_previous_page_cannot_restore_height() -> None:
    web = cast(BottomWebView, MagicMock(spec=BottomWebView))
    web._page_epoch = 2
    BottomWebView._finish_height(web, 74, 1)
    web.setFixedHeight.assert_not_called()


@pytest.mark.parametrize(
    ("owner", "state", "review_visible", "expected"),
    [
        (None, "deckBrowser", True, False),
        ("review", "deckBrowser", True, False),
        ("review", "review", False, False),
        ("review", "review", True, True),
        ("overview", "overview", False, True),
        ("review", "profileManager", True, False),
    ],
)
def test_bottom_content_belongs_to_the_active_page(
    owner, state, review_visible, expected
) -> None:
    web = SimpleNamespace(
        _content_state=owner,
        mw=SimpleNamespace(state=state),
        _review_page_visible=review_visible,
    )
    assert BottomWebView._can_display(web) == expected


@pytest.mark.parametrize("command", ["ans", "ease1", "edit", "more", "play:q:0"])
def test_review_actions_are_ignored_outside_the_active_reviewer(command: str) -> None:
    reviewer = cast(Reviewer, MagicMock(spec=Reviewer))
    reviewer.mw = MagicMock()
    reviewer.mw.dual_review = None
    reviewer.review_panel.return_value = None
    reviewer.controls_active.return_value = False
    reviewer.mw.bottomWeb.review_controls_active.return_value = False
    Reviewer._linkHandler(reviewer, command)
    reviewer._getTypedAnswer.assert_not_called()
    reviewer._answerCard.assert_not_called()
    reviewer.mw.onEditCurrent.assert_not_called()
    reviewer.showContextMenu.assert_not_called()


def test_background_review_state_callback_still_completes_while_statistics_are_open() -> (
    None
):
    reviewer = cast(Reviewer, MagicMock(spec=Reviewer))
    reviewer.mw = MagicMock()
    reviewer.mw.dual_review = None
    reviewer.review_panel.return_value = None
    reviewer.mw.bottomWeb.review_controls_active.return_value = False
    reviewer._states_mutated = False
    Reviewer._linkHandler(reviewer, "statesMutated")
    assert reviewer._states_mutated
