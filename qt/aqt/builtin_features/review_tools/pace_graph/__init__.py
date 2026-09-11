# Source integration: Ankitects Pty Ltd and contributors
"""Independent, movable pace overlay for Anki Qt 5/6 (Anki 2.1.50+)."""
from collections import deque
import time
import math
import copy
import sys
from aqt import mw, gui_hooks
from aqt.utils import tooltip
from aqt.qt import (QAction, QApplication, QCheckBox, QColor, QColorDialog, QLineEdit, QSlider, QPalette, QComboBox, QDialog, QDoubleSpinBox,
                    QFormLayout, QHBoxLayout, QMenu, QScrollArea, QLabel, QTabWidget, QVBoxLayout, QPainter, QPainterPath, QPen, QPoint,
                    QPointF, QPushButton, QRectF, QSpinBox, Qt, QTimer, QWidget)
from ..config import get_config, save_config, review_is_visible
from .model import Pace, SmoothPace
from .compat import local_position, global_position, execute_menu, normalize_config


class Overlay(QWidget):
    def __init__(self, owner):
        super().__init__(mw, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.owner = owner
        self.drag = None
        self.resizing = None
        self.hovered = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.apply_size()
        self.setStyleSheet('QPushButton {color: #b7c5ce; background: rgba(38, 52, 62, 150); border: 0; border-radius: 4px; padding: 3px;}')
        self.setToolTip('拖动空白处移动，拖动右下角调整大小；正值表示快于目标，虚线代表目标速度。')
        self.settings = QPushButton('设置', self)
        self.settings.setGeometry(292, 9, 66, 24)
        self.settings.clicked.connect(owner.configure)
        self.pause = QPushButton('暂停', self)
        self.pause.setGeometry(226, 9, 60, 24)
        self.pause.clicked.connect(owner.toggle_pause)
        self.hide_button = QPushButton('隐藏', self)
        self.hide_button.setToolTip('隐藏至离开并重新进入复习')
        self.hide_button.clicked.connect(owner.hide_temporarily)
        self.hide_button.hide()
        self.settings.hide()
        self.pause.hide()
        self.layout_controls()
        self.settings.setVisible(owner.config.get('controls') == 'always')
        self.pause.setVisible(owner.config.get('controls') == 'always')
        self.hide_button.setVisible(owner.config.get('controls') == 'always')

    def compact(self):
        return self.owner.config.get('view', 'compact') != 'full'

    def minimal(self):
        return self.owner.config.get('view') == 'minimal'

    def size_key(self):
        return 'minimal_size' if self.minimal() else ('compact_size' if self.compact() else 'size')

    def apply_size(self):
        no_shadow = not self.owner.config.get('window_shadow', False)
        flag = Qt.WindowType.NoDropShadowWindowHint
        if bool(self.windowFlags() & flag) != no_shadow:
            visible = self.isVisible()
            self.setWindowFlag(flag, no_shadow)
            if visible:
                self.show()
        compact = self.compact()
        minimum = (110, 76) if self.minimal() else ((150, 76) if compact else (280, 120))
        default = [180, 86] if compact else [320, 140]
        self.setMinimumSize(*minimum)
        self.setMaximumSize(900, 400)
        size = self.owner.config.get(self.size_key(), default)
        if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) for v in size)):
            size = default
        self.resize(max(minimum[0], min(900, size[0])), max(minimum[1], min(400, size[1])))

    def layout_controls(self):
        self.hide_button.setGeometry(6, self.height() - 26, 34, 22)
        if self.compact():
            self.settings.setText('...')
            self.settings.setToolTip('速度图设置')
            self.settings.setGeometry(self.width() - 50, 4 if self.width() < 130 else self.height() - 26, 22, 22)
            self.pause.setText('>' if self.owner.model.paused else 'Ⅱ')
            self.pause.setToolTip('继续' if self.owner.model.paused else '暂停')
            self.pause.setGeometry(self.width() - 76, 4 if self.width() < 130 else self.height() - 26, 22, 22)
        else:
            self.settings.setText('设置')
            self.pause.setText('继续' if self.owner.model.paused else '暂停')
            self.settings.setGeometry(self.width() - 74, 6, 66, 22)
            self.pause.setGeometry(self.width() - 140, 6, 60, 22)

    def resizeEvent(self, event):
        if hasattr(self, 'pause'):
            self.layout_controls()
        super().resizeEvent(event)

    def enterEvent(self, event):
        self.hovered = True
        self.settings.setVisible(self.owner.config.get('controls', 'hover') != 'hidden')
        self.pause.setVisible(self.owner.config.get('controls', 'hover') != 'hidden')
        self.hide_button.setVisible(self.owner.config.get('controls', 'hover') != 'hidden')
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.settings.setVisible(self.owner.config.get('controls', 'hover') == 'always')
        self.pause.setVisible(self.owner.config.get('controls', 'hover') == 'always')
        self.hide_button.setVisible(self.owner.config.get('controls', 'hover') == 'always')
        self.update()
        super().leaveEvent(event)

    def resize_corner(self, point):
        return point.x() >= self.width() - 20 and point.y() >= self.height() - 20

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for title, callback in [
            ('设置…', self.owner.configure),
            ('继续计时' if self.owner.model.paused else '暂停计时', self.owner.toggle_pause),
            ('隐藏速度图', self.owner.toggle_visible),
            ('解锁位置' if self.owner.config.get('locked') else '锁定位置', self.owner.toggle_lock),
            ('清空速度历史', self.owner.reset_history),
        ]:
            menu.addAction(title, callback)
        execute_menu(menu, event.globalPos())

    def mousePressEvent(self, event):
        if self.owner.config.get('locked', False):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            resizing = self.resize_corner(local_position(event))
            if QApplication.platformName().startswith('wayland') and handle:
                if resizing and hasattr(handle, 'startSystemResize'):
                    if handle.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
                        event.accept()
                        return
                elif not resizing and hasattr(handle, 'startSystemMove'):
                    if handle.startSystemMove():
                        event.accept()
                        return
            if self.resize_corner(local_position(event)):
                self.resizing = (global_position(event), self.size())
            else:
                self.drag = global_position(event) - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.resizing is not None:
            origin, size = self.resizing
            delta = global_position(event) - origin
            self.resize(size.width() + delta.x(), size.height() + delta.y())
            event.accept()
        elif self.drag is not None:
            self.move(global_position(event) - self.drag)
            event.accept()

        else:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self.resize_corner(local_position(event)) else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        if self.resizing is not None:
            self.resizing = None
            self.owner.config[self.size_key()] = [self.width(), self.height()]
            self.owner.save()
        if self.drag is not None:
            self.drag = None
            self.owner.config['position'] = [self.x(), self.y()]
            self.owner.save()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        config = self.owner.config
        mode = config.get('theme', 'auto')
        light = mode == 'light' or (mode == 'auto' and mw.palette().color(QPalette.ColorRole.Window).lightness() > 128)
        palettes = ({'muted': ('#21877b', '#a3652d'), 'bright': ('#007e72', '#ad5119'), 'mono': ('#435862', '#435862')}
                    if light else {'muted': ('#8ac4bf', '#cbb194'), 'bright': ('#46d9cf', '#ffad78'), 'mono': ('#cad4dc', '#cad4dc')})
        button_style = ('QPushButton {color: #34454d; background: rgba(230, 236, 238, 190); border: 0; border-radius: 4px; padding: 3px;}' if light else
                        'QPushButton {color: #b7c5ce; background: rgba(38, 52, 62, 150); border: 0; border-radius: 4px; padding: 3px;}')
        if self.styleSheet() != button_style:
            self.setStyleSheet(button_style)
        custom = config.get('palette') == 'custom'
        ahead, behind = palettes.get(config.get('palette'), palettes['muted'])
        if custom:
            ahead, behind = config['custom_ahead'], config['custom_behind']
        text_color = config['custom_text'] if custom else ('#34454d' if light else '#afc0c8')
        background = QColor(config['custom_background'] if custom else ('#f1f4f5' if light else '#18232c'))
        background.setAlpha(round(255 * config.get('background', 20) / 100))
        p.setBrush(background)
        p.drawRoundedRect(QRectF(self.rect()), 9, 9)
        model = self.owner.model
        delta = self.owner.smooth.value
        color = QColor(ahead if delta is None or delta >= 0 else behind)
        def label(x, y, text, size, tint, bold=False):
            font = p.font()
            font.setPixelSize(int(size))
            font.setBold(bold)
            p.setFont(font)
            p.setOpacity(config.get("foreground", 72) / 100)
            p.setPen(color if tint == color.name() else QColor(text_color))
            p.drawText(x, y, text)
        compact = self.compact()
        width, height = self.width(), self.height()
        number_size = self.owner.config.get('number_size', 22)
        number = 'Ⅱ' if model.paused else ('—' if delta is None else f'{delta:+.1f}秒')
        if self.minimal():
            rect = QRectF(12, 12, width - 24, height - 24)
        elif compact:
            # Three header columns; the chart has a separate area underneath.
            pace_width = max(58, min(96, width * 0.43))
            font = p.font()
            font.setBold(True)
            font.setPixelSize(int(number_size))
            p.setFont(font)
            while p.fontMetrics().horizontalAdvance(number) > pace_width - 7 and font.pixelSize() > 12:
                font.setPixelSize(font.pixelSize() - 1)
                p.setFont(font)
            label(11, 32, number, font.pixelSize(), color.name(), True)
            average = None if delta is None else model.goal - delta
            column_width = (width - pace_width - 16) / 2
            for index, (title, value) in enumerate([
                ('平均', '—' if average is None else f'{average:.1f}秒'),
                ('目标耗时', f'{model.goal:g}秒'),
            ]):
                left = pace_width + 8 + index * column_width
                font = p.font()
                font.setBold(False)
                font.setPixelSize(10)
                p.setFont(font)
                value = p.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, int(column_width - 2))
                label(int(left), 19, title, 9, '#91a4b2')
                label(int(left), 32, value, 10, '#a5b6c2')
            rect = QRectF(12, 44, width - 24, max(20, height - 55))
        else:
            label(12, 24, '速度', 11, '#b7c5ce', True)
            label(12, 59, number, number_size, color.name(), True)
            label(12, 77, '等待作答' if delta is None else ('每张快于目标' if delta >= 0 else '每张慢于目标'), 11, '#a5b6c2')
            rect = QRectF(132, 41, width - 146, max(32, height - 90))
        p.setOpacity(config.get("graph_opacity", 65) / 100)
        endpoint = self.minimal() or self.owner.config.get('endpoint', True)
        dot_value = delta if delta is not None else 0
        dot = QPointF(rect.right(), rect.center().y() - math.tanh(dot_value / max(model.goal * 0.5, 1)) * (rect.height() / 2 - 3))
        p.save()
        if endpoint:
            clip = QPainterPath()
            clip.addRect(QRectF(self.rect()))
            hole = QPainterPath()
            hole.addEllipse(dot, 3, 3)
            p.setClipPath(clip.subtracted(hole))
        p.setPen(QPen(QColor('#6d858b' if light else '#566773'), 1, Qt.PenStyle.DotLine))
        if self.minimal() or self.owner.config.get('goal_line', True):
            p.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        values = [(stamp, value) for stamp, value in self.owner.history if self.owner.plot_time - stamp <= self.owner.config.get('history_seconds', 60)]
        if values:
            scale = max(model.goal * 0.5, 1)
            points = [QPointF(rect.right() - (self.owner.plot_time - stamp) / self.owner.config.get('history_seconds', 60) * rect.width(),
                             rect.center().y() - math.tanh(v / scale) * (rect.height()/2 - 3))
                      for stamp, v in values if self.owner.plot_time - stamp <= self.owner.config.get('history_seconds', 60)]
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            p.setPen(QPen(color, 1.5))
            p.drawPath(path)
        p.restore()
        if endpoint:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(dot, 3, 3)
        if not compact and self.owner.config.get('details', True):
            average = None if delta is None else model.goal - delta
            label(12, height - 25, f'目标 {model.goal:g}秒 · 平均 {average:.1f}秒' if average is not None else f'目标 {model.goal:g}秒 · 请先完成一张卡片', 11, '#e0e8ec')
            state = '已暂停' if model.paused else ('已显示答案，计时暂停' if model.flipped and model.current is not None else '')
            if state:
                label(12, height - 9, state, 10, '#91a4b2')
        if self.hovered and not self.owner.config.get('locked', False):
            p.setPen(QPen(QColor('#91a4b2'), 1))
            p.drawLine(QPointF(width - 13, height - 5), QPointF(width - 5, height - 13))
            p.drawLine(QPointF(width - 9, height - 5), QPointF(width - 5, height - 9))
        p.end()


class Controller:
    def __init__(self):
        raw = get_config("pace_graph") or {}
        self.config = normalize_config(raw)
        self.user_hidden = False
        self.was_studying = False
        self.model = Pace(self.config['goal'], self.config['window'])
        self.history = deque(maxlen=1300)
        self.smooth = SmoothPace(self.config["transition"])
        self.target = None
        self.plot_time = 0.0
        self.last_sample = -1.0
        self.last_frame = time.monotonic()
        self.overlay = Overlay(self)
        self.dialog = None
        self.last = time.monotonic()
        self.last_plot = self.last
        self.action = QAction('速度图设置…', mw)
        self.action.triggered.connect(self.configure)
        mw.review_tools.pace_menu.addAction(self.action)
        self.shortcuts = []
        for title, keys, callback in [
            ('显示／隐藏速度图', 'Ctrl+Alt+G', self.toggle_visible),
            ('暂停／继续速度计时', 'Ctrl+Alt+P', self.toggle_pause),
            ('找回速度图位置', '', self.recover_position),
        ]:
            action = QAction(title, mw)
            if keys:
                action.setShortcut(keys)
            action.triggered.connect(callback)
            mw.review_tools.pace_menu.addAction(action)
            self.shortcuts.append(action)
        self.timer = QTimer(mw)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.animation = QTimer(mw)
        self.animation.setInterval(33)
        self.animation.timeout.connect(self.animate)
        self.animation.start()
        gui_hooks.reviewer_did_show_question.append(self.question)
        gui_hooks.reviewer_did_answer_card.append(self.answer)
        gui_hooks.reviewer_did_show_answer.append(self.flip)
        gui_hooks.reviewer_will_end.append(self.end_review)
        gui_hooks.profile_will_close.append(self.reset)
        self.restore_position()
        QApplication.instance().screenRemoved.connect(lambda *_: QTimer.singleShot(0, self.restore_position))

    def save(self):
        save_config("pace_graph", self.config)

    def restore_position(self):
        position = self.config.get('position')
        if isinstance(position, list) and len(position) == 2 and all(isinstance(v, int) for v in position):
            point = QPoint(*position)
            if any(screen.availableGeometry().contains(point) and
                   screen.availableGeometry().contains(point + QPoint(self.overlay.width() - 1, self.overlay.height() - 1)) for screen in QApplication.screens()):
                self.overlay.move(point)
                return
        display = mw.screen() or QApplication.primaryScreen()
        if display is None:
            return
        screen = display.availableGeometry()
        self.overlay.resize(min(self.overlay.width(), screen.width()), min(self.overlay.height(), screen.height()))
        self.overlay.move(max(screen.left(), screen.right() - self.overlay.width() - 20),
                          max(screen.top(), min(screen.top() + 80, screen.bottom() - self.overlay.height())))

    def studying(self):
        return (review_is_visible() and get_config('policy')['pace_enabled'] and
                QApplication.activeWindow() in (mw, self.overlay) and
                not mw.isMinimized() and self.dialog is None)

    def advance(self):
        now = time.monotonic()
        studying = self.studying()
        self.model.advance(now - self.last, studying and self.was_studying)
        self.was_studying = studying
        self.last = now
        return now

    def animate(self):
        now = time.monotonic()
        dt = now - self.last_frame
        self.last_frame = now
        if not self.overlay.isVisible() or self.model.paused or not self.studying():
            return
        if not 0 < dt <= 2:
            return
        value = self.smooth.advance(self.target, dt)
        if value is not None:
            self.plot_time += dt
            if self.plot_time - self.last_sample >= 0.1:
                self.history.append((self.plot_time, value))
                self.last_sample = self.plot_time
            while self.history and self.plot_time - self.history[0][0] > self.config.get('history_seconds', 60):
                self.history.popleft()
        self.overlay.update()

    def clear_graph(self):
        self.history.clear()
        self.smooth = SmoothPace(self.config['transition'])
        self.target = None
        self.plot_time = 0.0
        self.last_sample = -1.0
        self.last_frame = time.monotonic()

    def tick(self):
        now = self.advance()
        if self.dialog is None:
            self.overlay.setVisible(review_is_visible() and get_config("policy")["pace_enabled"] and not self.user_hidden)
        if now - self.last_plot >= self.config['refresh']:
            self.last_plot = now
            self.target = self.model.delta()
            self.overlay.update()

    def flip(self, card):
        self.advance()
        self.model.flip()
        self.target = self.model.delta()
        self.overlay.update()

    def question(self, card):
        self.advance()
        self.model.question()
        self.restore_position() if not self.overlay.isVisible() else None
        if not self.user_hidden and get_config("policy")["pace_enabled"] and review_is_visible():
            self.overlay.show()
        self.overlay.update()

    def answer(self, reviewer, card, ease):
        if not get_config('policy')['pace_enabled']:
            self.model.current = None
            return
        self.advance()
        self.model.answer()
        self.target = self.model.delta()
        self.overlay.update()

    def end_review(self):
        self.user_hidden = False
        self.advance()
        self.model.current = None
        self.overlay.hide()

    def hide_temporarily(self):
        self.user_hidden = True
        self.overlay.hide()
        keys = 'Command–Option–G' if sys.platform == 'darwin' else 'Ctrl–Alt–G'
        tooltip('速度图已临时隐藏，重新进入复习时恢复。按 ' + keys + ' 可立即显示。', period=5000, parent=mw)

    def toggle_visible(self):
        self.user_hidden = not self.user_hidden
        self.overlay.setVisible(not self.user_hidden and review_is_visible() and get_config('policy')['pace_enabled'])

    def toggle_lock(self):
        self.config['locked'] = not self.config.get('locked', False)
        self.save()
        self.overlay.update()

    def recover_position(self):
        self.user_hidden = False
        self.config['position'] = None
        self.restore_position()
        self.save()
        self.overlay.show()

    def reset_history(self):
        self.advance()
        # Clear completed history without shortening the card being timed.
        self.model.answers.clear()
        self.clear_graph()
        self.overlay.update()

    def reset(self):
        self.user_hidden = False
        self.model = Pace(self.config['goal'], self.config['window'])
        self.clear_graph()
        self.overlay.layout_controls()
        self.overlay.hide()
        if self.dialog:
            self.dialog.close()

    def toggle_pause(self):
        self.advance()
        if not review_is_visible():
            return
        self.model.paused = not self.model.paused
        self.overlay.layout_controls()
        self.overlay.update()

    def configure(self):
        if self.dialog:
            self.dialog.raise_()
            return
        self.advance()
        original_config = copy.deepcopy(self.config)
        original_model = self.model
        original_smooth = self.smooth
        original_geometry = self.overlay.geometry()
        original_visible = self.overlay.isVisible()
        committed = False
        dialog = QDialog(mw)
        self.dialog = dialog
        dialog.setWindowTitle('速度图设置')
        screen = (mw.screen() or QApplication.primaryScreen()).availableGeometry()
        dialog.resize(min(490, screen.width()), min(540, screen.height()))
        layout = QVBoxLayout(dialog)
        intro = QLabel('调整复习速度图')
        intro.setStyleSheet('font-size: 20px; font-weight: 600; margin: 6px 0;')
        layout.addWidget(intro)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        fields = {}
        def tab(title):
            page = QWidget()
            form = QFormLayout(page)
            form.setVerticalSpacing(12)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            tabs.addTab(scroll, title)
            return form
        def numeric(form, title, key, default, low, high, suffix='', decimal=False):
            field = QDoubleSpinBox() if decimal else QSpinBox()
            field.setRange(low, high)
            field.setValue(float(self.config.get(key, default)) if decimal else int(self.config.get(key, default)))
            field.setSuffix(suffix)
            form.addRow(title, field)
            fields[key] = field
        def choice(form, title, key, options, default):
            field = QComboBox()
            for label, value in options:
                field.addItem(label, value)
            field.setCurrentIndex(max(0, field.findData(self.config.get(key, default))))
            form.addRow(title, field)
            fields[key] = field
        def check(form, title, key, default=True):
            field = QCheckBox(title)
            field.setChecked(self.config.get(key, default))
            form.addRow(field)
            fields[key] = field
        pace = tab('速度计算')
        numeric(pace, '目标耗时', 'goal', 10, 1, 300, ' 秒／张', True)
        numeric(pace, '平均窗口', 'window', 20, 5, 100, ' 次作答')
        numeric(pace, '重新计算间隔', 'refresh', 1, 1, 10, ' 秒')
        numeric(pace, '平滑过渡时长', 'transition', 4, 0.5, 15, ' 秒', True)
        numeric(pace, '曲线历史长度', 'history_seconds', 60, 15, 120, ' 秒')
        help_text = QLabel('翻面时停止本张计时；默认统计最近 20 次作答。平滑过渡在所设时间内完成约 95%。')
        help_text.setWordWrap(True)
        pace.addRow(help_text)
        look = tab('外观')
        choice(look, '布局', 'view', [('极简：曲线与圆点', 'minimal'), ('简洁：速度、平均值与目标', 'compact'), ('详细：完整信息', 'full')], 'compact')
        choice(look, '主题', 'theme', [('跟随软件', 'auto'), ('浅色', 'light'), ('深色', 'dark')], 'auto')
        def opacity_slider(title, key, default):
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(self.config.get(key, default)))
            value = QSpinBox()
            value.setRange(0, 100)
            value.setSuffix('%')
            value.setValue(slider.value())
            slider.valueChanged.connect(value.setValue)
            value.valueChanged.connect(slider.setValue)
            box.addWidget(slider)
            box.addWidget(value)
            look.addRow(title, row)
            fields[key] = slider
        opacity_slider('背景不透明度', 'background', 20)
        opacity_slider('文字不透明度', 'foreground', 72)
        opacity_slider('圆点与曲线不透明度', 'graph_opacity', 65)
        numeric(look, '数字字号', 'number_size', 22, 16, 28, ' 像素')
        choice(look, '配色', 'palette', [('柔和青绿／琥珀', 'muted'), ('鲜明青绿／琥珀', 'bright'), ('中性色', 'mono'), ('自定义颜色', 'custom')], 'muted')
        for title, key in [('快于目标时的颜色', 'custom_ahead'), ('慢于目标时的颜色', 'custom_behind'), ('文字颜色', 'custom_text'), ('背景颜色', 'custom_background')]:
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            field = QLineEdit(self.config[key])
            field.setReadOnly(True)
            button = QPushButton('选色…')
            def pick(checked=False, field=field):
                selected = QColorDialog.getColor(QColor(field.text()), dialog, '选择颜色')
                if selected.isValid():
                    field.setText(selected.name())
                    fields['palette'].setCurrentIndex(fields['palette'].findData('custom'))
            button.clicked.connect(pick)
            box.addWidget(field)
            box.addWidget(button)
            look.addRow(title, row)
            fields[key] = field
        check(look, '显示窗口阴影与边缘', 'window_shadow', False)
        check(look, '显示目标虚线', 'goal_line')
        check(look, '显示终点圆点', 'endpoint')
        check(look, '详细布局显示目标、平均值和状态', 'details')
        controls = tab('操作')
        choice(controls, '图上按钮', 'controls', [('悬停时显示', 'hover'), ('始终显示', 'always'), ('隐藏（使用工具菜单）', 'hidden')], 'hover')
        check(controls, '锁定位置与尺寸', 'locked', False)
        size = self.overlay.size()
        numeric(controls, '宽度', 'edit_width', size.width(), 110, 900, ' 像素')
        numeric(controls, '高度', 'edit_height', size.height(), 76, 400, ' 像素')
        recover = QPushButton('将速度图移回当前屏幕')
        controls.addRow(recover)
        recover.clicked.connect(self.recover_position)
        tips = QLabel('右键可打开快捷菜单；工具菜单也可控制显示、隐藏、暂停与继续。隐藏仍会计时，暂停才会停止计时。苹果系统使用对应的命令键。')
        tips.setWordWrap(True)
        controls.addRow(tips)
        preset_row = QHBoxLayout()
        for title, values in [
            ('简洁预设', dict(view='minimal', background=20, foreground=65, graph_opacity=55, palette='muted', controls='hover', number_size=20, edit_width=180, edit_height=86)),
            ('清晰预设', dict(view='compact', background=65, foreground=100, graph_opacity=100, palette='bright', controls='hover', number_size=26, edit_width=220, edit_height=100)),
            ('详细预设', dict(view='full', background=50, foreground=90, graph_opacity=85, palette='muted', controls='always', number_size=24, edit_width=340, edit_height=150)),
        ]:
            button = QPushButton(title)
            preset_row.addWidget(button)
            def set_values(values=values):
                for key, value in values.items():
                    field = fields[key]
                    if isinstance(field, QComboBox):
                        field.setCurrentIndex(field.findData(value))
                    else:
                        field.setValue(value)
            button.clicked.connect(lambda checked=False, fn=set_values: fn())
        layout.addLayout(preset_row)
        row = QHBoxLayout()
        defaults = QPushButton('恢复默认')
        cancel = QPushButton('取消')
        save = QPushButton('保存设置')
        save.setDefault(True)
        for button in (defaults, cancel, save): row.addWidget(button)
        layout.addLayout(row)
        def reset_defaults():
            values = dict(goal=10, window=20, refresh=1, transition=4, history_seconds=60, view='minimal', background=20, foreground=65, graph_opacity=55, theme='auto', number_size=20, palette='muted', goal_line=True, endpoint=True, details=True, window_shadow=False, custom_ahead='#21877b', custom_behind='#b16d32', custom_text='#34454d', custom_background='#f1f4f5', controls='hover', locked=False, edit_width=180, edit_height=86)
            for key, value in values.items():
                field = fields[key]
                if isinstance(field, QComboBox): field.setCurrentIndex(field.findData(value))
                elif isinstance(field, QCheckBox): field.setChecked(value)
                elif isinstance(field, QLineEdit): field.setText(value)
                else: field.setValue(value)
        defaults.clicked.connect(reset_defaults)
        cancel.clicked.connect(dialog.close)
        def apply():
            nonlocal committed
            self.model = original_model
            self.smooth = original_smooth
            old_goal, old_window = self.model.goal, self.model.window
            for key, field in fields.items():
                if isinstance(field, QComboBox): value = field.currentData()
                elif isinstance(field, QCheckBox): value = field.isChecked()
                elif isinstance(field, QLineEdit): value = field.text()
                else: value = field.value()
                if not key.startswith('edit_'): self.config[key] = value
            dimensions = [fields['edit_width'].value(), fields['edit_height'].value()]
            if dimensions != [size.width(), size.height()]:
                self.config[self.overlay.size_key()] = dimensions
            self.overlay.apply_size()
            self.overlay.layout_controls()
            visible = self.config['controls'] == 'always'
            self.overlay.settings.setVisible(visible)
            self.overlay.pause.setVisible(visible)
            self.overlay.hide_button.setVisible(visible)
            self.restore_position()
            self.save()
            # Cosmetic edits preserve study progress.
            if old_goal != self.config['goal'] or old_window != self.config['window']:
                self.model = Pace(self.config['goal'], self.config['window'])
                self.clear_graph()
                if review_is_visible():
                    self.model.question()
                    if getattr(getattr(mw, 'reviewer', None), 'state', '') == 'answer':
                        self.model.current = None
            self.smooth.seconds = self.config['transition']
            self.overlay.layout_controls()
            if review_is_visible() and not self.user_hidden: self.overlay.show()
            committed = True
            dialog.close()
            self.overlay.update()
        save.clicked.connect(apply)
        def preview(*_):
            for key, field in fields.items():
                if isinstance(field, QComboBox): value = field.currentData()
                elif isinstance(field, QCheckBox): value = field.isChecked()
                elif isinstance(field, QLineEdit): value = field.text()
                else: value = field.value()
                if not key.startswith('edit_'): self.config[key] = value
            dimensions = [fields['edit_width'].value(), fields['edit_height'].value()]
            if dimensions != [size.width(), size.height()]:
                self.config[self.overlay.size_key()] = dimensions
            self.model = copy.deepcopy(original_model)
            self.model.goal = self.config['goal']
            self.model.window = self.config['window']
            self.model.answers = deque(list(original_model.answers)[-self.model.window:], maxlen=self.model.window)
            self.smooth = copy.deepcopy(original_smooth)
            self.smooth.seconds = self.config['transition']
            if self.model.average() is not None:
                self.smooth.value = self.model.delta()
            self.overlay.apply_size()
            self.overlay.layout_controls()
            visible = self.config['controls'] == 'always'
            self.overlay.settings.setVisible(visible)
            self.overlay.pause.setVisible(visible)
            self.overlay.hide_button.setVisible(visible)
            self.overlay.show()
            self.overlay.update()
        for field in fields.values():
            if isinstance(field, QComboBox): field.currentIndexChanged.connect(preview)
            elif isinstance(field, QCheckBox): field.toggled.connect(preview)
            elif isinstance(field, QLineEdit): field.textChanged.connect(preview)
            else: field.valueChanged.connect(preview)
        def finished(_):
            if not committed:
                self.config = original_config
                self.model = original_model
                self.smooth = original_smooth
                self.overlay.apply_size()
                self.overlay.setGeometry(original_geometry)
                self.overlay.layout_controls()
                visible = self.config.get('controls') == 'always'
                self.overlay.settings.setVisible(visible)
                self.overlay.pause.setVisible(visible)
                self.overlay.hide_button.setVisible(visible)
                self.overlay.setVisible(original_visible)
                self.overlay.update()
            self.dialog = None
            self.last = time.monotonic()
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.show()


controller = None

def install():
    global controller
    if controller is None:
        controller = Controller()
    return controller
