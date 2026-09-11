"""Compact controls backed by their existing setting owners."""

from aqt.qt import (
    QApplication,
    QCheckBox,
    QEvent,
    QLabel,
    QMenu,
    QPoint,
    QPushButton,
    QScrollArea,
    QTimer,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    Qt,
)
from aqt.utils import showWarning


def save_setting(key: str, enabled: bool) -> None:
    from . import addon_settings, save_addon_settings

    missing = object()
    previous = addon_settings.get(key, missing)
    addon_settings[key] = enabled
    if not save_addon_settings():
        if previous is missing:
            addon_settings.pop(key, None)
        else:
            addon_settings[key] = previous
        raise OSError("无法保存快捷开关，请检查配置目录的写入权限。")
    if key == "soundcloud_playlist_loop":
        from . import background_music

        player = background_music._music_window
        if player:
            player._sc_js(f"scSetLoop({str(enabled).lower()});")
            player._send_init()


def playlist_loop() -> bool:
    from . import addon_settings

    return bool(addon_settings.get("soundcloud_playlist_loop", False))


class QuickSwitchMenu(QMenu):
    def __init__(self, owner, anchor=None):
        super().__init__(owner)
        self.owner, self.anchor = owner, anchor
        QApplication.instance().installEventFilter(self)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setTitle("快捷开关")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("快捷开关"))
        self.controls = []
        workspace = owner.learning_workspace
        self.add_switch(
            layout,
            "显示复习工具栏",
            workspace.review_toolbar_visible,
            workspace.set_review_toolbar_visible,
            "立即生效；隐藏后仍可在这里恢复。",
        )
        from . import addon_settings

        self.add_switch(
            layout,
            "学习奖励弹窗",
            lambda: bool(addon_settings.get("gamification_popups_enabled", True)),
            lambda value: save_setting("gamification_popups_enabled", value),
        )
        self.add_switch(
            layout,
            "SoundCloud 歌单循环",
            playlist_loop,
            lambda value: save_setting("soundcloud_playlist_loop", value),
            "最后一首结束后回到第一首；需可播放的歌单与网络。",
        )
        from ..passfail2 import mode_selector

        layout.addWidget(QLabel("复习评分模式"))
        layout.addWidget(mode_selector(owner))
        for label, callback in (
            ("恢复卡片布局", workspace.native.viewport.reset_layout),
            ("结束复习 · 返回牌组", lambda: owner.moveToState("deckBrowser")),
        ):
            button = QPushButton(label)
            button.setEnabled(owner.state == "review")
            button.clicked.connect(
                lambda checked=False, fn=callback: (self.close(), fn())
            )
            layout.addWidget(button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        bounds = owner.rect().size()
        scroll.setFixedSize(
            min(340, max(160, bounds.width() - 24)),
            min(380, max(100, bounds.height() - 32)),
        )
        action = QWidgetAction(self)
        action.setDefaultWidget(scroll)
        self.addAction(action)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.sync)
        self.aboutToShow.connect(self.timer.start)
        self.aboutToHide.connect(self.timer.stop)
        if anchor:
            self.aboutToShow.connect(lambda: anchor.setChecked(True))
            self.aboutToHide.connect(lambda: anchor.setChecked(False))

    def add_switch(self, layout, text, getter, setter, hint=""):
        box = QCheckBox(text)
        box.setToolTip(hint)
        self.controls.append((box, text, getter))

        def changed(value):
            try:
                setter(value)
            except Exception as exc:
                showWarning(str(exc), parent=self.owner)
            self.sync()

        box.toggled.connect(changed)
        layout.addWidget(box)
        if hint:
            label = QLabel(hint)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.sync()

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() == QEvent.Type.MouseButtonPress:
            point = event.globalPosition().toPoint()
            inside_child = isinstance(watched, QWidget) and self.isAncestorOf(watched)
            if not self.frameGeometry().contains(point) and not inside_child:
                self.close()
                if self.anchor and self.anchor.rect().contains(
                    self.anchor.mapFromGlobal(point)
                ):
                    return True
        if watched is self.owner and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.WindowStateChange,
        ):
            self.close()
        return super().eventFilter(watched, event)

    def sync(self):
        for box, text, getter in self.controls:
            value = getter()
            box.blockSignals(True)
            box.setChecked(value)
            box.setText(f"{text} · {'开启' if value else '关闭'}")
            box.blockSignals(False)

    def open_near_anchor(self):
        self.sync()
        anchor = self.anchor or self.owner
        point = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        bounds = self.owner.rect()
        self.adjustSize()
        top_left = self.owner.mapToGlobal(bounds.topLeft())
        point.setX(
            max(
                top_left.x(),
                min(point.x(), top_left.x() + bounds.width() - self.sizeHint().width()),
            )
        )
        point.setY(
            max(
                top_left.y(),
                min(
                    point.y(), top_left.y() + bounds.height() - self.sizeHint().height()
                ),
            )
        )
        self.popup(point)


def open_quick_switches(owner, anchor=None):
    previous = getattr(owner, "_quick_switch_menu", None)
    if previous and previous.isVisible():
        previous.close()
        return
    if previous:
        previous.deleteLater()
    menu = QuickSwitchMenu(owner, anchor)
    owner._quick_switch_menu = menu
    menu.open_near_anchor()
