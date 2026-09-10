"""Anki's preview renderer, hosted as a widget without reviewer actions."""

from __future__ import annotations

from anki.errors import NotFoundError
from aqt import gui_hooks
from aqt.browser.previewer import Previewer
from aqt.qt import QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout
from aqt.sound import av_player
from aqt.webview import AnkiWebView, AnkiWebViewKind


class EmbeddedPreview(Previewer):
    def __init__(self, browser, parent):
        super().__init__(browser, browser.mw, lambda: None)
        self.browser = browser
        self.setParent(parent, Qt.WindowType.Widget)
        self.setObjectName("synapseCardPreview")
        self._state = "question"
        self._last_card_id = None
        self._show_both_sides = False
        self._card = None
        self._playing = False
        self._create_gui()
        self._setup_web_view()
        self._audio_hooks = [
            (gui_hooks.av_player_will_play_tags, self._audio_context),
            (gui_hooks.audio_will_replay, self._audio_replay_context),
            (gui_hooks.webview_did_receive_js_message, self._audio_bridge_context),
        ]
        for hook, callback in self._audio_hooks:
            hook.append(callback)

    def _create_gui(self):
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("请选择一张卡片")
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setWordWrap(True)
        self.vbox.addWidget(self.caption)
        self._web = AnkiWebView(kind=AnkiWebViewKind.PREVIEWER)
        self._web.setMinimumWidth(0)
        self.vbox.addWidget(self._web, 1)
        gui_hooks.card_review_webview_did_init(self._web, AnkiWebViewKind.PREVIEWER)
        controls = QHBoxLayout()
        self.flip_button = QPushButton("显示答案")
        self.flip_button.setAutoDefault(False)
        self.flip_button.setObjectName("synapseFlipCard")
        self.flip_button.clicked.connect(self.flip)
        self.replay_button = QPushButton("重播音频")
        self.replay_button.setAutoDefault(False)
        self.replay_button.clicked.connect(self.replay)
        controls.addWidget(self.flip_button)
        controls.addWidget(self.replay_button)
        controls.addStretch()
        self.vbox.addLayout(controls)

    def card(self):
        return self._card

    def card_changed(self):
        card_id = self._card.id if self._card else None
        changed = card_id != self._last_card_id
        self._last_card_id = card_id
        return changed

    def set_card(self, card, message="请选择一张卡片"):
        if (card.id if card else None) != (self._card.id if self._card else None):
            self.stop_audio()
            self._state = "question"
            self._last_state = None
        self._card = card
        if card:
            try:
                name = card.template()["name"]
                self.caption.setText(f"{name} · 卡片 {card.ord + 1}")
            except Exception:
                self.caption.setText(f"卡片 {card.ord + 1}")
        else:
            self.caption.setText(message)
            self.cancel_timer()
            self._web.eval("_showQuestion('', '', '');")
        self.flip_button.setEnabled(card is not None)
        self.replay_button.setEnabled(card is not None)
        self.flip_button.setText("显示正面" if self._state == "answer" else "显示答案")
        self.render_card()

    def render_card(self):
        if self._open and self.isVisible():
            super().render_card()

    def _render_scheduled(self):
        if not self._open or not self.isVisible():
            self.cancel_timer()
            return
        try:
            super()._render_scheduled()
        except NotFoundError:
            # A card or its note can disappear between selection and the timer.
            self._card = None
            self._last_state = None
            self.caption.setText("卡片已不存在，请重新选择")
            self.flip_button.setEnabled(False)
            self.replay_button.setEnabled(False)
            self._web.eval("_showQuestion('', '', '');")

    def flip(self):
        if not self._card:
            return
        self._state = "answer" if self._state == "question" else "question"
        self.flip_button.setText("显示正面" if self._state == "answer" else "显示答案")
        self.render_card()

    def replay(self):
        if self._card and self.isVisible():
            self._on_replay_audio()

    def _audio_context(self, tags, _side, context):
        self._playing = context is self and bool(tags)

    def _audio_replay_context(self, web, _card, _question):
        self._playing = web is self._web

    def _audio_bridge_context(self, handled, command, context):
        if command.startswith("play:"):
            self._playing = context is self
        return handled

    def stop_audio(self):
        self.cancel_timer()
        if self._playing:
            av_player.stop_and_clear_queue()
            self._playing = False

    def dispose(self):
        if self._open:
            self.stop_audio()
            for hook, callback in self._audio_hooks:
                hook.remove(callback)
            self._on_close()
            self._card = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # QDialog's default reject() would hide only the embedded pane.
            self.browser.close()
            event.accept()
        else:
            super().keyPressEvent(event)
