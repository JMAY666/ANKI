"""Optional three-pane mode for the existing Anki Browser (Qt6).

All adapters are per window and are undone before Anki saves its normal layout.
The collection, native table, editor, and preview rendering remain Anki-owned.
"""

from __future__ import annotations

from anki.collection import Config, SearchNode
from anki.utils import strip_html
from aqt import gui_hooks
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QByteArray,
    QCheckBox,
    QComboBox,
    QEvent,
    QHBoxLayout,
    QHeaderView,
    QKeySequence,
    QLabel,
    QLineEdit,
    QObject,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QStackedWidget,
    Qt,
    QTabWidget,
    QTimer,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .browser_preview import EmbeddedPreview
from .browser_scope import RequestGate, deck_query, valid_sizes

PREF_KEY = "synapseproCardBrowser"
ROLE = Qt.ItemDataRole.UserRole


class BrowserWorkspace(QObject):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.mw = browser.mw
        self.enabled = False
        self.closed = False
        self.built = False
        self.loading = False
        self.saving_scope = False
        self.inflight = False
        self.pending = None
        self.ready = None
        self.own_search = False
        self.scope_id = None
        self.gate = RequestGate()
        self.error = ""
        self._rebuilding = False
        self._resizing = False
        self.compact = False
        self.compact_preview = False
        self._init_attempts = 0
        prefs = self.mw.pm.profile.get(PREF_KEY, {})
        self.prefs = prefs if isinstance(prefs, dict) else {}
        self.mw.pm.profile[PREF_KEY] = self.prefs
        self.original_search = browser.search
        self.original_search_for = browser.search_for
        self.original_preview = browser.onTogglePreview
        self.original_close = browser._closeWindow
        self.original_select = browser.table.select_single_card
        self.requested_card = None
        browser.table.select_single_card = self.select_card
        browser.search = self.search
        browser.search_for = self.search_for
        browser.onTogglePreview = self.show_preview
        browser._closeWindow = self.close
        self.query_timer = QTimer(self)
        self.query_timer.setSingleShot(True)
        self.query_timer.setInterval(220)
        self.query_timer.timeout.connect(self.search_scope)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(80)
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.toolbar = QToolBar("卡片浏览布局", browser)
        self.toolbar.setObjectName("synapseBrowserToolbar")
        self.toolbar.setMovable(False)
        browser.addToolBar(self.toolbar)
        self.mode_action = QAction("三栏浏览", browser)
        self.mode_action.setCheckable(True)
        self.mode_action.setToolTip("切换三栏浏览与原生标准布局")
        self.mode_action.toggled.connect(self.request_mode)
        self.toolbar.addAction(self.mode_action)
        browser.form.menuqt_accel_view.addAction(self.mode_action)
        browser.form.actionSidebar.triggered.connect(self.focus_decks)
        browser.form.actionSidebarFilter.triggered.connect(self.focus_deck_search)
        browser.form.actionFind.triggered.connect(self.focus_card_search)
        browser.form.actionCardList.triggered.connect(self.show_list)
        browser.form.actionNote.triggered.connect(self.show_editor)
        browser.form.actionToggleSidebar.triggered.connect(self.native_sidebar_toggled)
        self.deck_action = self.toolbar.addAction("牌组目录", self.toggle_decks)
        self.list_action = self.toolbar.addAction("卡片列表", self.show_list)
        self.preview_action = self.toolbar.addAction("卡片预览", self.show_preview)
        self.pane_actions = [self.deck_action, self.list_action, self.preview_action]
        for action in self.pane_actions:
            action.setVisible(False)
        self.shortcuts = []
        for key, callback in (
            ("Ctrl+Alt+1", self.focus_decks),
            ("Ctrl+Alt+2", self.show_list),
            ("Ctrl+Alt+3", self.show_preview),
            ("F6", self.next_pane),
        ):
            shortcut = QShortcut(QKeySequence(key), browser)
            shortcut.activated.connect(callback)
            shortcut.setEnabled(False)
            self.shortcuts.append(shortcut)
        self.hooks = [
            (gui_hooks.browser_did_change_row, self.row_changed),
            (gui_hooks.browser_will_search, self.supply_results),
            (gui_hooks.operation_did_execute, self.operation_executed),
            (gui_hooks.browser_did_fetch_row, self.summary_fallback),
        ]
        for hook, callback in self.hooks:
            hook.append(callback)
        browser.installEventFilter(self)
        QTimer.singleShot(0, self.initialize)

    def initialize(self):
        if self.closed or not self.prefs.get("enabled", True):
            return

        def ready(loaded):
            if self.closed or self.enabled:
                return
            if loaded:
                self.mode_action.setChecked(True)
            elif self._init_attempts < 200:
                self._init_attempts += 1
                QTimer.singleShot(30, self.initialize)
            else:
                self.mode_action.setToolTip("编辑器尚未就绪，请稍后重新打开浏览器")

        # A Browser can already have a note before its WebView defines saveNow.
        # Wait without blocking Qt, then flush drafts before changing widgets.
        self.browser.editor.web.page().runJavaScript(
            "typeof saveNow === 'function' || typeof uiPromise !== 'undefined'", ready
        )

    def request_mode(self, enabled):
        if not self.closed:
            self.browser.editor.call_after_note_saved(
                lambda: self.set_enabled(self.mode_action.isChecked())
            )

    def build(self):
        b = self.browser
        self.list_widget = b.form.splitter.widget(0)
        self.editor_widget = b.form.splitter.widget(1)
        self.editor_widget.setMinimumWidth(0)
        self.list_widget.setMinimumWidth(0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("synapsePreviewTabs")
        self.tabs.setMinimumWidth(0)
        self.preview = EmbeddedPreview(b, self.tabs)
        self.tabs.addTab(self.preview, "预览")
        self.tabs.currentChanged.connect(self.tab_changed)
        self.native_sidebar = b.sidebarDockWidget.widget()
        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.setMinimumWidth(160)
        self.deck_panel = QWidget()
        layout = QVBoxLayout(self.deck_panel)
        layout.setContentsMargins(6, 6, 6, 6)
        self.deck_search = QLineEdit()
        self.deck_search.setObjectName("synapseDeckSearch")
        self.deck_search.setPlaceholderText("查找牌组…")
        self.deck_search.setClearButtonEnabled(True)
        self.deck_search.setAccessibleName("查找牌组")
        self.deck_search.textChanged.connect(self.filter_tree)
        layout.addWidget(self.deck_search)
        self.include_children = QCheckBox("包含子牌组")
        self.include_children.setChecked(self.prefs.get("include_children", True))
        self.include_children.toggled.connect(self.children_toggled)
        layout.addWidget(self.include_children)
        self.tree = QTreeWidget()
        self.tree.setObjectName("synapseDeckTree")
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setAccessibleName("牌组目录")
        self.tree.currentItemChanged.connect(self.deck_selected)
        self.tree.itemExpanded.connect(self.remember_tree)
        self.tree.itemCollapsed.connect(self.remember_tree)
        layout.addWidget(self.tree, 1)
        self.tree_empty = QLabel("没有匹配的牌组")
        layout.addWidget(self.tree_empty)
        all_filters = QPushButton("全部筛选条件")
        all_filters.clicked.connect(self.show_filters)
        layout.addWidget(all_filters)
        self.sidebar_stack.addWidget(self.deck_panel)
        self.scope_label = QLabel()
        self.scope_label.setTextFormat(Qt.TextFormat.PlainText)
        self.scope_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.scope_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.search_box = QLineEdit()
        self.search_box.setObjectName("synapseCardSearch")
        self.search_box.setPlaceholderText("在当前牌组内搜索…")
        self.search_box.setAccessibleName("搜索卡片，支持 Anki 搜索语法")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textEdited.connect(self.search_edited)
        self.search_box.returnPressed.connect(self.search_scope)
        self.sort_box = QComboBox()
        self.sort_box.setAccessibleName("卡片排序")
        for title, key in (
            ("排序字段", "noteFld"),
            ("添加时间", "noteCrt"),
            ("到期时间", "cardDue"),
            ("卡片模板", "template"),
            ("牌组", "deck"),
        ):
            self.sort_box.addItem(title, key)
        self.sort_box.currentIndexChanged.connect(self.sort_changed)
        self.reverse_button = QPushButton("↑")
        self.reverse_button.setCheckable(True)
        self.reverse_button.setToolTip("切换升序／降序")
        self.reverse_button.clicked.connect(self.sort_changed)
        search_row = QHBoxLayout()
        search_row.addWidget(self.sort_box, 1)
        search_row.addWidget(self.reverse_button)
        self.search_panel = QWidget()
        search_layout = QVBoxLayout(self.search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(self.scope_label)
        search_layout.addWidget(self.search_box)
        search_layout.addLayout(search_row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        b.form.tableView.installEventFilter(self)
        b.form.splitter.splitterMoved.connect(self.remember_sizes)
        self.items = {}
        self.built = True

    def set_enabled(self, enabled, closing=False):
        if self.closed or enabled == self.enabled:
            return
        b = self.browser
        if enabled:
            if not self.built:
                self.build()
            self.standard = {
                "splitter": b.form.splitter.saveState(),
                "window": b.saveState(),
                "geometry": b.saveGeometry(),
                "auto": b.auto_layout,
                "notes": b.table.is_notes_mode(),
                "state": b.table._state,
                "card_columns": b.col.load_browser_card_columns(),
                "minimum": b.minimumSize(),
                "header": b.form.tableView.horizontalHeader().saveState(),
            }
            if b.table.is_notes_mode():
                b.table.toggle_state(False, b._lastSearchTxt)
                b._switch.blockSignals(True)
                b._switch.setChecked(False)
                b._switch.blockSignals(False)
            self.standard["card_header"] = (
                b.form.tableView.horizontalHeader().saveState()
            )
            self.standard["sort"] = (
                b.table._state.sort_column,
                b.table._state.sort_backwards,
            )
            self.enabled = True
            b.auto_layout = False
            b.form.splitter.setOrientation(Qt.Orientation.Horizontal)
            self.tabs.addTab(self.editor_widget, "编辑")
            b.form.splitter.addWidget(self.tabs)
            self.sidebar_stack.addWidget(self.native_sidebar)
            b.sidebarDockWidget.setWidget(self.sidebar_stack)
            self.sidebar_stack.setCurrentWidget(self.deck_panel)
            b.form.searchEdit.hide()
            b._switch.hide()
            b.form.gridLayout.addWidget(self.search_panel, 0, 0, 1, 2)
            b.form.gridLayout.addWidget(self.status, 2, 0, 1, 2)
            self.search_panel.show()
            self.status.show()
            self._set_columns(["question", "template", "cardDue"])
            header = b.form.tableView.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.resizeSection(0, 250)
            header.resizeSection(1, 85)
            header.resizeSection(2, 90)
            self.tree_refresh()
            self._initial_scope()
            self.sort_box.blockSignals(True)
            index = self.sort_box.findData(self.prefs.get("sort", "noteFld"))
            self.sort_box.setCurrentIndex(max(0, index))
            self.sort_box.blockSignals(False)
            self.reverse_button.setChecked(bool(self.prefs.get("reverse", False)))
            self.sort_changed()
            b.setMinimumSize(440, 360)
            geometry = self.prefs.get("geometry")
            if isinstance(geometry, str) and len(geometry) <= 2048:
                try:
                    b.restoreGeometry(QByteArray(bytes.fromhex(geometry)))
                except ValueError:
                    pass
            elif "widths" not in self.prefs and b.width() < 1100:
                available = b.screen().availableGeometry()
                b.resize(
                    min(1320, int(available.width() * 0.9)),
                    min(760, int(available.height() * 0.9)),
                )
            self._resizing = True
            if valid_sizes(self.prefs.get("widths")):
                b.form.splitter.setSizes(self.prefs["widths"])
            else:
                b.form.splitter.setSizes([360, 480])
            self._resizing = False
            deck_width = self.prefs.get("deck_width", 230)
            if not isinstance(deck_width, int) or not 160 <= deck_width <= 1500:
                deck_width = 230
            b.resizeDocks(
                [b.sidebarDockWidget], [deck_width], Qt.Orientation.Horizontal
            )
            self.tabs.setCurrentIndex(0)
            self.apply_responsive()
            QTimer.singleShot(0, self.keep_on_screen)
        else:
            self.prefs["geometry"] = bytes(b.saveGeometry()).hex()
            # Retain the user's splitter choice. Automatic resizing / hiding a
            # pane must not replace it with the temporary constrained widths.
            if b.sidebarDockWidget.isVisible() and not self.compact:
                self.prefs["deck_width"] = b.sidebarDockWidget.width()
            self.gate.advance()
            self.query_timer.stop()
            self.refresh_timer.stop()
            self.pending = None
            self.enabled = False
            self.loading = False
            self.saving_scope = False
            if closing:
                # Closing already runs after the editor saved. Model resets
                # must not enqueue another save against a WebView being torn down.
                b.table._selection_model().blockSignals(True)
                self.tabs.blockSignals(True)
            self.preview.stop_audio()
            self.tabs.removeTab(self.tabs.indexOf(self.editor_widget))
            self.editor_widget.setParent(b.form.splitter)
            self.tabs.setParent(None)
            self.tabs.hide()
            b.form.splitter.addWidget(self.editor_widget)
            self.sidebar_stack.removeWidget(self.native_sidebar)
            b.sidebarDockWidget.setWidget(self.native_sidebar)
            self.sidebar_stack.setParent(None)
            self.sidebar_stack.hide()
            self.search_panel.hide()
            self.status.hide()
            b.form.searchEdit.show()
            b._switch.show()
            b.form.tableView.setEnabled(True)
            self.list_widget.show()
            self.editor_widget.show()
            self._set_columns(self.standard["card_columns"], closing=closing)
            b.table._state.sort_column, b.table._state.sort_backwards = self.standard[
                "sort"
            ]
            b.form.tableView.horizontalHeader().restoreState(
                self.standard["card_header"]
            )
            if self.standard["notes"]:
                if closing:
                    b.table._state = self.standard["state"]
                    b.table._model._state = self.standard["state"]
                    b.col.set_config_bool(
                        Config.Bool.BROWSER_TABLE_SHOW_NOTES_MODE, True
                    )
                else:
                    b.table.toggle_state(True, b._lastSearchTxt)
                b._switch.blockSignals(True)
                b._switch.setChecked(True)
                b._switch.blockSignals(False)
            b.form.tableView.horizontalHeader().restoreState(self.standard["header"])
            b.form.splitter.restoreState(self.standard["splitter"])
            b.restoreState(self.standard["window"])
            b.auto_layout = self.standard["auto"]
            b.setMinimumSize(self.standard["minimum"])
            b.restoreGeometry(self.standard["geometry"])
            if not closing:
                self.original_search()
        for action in self.pane_actions:
            action.setVisible(enabled)
        for shortcut in self.shortcuts:
            shortcut.setEnabled(enabled)
        for name in (
            "actionLayoutAuto",
            "actionLayoutVertical",
            "actionLayoutHorizontal",
            "action_toggle_mode",
        ):
            getattr(b.form, name).setEnabled(not enabled)
        if not closing:
            self.prefs["enabled"] = enabled

    def _set_columns(self, columns, closing=False):
        table = self.browser.table
        if not closing:
            table._save_selection()
        table._model.begin_reset()
        table._state._active_columns = list(columns)
        self.browser.col.set_browser_card_columns(list(columns))
        table._model._rows.clear()
        table._model.end_reset()
        table._reset_selection()
        if not closing:
            table._restore_selection(table._intersected_selection)
        if not closing:
            table._set_sort_indicator()

    def _initial_scope(self):
        b = self.browser
        search = b._lastSearchTxt
        default = b.col.build_search_string(SearchNode(deck="current"))
        if search == default:
            # Anki may have opened this browser for the current review card.
            # A remembered, unrelated deck must not override that caller.
            did = int(b.col.decks.selected())
            self.scope_id = did if did in self.items else 0
            self.search_box.setText("")
            self._select_tree(self.scope_id)
            self._update_scope_label()
            self.own_search = True
            try:
                self.original_search_for(self.scope_query())
            finally:
                self.own_search = False
        else:
            self.scope_id = None
            self.search_box.setText(search)
            self._update_scope_label()

    def close(self):
        if not self.closed:
            self.set_enabled(False, closing=True)
            self.closed = True
            self.gate.advance()
            self.query_timer.stop()
            self.refresh_timer.stop()
            for hook, callback in self.hooks:
                hook.remove(callback)
            if self.built:
                self.preview.dispose()
                self.tabs.deleteLater()
                self.sidebar_stack.deleteLater()
            self.browser.search = self.original_search
            self.browser.search_for = self.original_search_for
            self.browser.onTogglePreview = self.original_preview
            self.browser._closeWindow = self.original_close
            self.browser.table.select_single_card = self.original_select
        self.original_close()

    def tree_refresh(self):
        self._rebuilding = True
        try:
            self.tree.clear()
            self.items = {}
            all_item = QTreeWidgetItem(["全部牌组"])
            all_item.setData(0, ROLE, 0)
            all_item.setToolTip(0, "全部牌组中的卡片")
            self.tree.addTopLevelItem(all_item)
            self.items[0] = (all_item, None)
            collapsed = set(self.prefs.get("collapsed", []))

            def add(parent, nodes, prefix=""):
                for node in nodes:
                    name = prefix + node.name
                    item = QTreeWidgetItem([node.name])
                    item.setData(0, ROLE, int(node.deck_id))
                    item.setToolTip(0, name)
                    parent.addChild(item)
                    self.items[int(node.deck_id)] = (item, name)
                    add(item, node.children, name + "::")
                    item.setExpanded(int(node.deck_id) not in collapsed)

            add(all_item, self.browser.col.decks.deck_tree().children)
            all_item.setExpanded(True)
            self._select_tree(self.scope_id)
        finally:
            self._rebuilding = False
        self.filter_tree(self.deck_search.text())

    def _select_tree(self, did):
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(self.items[did][0] if did in self.items else None)
        self.tree.blockSignals(False)

    def filter_tree(self, text):
        query = text.strip().casefold()
        self._rebuilding = True
        collapsed = set(self.prefs.get("collapsed", []))

        def visit(item):
            did = item.data(0, ROLE)
            name = self.items[did][1] or ""
            matched = not query or query in name.casefold()
            children = [visit(item.child(i)) for i in range(item.childCount())]
            visible = matched or any(children)
            item.setHidden(not visible)
            item.setExpanded(
                bool(query and any(children)) if query else did not in collapsed
            )
            return visible

        visible = visit(self.tree.topLevelItem(0))
        self._rebuilding = False
        self.tree_empty.setVisible(not visible)

    def remember_tree(self, _item=None):
        if self._rebuilding or self.deck_search.text().strip():
            return
        self.prefs["collapsed"] = [
            did
            for did, (item, _name) in self.items.items()
            if item.childCount() and not item.isExpanded()
        ]

    def deck_selected(self, current, _previous=None):
        if self._rebuilding or not self.enabled or current is None:
            return
        self.scope_id = current.data(0, ROLE)
        self.prefs["deck_id"] = self.scope_id
        # Selecting a new scope starts a fresh search; an external deck query
        # must not silently remain ANDed with a different deck.
        self.search_box.setText("")
        self.search_scope()

    def children_toggled(self, checked):
        self.prefs["include_children"] = checked
        if self.enabled:
            self.search_scope()

    def _update_scope_label(self):
        if self.scope_id is None:
            text = "自定义搜索范围"
        elif self.scope_id == 0:
            text = "全部牌组"
        else:
            text = self.items.get(self.scope_id, (None, ""))[1] or ""
            text += (
                " · 含子牌组" if self.include_children.isChecked() else " · 仅本牌组"
            )
        self.scope_label.setText(
            self.scope_label.fontMetrics().elidedText(
                text,
                Qt.TextElideMode.ElideMiddle,
                max(120, self.list_widget.width() - 18),
            )
        )
        self.scope_label.setToolTip(text)
        self.include_children.setEnabled(self.scope_id not in (None, 0))

    def scope_query(self):
        name = self.items.get(self.scope_id, (None, None))[1]
        return deck_query(
            self.browser.col,
            name,
            self.include_children.isChecked(),
            self.search_box.text(),
        )

    def search_edited(self, _text):
        self.gate.advance()
        self.query_timer.start()

    def search_scope(self):
        self.query_timer.stop()
        if not self.enabled or self.closed:
            return
        revision = self.gate.advance()
        self.saving_scope = True

        def saved():
            if not self.enabled or self.closed or not self.gate.accepts(revision):
                return
            self.saving_scope = False
            try:
                query = self.scope_query()
            except Exception as exc:
                self.error = "搜索条件无效：" + str(exc)
                self.loading = False
                self._apply_ids(self.browser._lastSearchTxt, [])
                return
            self._update_scope_label()
            self.own_search = True
            try:
                self.original_search_for(query)
            finally:
                self.own_search = False

        self.browser.editor.call_after_note_saved(saved)

    def search_for(self, search, prompt=None):
        self.requested_card = None
        if self.enabled and not self.own_search:
            # Calls from Anki menus/other add-ons keep their exact search.
            self.scope_id = None
            self.search_box.setText(search)
            self._select_tree(None)
            self._update_scope_label()
        self.original_search_for(search, prompt)

    def sort_changed(self, *_args):
        if not self.enabled:
            return
        key = self.sort_box.currentData()
        reverse = self.reverse_button.isChecked()
        self.prefs.update(sort=key, reverse=reverse)
        state = self.browser.table._state
        state.sort_column = key
        state.sort_backwards = reverse
        self.reverse_button.setText("↓" if reverse else "↑")
        self.browser.table._set_sort_indicator()
        self.search()

    def search(self):
        if not self.enabled or self.closed:
            return self.original_search()
        b = self.browser
        state = b.table._state
        revision = self.gate.advance()
        column = b.table._model.columns.get(state.sort_column)
        self.pending = (revision, b._lastSearchTxt, column, state.sort_backwards)
        self.loading = True
        self.error = ""
        self.status.setText("正在查找卡片…")
        b.form.tableView.setEnabled(False)
        self.tabs.setTabEnabled(1, False)
        self.preview.set_card(None, "正在查找卡片…")
        self._start_pending()

    def _start_pending(self):
        if self.inflight or not self.pending or self.closed or not self.enabled:
            return
        request = self.pending
        self.pending = None
        self.inflight = True
        revision, query, column, reverse = request
        QueryOp(
            parent=self.browser,
            op=lambda col: col.find_cards(query, order=column or True, reverse=reverse),
            success=lambda ids: self._search_finished(request, ids),
        ).failure(
            lambda exc: self._search_finished(request, [], exc)
        ).run_in_background()

    def _search_finished(self, request, ids, error=None):
        self.inflight = False
        revision, query, column, reverse = request
        if self.closed:
            return
        if self.enabled and self.gate.accepts(revision):
            state = self.browser.table._state
            if column and (
                state.sort_column != column.key or state.sort_backwards != reverse
            ):
                self.search()
                return
            self.loading = False
            self.error = "搜索失败：" + str(error) if error else ""
            self._apply_ids(query, ids)
        self._start_pending()

    def _apply_ids(self, query, ids):
        self.ready = (query, ids)
        try:
            self.original_search()
        finally:
            self.ready = None
        self.browser.form.tableView.setEnabled(True)
        if self.requested_card is not None:
            card_id, scroll = self.requested_card
            self.requested_card = None
            self.original_select(card_id, scroll)
        self.row_changed(self.browser)

    def select_card(self, card_id, scroll_even_if_visible=True):
        if self.enabled and (
            self.loading or self.saving_scope or self.query_timer.isActive()
        ):
            self.requested_card = (card_id, scroll_even_if_visible)
        else:
            self.original_select(card_id, scroll_even_if_visible)

    def summary_fallback(self, card_id, is_note, row, columns):
        if not self.enabled or self.closed or is_note or "question" not in columns:
            return
        cell = row.cells[columns.index("question")]
        if cell.text.strip() or row.is_disabled:
            return
        try:
            note = self.browser.col.get_card(card_id).note()
            model = note.note_type()
            text = strip_html(note.fields[model["sortf"]]).strip()
            cell.text = text[:300] or "图片／音频卡片（选择后预览）"
        except Exception:
            cell.text = "卡片内容暂不可用"

    def supply_results(self, context):
        if context.browser is self.browser and self.enabled and self.ready:
            query, ids = self.ready
            # Earlier add-on hooks may have supplied IDs or rewritten the
            # search. Respect them instead of reusing results for another query.
            if context.ids is None and context.search == query:
                context.ids = ids

    def row_changed(self, browser):
        if browser is not self.browser or not self.enabled or self.closed:
            return
        count = browser.table.len()
        selected = browser.table.len_selection()
        card = None if self.loading else browser.table.get_single_selected_card()
        if self.loading:
            message = "正在查找卡片…"
        elif self.error:
            message = self.error
        elif not count:
            message = (
                "没有符合搜索条件的卡片"
                if self.search_box.text().strip()
                else "此范围内没有卡片"
            )
        elif selected > 1:
            message = f"已选择 {selected} 张卡片，请选择一张预览"
        elif not card:
            message = "卡片已不存在或尚未选择，请重新选择"
        else:
            message = f"共 {count:,} 张卡片 · 已选择 {selected:,} 张"
        self.status.setText(message)
        self.tabs.setTabEnabled(1, card is not None)
        self.apply_responsive()
        self.preview.set_card(card, message)

    def operation_executed(self, changes, _handler):
        if (
            self.enabled
            and not self.closed
            and any(
                getattr(changes, name, False)
                for name in ("browser_table", "card", "note_text", "deck")
            )
        ):
            self.refresh_timer.start()

    def refresh_data(self):
        if not self.enabled or self.closed:
            return
        if self.saving_scope or self.query_timer.isActive():
            self.refresh_timer.start()
            return
        old_name = self.items.get(self.scope_id, (None, None))[1]
        self.tree_refresh()
        new_name = self.items.get(self.scope_id, (None, None))[1]
        if self.scope_id is not None and self.scope_id not in self.items:
            self.scope_id = 0
            self._select_tree(0)
            self.search_box.setText("")
        if self.scope_id is not None and (old_name != new_name or self.scope_id == 0):
            self.search_scope()
        else:
            self.browser.editor.call_after_note_saved(self.search)

    def show_filters(self):
        if self.enabled:
            self.sidebar_stack.setCurrentWidget(self.native_sidebar)
            self.browser.sidebar.refresh()

    def toggle_decks(self):
        if not self.enabled:
            return
        visible = self.browser.sidebarDockWidget.isVisible()
        if visible and self.sidebar_stack.currentWidget() is self.native_sidebar:
            self.sidebar_stack.setCurrentWidget(self.deck_panel)
            return
        self.prefs["decks_visible"] = not visible
        self.force_decks = not visible
        self.sidebar_stack.setCurrentWidget(self.deck_panel)
        self.apply_responsive()

    def focus_decks(self):
        if self.enabled:
            self.prefs["decks_visible"] = True
            self.force_decks = True
            self.sidebar_stack.setCurrentWidget(self.deck_panel)
            self.apply_responsive()
            self.tree.setFocus()

    def focus_deck_search(self):
        if self.enabled:
            self.focus_decks()
            self.deck_search.setFocus()

    def focus_card_search(self):
        if self.enabled:
            self.show_list()
            self.search_box.setFocus()

    def show_editor(self):
        if self.enabled and self.tabs.isTabEnabled(1):
            self.compact_preview = True
            self.tabs.setCurrentIndex(1)
            self.apply_responsive()
            self.browser.editor.web.setFocus()

    def native_sidebar_toggled(self):
        if self.enabled:
            visible = self.browser.sidebarDockWidget.isVisible()
            self.prefs["decks_visible"] = visible
            self.force_decks = visible
            self.apply_responsive()

    def show_list(self):
        if self.enabled:
            self.compact_preview = False
            self.apply_responsive()
            self.browser.form.tableView.setFocus()

    def show_preview(self):
        if not self.enabled:
            return self.original_preview()
        self.compact_preview = True
        self.tabs.setCurrentIndex(0)
        self.apply_responsive()
        self.preview.render_card()
        self.preview.flip_button.setFocus()

    def next_pane(self):
        if not self.enabled:
            return
        from aqt.qt import QApplication

        focused = QApplication.focusWidget()
        if focused and self.deck_panel.isAncestorOf(focused):
            self.show_list()
        elif focused and self.list_widget.isAncestorOf(focused):
            self.show_preview()
        else:
            self.focus_decks()

    def tab_changed(self, index):
        if not self.enabled:
            return
        if index == 0:
            self.browser.editor.call_after_note_saved(
                lambda: self.row_changed(self.browser)
            )
        else:
            self.preview.stop_audio()

    def apply_responsive(self):
        if not self.enabled or self.closed:
            return
        b = self.browser
        self._resizing = True
        try:
            show_decks = self.prefs.get("decks_visible", True) and (
                b.width() >= 980 or getattr(self, "force_decks", False)
            )
            b.sidebarDockWidget.setVisible(show_decks)
            center_width = b.width() - (
                b.sidebarDockWidget.width() if show_decks else 0
            )
            was_compact = self.compact
            self.compact = center_width < 820
            self.list_widget.setVisible(not self.compact or not self.compact_preview)
            self.tabs.setVisible(not self.compact or self.compact_preview)
            if (
                was_compact
                and not self.compact
                and valid_sizes(self.prefs.get("widths"))
            ):
                b.form.splitter.setSizes(self.prefs["widths"])
            if not self.tabs.isVisible():
                self.preview.stop_audio()
            self._update_scope_label()
        finally:
            self._resizing = False

    def remember_sizes(self, *_args):
        if not self.enabled or self._resizing or self.compact:
            return
        sizes = self.browser.form.splitter.sizes()
        if valid_sizes(sizes):
            self.prefs["widths"] = sizes
        if self.browser.sidebarDockWidget.isVisible():
            self.prefs["deck_width"] = self.browser.sidebarDockWidget.width()

    def eventFilter(self, obj, event):
        if self.enabled and not self.closed:
            if obj is self.browser and event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self.apply_responsive)
            elif (
                self.built
                and obj is self.browser.form.tableView
                and event.type() == QEvent.Type.KeyPress
            ):
                if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    if event.key() == Qt.Key.Key_Space:
                        self.show_preview()
                        self.preview.flip()
                        return True
                    if event.key() == Qt.Key.Key_R:
                        self.preview.replay()
                        return True
        return super().eventFilter(obj, event)

    def keep_on_screen(self):
        if self.closed or not self.enabled:
            return
        b = self.browser
        if b.isMaximized() or b.isFullScreen():
            return
        available = b.screen().availableGeometry()
        frame = b.frameGeometry()
        x = min(
            max(frame.x(), available.x()),
            available.x() + max(0, available.width() - frame.width()),
        )
        y = min(
            max(frame.y(), available.y()),
            available.y() + max(0, available.height() - frame.height()),
        )
        # Move by the frame delta; Qt/platform frame margins need not be equal.
        b.move(b.pos().x() + x - frame.x(), b.pos().y() + y - frame.y())


def on_browser(browser):
    if not hasattr(browser, "_synapse_workspace"):
        browser._synapse_workspace = BrowserWorkspace(browser)


def register():
    global _registered
    if not _registered:
        gui_hooks.browser_will_show.append(on_browser)
        _registered = True


_registered = False
