# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

from aqt.builtin_features.protected_secrets import read_secrets, write_secrets
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .deck_select import DeckTreeSelect
from .storage import LearningStore

OWN_KEY = "learning_workspace_deepseek"


def secret_path(store: LearningStore) -> Path:
    return store.root.parent / "SynapsePro_Data/ai_secrets.json"


def get_key(store: LearningStore, settings: dict) -> str:
    ai = importlib.import_module("aqt.builtin_features.synapsepro.ai_assistant")
    values = read_secrets(secret_path(store))
    return values.get(
        ai.CK_KEY_DEEPSEEK if settings["use_existing_key"] else OWN_KEY, ""
    )


class SettingsDialog(QDialog):
    def __init__(self, parent: Any, store: LearningStore):
        super().__init__(parent)
        self.store = store
        self.value = store.settings()
        self.setWindowTitle("学习分析设置")
        self.resize(620, 580)
        layout = QVBoxLayout(self)
        description = QLabel(
            "每日分析默认关闭。先选定范围并确认数据，再启用每日建议。\n本版本不会自动调整；所有应用均需确认，首次启用后观察 14 天。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        layout.addLayout(form)
        self.deck = DeckTreeSelect()
        entries = [("请选择一个普通牌组", 0)]
        for deck in parent.mw.col.decks.all_names_and_ids():
            item = parent.mw.col.decks.get(deck.id)
            if not item.get("dyn"):
                entries.append((deck.name, int(deck.id)))
        self.deck.set_decks(entries, self.value["deck_id"])
        form.addRow("每日分析牌组", self.deck)
        self.include_children = QCheckBox("包含子牌组；调整仅作用于所选牌组的新卡限额")
        self.include_children.setChecked(self.value["include_children"])
        form.addRow("范围", self.include_children)
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 480)
        self.minutes.setSpecialValueText("尚未设置")
        self.minutes.setSuffix(" 分钟 / 天")
        self.minutes.setValue(self.value["minutes"])
        form.addRow("每日可用时间", self.minutes)
        self.limit = QSpinBox()
        self.limit.setRange(0, 9999)
        self.limit.setValue(self.value["new_limit"])
        self.limit.setSpecialValueText("仅观察，不允许调整")
        form.addRow("批准的新卡上限", self.limit)
        self.mode = QComboBox()
        self.mode.addItem("确认后应用（推荐）", "confirm")
        self.mode.addItem("只生成建议", "suggest")
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.value["mode"])))
        form.addRow("控制方式", self.mode)
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0.15, 100)
        self.budget.setSuffix(" 元 / 月（估算上限）")
        self.budget.setValue(self.value["monthly_budget"])
        form.addRow("调用预算", self.budget)
        self.reuse = QCheckBox("复用当前账户 SynapsePro 已保存的 DeepSeek Key")
        self.reuse.setChecked(self.value["use_existing_key"])
        form.addRow("凭据", self.reuse)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("不回显已有 Key；留空保持不变")
        self.key.setEnabled(not self.reuse.isChecked())
        self.reuse.toggled.connect(lambda checked: self.key.setEnabled(not checked))
        form.addRow("独立 DeepSeek Key", self.key)
        self.consent = QCheckBox("允许将必要的汇总数据发送到 DeepSeek")
        self.consent.setChecked(self.value["consent"])
        self.primary = QCheckBox("由本机执行每日分析（其他设备应关闭）")
        self.primary.setChecked(self.value["primary_device"])
        self.daily = QCheckBox("学习日结束后分析；未打开软件时下次启动补做")
        self.daily.setChecked(self.value["daily_enabled"])
        for widget in (self.consent, self.primary, self.daily):
            layout.addWidget(widget)
        privacy = QLabel(
            "发送范围：按日次数、评分分布、耗时、保留率、当前积压及相关参数。\n不发送题面、答案、媒体、真实牌组名称或逐条复习记录。\nKey 保存时使用 Windows 当前用户加密，换电脑可能需要重新输入。"
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self) -> None:
        value = self.value | {
            "deck_id": self.deck.currentData(),
            "include_children": self.include_children.isChecked(),
            "minutes": self.minutes.value(),
            "new_limit": self.limit.value(),
            "mode": self.mode.currentData(),
            "monthly_budget": self.budget.value(),
            "daily_enabled": self.daily.isChecked(),
            "consent": self.consent.isChecked(),
            "primary_device": self.primary.isChecked(),
            "use_existing_key": self.reuse.isChecked(),
        }
        try:
            from .policy import validate_settings

            if value["consent"] and not value["enabled_since"]:
                value["enabled_since"] = int(time.time())
            validate_settings(value)
            if value["daily_enabled"] and not value["deck_id"]:
                raise ValueError("请先选定每日分析牌组")
            if not self.reuse.isChecked() and self.key.text().strip():
                path = secret_path(self.store)
                values = read_secrets(path)
                values[OWN_KEY] = self.key.text().strip()
                write_secrets(path, values)
            if value["daily_enabled"] and not get_key(self.store, value):
                raise ValueError("尚未找到 DeepSeek Key；可以先保存关闭每日分析的设置")
            self.store.save_settings(value)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
