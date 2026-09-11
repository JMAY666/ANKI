# Copyright: Simone Gaiarin <simgunz@gmail.com>
# License: GNU GPL, version 3 or later; http://www.gnu.org/copyleft/gpl.html
"""Minimize to Tray 2 (0.2), adapted to the native window lifecycle."""

from typing import Any

from aqt.qt import QApplication, QIcon, QMenu, QSystemTrayIcon, Qt, sip


class Tray:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.mw = owner.mw
        self.hidden: list[tuple[Any, Any]] = []
        self.focus: Any = None
        self.bypass = False
        self.icon = QSystemTrayIcon(self.mw.windowIcon(), self.mw)
        if self.icon.icon().isNull():
            self.icon.setIcon(QIcon("icons:anki.png"))
        self.icon.setToolTip("Anki")
        menu = QMenu(self.mw)
        menu.addAction(owner.tr("显示所有窗口", "Show all windows"), self.restore)
        menu.addAction(owner.tr("设置…", "Settings…"), owner.settings)
        menu.addSeparator()
        menu.addAction(self.mw.form.actionExit)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self.activate)
        self.apply()

    def apply(self) -> None:
        if not self.owner.tray_value["enabled"]:
            self.restore()
        self.icon.setVisible(bool(self.owner.tray_value["enabled"]))

    def available(self) -> bool:
        return bool(
            self.owner.tray_value["enabled"]
            and QSystemTrayIcon.isSystemTrayAvailable()
            and self.icon.isVisible()
        )

    def intercept_close(self) -> bool:
        if self.bypass or not self.available():
            return False
        self.hide()
        return True

    def hide(self) -> None:
        if self.hidden or not self.available():
            return
        if self.owner.tray_value["debug"]:
            print("[MinimizeToTray] Hiding visible windows")
        self.focus = QApplication.focusWidget()
        self.hidden = [
            (window, window.windowState())
            for window in QApplication.topLevelWidgets()
            if window.isVisible()
            and not isinstance(window, QMenu)
            and (window is self.mw or window.parent() is not None)
        ]
        for window, _state in self.hidden:
            window.hide()

    def restore(self) -> None:
        windows, self.hidden = self.hidden, []
        if windows and self.owner.tray_value["debug"]:
            print("[MinimizeToTray] Restoring window snapshot")
        # Main window first; then only children that were visible before hiding.
        windows.sort(key=lambda pair: pair[0] is not self.mw)
        for window, state in windows:
            if sip.isdeleted(window):
                continue
            window.setWindowState(state & ~Qt.WindowState.WindowMinimized)
            window.show()
        if windows:
            target = (
                self.focus if self.focus and not sip.isdeleted(self.focus) else self.mw
            )
            target.window().raise_()
            target.window().activateWindow()
            target.setFocus()

    def activate(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.hidden:
                self.restore()
            else:
                self.mw.setWindowState(
                    self.mw.windowState() & ~Qt.WindowState.WindowMinimized
                )
                self.mw.show()
                self.mw.raise_()
                self.mw.activateWindow()
