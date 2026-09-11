# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Native, persistent settings for the six integrated tools."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from aqt.qt import (
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import defaults, merge, validate
from .i18n import caption, tr
from .structured_settings import StructuredEditor

CHOICES: dict[str, list[tuple[str, Any]]] = {
    "language": [
        ("简体中文", "zh_CN"),
        ("自定义", "custom"),
        ("英语", "en"),
        ("爱尔兰语", "ga"),
    ],
    "forceLang": [
        ("跟随软件", None),
        ("简体中文", "zh_CN"),
        ("英语", "en_GB"),
        ("葡萄牙语", "pt_BR"),
    ],
    "graphMode": [("饼图", "Pie"), ("柱状图", "Bar")],
    "style": [
        ("当前外观", "current"),
        ("评分配色", "colours"),
        ("高级复习栏", "advanced"),
    ],
    "feedback": [
        ("关闭", "off"),
        ("顶部评分标签", "badge"),
        ("浮动评分提示", "advanced"),
    ],
    " Review_ Buttons Style": [
        (name, i)
        for i, name in enumerate(
            (
                "Text",
                "Background",
                "Wide text",
                "Wide background",
                "Neon 1",
                "Neon 2",
                "Fill 1",
                "Fill 2",
            )
        )
    ],
    " Review_ Bottombar Buttons Style": [
        (name, i)
        for i, name in enumerate(("Default", "Neon 1", "Neon 2", "Fill 1", "Fill 2"))
    ],
    " Review_ Hover Effect": [("关闭", 0), ("提亮", 1), ("发光", 2), ("提亮及发光", 3)],
    " Review_ Active Button Indicator": [("关闭", 0), ("边框", 1), ("发光", 2)],
    " Review_ Cursor Style": [("默认", 0), ("手形", 1)],
    "ShowAnswer_ Border Color Style": [("固定颜色", 0), ("按卡片易度", 1)],
    "Card Info sidebar_ Hide Current Card": [("显示当前卡片", 0), ("隐藏当前卡片", 1)],
    " Review_ Interval Style": [("Default", 0), ("Coloured", 1), ("Inside button", 2)],
    "  More Overview Stats": [("关闭", 0), ("每日数量", 1), ("成熟度及完成预测", 2)],
    "  Skip Method": [
        ("搁置至退出复习（当前调度器）", 0),
        ("搁置至退出复习", 1),
        ("暂停至手动恢复", 2),
    ],
    "Tooltip Style": [("在评分按钮上", 0), ("固定位置", 1)],
    "Card Info sidebar_ theme": [("跟随软件", 0), ("浅色", 1), ("深色", 2)],
}
CAPTIONS = {
    "style": "评分外观",
    "feedback": "评分反馈",
    "pace_enabled": "显示复习速度图",
    "search_stats_enabled": "显示扩展统计图表",
}
# These old add-on interoperability/layout settings are preserved on disk.
# The explicitly approved core integration owns their former responsibilities.
MANAGED = {
    "  Settings Menu Place",
    "  Direct Config Edit",
    "Button Label_ Study Now",
    "  Style Main Screen Buttons",
    "  Speed Focus Add-on",
    "  Rebuild Empty All Add-on",
}


class ToolSettings(QDialog):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner.mw)
        self.owner = owner
        self.draft = copy.deepcopy(owner.config.values)
        self.fields: dict[tuple[str, str], Any] = {}
        self.setWindowTitle("内置复习与统计扩展 · 设置")
        self.resize(740, 650)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "评分仍由现有原生四档／通过与失败两档模式决定；两档自定义名称和文字颜色优先。保存只更新本机工具配置，不修改卡片与学习记录。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        sections: dict[str, QFormLayout] = {}

        def section(title: str) -> QFormLayout:
            if title not in sections:
                page = QWidget()
                form = QFormLayout(page)
                form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                form.setFieldGrowthPolicy(
                    QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
                )
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(page)
                self.tabs.addTab(scroll, title)
                sections[title] = form
            return sections[title]

        for feature, title in (
            ("policy", "运行方式"),
            ("button_colours", "评分配色"),
            ("answer_feedback", "顶部标签"),
            ("confident_wrong", "快速作答分析"),
            ("advanced_review", "高级复习栏"),
            ("search_stats", "搜索统计"),
        ):
            form = section(title)
            if feature == "advanced_review":
                note = QLabel(
                    "主页布局与入口保持现状；牌组附加统计可从统计概览查看。旧插件菜单位置及其他独立插件的兼容开关由主程序接管。隐藏按钮只控制显示，不改变原生数字评分键。"
                )
                note.setWordWrap(True)
                form.addRow(note)
            for key, original in defaults(feature).items():
                if key in MANAGED:
                    continue
                value = self.draft[feature][key]
                label = CAPTIONS.get(key, caption(key))
                field: Any
                if key in CHOICES or key.startswith("Button_ Position_"):
                    choices = CHOICES.get(
                        key,
                        [
                            (text, text)
                            for text in ("left", "middle left", "middle right", "right")
                        ],
                    )
                    field = QComboBox()
                    for text, data in choices:
                        field.addItem(tr(text), data)
                    field.setCurrentIndex(max(0, field.findData(value)))
                elif isinstance(original, bool):
                    field = QCheckBox()
                    field.setChecked(value)
                elif isinstance(original, (int, float)):
                    field = (
                        QDoubleSpinBox() if isinstance(original, float) else QSpinBox()
                    )
                    field.setRange(0, 100000)
                    if isinstance(field, QDoubleSpinBox):
                        field.setDecimals(3)
                    field.setValue(value)
                elif isinstance(original, (dict, list)):
                    field = StructuredEditor(key, value, self)
                elif original is None:
                    field = QPlainTextEdit(
                        json.dumps(value, ensure_ascii=False, indent=2)
                    )
                    field.setMinimumHeight(80)
                    field.setMaximumHeight(155)
                else:
                    field = QLineEdit(tr(str(value)))
                field.setAccessibleName(label)
                self.fields[(feature, key)] = field
                if isinstance(original, str) and original.startswith("#"):
                    row = QWidget()
                    box = QHBoxLayout(row)
                    box.setContentsMargins(0, 0, 0, 0)
                    box.addWidget(field)
                    picker = QPushButton("选色…")

                    def pick(checked: bool = False, edit: Any = field) -> None:
                        color = QColorDialog.getColor(QColor(edit.text()), self)
                        if color.isValid():
                            edit.setText(color.name())

                    picker.clicked.connect(pick)
                    box.addWidget(picker)
                    label_widget = QLabel(label)
                    label_widget.setWordWrap(True)
                    form.addRow(label_widget, row)
                else:
                    label_widget = QLabel(label)
                    label_widget.setWordWrap(True)
                    form.addRow(label_widget, field)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        tools = QHBoxLayout()
        export = QPushButton("导出设置…")
        export.clicked.connect(self.export_settings)
        tools.addWidget(export)
        imported = QPushButton("导入设置…")
        imported.clicked.connect(self.import_settings)
        tools.addWidget(imported)
        reset = QPushButton("恢复当前页默认值")
        reset.clicked.connect(self.reset_page)
        tools.addWidget(reset)
        layout.addLayout(tools)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def collect(self) -> dict:
        values = copy.deepcopy(self.draft)
        for (feature, key), field in self.fields.items():
            value: Any
            if isinstance(field, StructuredEditor):
                value = field.value()
            elif isinstance(field, QComboBox):
                value = field.currentData()
            elif isinstance(field, QCheckBox):
                value = field.isChecked()
            elif isinstance(field, (QSpinBox, QDoubleSpinBox)):
                value = field.value()
            elif isinstance(field, QPlainTextEdit):
                value = json.loads(field.toPlainText())
            else:
                value = field.text()
            values[feature][key] = value
        for feature, value in values.items():
            validate(feature, value)
        self.validate_shortcuts(values)
        return values

    def validate_shortcuts(self, values: dict) -> None:
        from aqt.qt import QAction, QKeySequence

        from .config import get_config

        # Build the reserved set with the original reviewer shortcuts, even
        # when the currently selected appearance is already Advanced.
        saved = get_config("policy")["style"]
        try:
            get_config("policy")["style"] = "current"
            reserved = {
                QKeySequence(key).toString().lower()
                for key, _ in self.owner.mw.reviewer._shortcutKeys()
            }
        finally:
            get_config("policy")["style"] = saved
        reserved.update(
            sequence.toString().lower()
            for action in self.owner.mw.findChildren(QAction)
            for sequence in action.shortcuts()
            if not sequence.isEmpty()
        )
        conf = values["advanced_review"]
        for label in ("Info", "Skip", "Show Skipped", "Undo"):
            if not conf[f"Button_   {label} Button"]:
                continue
            raw = conf[f"Button_ Shortcut_ {label} Button"]
            sequence = QKeySequence(re.sub(r"\s*\+\s*", "+", raw)).toString().lower()
            if raw and (not sequence or sequence in reserved):
                raise ValueError(
                    f"{tr(label)} 快捷键 {raw!r} 与现有操作冲突，请修改或清空。"
                )
            reserved.add(sequence)

    def save(self) -> None:
        try:
            values = self.collect()
            # Validate every tab before performing any writes.
            for feature, value in values.items():
                if value != self.owner.config.values[feature]:
                    self.owner.config.save(feature, value)
            self.owner.changed()
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def export_settings(self) -> None:
        try:
            values = self.collect()
            path, _ = QFileDialog.getSaveFileName(
                self, "导出工具设置", "review-tools.json", "JSON (*.json)"
            )
            if path:
                from ..storage import write_object

                write_object(Path(path), values)
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入工具设置或原高级复习栏预设",
            str(Path(__file__).parent / "advanced/presets"),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            from ..storage import read_object

            incoming = read_object(Path(path))
            if "  Button Colors" in incoming:
                incoming = {"advanced_review": incoming}
            draft = merge(self.draft, incoming)
            for feature in self.draft:
                validate(feature, draft[feature])
            self.draft = draft
            self.fill()
            self.error.setText("已载入预览；点击保存后才生效。")
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))

    def fill(self) -> None:
        for (feature, key), field in self.fields.items():
            value = self.draft[feature][key]
            if isinstance(field, StructuredEditor):
                field.set_value(value)
            elif isinstance(field, QComboBox):
                field.setCurrentIndex(max(0, field.findData(value)))
            elif isinstance(field, QCheckBox):
                field.setChecked(value)
            elif isinstance(field, (QSpinBox, QDoubleSpinBox)):
                field.setValue(value)
            elif isinstance(field, QPlainTextEdit):
                field.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            else:
                field.setText(tr(value))

    def reset_page(self) -> None:
        features = (
            "policy",
            "button_colours",
            "answer_feedback",
            "confident_wrong",
            "advanced_review",
            "search_stats",
        )
        feature = features[self.tabs.currentIndex()]
        # Keep edits on all other tabs and preserve unknown settings.
        try:
            self.draft = self.collect()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.draft[feature] = merge(self.draft[feature], defaults(feature))
        self.fill()
