# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Learning workspace. Importing this package never starts a task or API request."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aqt.main import AnkiQt


def install(mw: AnkiQt) -> None:
    from .workspace import LearningWorkspace

    if getattr(mw, "learning_workspace", None) is None:
        setattr(mw, "learning_workspace", LearningWorkspace(mw))
