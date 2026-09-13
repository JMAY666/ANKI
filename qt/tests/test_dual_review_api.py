# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden

import aqt
from aqt import mediasrv


def test_review_templates_can_read_scoped_states_but_cannot_call_answer_api(
    monkeypatch,
):
    app = Flask(__name__)
    warn = Mock()
    monkeypatch.setattr(
        aqt, "mw", SimpleNamespace(taskman=SimpleNamespace(run_on_main=warn))
    )
    monkeypatch.setattr(mediasrv, "_have_api_access", lambda: False)
    with app.test_request_context(
        "/_anki/getReviewSchedulingStatesWithContext",
        method="POST",
        content_type="application/binary",
    ):
        mediasrv._check_dynamic_request_permissions()
    warn.assert_not_called()
    with app.test_request_context(
        "/_anki/answerReviewCard", method="POST", content_type="application/binary"
    ):
        with pytest.raises(Forbidden):
            mediasrv._check_dynamic_request_permissions()
    warn.assert_called_once()
