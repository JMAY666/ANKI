# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Chinese editors for nested settings, retaining the original JSON schema."""

from __future__ import annotations

import copy
from typing import Any

from aqt.qt import (
    QAbstractItemView,
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    Qt,
    QVBoxLayout,
    QWidget,
)

from .i18n import caption, tr


class StructuredEditor(QWidget):
    def __init__(
        self, key: str, value: dict | list, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.original = value
        self.editors: dict[Any, Any] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.order: QListWidget | None = None
        if key == "categoryOrder":
            self.order = QListWidget()
            self.order.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.order.setDefaultDropAction(Qt.DropAction.MoveAction)
            for item in value:
                row = QListWidgetItem(caption(item))
                row.setData(Qt.ItemDataRole.UserRole, item)
                self.order.addItem(row)
            self.order.setMaximumHeight(210)
            layout.addWidget(self.order)
            return
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for child_key, child_value in items:
            label = caption(str(child_key))
            field: Any
            if key in ("Tooltip Position", "Tooltip Offset"):
                label = ("水平（像素）", "垂直（像素）")[int(child_key)]
            elif key == "custom_labels":
                label = {"1": "重来", "2": "困难", "3": "良好", "4": "简单"}.get(
                    str(child_key), "其他评分"
                )
            elif str(child_key).endswith(" answers"):
                label = str(child_key).split()[0] + " 档评分颜色"
            elif isinstance(value, list):
                label = "颜色 " + str(int(child_key) + 1)
            if isinstance(child_value, (dict, list)):
                field = StructuredEditor(str(child_key), child_value, self)
            elif key == "categories":
                field = QComboBox()
                for text, data in (
                    ("展开", True),
                    ("折叠", False),
                    ("不显示", "removed"),
                ):
                    field.addItem(text, data)
                field.setCurrentIndex(max(0, field.findData(child_value)))
            elif isinstance(child_value, bool):
                field = QCheckBox()
                field.setChecked(child_value)
            elif isinstance(child_value, (float, int)):
                field = (
                    QDoubleSpinBox() if isinstance(child_value, float) else QSpinBox()
                )
                field.setRange(-10000, 100000)
                field.setValue(child_value)
            else:
                field = QLineEdit(str(child_value))
                if isinstance(value, list) and QColor(str(child_value)).isValid():
                    field.setText(QColor(str(child_value)).name())
                    field.setProperty("originalColour", child_value)
                    field.setProperty("initialColourText", field.text())
            field.setAccessibleName(label)
            self.editors[child_key] = field
            label_widget = QLabel(label)
            label_widget.setWordWrap(True)
            if isinstance(value, list) and isinstance(child_value, str):
                color_row = QWidget()
                box = QHBoxLayout(color_row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(field)
                button = QPushButton("选择颜色…")

                def choose(checked: bool = False, edit: Any = field) -> None:
                    color = QColorDialog.getColor(
                        QColor(edit.text()), self, "选择评分颜色"
                    )
                    if color.isValid():
                        edit.setText(color.name())

                button.clicked.connect(choose)
                box.addWidget(button)
                form.addRow(label_widget, color_row)
            else:
                form.addRow(label_widget, field)

    def value(self) -> dict | list:
        if self.order is not None:
            return [
                self.order.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.order.count())
            ]
        result = copy.deepcopy(self.original) if isinstance(self.original, dict) else {}
        for key, editor in self.editors.items():
            value: Any
            if isinstance(editor, StructuredEditor):
                value = editor.value()
            elif isinstance(editor, QComboBox):
                value = editor.currentData()
            elif isinstance(editor, QCheckBox):
                value = editor.isChecked()
            elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                value = editor.value()
            else:
                value = editor.text()
                if editor.property("initialColourText") == value:
                    value = editor.property("originalColour")
            result[key] = value
        return (
            result
            if isinstance(self.original, dict)
            else [result.get(index, item) for index, item in enumerate(self.original)]
        )

    def set_value(self, value: dict | list) -> None:
        self.original = copy.deepcopy(value)
        if self.order is not None:
            self.order.clear()
            for item in value:
                row = QListWidgetItem(caption(item))
                row.setData(Qt.ItemDataRole.UserRole, item)
                self.order.addItem(row)
            return
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, item in items:
            if key not in self.editors:
                continue
            editor = self.editors[key]
            if isinstance(editor, StructuredEditor):
                editor.set_value(item)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(item)))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(item)
            elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                editor.setValue(item)
            elif isinstance(self.original, list) and QColor(str(item)).isValid():
                editor.setText(QColor(str(item)).name())
                editor.setProperty("originalColour", item)
                editor.setProperty("initialColourText", editor.text())
            else:
                editor.setText(tr(str(item)))
