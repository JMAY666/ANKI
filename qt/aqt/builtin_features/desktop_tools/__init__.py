# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Native lifecycle for tray and AnkiPenDown; no add-on manager loading."""

from typing import Any

from anki import lang
from aqt import gui_hooks
from aqt.qt import QAction, QKeySequence, QShortcut
from aqt.utils import showWarning

from ..storage import write_object
from .canvas import mount_script
from .config import PEN_DEFAULTS, pen_settings, tray_settings, validate_pen


class DesktopTools:
    def __init__(self, mw: Any, storage: Any) -> None:
        self.mw = mw
        self.storage = storage
        self.tray_value = tray_settings(storage)
        self.pen_value = dict(PEN_DEFAULTS)
        self.tray: Any = None
        self.loaded = False
        self.menu = mw.form.menuTools.addMenu(
            self.tr("托盘与手写", "Tray and handwriting")
        )
        self.toggle = QAction(self.tr("启用卡片手写", "Enable card handwriting"), mw)
        self.toggle.setCheckable(True)
        self.toggle.setEnabled(False)
        self.toggle.triggered.connect(self.set_enabled)
        self.shortcut = QShortcut(QKeySequence("Ctrl+R"), mw)
        self.shortcut.setEnabled(False)
        self.shortcut.activated.connect(
            lambda: mw.reviewer.shortcuts.run(
                lambda: self.set_enabled(not self.pen_value["ts_state_on"])
            )
        )
        self.menu.addAction(self.toggle)
        self.menu.addAction(self.tr("设置…", "Settings…"), self.settings)
        self.menu.addAction(self.tr("使用说明", "Help"), self.help)
        gui_hooks.main_window_did_init.append(self.start_tray)
        gui_hooks.profile_did_open.append(self.open_profile)
        gui_hooks.profile_will_close.append(self.close_profile)
        gui_hooks.reviewer_did_show_question.append(self.question)
        gui_hooks.reviewer_did_show_answer.append(self.answer)
        gui_hooks.state_will_change.append(self.state_change)

    @staticmethod
    def tr(chinese: str, english: str) -> str:
        return chinese if lang.current_lang.startswith("zh") else english

    def start_tray(self) -> None:
        from .tray import Tray

        if self.tray is None:
            self.tray = Tray(self)
        if self.tray_value["hide_on_startup"]:
            self.tray.hide()

    def open_profile(self) -> None:
        try:
            self.pen_value = pen_settings(self.mw.pm.profile)
        except (ValueError, TypeError, KeyError):
            # Invalid legacy settings remain intact until explicitly repaired.
            self.loaded = False
            showWarning(
                self.tr(
                    "原手写配置无效，已保留原件。本次未启用手写功能。",
                    "Invalid handwriting settings were preserved. Handwriting was not enabled.",
                )
            )
            return
        self.loaded = True
        self.toggle.setEnabled(True)
        self.toggle.setChecked(self.pen_value["ts_state_on"])

    def close_profile(self) -> None:
        self.dispose()
        self.loaded = False
        self.toggle.setEnabled(False)
        self.toggle.setChecked(False)

    def save(self, pen: dict[str, Any], tray: dict[str, Any]) -> None:
        validate_pen(pen)
        write_object(self.storage.root / "minimize_to_tray.json", tray)
        if self.loaded:
            self.mw.pm.profile.update(pen)
            self.mw.pm.save()
            self.pen_value = pen
        self.tray_value = tray
        self.toggle.setChecked(bool(self.loaded and self.pen_value["ts_state_on"]))
        if self.tray:
            self.tray.apply()
        self.refresh()

    def set_enabled(self, enabled: bool) -> None:
        if self.loaded:
            self.save({**self.pen_value, "ts_state_on": enabled}, dict(self.tray_value))

    def refresh(self, preserve: bool = True) -> None:
        if self.mw.state != "review":
            return
        if self.loaded and self.pen_value["ts_state_on"]:
            self.mw.reviewer.web.eval(mount_script(self.pen_value, preserve))
        else:
            self.dispose()

    def dispose(self) -> None:
        self.mw.reviewer.web.eval("window.ankiPenDown?.dispose();")

    def question(self, _card: Any) -> None:
        self.refresh(False)

    def answer(self, _card: Any) -> None:
        if self.loaded and self.pen_value["ts_state_on"]:
            self.mw.reviewer.web.eval("window.ankiPenDown?.resize();")

    def state_change(self, new: str, _old: str) -> None:
        self.shortcut.setEnabled(new == "review" and self.loaded)
        if new != "review":
            self.dispose()

    def settings(self) -> None:
        from .settings import Settings

        dialog = Settings(self)
        dialog.exec()

    def help(self) -> None:
        from aqt.utils import showText

        showText(
            self.tr(
                "托盘：默认点击关闭按钮正常退出。开启“关闭时收起到托盘”后，可点击托盘图标恢复窗口；使用“文件 → 退出”真正退出。系统托盘不可用时正常退出。\n\n"
                "手写：在复习卡片上使用双画笔、荧光笔和笔画橡皮。橡皮删除相交的整条笔画。Alt+Z 撤销，Alt+Y 重做，句点清空，逗号隐藏／显示笔迹，Alt+B 切换大／小画布。输入文字时不处理这些按键。\n\n"
                "隐藏笔迹后可操作卡片中的链接或输入框。工具栏隐藏时可从本菜单关闭专注模式。笔迹只用于当前卡片，翻面保留、下一张清空；不会写入卡片、模板或媒体，也不会在重启后保存。设置按账户保存，托盘设置适用于本机所有账户。",
                "Tray: closing normally exits by default. Enable close-to-tray to hide windows; click the tray icon to restore them. File → Exit always exits. Without a system tray, closing exits normally.\n\n"
                "Handwriting provides two pens, a highlighter, stroke erasing and undo/redo. Alt+Z: undo; Alt+Y: redo; period: clear; comma: visibility; Alt+B: canvas size. Text inputs do not use these shortcuts. Hide ink to interact with card controls. Disable Zen mode in settings to recover the toolbar.\n\n"
                "Ink lasts for this card only, survives flipping, and clears on the next card. Ink is not written to cards, templates or media, and is not saved across restarts. Handwriting settings are per profile; tray settings apply to all local profiles.",
            ),
            parent=self.mw,
        )


def install(mw: Any, storage: Any) -> None:
    if not hasattr(mw, "desktop_tools"):
        mw.desktop_tools = DesktopTools(mw, storage)
