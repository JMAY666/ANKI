# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Scrollable, localized settings with staged edits and explicit save."""

from typing import Any

from aqt.qt import (
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import PEN_DEFAULTS


class Settings(QDialog):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner.mw)
        self.owner = owner
        tr = owner.tr
        self.setWindowTitle(tr("托盘与手写设置", "Tray and handwriting settings"))
        self.resize(570, 650)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.controls: dict[str, Any] = {}
        for key, zh, en in (
            ("enabled", "关闭时收起到托盘", "Close to tray"),
            (
                "hide_on_startup",
                "启动时收起（需开启托盘）",
                "Hide on startup (requires tray)",
            ),
            ("debug", "记录托盘诊断日志", "Diagnostic logging"),
        ):
            widget = QCheckBox(tr(zh, en))
            widget.setChecked(owner.tray_value[key])
            self.controls[key] = widget
            form.addRow(widget)
        label = QLabel(
            tr(
                "托盘不可用时，关闭按钮仍正常退出。以下手写设置仅作用于当前账户。",
                "Without a system tray, closing exits normally. Handwriting settings below apply to the current profile.",
            )
        )
        label.setWordWrap(True)
        form.addRow(label)
        for key, zh, en in (
            ("ts_state_on", "启用卡片手写", "Enable card handwriting"),
            ("ts_auto_hide", "绘画时隐藏工具栏", "Hide toolbar while drawing"),
            ("ts_auto_hide_pointer", "绘画时隐藏指针", "Hide pointer while drawing"),
            (
                "ts_default_small_canvas",
                "默认使用小画布",
                "Use small canvas by default",
            ),
            (
                "ts_zen_mode",
                "专注模式（持续隐藏工具栏）",
                "Zen mode (keep toolbar hidden)",
            ),
            (
                "ts_follow",
                "画布跟随窗口滚动",
                "Keep canvas in viewport while scrolling",
            ),
            ("ts_compact_toolbar", "紧凑工具栏", "Compact toolbar"),
            ("ts_orient_vertical", "工具栏纵向排列", "Vertical toolbar"),
        ):
            widget = QCheckBox(tr(zh, en))
            widget.setChecked(owner.pen_value[key])
            widget.setEnabled(owner.loaded)
            self.controls[key] = widget
            form.addRow(widget)
        location = QComboBox()
        location.addItems(
            [
                tr("左上", "Top left"),
                tr("右上", "Top right"),
                tr("左下", "Bottom left"),
                tr("右下", "Bottom right"),
            ]
        )
        location.setCurrentIndex(owner.pen_value["ts_location"])
        self.controls["ts_location"] = location
        form.addRow(tr("工具栏位置", "Toolbar position"), location)
        for key, zh, en, low, high in (
            ("ts_line_width", "画笔粗细", "Pen width", 0.1, 100),
            ("ts_x_offset", "水平边距", "Horizontal offset", 0, 1000),
            ("ts_y_offset", "垂直边距", "Vertical offset", 0, 1000),
            ("ts_small_width", "小画布宽度", "Small canvas width", 1, 9999),
            ("ts_small_height", "小画布高度", "Small canvas height", 1, 9999),
        ):
            spin = QDoubleSpinBox() if key == "ts_line_width" else QSpinBox()
            if isinstance(spin, QSpinBox):
                spin.setRange(int(low), int(high))
            else:
                spin.setRange(low, high)
            spin.setValue(owner.pen_value[key])
            self.controls[key] = spin
            form.addRow(tr(zh, en), spin)
        for key, zh, en in (
            ("ts_pen1_color", "画笔一颜色", "Pen 1 color"),
            ("ts_pen2_color", "画笔二颜色", "Pen 2 color"),
            (
                "ts_background_color",
                "画布背景（支持透明）",
                "Canvas background (supports transparency)",
            ),
        ):
            button = QPushButton(owner.pen_value[key])
            self.controls[key] = button
            button.clicked.connect(lambda _checked=False, key=key: self.color(key))
            form.addRow(tr(zh, en), button)
        for key, control in self.controls.items():
            if key.startswith("ts_"):
                control.setEnabled(owner.loaded)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("保存", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("取消", "Cancel")
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        reset = buttons.addButton(
            tr("重置画布布局", "Reset canvas layout"),
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        reset.setEnabled(owner.loaded)
        reset.clicked.connect(self.reset_layout)
        layout.addWidget(buttons)

    def reset_layout(self) -> None:
        for key in (
            "ts_location",
            "ts_x_offset",
            "ts_y_offset",
            "ts_small_width",
            "ts_small_height",
            "ts_background_color",
            "ts_orient_vertical",
        ):
            control = self.controls[key]
            value = PEN_DEFAULTS[key]
            if isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(value)
            elif isinstance(control, QPushButton):
                control.setText(value)
            else:
                control.setValue(value)

    def color(self, key: str) -> None:
        button = self.controls[key]
        value = button.text()
        background = key == "ts_background_color"
        initial = (
            QColor("#" + value[-2:] + value[1:-2]) if background else QColor(value)
        )
        options = (
            QColorDialog.ColorDialogOption.ShowAlphaChannel
            if background
            else QColorDialog.ColorDialogOption(0)
        )
        color = QColorDialog.getColor(
            initial, self, self.owner.tr("选择颜色", "Choose color"), options
        )
        if color.isValid():
            result = color.name()
            if background:
                result += f"{color.alpha():02x}"
            button.setText(result)

    def save(self) -> None:
        pen, tray = dict(self.owner.pen_value), dict(self.owner.tray_value)
        value: Any
        for key, control in self.controls.items():
            if isinstance(control, QCheckBox):
                value = control.isChecked()
            elif isinstance(control, QComboBox):
                value = control.currentIndex()
            elif isinstance(control, QPushButton):
                value = control.text()
            else:
                value = control.value()
            (pen if key.startswith("ts_") else tray)[key] = value
        try:
            self.owner.save(pen, tray)
        except (ValueError, OSError):
            self.error.setText(
                self.owner.tr(
                    "保存失败，请检查配置值及目录写入权限。",
                    "Could not save. Check settings and directory permissions.",
                )
            )
            return
        self.accept()
