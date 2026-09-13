# Source integration: Ankitects Pty Ltd and contributors
# Adapted from AnkiWeb 2060144143 and ARBb 3.6.1; see SOURCE.md.
"""One reusable rating indicator, shown only after a successful native answer."""

from __future__ import annotations

import html
from typing import Any

from aqt.qt import QEvent, QLabel, QObject, QPoint, Qt, QTimer

from .config import get_config, review_is_visible
from .i18n import tr

LANGUAGES = {
    "zh_CN": {1: "重来", 2: "困难", 3: "良好", 4: "简单"},
    "en": {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"},
    "ga": {1: "Arís", 2: "Deacair", 3: "Go Maith", 4: "Éasca"},
}
COLORS = {
    1: "rgba(170,51,51,0.33)",
    2: "rgba(204,119,0,0.33)",
    3: "rgba(0,170,0,0.33)",
    4: "rgba(0,108,255,0.33)",
}


class Feedback(QObject):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner.mw)
        self.owner = owner
        self.label = QLabel(owner.mw)
        self.label.setObjectName("builtinRatingFeedback")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.label.hide)
        self.positions: dict[str, list[float]] = {}
        self.positions_by_web: dict[Any, dict] = {}
        self.target_web = owner.mw.bottomWeb
        self.ease = 1
        owner.mw.installEventFilter(self)

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
            if self.label.isVisible():
                self.position()
        return False

    def capture_buttons(self, card: Any) -> None:
        web = self.owner.mw.reviewer.bottom.web

        def received(value: Any) -> None:
            if isinstance(value, dict):
                self.positions_by_web[web] = value

        web.evalWithCallback(
            "Object.fromEntries([...document.querySelectorAll('button[data-ease]')].map(b=>{let r=b.getBoundingClientRect();return [b.dataset.ease,[r.x,r.y,r.width,r.height]]}))",
            received,
        )

    def hide(self) -> None:
        self.timer.stop()
        self.label.hide()

    def position(self) -> None:
        mw = self.owner.mw
        if not review_is_visible():
            self.hide()
            return
        if get_config("policy")["feedback"] == "badge":
            self.label.resize(
                max(
                    85,
                    self.label.fontMetrics().horizontalAdvance(self.label.text()) + 24,
                ),
                30,
            )
            x, y = mw.width() - self.label.width() - 20, 0
        else:
            conf = get_config("advanced_review")
            offset = conf["Tooltip Offset"]
            if conf["Tooltip Style"] == 1:
                self.label.resize(conf["Tooltip Width"], conf["Tooltip Height"])
                x, y = conf["Tooltip Position"]
                x += mw.width() // 2 - self.label.width() // 2
                y += mw.height() - self.label.height()
            else:
                pos = self.positions.get(
                    str(self.ease), [self.target_web.width() / 2 - 50, 0, 100, 36]
                )
                self.label.resize(max(60, int(pos[2])), max(30, int(pos[3])))
                point = self.target_web.mapTo(mw, QPoint(int(pos[0]), int(pos[1])))
                x, y = point.x(), point.y()
            x += offset[0]
            y += offset[1]
        self.label.resize(
            min(self.label.width(), mw.width()), min(self.label.height(), mw.height())
        )
        self.label.move(
            max(0, min(int(x), mw.width() - self.label.width())),
            max(0, min(int(y), mw.height() - self.label.height())),
        )

    def label_for(self, ease: int) -> str:
        passfail = self.owner.mw.passfail2.value
        if passfail["enabled"]:
            key = "again" if ease == 1 else "good"
            return (
                tr(passfail[f"{key}_button_name"])
                if passfail["toggle_names_textcolors"] == "1"
                else ("失败" if ease == 1 else "通过")
            )
        config = get_config("answer_feedback")
        if get_config("policy")["feedback"] == "advanced":
            return tr(
                get_config("advanced_review")["Button Label_ " + LANGUAGES["en"][ease]]
            )
        language = config["language"]
        return (
            LANGUAGES[language][ease]
            if language in LANGUAGES
            else str(config["custom_labels"].get(str(ease)) or LANGUAGES["en"][ease])
        )

    def show_grade(self, ease: int) -> None:
        self.target_web = self.owner.mw.reviewer.bottom.web
        self.positions = self.positions_by_web.get(self.target_web, {})
        mode = get_config("policy")["feedback"]
        if mode == "off" or not review_is_visible():
            self.hide()
            return
        self.ease = ease
        conf = get_config("answer_feedback")
        advanced = get_config("advanced_review")
        if mode == "advanced" and not advanced["Tooltip"]:
            return
        background = (
            COLORS[ease]
            if mode == "badge"
            else advanced["Color_ " + LANGUAGES["en"][ease] + " on hover"]
        )
        foreground = "white" if mode == "badge" else advanced["Tooltip Text Color"]
        self.label.setStyleSheet(
            f"font-size:15px;padding:5px 12px;border-radius:10px;color:{html.escape(foreground)};background:{background}"
        )
        self.label.setText(self.label_for(ease))
        self.position()
        self.label.show()
        self.label.raise_()
        if mode == "advanced" or not conf["debug_always_show"]:
            self.timer.start(
                advanced["Tooltip Timer"]
                if mode == "advanced"
                else conf["hide_duration_ms"]
            )

    def show_debug(self) -> None:
        if (
            get_config("policy")["feedback"] == "badge"
            and get_config("answer_feedback")["debug_always_show"]
            and review_is_visible()
        ):
            self.show_grade(1)
            self.label.setText("?")
