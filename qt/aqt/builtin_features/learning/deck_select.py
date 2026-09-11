# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Searchable deck tree with stable IDs and full-path disambiguation."""

from __future__ import annotations

from aqt.qt import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QLineEdit,
    QPoint,
    QPushButton,
    Qt,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)


class DeckTreeSelect(QPushButton):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entries: list[tuple[str, int]] = []
        self.items: dict[int, QTreeWidgetItem] = {}
        self.selected = 0
        self.popup = QFrame(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(self.popup)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索牌组名称或完整路径")
        self.search.setAccessibleName("搜索牌组")
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["牌组", "完整路径"])
        self.tree.setAccessibleName("牌组层级选择")
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setMinimumHeight(160)
        self.tree.setMaximumHeight(340)
        layout.addWidget(self.tree)
        self.empty = QLabel("没有匹配的牌组")
        layout.addWidget(self.empty)
        self.empty.hide()
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.select_first_match)
        self.tree.itemClicked.connect(self.choose)
        self.tree.itemActivated.connect(self.choose)
        self.clicked.connect(self.show_popup)

    def set_decks(self, entries: list[tuple[str, int]], selected: int) -> None:
        expanded = {did for did, item in self.items.items() if item.isExpanded()}
        self.entries = entries
        self.tree.clear()
        self.items.clear()
        paths: dict[str, QTreeWidgetItem] = {}
        for name, did in entries:
            if did == 0:
                item = QTreeWidgetItem(self.tree, [name, ""])
                item.setData(0, Qt.ItemDataRole.UserRole, 0)
                self.items[0] = item
                continue
            parts = name.split("::")
            parent = self.tree.invisibleRootItem()
            for depth, part in enumerate(parts):
                path = "::".join(parts[: depth + 1])
                if path not in paths:
                    item = QTreeWidgetItem(parent, [part, path])
                    item.setToolTip(0, path)
                    item.setToolTip(1, path)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    paths[path] = item
                parent = paths[path]
            parent.setData(0, Qt.ItemDataRole.UserRole, did)
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsSelectable)
            self.items[did] = parent
        for did in expanded:
            if did in self.items:
                self.items[did].setExpanded(True)
        self.setCurrentIndex(max(0, self.findData(selected)))
        self.filter(self.search.text())
        self.tree.setColumnWidth(0, 220)

    def count(self) -> int:
        return len(self.entries)

    def currentData(self) -> int:
        return (
            self.entries[self.selected][1]
            if 0 <= self.selected < len(self.entries)
            else 0
        )

    def currentText(self) -> str:
        return self.entries[self.selected][0] if self.entries else "请选择牌组"

    def findData(self, did: int) -> int:
        return next((i for i, entry in enumerate(self.entries) if entry[1] == did), -1)

    def setCurrentIndex(self, index: int) -> None:
        before = self.currentData()
        self.selected = index if 0 <= index < len(self.entries) else 0
        self.setText(
            self.fontMetrics().elidedText(
                self.currentText(),
                Qt.TextElideMode.ElideMiddle,
                max(100, self.width() - 35),
            )
            + " ▾"
        )
        self.setToolTip(self.currentText())
        if item := self.items.get(self.currentData()):
            self.tree.setCurrentItem(item)
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.scrollToItem(item)
        if before != self.currentData():
            self.currentIndexChanged.emit(self.selected)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setText(
            self.fontMetrics().elidedText(
                self.currentText(),
                Qt.TextElideMode.ElideMiddle,
                max(100, self.width() - 35),
            )
            + " ▾"
        )

    def filter(self, text: str) -> None:
        query = text.strip().casefold()

        def visit(item: QTreeWidgetItem) -> bool:
            children = [visit(item.child(i)) for i in range(item.childCount())]
            matches = query in item.text(1).casefold()
            visible = matches or any(children)
            item.setHidden(not visible)
            if query and any(children):
                item.setExpanded(True)
            return visible

        visible = [
            visit(self.tree.topLevelItem(i))
            for i in range(self.tree.topLevelItemCount())
        ]
        self.empty.setVisible(not any(visible))
        if selected := self.items.get(self.currentData()):
            if not selected.isHidden():
                self.tree.scrollToItem(selected)

    def select_first_match(self) -> None:
        query = self.search.text().strip().casefold()
        for name, did in self.entries:
            if query in name.casefold():
                self.choose(self.items[did])
                return

    def choose(self, item: QTreeWidgetItem, column: int = 0) -> None:
        did = item.data(0, Qt.ItemDataRole.UserRole)
        if did is None:
            return
        self.setCurrentIndex(self.findData(did))
        self.popup.hide()
        self.setFocus()

    def show_popup(self) -> None:
        self.search.clear()
        screen = self.screen().availableGeometry()
        width = min(max(self.width(), 540), 720, screen.width() - 20)
        self.popup.resize(width, min(410, screen.height() - 30))
        point = self.mapToGlobal(QPoint(0, self.height()))
        point.setX(max(screen.left(), min(point.x(), screen.right() - width)))
        if point.y() + self.popup.height() > screen.bottom():
            point.setY(
                max(
                    screen.top(),
                    self.mapToGlobal(QPoint(0, 0)).y() - self.popup.height(),
                )
            )
        self.popup.move(point)
        self.popup.show()
        self.setCurrentIndex(self.selected)
        self.search.setFocus()
