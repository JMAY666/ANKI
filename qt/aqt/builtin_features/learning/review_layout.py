# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Resize the existing card viewport without touching its document or review state."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from aqt.qt import (
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPoint,
    QResizeEvent,
    Qt,
    QVBoxLayout,
    QWidget,
)

LAYOUT_KEY = "reviewViewportLayout"
HANDLE = 8
MIN_CARD_WIDTH = 400
MIN_CARD_HEIGHT = 180


def layout_ratios(value: Any) -> tuple[float, float]:
    if not isinstance(value, dict):
        return (1.0, 1.0)

    def ratio(key: str) -> float:
        number = value.get(key)
        if (
            isinstance(number, (float, int))
            and not isinstance(number, bool)
            and math.isfinite(number)
            and 0 < number <= 1
        ):
            return float(number)
        return 1.0

    return (ratio("width"), ratio("height"))


class ResizeHandle(QWidget):
    def __init__(self, panel: CardViewport, edge: str) -> None:
        super().__init__(panel)
        self.panel = panel
        self.edge = edge
        self.start: QPoint | None = None
        self.start_size = (0, 0)
        horizontal = edge != "bottom"
        label = "卡片宽度" if horizontal else "卡片高度"
        self.setAccessibleName("调整" + label)
        self.setToolTip(f"拖动调整{label}；方向键微调；双击恢复默认布局")
        self.setCursor(
            Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorRole.Text)
        color.setAlpha(150 if self.hasFocus() or self.start else 90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        if self.edge == "bottom":
            painter.drawRoundedRect(self.width() // 2 - 24, 2, 48, 3, 1, 1)
        else:
            painter.drawRoundedRect(2, self.height() // 2 - 24, 3, 48, 1, 1)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.start = event.globalPosition().toPoint()
            self.start_size = (self.panel.web.width(), self.panel.web.height())
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event and self.start is not None:
            delta = event.globalPosition().toPoint() - self.start
            width, height = self.start_size
            if self.edge == "bottom":
                height += delta.y()
            else:
                width += delta.x() * (2 if self.edge == "right" else -2)
            self.panel.resize_card(width, height)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if (
            event
            and event.button() == Qt.MouseButton.LeftButton
            and self.start is not None
        ):
            self.start = None
            self.panel.save()
            self.panel.web.setFocus(Qt.FocusReason.MouseFocusReason)
            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.start = None
            self.panel.reset_layout()
            event.accept()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        keys = (
            (Qt.Key.Key_Up, Qt.Key.Key_Down)
            if self.edge == "bottom"
            else (Qt.Key.Key_Left, Qt.Key.Key_Right)
        )
        if event.key() in keys:
            delta = -16 if event.key() == keys[0] else 16
            width, height = self.panel.web.width(), self.panel.web.height()
            if self.edge == "bottom":
                height += delta
            else:
                width += delta * (-1 if self.edge == "left" else 1)
            self.panel.resize_card(width, height)
            self.panel.save()
            event.accept()
        elif event.key() == Qt.Key.Key_Home:
            self.panel.reset_layout()
            event.accept()
        else:
            super().keyPressEvent(event)


class CardViewport(QWidget):
    def __init__(self, web: QWidget, save: Callable[[dict[str, float]], None]) -> None:
        super().__init__()
        self.web = web
        web.setParent(self)
        self.save_settings = save
        self.ratios = (1.0, 1.0)
        self.minimum_card_width = MIN_CARD_WIDTH
        self.reviewing = False
        self.handles = {
            edge: ResizeHandle(self, edge) for edge in ("left", "right", "bottom")
        }
        self.set_reviewing(False)

    def set_reviewing(self, reviewing: bool) -> None:
        self.reviewing = reviewing
        self.setMinimumSize(
            max(self.minimum_card_width, self.web.minimumWidth()) + 2 * HANDLE
            if reviewing
            else self.web.minimumWidth(),
            MIN_CARD_HEIGHT + HANDLE if reviewing else 0,
        )
        for handle in self.handles.values():
            handle.setVisible(reviewing)
        self.place_widgets()

    def load(self, value: Any) -> None:
        self.ratios = layout_ratios(value)
        self.place_widgets()

    def save(self) -> None:
        self.save_settings(dict(zip(("width", "height"), self.ratios)))

    def reset_layout(self) -> None:
        self.ratios = (1.0, 1.0)
        self.place_widgets()
        self.save()

    def resize_card(self, width: int, height: int) -> None:
        available_width = max(1, self.width() - 2 * HANDLE)
        available_height = max(1, self.height() - HANDLE)
        width = min(
            available_width,
            max(self.minimum_card_width, self.web.minimumWidth(), width),
        )
        height = min(available_height, max(MIN_CARD_HEIGHT, height))
        self.ratios = (width / available_width, height / available_height)
        self.place_widgets()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.place_widgets()

    def place_widgets(self) -> None:
        if not self.reviewing:
            self.web.setGeometry(self.rect())
            return
        available_width = max(0, self.width() - 2 * HANDLE)
        available_height = max(0, self.height() - HANDLE)
        width = min(
            available_width,
            max(
                self.minimum_card_width,
                self.web.minimumWidth(),
                round(available_width * self.ratios[0]),
            ),
        )
        height = min(
            available_height,
            max(MIN_CARD_HEIGHT, round(available_height * self.ratios[1])),
        )
        left = (self.width() - width) // 2
        self.web.setGeometry(left, 0, width, height)
        self.handles["left"].setGeometry(left - HANDLE, 0, HANDLE, height)
        self.handles["right"].setGeometry(left + width, 0, HANDLE, height)
        self.handles["bottom"].setGeometry(left, height, width, HANDLE)


class ReviewLayout(QWidget):
    def __init__(
        self, web: QWidget, bottom: QWidget, save: Callable[[dict[str, float]], None]
    ) -> None:
        super().__init__()
        self.viewport = CardViewport(web, save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.viewport, 1)
        # The action bar always keeps its intrinsic height and full available width.
        layout.addWidget(bottom)
