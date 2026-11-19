import sys
import os
import random
import logging
import time
import math
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from focus_windows import foreground_window, window_monitor, window_pid
from pet_core import (AFFECTION_THRESHOLDS, DAILY_PET_AFFECTION_LIMIT, REWARD_INTERVALS,
                      WORK_AFFECTION_INTERVAL, affection_tier, behavior_weights, read_save, write_save)
import startup_windows
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QMessageBox, QSystemTrayIcon, QCalendarWidget, QComboBox,
    QLineEdit, QDateTimeEdit, QPushButton, QCheckBox, QScrollArea,
    QVBoxLayout, QHBoxLayout, QFrame, QAbstractSpinBox
)

from PyQt6.QtCore import (Qt, QEvent, QTimer, QPoint, QSize, QRect, QDateTime, QLocale,
                          QStandardPaths, QAbstractListModel, QModelIndex)
from PyQt6.QtGui import (QPixmap, QTransform, QCursor, QPainter, QColor, QFont,
                         QPainterPath, QIcon, QPalette, QTextCharFormat)


from PyQt6.QtNetwork import QLocalServer, QLocalSocket

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


LEGACY_DATA_PATH = os.path.join(get_app_dir(), 'pet_data.json')
SAVE_DATA_PATH = os.path.join(QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.GenericDataLocation), 'CuteDesktopPet', 'pet_data.json')
log_path = os.path.join(os.environ.get('TEMP', os.getcwd()), 'CuteDesktopPet.log')


logging.basicConfig(handlers=[RotatingFileHandler(log_path, maxBytes=256 * 1024,
                                                backupCount=1, encoding='utf-8', delay=True)],
                    level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

IDLE_SPEECHES = [
    "你在努力工作吗",
    "注意身体健康喔",
    "赚钱钱，赚钱钱",
    "别太累啦",
    "休息一下喝口水吧",
    "你是最棒的，加油！",
    "今天也要开开心心的呀",
    "累了就靠着我休息一会儿",
    "不管多难，我都会陪着你",
    "你认真工作的样子超可爱",
    "不许熬夜哦，会掉头发",
    "记得按时吃饭，别饿着",
    "伸个懒腰，活动一下脖子",
    "你已经做得很棒啦",
    "抱抱，给你充充电",
    "深呼吸，放松一下心情",
]
MANUAL_GREETING = '我来陪你啦～单击一起玩，双击摸摸头！'
AUTOSTART_GREETING = '电脑醒啦，葡萄冻冻也醒啦！今天也陪你一起开机～'
AFFECTION_LINES = (
    ('嘿嘿，好舒服～', '今天也一起玩吧。'),
    ('能和你待在一起，我好开心呀。', '你来摸头啦，我等你好久了～'),
    ('哥哥，今天也想跟你坐在一起～', '哥哥的手好暖，再摸一下嘛。'),
    ('哥哥，哥哥好棒～', '哥哥累啦？我给你留了个位置。'),
    ('今天最开心的事，就是哥哥来陪我。', '哥哥认真起来的时候，特别好看。'),
    ('哥哥好腻害，给哥哥一个亲亲～', '哥哥，今天的抱抱可以久一点吗？'),
    ('哥哥忙完就来找我吧，我想听听你今天的故事。', '我把今天的好心情留了一半给哥哥。'),
    ('每次哥哥打开电脑，我都想第一个跟你打招呼。', '哥哥，累了就靠过来，我陪你慢慢歇。'),
    ('哥哥的手一伸过来，我就忍不住笑啦。', '哥哥，今天不管顺不顺利，都有我陪你。'),
    ('哥哥，我喜欢我们一起度过的每个普通日子。', '给哥哥一个抱抱，再偷偷给你一个亲亲～'),
    ('哥哥，谢谢你一直把葡萄冻冻带在身边。今天也最喜欢你啦～', '哥哥，四千个小爱心都送给你，再附赠一个亲亲～'),
)

SATIETY_MAX = 100
SATIETY_DECAY_PER_HOUR = 4
CANDY_AMOUNT = 2
BURGER_AMOUNT = 20
CAKE_AMOUNT = 50


def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class TodoCalendar(QCalendarWidget):
    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if hasattr(self, 'navigation'):
            bar_size = self.navigation.sizeHint()
            size.setWidth(max(size.width(), bar_size.width()))
            size.setHeight(size.height() + bar_size.height())
        return size


class CalendarYears(QAbstractListModel):
    def __init__(self, first, last, parent):
        super().__init__(parent)
        self.first = first
        self.count = last - first + 1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.count

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return str(self.first + index.row())
        return None


def todo_calendar(minimum_date, maximum_date):
    calendar = TodoCalendar()
    calendar.setDateRange(minimum_date, maximum_date)
    calendar.setNavigationBarVisible(False)
    calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
    calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

    navigation = QWidget(calendar)
    calendar.navigation = navigation
    navigation.setObjectName('todoCalendarNavigation')
    row = QHBoxLayout(navigation)
    row.setContentsMargins(4, 2, 4, 2)
    row.setSpacing(4)
    previous = QPushButton('‹', navigation)
    following = QPushButton('›', navigation)
    previous.setToolTip('上个月')
    following.setToolTip('下个月')
    for button in (previous, following):
        button.setFixedWidth(26)
    previous.clicked.connect(calendar.showPreviousMonth)
    following.clicked.connect(calendar.showNextMonth)

    month = QComboBox(navigation)
    month.setObjectName('todoCalendarMonth')
    month.setToolTip('选择月份')
    month.setMinimumWidth(72)
    month.addItems([calendar.locale().standaloneMonthName(i, QLocale.FormatType.LongFormat)
                    for i in range(1, 13)])
    year = QComboBox(navigation)
    year.setObjectName('todoCalendarYear')
    year.setToolTip('选择年份')
    year.setMinimumWidth(60)
    first_year, last_year = minimum_date.year(), maximum_date.year()
    year.setModel(CalendarYears(first_year, last_year, year))
    year.setMinimumContentsLength(4)
    year.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    for selector in (month, year):
        selector.setMaxVisibleItems(12)

    def update_navigation(shown_year, shown_month):
        month.setCurrentIndex(shown_month - 1)
        year.setCurrentIndex(shown_year - first_year)
        previous.setEnabled((shown_year, shown_month) > (first_year, minimum_date.month()))
        following.setEnabled((shown_year, shown_month) < (last_year, maximum_date.month()))

    def go_to(selected_year, selected_month):
        earliest = minimum_date.month() if selected_year == first_year else 1
        latest = maximum_date.month() if selected_year == last_year else 12
        calendar.setCurrentPage(selected_year, max(earliest, min(selected_month, latest)))
        update_navigation(calendar.yearShown(), calendar.monthShown())

    month.activated.connect(lambda index: go_to(calendar.yearShown(), index + 1))
    year.activated.connect(lambda index: go_to(first_year + index, calendar.monthShown()))
    calendar.currentPageChanged.connect(update_navigation)
    update_navigation(calendar.yearShown(), calendar.monthShown())
    row.addWidget(previous)
    row.addStretch()
    row.addWidget(month)
    row.addWidget(year)
    row.addStretch()
    row.addWidget(following)
    calendar.layout().insertWidget(0, navigation)

    palette = calendar.palette()
    for role, color in {
        QPalette.ColorRole.Window: '#f4effc', QPalette.ColorRole.Base: '#ffffff',
        QPalette.ColorRole.AlternateBase: '#f8f5fc', QPalette.ColorRole.Text: '#4a3a6a',
        QPalette.ColorRole.Button: '#f4effc',
        QPalette.ColorRole.WindowText: '#4a3a6a', QPalette.ColorRole.ButtonText: '#4a3a6a',
        QPalette.ColorRole.Highlight: '#7444aa', QPalette.ColorRole.HighlightedText: '#ffffff',
    }.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#746788'))
    calendar.setPalette(palette)
    header = QTextCharFormat()
    header.setBackground(QColor('#f4effc'))
    header.setForeground(QColor('#4a3a6a'))
    calendar.setHeaderTextFormat(header)
    weekend = QTextCharFormat()
    weekend.setForeground(QColor('#9b3768'))
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        calendar.setWeekdayTextFormat(day, weekend)
    calendar.setStyleSheet('''
        QWidget#todoCalendarNavigation { background: #e6daf7; }
        QWidget#todoCalendarNavigation QPushButton, QWidget#todoCalendarNavigation QComboBox {
            color: #392752; background: #e6daf7; border: 0; border-radius: 4px; padding: 3px 7px;
        }
        QWidget#todoCalendarNavigation QPushButton:hover, QWidget#todoCalendarNavigation QComboBox:hover {
            background: #d6c4ee;
        }
        QWidget#todoCalendarNavigation QPushButton:disabled { color: #847799; }
        QWidget#todoCalendarNavigation QComboBox { combobox-popup: 0; }
        QWidget#todoCalendarNavigation QComboBox::drop-down { width: 0; border: 0; }
        QWidget#todoCalendarNavigation QComboBox::down-arrow { image: none; width: 0; height: 0; }
        QCalendarWidget QAbstractItemView {
            color: #4a3a6a; background: #ffffff;
            selection-color: #ffffff; selection-background-color: #7444aa;
        }
    ''')
    return calendar


class PetMenu(QMenu):
    """Keep Qt's hover behavior and let a click close the open submenu."""

    def __init__(self, parent):
        super().__init__(parent)
        self.pressed_submenu = None
        self.collapsed_action = None
        self.installEventFilter(self)

    def add_toggleable_submenu(self, title):
        submenu = self.addMenu(title)
        submenu.installEventFilter(self)
        return submenu

    def eventFilter(self, receiver, event):
        kind = event.type()
        mouse = QEvent.Type
        if kind not in (mouse.MouseMove, mouse.MouseButtonPress,
                        mouse.MouseButtonDblClick, mouse.MouseButtonRelease):
            return super().eventFilter(receiver, event)

        # The open child can own the mouse grab and receive both events for
        # a click whose screen position is over a row in the parent menu.
        point = event.globalPosition().toPoint()
        inside_child = receiver is not self and receiver.rect().contains(receiver.mapFromGlobal(point))
        action = None if inside_child else self.actionAt(self.mapFromGlobal(point))
        if kind == mouse.MouseMove:
            if self.pressed_submenu or (self.collapsed_action and action == self.collapsed_action):
                return True
            self.collapsed_action = None
        elif event.button() == Qt.MouseButton.LeftButton:
            if kind in (mouse.MouseButtonPress, mouse.MouseButtonDblClick):
                self.collapsed_action = None
                if action and action.isEnabled() and action.menu():
                    # Capture the intent now: Qt's hover timers may still
                    # open or close the child before this click is released.
                    self.pressed_submenu = action, not action.menu().isVisible()
                    return True
            elif self.pressed_submenu:
                pressed, should_open = self.pressed_submenu
                self.pressed_submenu = None
                if action == pressed:
                    if not should_open:
                        self.collapsed_action = pressed
                        self.setActiveAction(None)
                        pressed.menu().hide()
                    elif not pressed.menu().isVisible():
                        self.setActiveAction(None)
                        self.setActiveAction(pressed)
                return True
        return super().eventFilter(receiver, event)

    def hideEvent(self, event):
        self.pressed_submenu = self.collapsed_action = None
        super().hideEvent(event)


class SpeechBubble(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(320)
        self.label.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(255, 255, 255, 240);"
            "  border: 2px solid #b39ddb;"
            "  border-radius: 16px;"
            "  padding: 8px 18px;"
            "  color: #4a3a6a;"
            "  font-size: 15px;"
            "  font-weight: bold;"
            "}"
        )
        self.label.adjustSize()
        self.setFixedSize(self.label.size())
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_text(self, text, center_x, top_y, duration=3000):
        self.label.setText(text)
        self.label.adjustSize()
        w = self.label.width()
        h = self.label.height()
        self.setFixedSize(w, h)
        self.label.setGeometry(0, 0, w, h)
        screen = QApplication.screenAt(QPoint(center_x, top_y)) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(center_x - w // 2, bounds.right() - w + 1))
        y = top_y - h - 5
        if y < bounds.top():
            y = top_y + 35
        y = max(bounds.top(), min(y, bounds.bottom() - h + 1))
        self.move(x, y)
        self.show()
        self.raise_()
        self.hide_timer.start(duration)


class TodoItemWidget(QWidget):
    """Widget representing a single todo item with checkbox, text, time badge, and delete button."""
    def __init__(self, item_data, on_complete, on_delete):
        super().__init__()
        self.item_data = item_data
        self.on_complete = on_complete
        self.on_delete = on_delete

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(item_data.get('completed', False))
        self.checkbox.stateChanged.connect(self._handle_check)
        layout.addWidget(self.checkbox)

        # Text and Time layout
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.text_label = QLabel(item_data.get('text', ''))
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        self.text_label.setStyleSheet("color: #4a3a6a; font-size: 11px; font-weight: bold;")
        text_layout.addWidget(self.text_label)

        due_at = item_data.get('due_at')
        target_time = QDateTime.fromSecsSinceEpoch(int(due_at)).toString('yyyy-MM-dd HH:mm') if due_at is not None else ''
        if target_time:
            time_label = QLabel(f"⏰ 截止 {target_time}")
            time_label.setStyleSheet("color: #8870b0; font-size: 9px;")
            text_layout.addWidget(time_label)

        layout.addLayout(text_layout, 1)

        # Delete button
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(18, 18)
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #b0a0cc;
                font-weight: bold;
                border: none;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #e57373;
            }
        """)
        del_btn.clicked.connect(lambda: self.on_delete(self.item_data))
        layout.addWidget(del_btn)

        self._update_style()

    def _update_style(self):
        if self.checkbox.isChecked():
            self.text_label.setStyleSheet("color: #a090c0; font-size: 11px; font-weight: bold; text-decoration: line-through;")
        else:
            self.text_label.setStyleSheet("color: #4a3a6a; font-size: 11px; font-weight: bold;")


    def _handle_check(self, state):
        is_checked = (state == Qt.CheckState.Checked.value or state == 2 or state == True)
        self.item_data['completed'] = is_checked
        self._update_style()
        self.on_complete(self.item_data, is_checked)


class TodoPanel(QWidget):
    """Floating scrollable todo list panel."""
    PANEL_W = 300
    PANEL_H = 280

    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.PANEL_W, self.PANEL_H)

        self._close_btn_rect = QRect(self.PANEL_W - 28, 8, 18, 18)

        # Main Layout container for widgets
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 28, 10, 10)
        main_layout.setSpacing(8)

        # Input Box
        input_box = QWidget()
        input_box.setStyleSheet("background: rgba(245, 240, 255, 220); border-radius: 8px;")
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(6, 6, 6, 6)
        input_layout.setSpacing(6)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("添加新待办...")
        self.input_edit.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #c7b8ea;
                border-radius: 6px;
                padding: 3px 6px;
                color: #4a3a6a;
                font-size: 11px;
            }
        """)
        input_layout.addWidget(self.input_edit)

        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        
        time_label = QLabel("预计完成:")
        time_label.setStyleSheet("color: #6a5a8a; font-size: 11px;")
        time_row.addWidget(time_label)

        self.time_edit = QDateTimeEdit()
        self.time_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.time_edit.setCalendarPopup(True)
        self.time_edit.setCalendarWidget(todo_calendar(self.time_edit.minimumDate(), self.time_edit.maximumDate()))
        self.time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.time_edit.setStyleSheet("""
            QDateTimeEdit {
                background: #ffffff;
                border: 1px solid #c7b8ea;
                border-radius: 5px;
                padding: 2px 6px;
                color: #4a3a6a;
                font-size: 11px;
            }
        """)
        time_row.addWidget(self.time_edit, 1)

        add_btn = QPushButton("添加")
        add_btn.setFixedSize(42, 22)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #9c27b0;
                color: #ffffff;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ab47bc;
            }
        """)
        add_btn.clicked.connect(self.add_todo)
        time_row.addWidget(add_btn)

        input_layout.addLayout(time_row)
        main_layout.addWidget(input_box)

        # Scroll Area for Todo Items
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(220, 210, 240, 100);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #b39ddb;
                border-radius: 3px;
            }
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.items_layout = QVBoxLayout(self.scroll_content)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(6)
        self.items_layout.addStretch()

        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area, 1)

        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self._close_btn_rect.contains(pos):
                self.pet.toggle_todo_panel()
                return
        super().mousePressEvent(event)


    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded background
        path = QPainterPath()
        path.addRoundedRect(6, 6, self.PANEL_W - 12, self.PANEL_H - 12, 12, 12)
        p.fillPath(path, QColor(255, 255, 255, 240))

        # Border
        pen = p.pen()
        pen.setColor(QColor(179, 157, 219))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawPath(path)

        # Title
        p.setPen(QColor(74, 58, 106))
        font_title = QFont('Microsoft YaHei', 11, QFont.Weight.Bold)
        p.setFont(font_title)
        p.drawText(QRect(0, 8, self.PANEL_W, 22), Qt.AlignmentFlag.AlignCenter, '📝 待办清单')

        # Close button '✕'
        p.setPen(QColor(160, 140, 190))
        font_close = QFont('Microsoft YaHei', 10, QFont.Weight.Bold)
        p.setFont(font_close)
        p.drawText(self._close_btn_rect, Qt.AlignmentFlag.AlignCenter, '✕')
        p.end()

    def refresh_items(self):
        while self.items_layout.count() > 0:
            child = self.items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for item_data in self.pet.todo_list:
            item_widget = TodoItemWidget(item_data, self.on_item_completed, self.on_item_deleted)
            item_widget.setStyleSheet("background: rgba(248, 245, 255, 220); border-radius: 6px;")
            self.items_layout.addWidget(item_widget)

        self.items_layout.addStretch()

    def add_todo(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        deadline = self.time_edit.dateTime().toSecsSinceEpoch()
        deadline = deadline - deadline % 60 + 59
        item_data = {
            'id': uuid.uuid4().hex,
            'text': text,
            'due_at': deadline,
            'completed': False,
            'reward_claimed': False,
        }
        self.pet.todo_list.append(item_data)
        self.input_edit.clear()
        self.time_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.refresh_items()
        self.pet.save_data()
        self.pet.refresh_panel()

    def on_item_completed(self, item_data, is_completed):
        item_data['completed'] = is_completed
        if is_completed:
            deadline = item_data.get('due_at')
            if not item_data.get('reward_claimed', False) and deadline is not None and time.time() <= deadline:
                item_data['reward_claimed'] = True
                self.pet.candy_count += 1
                self.pet.show_speech("准时完成待办！🍬 获得1颗糖果！", 3000)
            else:
                self.pet.show_speech("太棒啦，又完成了一项待办！💪", 2500)
        self.pet.save_data()
        self.pet.refresh_panel()


    def on_item_deleted(self, item_data):
        self.pet.todo_list = [i for i in self.pet.todo_list if i.get('id') != item_data.get('id')]
        self.refresh_items()
        self.pet.save_data()
        self.pet.refresh_panel()


class StatusPanel(QWidget):
    """Status panel that shows food counts, satiety, work duration, todo count, and allows feeding."""

    PANEL_W = 180
    PANEL_H = 200

    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.PANEL_W, self.PANEL_H)

        self.candy_count = 0
        self.burger_count = 0
        self.cake_count = 0
        self.satiety = SATIETY_MAX
        self.working = False
        self.work_elapsed = 0
        self.todo_count = 0
        self._displayed = None

        # Clickable row rectangles
        self._row_rects = {}
        self._close_btn_rect = QRect(self.PANEL_W - 32, 6, 18, 18)
        self._todo_rect = QRect(14, 130, self.PANEL_W - 28, 16)
        self.hide()

    def update_data(self, candy, burger, cake, satiety, working, work_elapsed, todo_count=0):
        displayed = (candy, burger, cake, round(satiety, 1), working,
                     int(work_elapsed // 60) if working else 0, todo_count, self.pet.affection)
        if displayed == self._displayed:
            return
        self._displayed = displayed
        self.candy_count = candy
        self.burger_count = burger
        self.cake_count = cake
        self.satiety = satiety
        self.working = working
        self.work_elapsed = work_elapsed
        self.todo_count = todo_count
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self._close_btn_rect.contains(pos):
                self.pet.toggle_panel()
                return
            if hasattr(self, '_todo_rect') and self._todo_rect.contains(pos):
                self.pet.toggle_todo_panel()
                return
            for food, rect in self._row_rects.items():
                if rect.contains(pos):
                    self.pet.feed_food(food)
                    return
        super().mousePressEvent(event)


    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._row_rects = {}

        # Rounded background
        path = QPainterPath()
        path.addRoundedRect(6, 6, self.PANEL_W - 12, self.PANEL_H - 12, 11, 11)
        p.fillPath(path, QColor(255, 255, 255, 230))

        # Border
        pen = p.pen()
        pen.setColor(QColor(179, 157, 219))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawPath(path)

        font_title = QFont('Microsoft YaHei', 10, QFont.Weight.Bold)
        font_item = QFont('Microsoft YaHei', 8)
        font_small = QFont('Microsoft YaHei', 8)
        font_emoji = QFont('Segoe UI Emoji', 11)
        font_feed = QFont('Microsoft YaHei', 7, QFont.Weight.Bold)

        # Title
        p.setPen(QColor(74, 58, 106))
        p.setFont(font_title)
        p.drawText(QRect(0, 6, self.PANEL_W, 18), Qt.AlignmentFlag.AlignCenter, '📋 状态栏')

        # Close button '✕'
        p.setPen(QColor(160, 140, 190))
        font_close = QFont('Microsoft YaHei', 9, QFont.Weight.Bold)
        p.setFont(font_close)
        p.drawText(self._close_btn_rect, Qt.AlignmentFlag.AlignCenter, '✕')

        y = 28
        row_h = 21
        pad = 14
        btn_w = 26
        btn_h = 16

        foods = [
            ('candy', '🍬', '糖果', self.candy_count, CANDY_AMOUNT),
            ('burger', '🍔', '汉堡', self.burger_count, BURGER_AMOUNT),
            ('cake', '🎂', '蛋糕', self.cake_count, CAKE_AMOUNT),
        ]

        for food_key, emoji, name, count, gain in foods:
            p.setFont(font_emoji)
            p.drawText(pad, y + 14, emoji)
            p.setFont(font_item)
            p.setPen(QColor(74, 58, 106))
            p.drawText(pad + 18, y + 14, f'{name}×{count} (+{gain})')
            bx = self.PANEL_W - pad - btn_w
            by = y + 2
            btn_rect = QRect(bx, by, btn_w, btn_h)
            self._row_rects[food_key] = btn_rect
            can_feed = count > 0 and self.satiety < SATIETY_MAX
            btn_color = QColor(200, 170, 230) if can_feed else QColor(210, 210, 210)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(btn_color)
            p.drawRoundedRect(btn_rect, 4, 4)
            p.setPen(QColor(255, 255, 255) if can_feed else QColor(170, 170, 170))
            p.setFont(font_feed)
            p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, '喂')
            y += row_h

        y += 2
        p.setPen(QColor(200, 180, 220))
        p.drawLine(pad, y, self.PANEL_W - pad, y)
        y += 5

        p.setPen(QColor(74, 58, 106))
        p.setFont(font_small)
        p.drawText(pad, y + 9, f'饱食度: {self.satiety:.1f}/{SATIETY_MAX}')
        y += 15

        bar_x = pad
        bar_y = y
        bar_w = self.PANEL_W - pad * 2
        bar_h = 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(220, 220, 230))
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

        ratio = max(0.0, min(1.0, self.satiety / SATIETY_MAX))
        if ratio > 0.5:
            fill_color = QColor(150, 210, 130)
        elif ratio > 0.2:
            fill_color = QColor(250, 200, 90)
        else:
            fill_color = QColor(230, 120, 120)
        p.setBrush(fill_color)
        p.drawRoundedRect(bar_x, bar_y, int(bar_w * ratio), bar_h, 4, 4)

        p.setBrush(Qt.BrushStyle.NoBrush)
        pen.setColor(QColor(179, 157, 219))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

        y += bar_h + 4

        # 待办事项数量行 (插入在饱食度与工作时间之间)
        p.setPen(QColor(74, 58, 106))
        p.setFont(font_small)
        self._todo_rect = QRect(pad, y, self.PANEL_W - pad * 2, 16)
        p.drawText(pad, y + 11, f'📝 待办事项: {self.todo_count} 项')

        y += 17

        # 工作时间
        p.setPen(QColor(74, 58, 106))
        p.setFont(font_small)
        if self.working:
            h = int(self.work_elapsed // 3600)
            m = int((self.work_elapsed % 3600) // 60)
            work_text = f'💼 工作{h}时{m}分'
        else:
            work_text = '💼 未工作'
        p.drawText(pad, y + 10, work_text)

        p.setPen(QColor(150, 100, 155))
        p.drawText(pad, y + 30, f'♥ 亲密度 {self.pet.affection} · {affection_tier(self.pet.affection)} 阶')

        p.end()




class DesktopPet(QWidget):
    def __init__(self, *, autostart=False):
        super().__init__()
        logging.info('DesktopPet init')
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)

        self.pet_size = QSize(200, 200)
        self.setFixedSize(self.pet_size)

        self.compute_screen_bounds()

        primary = QApplication.primaryScreen().availableGeometry()
        # A new companion sits near the taskbar; returning pets remember their spot.
        start_x = max(primary.left(), primary.right() - self.pet_size.width() - 48)
        start_y = max(primary.top(), primary.bottom() - self.pet_size.height() + 1)
        self.move(start_x, start_y)
        self.saved_start = QPoint(start_x, start_y)

        self.label = QLabel(self)
        self.label.setFixedSize(self.pet_size)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAutoFillBackground(False)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.todo_list = []
        self.bubble = SpeechBubble()
        self.status_panel = StatusPanel(self)
        self.panel_visible = False
        self.todo_panel = TodoPanel(self)
        self.todo_panel_visible = False
        self.load_frames()

        self.state = 'idle'
        self.frame_index = 0
        self.facing_right = True
        self.drag_offset = None
        self.last_drag_pos = None
        self.press_pos = None
        self._double_click = False
        self.last_pet_time = -100.0
        self.heart_until = 0.0
        self.recent_behavior = None
        self.actions_this_round = set()
        self.affection = 0
        self.quiet_mode = False
        self.last_snack_date = ''
        self.saved_position = None
        self._render_key = None
        self.ground_y = start_y

        self.pos_f = [float(start_x), float(start_y)]
        self.vx = 0.0
        self.vy = 0.0
        self.run_speed = 4.0
        self.jump_strength = -14.0
        self.gravity = 0.8
        self.target_x = None
        self.walk_target = None
        self.walk_speed = 0.0
        self.chase_until = 0.0
        self.focus_target = None
        self.focus_screen = None
        self.focus_bind_at = None
        self.focus_away_at = None
        self.focus_warned = False
        self.focus_knock_at = None
        self.last_checkpoint = time.monotonic()
        self.dance_timer = 0
        self.playful_eat_timer = 0
        self.eat_timer = 0
        self.playful_sleep_timer = 0
        self.playful_wave_timer = 0
        self.bounce_started_at = 0.0
        self.playful_bounce_base_y = 0
        self.last_night_speech_time = 0
        self.stretch_step = 0

        # Hunger / work system

        self.satiety = SATIETY_MAX
        self.candy_count = 0
        self.burger_count = 0
        self.cake_count = 0
        self.working = False
        self.work_start_time = 0
        self.work_session_seconds = 0.0
        self.work_total_seconds = 0.0
        self.work_last_tick = time.monotonic()
        self.reward_marks = dict.fromkeys(REWARD_INTERVALS, 0)
        self.next_stretch_seconds = 45 * 60
        self.last_satiety_check = time.monotonic()
        self.load_data()
        if self.saved_position:
            point = self.clamp_position(QPoint(*map(int, self.saved_position)))
            self.move(point)
            self.pos_f = [float(point.x()), float(point.y())]
            self.ground_y = point.y()

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.next_frame)
        self.anim_last_tick = time.monotonic()

        self.physics_timer = QTimer(self)
        self.physics_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.physics_timer.timeout.connect(self.update_physics)
        self.physics_last_tick = time.monotonic()

        self.stretch_timer = QTimer(self)
        self.stretch_timer.setSingleShot(True)
        self.stretch_timer.timeout.connect(self.advance_stretch)

        self.behavior_timer = QTimer(self)
        self.behavior_timer.setSingleShot(True)
        self.behavior_timer.timeout.connect(self.behavior_tick)
        self.behavior_timer.start(random.randint(25, 50) * 1000)

        self.satiety_timer = QTimer(self)
        self.satiety_timer.timeout.connect(self.check_satiety)
        self.satiety_timer.start(10000)

        self.panel_refresh_timer = QTimer(self)
        self.panel_refresh_timer.timeout.connect(self.refresh_panel)
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(100)
        self.resize_timer.timeout.connect(self.finish_resize)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.play_with_pet)
        self.speech_timer = QTimer(self)
        self.speech_timer.setSingleShot(True)
        self.speech_timer.timeout.connect(self.random_speech)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(
            lambda: self.show_speech(AUTOSTART_GREETING if autostart else MANUAL_GREETING, 4500, ambient=True))
        self.focus_timer = QTimer(self)
        self.focus_timer.setInterval(300)
        self.focus_timer.timeout.connect(self.check_focus)

        app = QApplication.instance()
        app.screenAdded.connect(self.on_screens_changed)
        app.screenRemoved.connect(self.on_screens_changed)
        self.on_screens_changed()

        self.schedule_next_speech()
        self.update_image()

        # startup speeches
        self.startup_timer.start(500)

    def save_data(self):
        self.settle_work()
        data = {
            'version': 3,
            'satiety': round(self.satiety, 2),
            'candy_count': self.candy_count,
            'burger_count': self.burger_count,
            'cake_count': self.cake_count,
            'todo_list': self.todo_list,
            'working': self.working,
            'work_start_time': self.work_start_time,
            'work_session_seconds': self.work_session_seconds,
            'work_total_seconds': self.work_total_seconds,
            'reward_marks': self.reward_marks,
            'affection': self.affection,
            'pet_affection_date': self.pet_affection_date,
            'pet_affection_today': self.pet_affection_today,
            'work_affection_claimed': self.work_affection_claimed,
            'quiet_mode': self.quiet_mode,
            'auto_chase': self.auto_chase,
            'auto_nap': self.auto_nap,
            'last_snack_date': self.last_snack_date,
            'pet_size': self.pet_size.width(),
            'position': [self.x(), self.y()],
            'last_save_time': time.time(),
        }
        try:
            write_save(SAVE_DATA_PATH, data)
            self.last_checkpoint = time.monotonic()
        except Exception as e:
            logging.error(f'Failed to save pet data: {e}')

    def load_data(self):
        data, errors = read_save(SAVE_DATA_PATH, LEGACY_DATA_PATH, time.time())
        for error in errors:
            logging.warning('Save recovery: %s', error)
        for key in ('satiety', 'candy_count', 'burger_count', 'cake_count', 'todo_list',
                    'affection', 'quiet_mode', 'auto_chase', 'auto_nap', 'last_snack_date', 'working', 'work_session_seconds',
                    'work_total_seconds', 'reward_marks', 'pet_affection_date', 'pet_affection_today',
                    'work_affection_claimed'):
            setattr(self, key, data[key])
        self.next_stretch_seconds = (int(self.work_session_seconds // 2700) + 1) * 2700
        self.work_start_time = time.time() if self.working else 0
        self.saved_position = data['position']
        if data['pet_size'] != self.pet_size.width():
            self.pet_size = QSize(data['pet_size'], data['pet_size'])
            self.setFixedSize(self.pet_size)
            self.label.setFixedSize(self.pet_size)
            self.load_frames()
        self.todo_panel.refresh_items()
        self.settle_work()


    def force_show(self, *, activate=True):
        logging.info('force_show called')
        self.show()
        self.showNormal()
        self.raise_()
        if activate and not self.focus_timer.isActive():
            self.activateWindow()
        point = self.clamp_position(self.pos())
        self.move(point)
        self.pos_f = [float(point.x()), float(point.y())]
        self.ground_y = point.y()
        logging.info(f'Window geometry: {self.geometry()}')

    def compute_screen_bounds(self):
        screens = QApplication.screens()
        min_x = min(s.availableGeometry().left() for s in screens)
        min_y = min(s.availableGeometry().top() for s in screens)
        max_x = max(s.availableGeometry().right() for s in screens)
        max_y = max(s.availableGeometry().bottom() for s in screens)
        self.screen_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        logging.info(f'Virtual screen rect: {self.screen_rect}')

    def current_bounds(self):
        center = self.geometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = min(QApplication.screens(), key=lambda s:
                         (s.availableGeometry().center() - center).manhattanLength())
        return screen.availableGeometry()

    def clamp_position(self, point, size=None):
        size = size or self.pet_size
        center = point + QPoint(size.width() // 2, size.height() // 2)
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = min(QApplication.screens(), key=lambda s:
                         (s.availableGeometry().center() - center).manhattanLength())
        return self.clamp_to_bounds(point, screen.availableGeometry(), size)

    @staticmethod
    def clamp_to_bounds(point, bounds, size):
        return QPoint(max(bounds.left(), min(point.x(), bounds.right() - size.width() + 1)),
                      max(bounds.top(), min(point.y(), bounds.bottom() - size.height() + 1)))

    def on_screens_changed(self, *_):
        self.compute_screen_bounds()
        for screen in QApplication.screens():
            if screen not in getattr(self, '_watched_screens', []):
                screen.availableGeometryChanged.connect(self.on_screens_changed)
        self._watched_screens = QApplication.screens()
        point = self.clamp_position(self.pos())
        self.move(point)
        self.pos_f = [float(point.x()), float(point.y())]
        self.ground_y = point.y()
        if self.focus_target:
            self.sleep_in_corner()
        elif self.state in ('walk', 'chase'):
            self.start_idle()
        if self.state in ('run', 'jump', 'fall'):
            self.start_idle()
        self.update_panel_position()

    def load_frames(self):
        self._render_key = None
        self.frame_cache = {}
        sleep_path = resource_path('assets/processed/sleep.png')
        if not os.path.exists(sleep_path):
            sleep_path = resource_path('assets/sleep.png')

        pajamas_path = resource_path('assets/processed/pajamas.png')
        if not os.path.exists(pajamas_path):
            pajamas_path = sleep_path

        stretch_1 = resource_path('assets/processed/stretch_1.png')
        stretch_2 = resource_path('assets/processed/stretch_2.png')
        stretch_3 = resource_path('assets/processed/stretch_3.png')
        stretch_4 = resource_path('assets/processed/stretch_4.png')
        stretch_5 = resource_path('assets/processed/stretch_5.png')
        stretch_6 = resource_path('assets/processed/stretch_6.png')

        self.raw_frames = {
            'idle': [resource_path('assets/processed/idle_0.png')],
            'run': [resource_path('assets/processed/run_0.png'),
                    resource_path('assets/processed/run_1.png')],
            'jump': [resource_path('assets/processed/jump_0.png')],
            'dance': [resource_path('assets/processed/dance_0.png'),
                      resource_path('assets/processed/dance_1.png')],
            'sleep': [sleep_path],
            'pajamas': [pajamas_path],
            'stretch_night': [stretch_1, stretch_2, stretch_3],
            'stretch_day': [stretch_4, stretch_5, stretch_6],
        }

        self.pixmaps = {}
        for state, paths in self.raw_frames.items():
            self.pixmaps[state] = []
            for p in paths:
                source = QPixmap(p)
                if not source.isNull():
                    pm = source.scaled(
                        self.pet_size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.pixmaps[state].append(pm)
                else:
                    logging.warning(f'missing asset: {p}')
        # A missing optional animation must never cause division by zero.
        if not self.pixmaps['idle']:
            fallback = QPixmap(self.pet_size)
            fallback.fill(Qt.GlobalColor.transparent)
            painter = QPainter(fallback)
            painter.setPen(QColor('#b39ddb'))
            painter.setFont(QFont('Segoe UI Emoji', 48))
            painter.drawText(fallback.rect(), Qt.AlignmentFlag.AlignCenter, '♥')
            painter.end()
            self.pixmaps['idle'] = [fallback]
        for key, frames in self.pixmaps.items():
            if not frames:
                self.pixmaps[key] = self.pixmaps['idle']

    def current_pixmap(self):
        # Being picked up is distinct from running around on her own.
        # Playful/hungry/eat states reuse idle animation with overlays.
        if self.state == 'drag':
            img_state = 'idle'
        elif self.state in ('playful_sleep', 'sleeping', 'focus_sleep'):
            img_state = 'sleep' if 'sleep' in self.pixmaps and self.pixmaps['sleep'] else 'idle'
        elif self.state == 'pajamas':
            img_state = 'pajamas' if 'pajamas' in self.pixmaps and self.pixmaps['pajamas'] else 'idle'
        elif self.state == 'stretch':
            ch = datetime.now().hour
            is_night = (ch >= 23 or ch < 5)
            s_key = 'stretch_night' if is_night else 'stretch_day'
            img_state = s_key if s_key in self.pixmaps and self.pixmaps[s_key] else 'idle'
        elif self.state == 'hungry':
            img_state = 'sleep' if 'sleep' in self.pixmaps and self.pixmaps['sleep'] else 'idle'
        elif self.state in ('playful_look', 'playful_eat', 'eat', 'playful_wave', 'petted'):
            img_state = 'idle'
        elif self.state in ('walk', 'chase'):
            img_state = 'run'
        elif self.state in ('playful_bounce', 'focus_knock'):
            img_state = 'jump'
        else:
            img_state = self.state
        if img_state == 'idle' and (datetime.now().hour >= 23 or datetime.now().hour < 5):
            img_state = 'pajamas'
        pms = self.pixmaps.get(img_state, self.pixmaps['idle'])
        if not pms:
            pms = self.pixmaps['idle']

        if self.state == 'stretch':
            idx = min(self.stretch_step, len(pms) - 1)
        else:
            idx = self.frame_index % len(pms)
        flipped = self.facing_right ^ (self.state == 'dance' and self.dance_timer >= 1500)
        overlay = self.state if self.state in ('eat', 'playful_eat', 'playful_wave', 'petted', 'focus_knock') else ''
        heart_phase = min(4, int(max(0, self.heart_until - time.monotonic()) * 3)) if overlay == 'petted' else 0
        knock_phase = self.frame_index % 4 if overlay == 'focus_knock' else 0
        key = (img_state, idx, flipped, overlay, heart_phase, knock_phase)
        if key in self.frame_cache:
            return self.frame_cache[key]
        if len(self.frame_cache) >= 32:
            del self.frame_cache[next(iter(self.frame_cache))]
        pm = pms[idx]
        if flipped:
            pm = pm.transformed(QTransform().scale(-1, 1))

        if not overlay:
            self.frame_cache[key] = pm
            return pm

        result = QPixmap(pm.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, pm)

        if self.state in ('playful_eat', 'eat'):
            # Draw a little snack near the mouth area.
            painter.setBrush(QColor(255, 180, 80))
            painter.setPen(Qt.PenStyle.NoPen)
            offset = 25 if self.facing_right else -25
            cx = result.width() // 2 + offset
            cy = result.height() // 2 + 15
            painter.drawEllipse(cx - 10, cy - 10, 20, 20)
            painter.setBrush(QColor(255, 220, 150))
            painter.drawEllipse(cx - 6, cy - 6, 12, 12)
        elif self.state == 'playful_wave':

            # Waving hand overlay.
            painter.setPen(QColor(255, 160, 180))
            painter.setBrush(QColor(255, 160, 180))
            offset = 35 if self.facing_right else -35
            cx = result.width() // 2 + offset
            cy = result.height() // 2 - 25
            painter.drawEllipse(cx - 8, cy - 8, 16, 16)

        elif self.state == 'petted':
            painter.setPen(QColor(238, 119, 160, 80 + heart_phase * 35))
            painter.setFont(QFont('Segoe UI Symbol', max(12, self.pet_size.width() // 9)))
            painter.drawText(result.width() * 2 // 3, result.height() // 5 - (4 - heart_phase) * 3, '♥')
            painter.setFont(QFont('Segoe UI Symbol', max(9, self.pet_size.width() // 14)))
            painter.drawText(result.width() // 5, result.height() // 3 - (4 - heart_phase) * 2, '♥')

        elif overlay == 'focus_knock':
            painter.setPen(QColor(158, 95, 212, 240 - knock_phase * 45))
            x = result.width() * (4 if self.facing_right else 1) // 5
            y = result.height() // 3
            radius = max(4, result.width() * (knock_phase + 2) // 45)
            painter.drawEllipse(QPoint(x, y), radius, radius)
            painter.drawEllipse(QPoint(x, y), radius + 5, radius + 5)

        painter.end()
        self.frame_cache[key] = result
        return result


    def update_image(self):
        self.sync_activity_timers()
        pixmap = self.current_pixmap()
        if pixmap.cacheKey() != self._render_key:
            self.label.setPixmap(pixmap)
            self._render_key = pixmap.cacheKey()

    def sync_activity_timers(self):
        if self.state != 'stretch':
            self.stretch_timer.stop()
        moving = self.state in ('run', 'walk', 'chase', 'jump', 'fall', 'playful_bounce')
        animated = self.state in ('run', 'walk', 'chase', 'focus_knock', 'dance', 'playful_look', 'playful_eat',
                                  'eat', 'playful_sleep', 'playful_wave', 'petted')
        for timer, active, interval, clock_attr in (
                (self.physics_timer, moving, 16, 'physics_last_tick'),
                (self.anim_timer, animated, 130, 'anim_last_tick')):
            if active and not timer.isActive():
                setattr(self, clock_attr, time.monotonic())
                timer.start(interval)
            elif not active:
                timer.stop()

    def next_frame(self):
        now = time.monotonic()
        elapsed = min(250, max(0, (now - self.anim_last_tick) * 1000))
        self.anim_last_tick = now
        if self.state in ('run', 'walk', 'chase'):
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['run'])
        elif self.state == 'focus_knock':
            self.frame_index += 1
        elif self.state == 'dance':
            self.dance_timer += elapsed
            if self.dance_timer >= 3000:
                self.start_idle()
                return
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['dance'])
        elif self.state == 'playful_look':
            self.frame_index += 1
            # Flip direction every ~0.8 s to mimic looking around.
            self.facing_right = (self.frame_index // 6) % 2 == 0
            if self.frame_index >= 24:  # ~3 s
                self.start_idle()
                return
        elif self.state == 'playful_eat':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            self.playful_eat_timer += elapsed
            if self.playful_eat_timer >= 4000:
                self.start_idle()
                return
        elif self.state == 'eat':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            self.eat_timer += elapsed
            if self.eat_timer >= 3000:
                self.start_idle()
                return
        elif self.state == 'hungry':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
        elif self.state == 'playful_sleep':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            self.playful_sleep_timer += elapsed
            if self.playful_sleep_timer >= 5000:
                self.start_idle()
                return
        elif self.state == 'playful_wave':
            self.playful_wave_timer += elapsed
            self.facing_right = int(self.playful_wave_timer // 520) % 2 == 0
            if self.playful_wave_timer >= 2600:
                self.start_idle()
                return
        elif self.state == 'petted':
            if now >= self.heart_until:
                self.start_idle()
                return
        else:
            self.frame_index = 0
        self.update_image()

    def show_speech(self, text, duration=3000, ambient=False):
        if ambient and (self.quiet_mode or self.state == 'sleeping' or self.focus_timer.isActive()):
            return
        cx = int(self.pos_f[0]) + self.pet_size.width() // 2
        ty = int(self.pos_f[1])
        self.bubble.show_text(text, cx, ty, duration)
        logging.info(f'Speech: {text}')

    def schedule_next_speech(self):
        interval = random.randint(120000, 300000)
        self.speech_timer.start(interval)

    def random_speech(self):
        if self.state not in ('drag', 'hungry', 'sleeping', 'petted') and self.satiety > 0:
            tier = affection_tier(self.affection)
            lines = AFFECTION_LINES[tier] if random.random() < tier * 0.06 else IDLE_SPEECHES
            text = random.choice(lines)
            self.show_speech(text, 3500, ambient=True)
        self.schedule_next_speech()

    def behavior_tick(self):
        self.behavior_timer.start(random.randint(25, 50) * 1000)
        self.decide_behavior()

    def decide_behavior(self):
        if (self.press_pos is not None or self.click_timer.isActive() or self.focus_timer.isActive()
                or QApplication.activePopupWidget()):
            return
        # Don't interrupt active movement, stretching, or short animations.
        if self.state in ('drag', 'jump', 'fall', 'run', 'walk', 'chase', 'stretch',
                          'playful_look', 'playful_eat', 'eat',
                          'playful_sleep', 'playful_wave', 'playful_bounce', 'petted', 'sleeping'):
            return

        if self.satiety <= 0 and not self.working:
            if self.state != 'hungry':
                self.start_hungry()
            return


        # Check late night mode (>= 23:00 or < 05:00)
        current_hour = datetime.now().hour
        if current_hour >= 23 or current_hour < 5:
            now = time.time()
            if now - self.last_night_speech_time >= 1800:
                self.last_night_speech_time = now
                self.show_speech('夜深啦，我会轻轻地陪着你，记得早点休息～', 4000, ambient=True)
            self.state = 'pajamas'
            self.update_image()
            return

        if self.state == 'pajamas':
            self.start_idle()
        if self.quiet_mode:
            return
        weights = behavior_weights(self.satiety, self.affection, self.working, self.recent_behavior)
        if not self.auto_chase:
            weights['chase'] = 0
        if not self.auto_nap:
            weights['sleep'] = 0
        eligible = {name: weight for name, weight in weights.items() if weight > 0}
        remaining = [name for name in eligible if name not in self.actions_this_round]
        if not remaining:
            self.actions_this_round.clear()
            remaining = [name for name in eligible if name != self.recent_behavior] or list(eligible)
        action = random.choices(remaining, weights=[eligible[name] for name in remaining], k=1)[0]
        self.actions_this_round.add(action)
        self.recent_behavior = action
        {'look': self.start_playful_look, 'wave': self.start_playful_wave, 'sleep': self.start_playful_sleep,
         'dance': self.start_dance, 'bounce': self.start_playful_bounce,
         'chase': self.start_playful_chase, 'wander': self.start_wander,
         'stretch': lambda: self.start_stretch(remind=False)}[action]()

    def play_with_pet(self):
        if self.state == 'drag':
            return
        self.start_idle()
        if self.satiety <= 0:
            self.start_playful_wave()
        else:
            self.start_playful_bounce()
        self.show_speech('一起玩！接住我的开心～', 2400)

    def pet_head(self):
        now = time.monotonic()
        if self.state == 'drag':
            return
        if self.state == 'playful_bounce':
            self.pos_f[1] = float(self.playful_bounce_base_y)
            self.move(int(self.pos_f[0]), int(self.pos_f[1]))
        today = datetime.now().date().isoformat()
        if self.pet_affection_date != today:
            self.pet_affection_date = today
            self.pet_affection_today = 0
        earned = self.pet_affection_today < DAILY_PET_AFFECTION_LIMIT and now - self.last_pet_time >= 5
        if earned:
            self.affection += 1
            self.pet_affection_today += 1
            self.last_pet_time = now
        self.state = 'petted'
        self.vx = self.vy = 0.0
        self.ground_y = int(self.pos_f[1])
        self.heart_until = now + 1.6
        self.frame_index = 0
        self.update_image()
        self.show_speech(random.choice(AFFECTION_LINES[affection_tier(self.affection)]), 2400)
        if earned:
            self.save_data()
        self.refresh_panel()

    def toggle_quiet(self):
        self.quiet_mode = not self.quiet_mode
        if self.quiet_mode:
            self.start_idle()
            self.bubble.hide()
        self.show_speech('我会安静地陪着你。' if self.quiet_mode else '可以一起玩啦～', 2200)
        self.save_data()
        self.refresh_panel()

    def toggle_nap(self):
        if self.state == 'sleeping':
            self.start_idle()
            self.show_speech('睡醒啦～又是元气满满的一天！', 2400)
        else:
            self.state = 'sleeping'
            self.vx = self.vy = 0.0
            self.update_image()
            self.show_speech('我在这里眯一会儿，摸摸头就能叫醒我。', 3000)

    def daily_snack(self):
        today = datetime.now().date().isoformat()
        if self.last_snack_date == today:
            self.show_speech('今天的零食已经收好啦，明天还有喔。', 2400)
            return
        self.last_snack_date = today
        self.burger_count += 2
        self.candy_count += 3
        self.show_speech('今日零食：汉堡×2、糖果×3！一起慢慢享用～', 3000)
        self.save_data()
        self.refresh_panel()

    def start_idle(self):
        self.state = 'idle'
        self.vx = 0.0
        self.vy = 0.0
        self.target_x = None
        self.walk_target = None
        self.frame_index = 0
        self.update_image()

    def start_run(self):
        if self.state == 'drag' or self.satiety <= 0:
            if self.satiety <= 0:
                self.start_hungry()
            return
        self.state = 'run'
        margin = self.pet_size.width() // 2
        bounds = self.current_bounds()
        max_x = bounds.right() - self.pet_size.width() + 1
        lo = bounds.left() + margin
        hi = max(lo, max_x - margin)
        self.target_x = random.randint(lo, hi)
        dx = self.target_x - self.pos_f[0]
        self.facing_right = dx >= 0
        self.vx = self.run_speed if self.facing_right else -self.run_speed
        self.vy = 0.0
        self.update_image()

    def start_jump(self):
        if self.state == 'drag' or self.satiety <= 0:
            if self.satiety <= 0:
                self.start_hungry()
            return
        self.state = 'jump'
        self.vy = self.jump_strength
        bounds = self.current_bounds()
        max_x = bounds.right() - self.pet_size.width() + 1
        lo = bounds.left()
        hi = max(lo, max_x)
        self.target_x = random.randint(lo, hi)
        dx = self.target_x - self.pos_f[0]
        self.facing_right = dx >= 0
        self.vx = (self.run_speed * 0.6) if self.facing_right else (-self.run_speed * 0.6)
        self.update_image()

    def start_dance(self):
        if self.state == 'drag' or self.satiety <= 0:
            if self.satiety <= 0:
                self.start_hungry()
            return
        self.state = 'dance'
        self.vx = 0.0
        self.vy = 0.0
        self.dance_timer = 0
        self.frame_index = 0
        self.update_image()

    def start_stretch(self, *, remind=True):
        """Stretch 1-2-3 sequence with 1 second interval between frames."""
        self.state = 'stretch'
        self.stretch_step = 0
        self.vx = 0.0
        self.vy = 0.0
        if remind:
            self.show_speech('站起来活动一下脖子、喝口水吧~', 4500)
        self.update_image()
        self.stretch_timer.start(1000)


    def advance_stretch(self):
        if self.state != 'stretch':
            return
        if self.stretch_step >= 2:
            self.start_idle()
            return
        self.stretch_step += 1
        self.update_image()
        self.stretch_timer.start(2000 if self.stretch_step == 2 else 1000)


    def start_playful_look(self):
        self.state = 'playful_look'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.update_image()

    def start_playful_eat(self):
        self.state = 'playful_eat'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.playful_eat_timer = 0
        self.update_image()

    def start_playful_chase(self):
        """Follow the live cursor in both axes for a short burst."""
        if self.focus_timer.isActive() or self.state == 'drag':
            return
        self.chase_until = time.monotonic() + 8
        self.begin_walk(self.cursor_destination(), 'chase')

    def cursor_destination(self):
        return self.destination_at(QCursor.pos())

    def destination_at(self, point, screen=None):
        half = QPoint(self.width() // 2, self.height() // 2)
        if screen is not None:
            return self.clamp_to_bounds(point - half, screen.availableGeometry(), self.pet_size)
        return self.clamp_position(point - half)

    def start_wander(self):
        bounds = self.current_bounds()
        offset = QPoint(random.randint(-260, 260), random.randint(-140, 140))
        self.begin_walk(self.clamp_to_bounds(self.pos() + offset, bounds, self.pet_size))

    def begin_walk(self, target, state='walk'):
        self.state = state
        self.walk_target = target
        self.walk_speed = 0.0
        self.frame_index = 0
        self.update_image()

    def update_walk(self, now, dt):
        if self.state == 'chase':
            if now >= self.chase_until:
                self.start_idle()
                return
            self.walk_target = self.cursor_destination()
        target = self.walk_target
        dx, dy = target.x() - self.pos_f[0], target.y() - self.pos_f[1]
        distance = math.hypot(dx, dy)
        if distance <= 2:
            self.pos_f = [float(target.x()), float(target.y())]
            self.move(target)
            self.ground_y = target.y()
            self.update_panel_position()
            if self.focus_target:
                self.start_focus_knock(now)
            else:
                self.start_idle()
            return
        max_speed = 840 if self.focus_target else 640 if self.state == 'chase' else 155
        desired_speed = min(max_speed, max(45, distance * 6))
        self.walk_speed += (desired_speed - self.walk_speed) * min(1, dt * 12)
        step = min(distance, self.walk_speed * dt)
        self.pos_f[0] += step * dx / distance
        self.pos_f[1] += step * dy / distance
        if abs(dx) > 6 and self.facing_right != (dx > 0):
            self.facing_right = dx > 0
            self.update_image()
        point = QPoint(round(self.pos_f[0]), round(self.pos_f[1]))
        if point != self.pos():
            self.move(point)
            self.update_panel_position()

    def start_playful_sleep(self):
        self.state = 'playful_sleep'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.playful_sleep_timer = 0
        self.update_image()

    def toggle_focus(self):
        if self.focus_timer.isActive():
            self.stop_focus('专注结束，休息一下吧～')
            return
        if sys.platform != 'win32':
            self.show_speech('专注模式目前支持 Windows。')
            return
        self.click_timer.stop()
        self.start_idle()
        self.focus_bind_at = time.monotonic() + 3
        self.focus_timer.start()
        self.show_speech('请在 3 秒内切到要专注的窗口。', 3000)

    def stop_focus(self, message):
        self.focus_timer.stop()
        self.focus_target = self.focus_screen = None
        self.focus_bind_at = self.focus_away_at = self.focus_knock_at = None
        self.focus_warned = False
        point = self.clamp_position(self.pos())
        self.move(point)
        self.pos_f = [float(point.x()), float(point.y())]
        self.ground_y = point.y()
        self.start_idle()
        self.update_panel_position()
        self.show_speech(message)

    def sleep_in_corner(self):
        screens = QApplication.screens()
        if self.focus_screen not in screens:
            self.focus_screen = QApplication.primaryScreen()
        bounds = self.focus_screen.availableGeometry()
        point = self.clamp_to_bounds(bounds.bottomRight() - QPoint(self.width() + 12, self.height() + 12),
                                     bounds, self.pet_size)
        self.move(point)
        self.pos_f = [float(point.x()), float(point.y())]
        self.ground_y = point.y()
        self.state = 'focus_sleep'
        self.frame_index = 0
        self.bubble.hide()
        self.update_image()
        self.update_panel_position()

    def start_focus_knock(self, now):
        self.focus_knock_at = now
        self.state = 'focus_knock'
        self.frame_index = 0
        self.update_image()
        self.show_speech('咚咚！回来继续专注吧～', 2500)

    @staticmethod
    def screen_for_window(handle):
        device = window_monitor(handle)
        return next((screen for screen in QApplication.screens() if screen.name() == device), None)

    def check_focus(self):
        now = time.monotonic()
        if self.focus_bind_at is not None and now < self.focus_bind_at:
            return
        foreground = foreground_window()
        if self.focus_bind_at is not None:
            self.focus_bind_at = None
            if foreground is None or foreground[2]:
                self.stop_focus('没有选中工作窗口，请重新开启专注。')
                return
            self.focus_target = foreground[:2]
            self.focus_screen = (self.screen_for_window(foreground[0])
                                 or QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen())
            self.sleep_in_corner()
            return

        handle, pid = self.focus_target
        if window_pid(handle) != pid:
            self.stop_focus('专注窗口已关闭。')
            return
        if foreground and foreground[:2] == self.focus_target:
            self.focus_away_at = self.focus_knock_at = None
            self.focus_warned = False
            if self.state != 'focus_sleep':
                self.sleep_in_corner()
            return
        if self.focus_warned:
            if self.focus_knock_at is not None and now - self.focus_knock_at >= 2.5:
                self.focus_knock_at = None
                self.sleep_in_corner()
            return
        if foreground is None:
            self.focus_away_at = None
        elif self.focus_away_at is None:
            self.focus_away_at = now
        elif now - self.focus_away_at >= 2:
            self.focus_warned = True
            screen = self.screen_for_window(foreground[0])
            pointer = QCursor.pos()
            if screen and not screen.geometry().contains(pointer):
                pointer = screen.availableGeometry().center()
            self.begin_walk(self.destination_at(pointer, screen))

    def start_playful_wave(self):
        self.state = 'playful_wave'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.playful_wave_timer = 0
        self.update_image()

    def start_playful_bounce(self):
        if self.satiety <= 0:
            self.start_hungry()
            return
        self.state = 'playful_bounce'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.bounce_started_at = time.monotonic()
        self.playful_bounce_base_y = int(self.pos_f[1])
        self.update_image()

    def start_eat(self):
        self.state = 'eat'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.eat_timer = 0
        self.update_image()

    def start_hungry(self, force=False):
        if self.working and not force:
            return
        self.state = 'hungry'
        self.working = False
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.update_image()
        self.show_speech('我饿了，快喂我吃东西...', 3000)


    def update_panel_position(self):
        if not self.panel_visible and not self.todo_panel_visible:
            return
        bounds = self.current_bounds()
        px, py = self.x(), self.y()
        occupied = [self.geometry()]
        for panel, visible, prefer_left in ((self.status_panel, self.panel_visible, False),
                                            (self.todo_panel, self.todo_panel_visible, True)):
            if not visible:
                continue
            right = px + self.pet_size.width() + 10
            left = px - panel.width() - 10
            y = max(bounds.top(), min(py, bounds.bottom() - panel.height() + 1))
            candidates = [(left, y), (right, y)] if prefer_left else [(right, y), (left, y)]
            candidates += [(min(r.left() for r in occupied) - panel.width() - 10, y),
                           (max(r.right() for r in occupied) + 11, y),
                           (px, py - panel.height() - 10), (px, py + self.height() + 10)]
            rects = [QRect(max(bounds.left(), min(x, bounds.right() - panel.width() + 1)),
                           max(bounds.top(), min(top, bounds.bottom() - panel.height() + 1)),
                           panel.width(), panel.height()) for x, top in candidates]
            chosen = next((r for r in rects if all(not r.intersects(other) for other in occupied)), rects[0])
            panel.move(chosen.topLeft())
            occupied.append(chosen)

    def settle_work(self):
        now = time.monotonic()
        elapsed = max(0, now - self.work_last_tick)
        self.work_last_tick = now
        # A suspended computer is not an active work session.
        if self.working and elapsed <= 60:
            self.work_session_seconds += elapsed
            self.work_total_seconds += elapsed
        due = int(self.work_total_seconds // WORK_AFFECTION_INTERVAL)
        earned = max(0, due - self.work_affection_claimed)
        if earned:
            self.work_affection_claimed += earned
            self.affection += earned
        return earned

    def get_work_elapsed(self):
        extra = max(0, time.monotonic() - self.work_last_tick) if self.working else 0
        return self.work_session_seconds + (extra if extra <= 60 else 0)

    def grant_work_rewards(self):
        earned = []
        for key, interval in REWARD_INTERVALS.items():
            due = int(self.work_total_seconds // interval)
            count = max(0, due - self.reward_marks[key])
            if count:
                setattr(self, key + '_count', getattr(self, key + '_count') + count)
                self.reward_marks[key] = due
                earned.append(f"{ {'candy': '糖果', 'burger': '汉堡', 'cake': '蛋糕'}[key]}×{count}")
        if earned:
            self.show_speech('陪伴工作奖励：' + '、'.join(earned), 3000, ambient=True)
        return bool(earned)

    def refresh_panel(self):
        tip = (f'葡萄冻冻 · 亲密度 {self.affection} · {affection_tier(self.affection)} 阶\n'
               '单击玩耍 · 双击摸头 · 按住拖动搬家 · 右键菜单')
        if self.toolTip() != tip:
            self.setToolTip(tip)
        if self.panel_visible and self.working:
            if not self.panel_refresh_timer.isActive():
                self.panel_refresh_timer.start(1000)
        else:
            self.panel_refresh_timer.stop()
        if not self.panel_visible:
            return
        uncompleted_count = sum(1 for item in self.todo_list if not item.get('completed', False))
        elapsed = self.get_work_elapsed()
        self.status_panel.update_data(
            self.candy_count,
            self.burger_count,
            self.cake_count,
            self.satiety,
            self.working,
            elapsed,
            uncompleted_count,
        )


    def toggle_panel(self):
        self.panel_visible = not self.panel_visible
        if self.panel_visible:
            self.refresh_panel()
            self.update_panel_position()
            self.status_panel.show()
            self.status_panel.raise_()
        else:
            self.status_panel.hide()
            self.panel_refresh_timer.stop()

    def toggle_todo_panel(self):
        self.todo_panel_visible = not self.todo_panel_visible
        if self.todo_panel_visible:
            self.update_panel_position()
            self.todo_panel.show()
            self.todo_panel.raise_()
        else:
            self.todo_panel.hide()

    def feed_food(self, food_key):
        """Feed the pet with a specific food from inventory."""
        if self.satiety >= SATIETY_MAX:
            self.show_speech('我已经吃饱啦', 2000)
            return
        food_map = {
            'candy': ('糖果', CANDY_AMOUNT, 'candy_count'),
            'burger': ('汉堡', BURGER_AMOUNT, 'burger_count'),
            'cake': ('蛋糕', CAKE_AMOUNT, 'cake_count'),
        }
        if food_key not in food_map:
            return
        name, amount, count_attr = food_map[food_key]
        if getattr(self, count_attr) <= 0:
            self.show_speech(f'没有{name}了，先去工作赚一点吧~', 2000)
            return
        setattr(self, count_attr, getattr(self, count_attr) - 1)
        self.satiety = min(SATIETY_MAX, self.satiety + amount)
        if not self.focus_timer.isActive():
            self.start_eat()
        self.show_speech(f'吃了一个{name}！+{amount}饱食度', 1800)
        self.save_data()
        self.refresh_panel()

    def start_work(self):
        if self.working:
            return
        self.working = True
        self.work_start_time = time.time()
        self.work_session_seconds = 0.0
        self.work_last_tick = time.monotonic()
        self.next_stretch_seconds = 45 * 60
        if not self.focus_timer.isActive():
            self.start_idle()
        self.show_speech('我会陪你一起努力，休息后零食进度也会保留喔。', 3000)
        self.save_data()
        self.refresh_panel()


    def end_work(self):
        if not self.working:
            return
        self.settle_work()
        self.grant_work_rewards()
        elapsed = self.work_session_seconds
        self.working = False
        self.work_start_time = 0
        h, m = int(elapsed // 3600), int(elapsed % 3600 // 60)
        self.show_speech(f'辛苦啦！陪你工作了{h}小时{m}分钟，休息一下吧～', 3000)
        self.save_data()
        self.refresh_panel()




    def check_satiety(self):
        now = time.monotonic()
        elapsed = max(0, now - self.last_satiety_check)
        self.last_satiety_check = now
        rate = 2 if self.state in ('sleeping', 'playful_sleep', 'pajamas', 'focus_sleep') else SATIETY_DECAY_PER_HOUR
        self.satiety = max(0, self.satiety - min(20, elapsed * rate / 3600))
        earned_affection = self.settle_work()
        earned = False
        if self.working:
            earned = self.grant_work_rewards()
            if self.work_session_seconds >= self.next_stretch_seconds:
                busy = self.state in ('drag', 'jump', 'run', 'fall', 'stretch', 'eat', 'petted')
                if not busy:
                    self.next_stretch_seconds = (int(self.work_session_seconds // 2700) + 1) * 2700
                    if not self.quiet_mode and not self.focus_timer.isActive() and self.state != 'sleeping':
                        self.start_stretch()
        elif self.satiety <= 0 and not self.focus_timer.isActive() and self.state in ('idle', 'pajamas'):
            self.start_hungry()
        if earned or earned_affection or now - self.last_checkpoint >= 60:
            self.save_data()
        self.refresh_panel()



    def update_physics(self):
        now = time.monotonic()
        dt = min(0.05, max(0, now - self.physics_last_tick))
        self.physics_last_tick = now
        if self.state in ('walk', 'chase'):
            self.update_walk(now, dt)
            return
        # Preserve existing motion tuning while accounting for delayed callbacks.
        steps = dt / 0.016
        if self.state == 'playful_bounce':
            phase = max(0.0, now - self.bounce_started_at)
            if phase >= 3:
                self.pos_f[1] = float(self.playful_bounce_base_y)
                self.ground_y = self.playful_bounce_base_y
                self.move(round(self.pos_f[0]), self.ground_y)
                self.start_idle()
                self.update_panel_position()
                return
            hop = 15 * abs(math.sin(phase * math.pi * 2))
            self.pos_f[1] = self.playful_bounce_base_y - hop
        elif self.state in ('jump', 'fall'):
            self.pos_f[1] += self.vy * steps + 0.5 * self.gravity * steps * steps
            self.vy += self.gravity * steps
            self.pos_f[0] += self.vx * steps
            if self.pos_f[1] >= self.ground_y:
                self.pos_f[1] = float(self.ground_y)
                self.move(int(self.pos_f[0]), int(self.pos_f[1]))
                self.start_idle()
                self.update_panel_position()
                return
        elif self.state == 'run':
            self.pos_f[0] += self.vx * steps
            if (self.vx > 0 and self.pos_f[0] >= self.target_x) or (self.vx < 0 and self.pos_f[0] <= self.target_x):
                self.pos_f[0] = float(self.target_x)
                self.move(int(self.pos_f[0]), int(self.pos_f[1]))
                self.start_idle()
                self.update_panel_position()
                return
        else:
            self.physics_timer.stop()
            return
        point = self.clamp_position(QPoint(int(self.pos_f[0]), int(self.pos_f[1])))
        if point.x() != int(self.pos_f[0]):
            self.vx = -self.vx
            self.facing_right = self.vx >= 0
        # Keep fractional coordinates unless a screen edge actually clamps them.
        if point.x() != int(self.pos_f[0]):
            self.pos_f[0] = float(point.x())
        if point.y() != int(self.pos_f[1]):
            self.pos_f[1] = float(point.y())
        if point != self.pos():
            self.move(point)
            self.update_panel_position()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.focus_timer.isActive():
                event.accept()
                return
            self.click_timer.stop()
            # Stop autonomous motion before deciding between a click and a drag.
            if self.state == 'playful_bounce':
                self.pos_f[1] = float(self.playful_bounce_base_y)
                self.move(int(self.pos_f[0]), int(self.pos_f[1]))
            self.start_idle()
            self.press_pos = event.globalPosition().toPoint()
            self.last_drag_pos = self.press_pos
            self.drag_offset = self.press_pos - self.pos()
            self._double_click = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.click_timer.stop()
            self.show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        # Hover/synthetic moves after a lost release must never start a drag.
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self.drag_offset = self.press_pos = self.last_drag_pos = None
            self.unsetCursor()
            if self.state == 'drag':
                self.start_idle()
            return
        if self.drag_offset is None or self.press_pos is None:
            return
        current_pos = event.globalPosition().toPoint()
        if self.state != 'drag':
            delta = current_pos - self.press_pos
            threshold = max(12, QApplication.startDragDistance())
            if delta.x() ** 2 + delta.y() ** 2 < threshold ** 2:
                return
            self.state = 'drag'
            self.vx = self.vy = 0.0
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            self.bubble.hide()
        dx = current_pos.x() - self.last_drag_pos.x()
        if abs(dx) > 1:
            self.facing_right = dx > 0
        self.last_drag_pos = current_pos
        point = self.clamp_position(current_pos - self.drag_offset)
        self.move(point)
        self.pos_f = [float(point.x()), float(point.y())]
        self.ground_y = point.y()
        self.update_image()
        self.update_panel_position()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_dragging = self.state == 'drag'
        had_press = self.press_pos is not None
        self.drag_offset = self.press_pos = self.last_drag_pos = None
        self.unsetCursor()
        if was_dragging:
            self.start_idle()
            self.save_data()
        elif had_press and not self._double_click:
            self.click_timer.start(QApplication.doubleClickInterval())
        self._double_click = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.focus_timer.isActive():
                event.accept()
                return
            self.click_timer.stop()
            self._double_click = True
            self.drag_offset = self.press_pos = self.last_drag_pos = None
            self.pet_head()
            event.accept()

    def closeEvent(self, event):
        self.shutdown()
        event.accept()
        # Closing the pet window should always terminate the whole application.
        app = QApplication.instance()
        if app:
            app.quit()

    def shutdown(self):
        if getattr(self, '_shutting_down', False):
            return
        self._shutting_down = True
        self.save_data()
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.bubble.hide_timer.stop()
        self.bubble.close()
        self.status_panel.close()
        self.todo_panel.close()

    def toggle_auto_setting(self, name):
        setattr(self, name, not getattr(self, name))
        self.save_data()

    def startup_enabled(self):
        try:
            return startup_windows.registered_command() is not None
        except OSError as error:
            logging.warning('Could not read startup setting: %s', error)
            return False

    def toggle_startup(self):
        try:
            enabled = startup_windows.registered_command() is None
            startup_windows.set_enabled(enabled)
        except OSError as error:
            logging.warning('Could not change startup setting: %s', error)
            self.show_speech('开机自启动设置失败，请稍后重试。', 3500)
            return
        self.show_speech('下次登录 Windows，我就在这里等你～' if enabled else '已关闭开机自启动。', 3500)

    def show_affection_help(self):
        tier = affection_tier(self.affection)
        next_level = (f'下一阶还差 {AFFECTION_THRESHOLDS[tier] - self.affection} 点。'
                      if tier < len(AFFECTION_THRESHOLDS) else '已解锁全部十阶台词。')
        today = datetime.now().date().isoformat()
        earned = self.pet_affection_today if self.pet_affection_date == today else 0
        thresholds = '、'.join(map(str, AFFECTION_THRESHOLDS))
        QMessageBox.information(self, '亲密度说明',
            f'当前 {self.affection} 点 · 第 {tier} 阶。{next_level}\n\n'
            f'摸头每日最多 +{DAILY_PET_AFFECTION_LIMIT}，今天已获得 {earned} 点。\n'
            '工作模式每累计 2 小时 +1，跨次保留，没有每日上限。\n\n'
            f'十阶门槛：{thresholds}。\n阶数越高，解锁的台词越亲密。')

    def create_menu(self, *, from_tray=False):
        menu = PetMenu(self)

        def add(parent, label, callback, *, enabled=None, checked=None):
            action = parent.addAction(label() if callable(label) else label)
            action.triggered.connect(lambda: callback())
            if checked is not None:
                action.setCheckable(True)

            def refresh():
                if callable(label):
                    action.setText(label())
                if enabled is not None:
                    action.setEnabled(enabled())
                if checked is not None:
                    action.setChecked(checked())

            refresh()
            parent.aboutToShow.connect(refresh)
            return action

        def can_interrupt():
            return not self.focus_timer.isActive()

        if from_tray:
            add(menu, '显示桌宠', self.force_show)
        interaction = menu.add_toggleable_submenu('互动')
        add(interaction, '摸摸头 ♥', self.pet_head, enabled=can_interrupt)
        add(interaction, '领取今日零食', self.daily_snack)
        interaction.addSeparator()
        add(interaction, '追鼠标', self.start_playful_chase, enabled=can_interrupt)
        add(interaction, lambda: '叫醒她' if self.state == 'sleeping' else '睡一会儿',
            self.toggle_nap, enabled=can_interrupt)
        add(interaction, '伸懒腰', self.start_stretch, enabled=can_interrupt)
        add(interaction, '跳跃', self.start_jump, enabled=can_interrupt)
        add(interaction, '跳舞', self.start_dance, enabled=can_interrupt)
        menu.addSeparator()
        add(menu, lambda: '结束工作' if self.working else '开始工作', self.toggle_work)
        add(menu, lambda: '关闭状态栏' if self.panel_visible else '打开状态栏', self.toggle_panel)
        add(menu, lambda: '关闭待办清单' if self.todo_panel_visible else '打开待办清单', self.toggle_todo_panel)
        add(menu, lambda: '结束专注模式' if self.focus_timer.isActive() else '开启专注模式', self.toggle_focus)
        menu.addSeparator()
        settings = menu.add_toggleable_submenu('设置')
        add(settings, '安静陪伴', self.toggle_quiet, enabled=can_interrupt, checked=lambda: self.quiet_mode)
        add(settings, '自动追鼠标', lambda: self.toggle_auto_setting('auto_chase'), checked=lambda: self.auto_chase)
        add(settings, '自动小睡', lambda: self.toggle_auto_setting('auto_nap'), checked=lambda: self.auto_nap)
        add(settings, '开机自启动', self.toggle_startup, enabled=lambda: sys.platform == 'win32',
            checked=self.startup_enabled)
        settings.addSeparator()
        add(settings, '亲密度说明', self.show_affection_help)
        add(menu, '退出', self.close)
        return menu

    def show_context_menu(self, pos):
        menu = self.create_menu()
        menu.exec(pos)
        menu.deleteLater()



    def toggle_work(self):
        if self.working:
            self.end_work()
        else:
            self.start_work()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        step = 10 if delta > 0 else -10
        new_w = max(80, min(400, self.pet_size.width() + step))
        if new_w == self.pet_size.width():
            return
        self.pet_size = QSize(new_w, new_w)
        self.setFixedSize(self.pet_size)
        self.label.setFixedSize(self.pet_size)
        self.label.setScaledContents(True)
        self.resize_timer.start()

    def finish_resize(self):
        self.load_frames()
        self.label.setScaledContents(False)
        self.update_image()
        self.on_screens_changed()
        self.save_data()


SINGLETON_NAME = 'CuteDesktopPetSingletonLock'


def handle_new_connection(server, pet):
    while server.hasPendingConnections():
        client = server.nextPendingConnection()
        watch_local_client(client, pet)


def watch_local_client(client, pet):
    client.setReadBufferSize(4)
    timeout = QTimer(client)
    timeout.setSingleShot(True)
    timeout.timeout.connect(client.deleteLater)
    client.disconnected.connect(client.deleteLater)

    def receive():
        if client.bytesAvailable() >= 4:
            if client.read(4) == b'SHOW':
                pet.force_show()
            client.deleteLater()

    client.readyRead.connect(receive)
    timeout.start(500)
    receive()


def cleanup(local_server, tray):
    logging.info('Application cleanup')
    if tray is not None:
        tray.hide()
    local_server.close()
    QLocalServer.removeServer(SINGLETON_NAME)


def create_desktop_shortcut():
    """Automatically create/update desktop shortcut with 葡萄冻冻.ico."""
    try:
        if sys.platform != 'win32':
            return
        import winreg, subprocess, shutil
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
        desktop_path, _ = winreg.QueryValueEx(key, 'Desktop')
        desktop_path = os.path.expandvars(desktop_path)
        
        shortcut_path = os.path.join(desktop_path, '葡萄冻冻.lnk')
        
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
            exe_dir = os.path.dirname(exe_path)
        else:
            exe_path = os.path.abspath(sys.argv[0])
            exe_dir = os.path.dirname(exe_path)
            
        dest_icon = os.path.join(exe_dir, '葡萄冻冻.ico')
        src_ico = resource_path('assets/葡萄冻冻.ico')
        if not os.path.exists(src_ico):
            src_ico = resource_path('assets/app_icon.ico')
            
        if os.path.exists(src_ico):
            try:
                shutil.copy2(src_ico, dest_icon)
            except Exception:
                pass

        if os.path.exists(dest_icon):
            icon_path = dest_icon
        elif os.path.exists(src_ico):
            icon_path = src_ico
        else:
            icon_path = exe_path
            
        ps_code = f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{shortcut_path}'); $s.TargetPath='{exe_path}'; $s.WorkingDirectory='{exe_dir}'; $s.IconLocation='{icon_path},0'; $s.Description='葡萄冻冻桌面宠物'; $s.Save()"
        subprocess.run(['powershell', '-NoProfile', '-Command', ps_code], capture_output=True, creationflags=0x08000000)
        logging.info(f"Verified desktop shortcut at: {shortcut_path} with icon: {icon_path}")
    except Exception as e:
        logging.error(f"Failed to create desktop shortcut: {e}")


def main():
    if sys.argv[1:] == ['--smoke-test']:
        app = QApplication(sys.argv[:1])
        window = QWidget()
        window.winId()  # Load the Windows Qt platform plugin and create a native window.
        pixmap = QPixmap(resource_path('assets/processed/idle_0.png'))
        sys.exit(1 if pixmap.isNull() else 0)

    autostart = startup_windows.STARTUP_ARGUMENT in sys.argv[1:]
    logging.info('Application starting (autostart=%s)', autostart)

    app = QApplication(sys.argv)
    # When the pet window closes, the whole application must quit.
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName('CuteDesktopPet')

    # Singleton: if another instance is running, tell it to show and exit.
    probe = QLocalSocket()
    probe.connectToServer(SINGLETON_NAME)
    if probe.waitForConnected(500):
        if not autostart:
            probe.write(b'SHOW')
            probe.flush()
            probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        probe.deleteLater()
        logging.info('Existing instance found; exiting duplicate launch')
        sys.exit(0)
    probe.deleteLater()

    # Clean stale singleton pipe and claim it.
    QLocalServer.removeServer(SINGLETON_NAME)
    local_server = QLocalServer()
    if not local_server.listen(SINGLETON_NAME):
        logging.error(f'Unable to claim singleton: {local_server.errorString()}')
        sys.exit(1)

    if not autostart:
        create_desktop_shortcut()
        try:
            registered = startup_windows.registered_command()
            if registered and registered != startup_windows.startup_command():
                startup_windows.set_enabled(True)
        except OSError as error:
            logging.warning('Could not update startup path: %s', error)

    pet = DesktopPet(autostart=autostart)
    local_server.newConnection.connect(lambda: handle_new_connection(local_server, pet))
    # Keep a reference so the server is not garbage collected.
    app.setProperty('singletonServer', local_server)

    if autostart:
        pet.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    pet.force_show(activate=not autostart)
    logging.info('Pet window shown')

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray_icon_path = resource_path('assets/app_icon.ico')
        if not os.path.exists(tray_icon_path):
            tray_icon_path = resource_path('assets/processed/idle_0.png')
        tray = QSystemTrayIcon(QIcon(tray_icon_path), app)
        tray.setToolTip('葡萄冻冻')
        tray.setVisible(True)


        tray.setContextMenu(pet.create_menu(from_tray=True))
    else:
        logging.warning('System tray is not available')
        tray = None

    app.aboutToQuit.connect(pet.shutdown)
    app.aboutToQuit.connect(lambda: cleanup(local_server, tray))

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
