import sys
import os
import random
import logging
import time
import json
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QMenu, QSystemTrayIcon
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, QRect
from PyQt6.QtGui import QPixmap, QTransform, QAction, QCursor, QPainter, QColor, QFont, QPainterPath
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


SAVE_DATA_PATH = os.path.join(get_app_dir(), 'pet_data.json')
log_path = os.path.join(os.environ.get('TEMP', os.getcwd()), 'CuteDesktopPet.log')


logging.basicConfig(filename=log_path, level=logging.INFO, encoding='utf-8',
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
STARTUP_SPEECHES = [
    "准备好今天的工作了吗？",
    "坐正坐好，别驼背啦",
    "开始工作！！！",
]

SATIETY_MAX = 100
SATIETY_DECAY_PER_HOUR = 10
FEED_AMOUNT = 30
CANDY_AMOUNT = 2
BURGER_AMOUNT = 20
CAKE_AMOUNT = 50


def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


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
        self.hide()

    def show_text(self, text, center_x, top_y, duration=3000):
        self.label.setText(text)
        self.label.adjustSize()
        w = self.label.width()
        h = self.label.height()
        self.setFixedSize(w, h)
        self.label.setGeometry(0, 0, w, h)
        self.move(center_x - w // 2, top_y - h - 5)
        self.show()
        self.raise_()
        QTimer.singleShot(duration, self.hide)


class StatusPanel(QWidget):
    """Status panel that shows food counts, satiety, work duration, and allows feeding."""

    PANEL_W = 180
    PANEL_H = 155

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

        # Clickable row rectangles for feeding
        self._row_rects = {}
        self._close_btn_rect = QRect(self.PANEL_W - 32, 6, 18, 18)
        self.hide()


    def update_data(self, candy, burger, cake, satiety, working, work_elapsed):
        self.candy_count = candy
        self.burger_count = burger
        self.cake_count = cake
        self.satiety = satiety
        self.working = working
        self.work_elapsed = work_elapsed
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self._close_btn_rect.contains(pos):
                self.pet.toggle_panel()
                return
            for food, rect in self._row_rects.items():
                if rect.contains(pos):
                    self.pet.feed_food(food)
                    return

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

        y += bar_h + 6

        p.setPen(QColor(74, 58, 106))
        p.setFont(font_small)
        if self.working:
            h = int(self.work_elapsed // 3600)
            m = int((self.work_elapsed % 3600) // 60)
            work_text = f'💼 工作{h}时{m}分'
        else:
            work_text = '💼 未工作'
        p.drawText(pad, y + 10, work_text)

        p.end()



class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        logging.info('DesktopPet init')
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.pet_size = QSize(200, 200)
        self.setFixedSize(self.pet_size)

        self.compute_screen_bounds()

        primary = QApplication.primaryScreen().availableGeometry()
        # Start clearly visible near top-left of primary screen to avoid scaling issues
        start_x = primary.left() + 100
        start_y = primary.top() + 100
        self.move(start_x, start_y)
        self.saved_start = QPoint(start_x, start_y)

        self.label = QLabel(self)
        self.label.setFixedSize(self.pet_size)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAutoFillBackground(False)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.bubble = SpeechBubble()
        self.status_panel = StatusPanel(self)
        self.panel_visible = False
        self.sleep_pixmap = None
        self.load_frames()

        self.state = 'idle'
        self.frame_index = 0
        self.facing_right = True
        self.drag_offset = None
        self.last_drag_pos = None
        self.drag_total_dx = 0
        self.ground_y = start_y

        self.pos_f = [float(start_x), float(start_y)]
        self.vx = 0.0
        self.vy = 0.0
        self.run_speed = 4.0
        self.jump_strength = -14.0
        self.gravity = 0.8
        self.target_x = None
        self.dance_timer = 0
        self.playful_eat_timer = 0
        self.eat_timer = 0
        self.playful_sleep_timer = 0
        self.playful_wave_timer = 0
        self.playful_bounce_timer = 0
        self.playful_bounce_base_y = 0
        self.last_stretch_time = 0
        self.last_night_speech_time = 0
        self.stretch_step = 0

        # Hunger / work system

        self.satiety = SATIETY_MAX
        self.candy_count = 0
        self.burger_count = 0
        self.cake_count = 0
        self.load_data()

        self.working = False
        self.work_start_time = 0
        self.last_satiety_check = time.time()
        self.last_candy = 0
        self.last_burger = 0
        self.last_cake = 0
        self.last_work_duration_speech = 0

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.next_frame)
        self.anim_timer.start(130)

        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self.update_physics)
        self.physics_timer.start(16)

        self.behavior_timer = QTimer(self)
        self.behavior_timer.timeout.connect(self.decide_behavior)
        self.behavior_timer.start(15000)

        self.satiety_timer = QTimer(self)
        self.satiety_timer.timeout.connect(self.check_satiety)
        self.satiety_timer.start(10000)

        self.panel_refresh_timer = QTimer(self)
        self.panel_refresh_timer.timeout.connect(self.refresh_panel)
        self.panel_refresh_timer.start(1000)

        self.schedule_next_speech()
        self.update_image()

        # startup speeches
        QTimer.singleShot(500, lambda: self.show_speech(STARTUP_SPEECHES[0], 2500))
        QTimer.singleShot(3200, lambda: self.show_speech(STARTUP_SPEECHES[1], 2500))
        QTimer.singleShot(6000, lambda: self.show_speech(STARTUP_SPEECHES[2], 2500))

    def save_data(self):
        data = {
            'satiety': round(self.satiety, 2),
            'candy_count': self.candy_count,
            'burger_count': self.burger_count,
            'cake_count': self.cake_count,
            'last_save_time': time.time(),
        }
        try:
            with open(SAVE_DATA_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f'Failed to save pet data: {e}')

    def load_data(self):
        if not os.path.exists(SAVE_DATA_PATH):
            return
        try:
            with open(SAVE_DATA_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                loaded_satiety = float(data.get('satiety', SATIETY_MAX))
                self.candy_count = int(data.get('candy_count', 0))
                self.burger_count = int(data.get('burger_count', 0))
                self.cake_count = int(data.get('cake_count', 0))
                last_save = float(data.get('last_save_time', time.time()))
                now = time.time()
                offline_elapsed = max(0.0, now - last_save)
                # Calculate offline decay (0.5 points per 180 seconds)
                offline_decay = offline_elapsed * (0.5 / 180.0)
                self.satiety = max(0.0, min(float(SATIETY_MAX), loaded_satiety - offline_decay))
                logging.info(f'Loaded pet data: {data}, offline decay: {offline_decay:.2f}, current satiety: {self.satiety:.2f}')
        except Exception as e:
            logging.error(f'Failed to load pet data: {e}')

    def force_show(self):
        logging.info('force_show called')
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        primary = QApplication.primaryScreen().availableGeometry()
        if not primary.intersects(self.geometry()):
            logging.warning('Window off-screen; resetting')
            self.move(self.saved_start)
            self.pos_f = [float(self.saved_start.x()), float(self.saved_start.y())]
            self.ground_y = self.saved_start.y()
        logging.info(f'Window geometry: {self.geometry()}')

    def compute_screen_bounds(self):
        screens = QApplication.screens()
        min_x = min(s.availableGeometry().left() for s in screens)
        min_y = min(s.availableGeometry().top() for s in screens)
        max_x = max(s.availableGeometry().right() for s in screens)
        max_y = max(s.availableGeometry().bottom() for s in screens)
        self.screen_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        logging.info(f'Virtual screen rect: {self.screen_rect}')

    def load_frames(self):
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
                if os.path.exists(p):
                    pm = QPixmap(p).scaled(
                        self.pet_size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.pixmaps[state].append(pm)
                else:
                    logging.warning(f'missing asset: {p}')

    def current_pixmap(self):
        # During drag, cycle run frames like normal running.
        # Playful/hungry/eat states reuse idle animation with overlays.
        if self.state == 'drag':
            img_state = 'run'
        elif self.state == 'playful_sleep':
            img_state = 'sleep' if 'sleep' in self.pixmaps and self.pixmaps['sleep'] else 'idle'
        elif self.state == 'pajamas':
            img_state = 'pajamas' if 'pajamas' in self.pixmaps and self.pixmaps['pajamas'] else 'idle'
        elif self.state == 'stretch':
            from datetime import datetime
            ch = datetime.now().hour
            is_night = (ch >= 23 or ch < 5)
            s_key = 'stretch_night' if is_night else 'stretch_day'
            img_state = s_key if s_key in self.pixmaps and self.pixmaps[s_key] else 'idle'
        elif self.state == 'hungry':
            img_state = 'sleep' if 'sleep' in self.pixmaps and self.pixmaps['sleep'] else 'idle'
        elif self.state in ('playful_look', 'playful_eat', 'eat', 'playful_wave'):
            img_state = 'idle'
        elif self.state == 'playful_bounce':
            img_state = 'jump'
        else:
            img_state = self.state
        pms = self.pixmaps.get(img_state, self.pixmaps['idle'])
        if not pms:
            pms = self.pixmaps['idle']

        if self.state == 'stretch':
            idx = min(self.stretch_step, len(pms) - 1)
        else:
            idx = self.frame_index % len(pms)
        pm = pms[idx]

        # Source assets face left; flip horizontally when we want to face right.
        if self.facing_right:
            pm = pm.transformed(QTransform().scale(-1, 1))
        # During the second half of a dance, mirror again so she raises the other arm.
        if self.state == 'dance' and self.dance_timer >= 1500:
            pm = pm.transformed(QTransform().scale(-1, 1))

        result = QPixmap(pm.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
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
        elif self.state == 'playful_sleep':
            pass

        elif self.state == 'playful_wave':

            # Waving hand overlay.
            painter.setPen(QColor(255, 160, 180))
            painter.setBrush(QColor(255, 160, 180))
            offset = 35 if self.facing_right else -35
            cx = result.width() // 2 + offset
            cy = result.height() // 2 - 25
            painter.drawEllipse(cx - 8, cy - 8, 16, 16)

        painter.end()
        return result


    def update_image(self):
        self.label.setPixmap(self.current_pixmap())

    def next_frame(self):
        if self.state in ('run', 'drag'):
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['run'])
        elif self.state == 'dance':
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
            self.playful_eat_timer += 130
            if self.playful_eat_timer >= 4000:
                self.start_idle()
                return
        elif self.state == 'eat':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            self.eat_timer += 130
            if self.eat_timer >= 3000:
                self.start_idle()
                return
        elif self.state == 'hungry':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
        elif self.state == 'playful_sleep':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            self.playful_sleep_timer += 130
            if self.playful_sleep_timer >= 5000:
                self.start_idle()
                return
        elif self.state == 'playful_wave':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['idle'])
            # Wave by flipping direction every 4 frames (~0.5 s).
            self.facing_right = (self.frame_index // 4) % 2 == 0
            self.playful_wave_timer += 130
            if self.playful_wave_timer >= 2600:
                self.start_idle()
                return
        elif self.state == 'playful_bounce':
            self.frame_index = (self.frame_index + 1) % len(self.pixmaps['jump'])
            self.playful_bounce_timer += 130
            if self.playful_bounce_timer >= 3000:
                self.pos_f[1] = float(self.playful_bounce_base_y)
                self.ground_y = self.playful_bounce_base_y
                self.start_idle()
                return
        else:
            self.frame_index = 0
        self.update_image()

    def show_speech(self, text, duration=3000):
        cx = int(self.pos_f[0]) + self.pet_size.width() // 2
        ty = int(self.pos_f[1])
        self.bubble.show_text(text, cx, ty, duration)
        logging.info(f'Speech: {text}')

    def schedule_next_speech(self):
        interval = random.randint(120000, 300000)
        QTimer.singleShot(interval, self.random_speech)

    def random_speech(self):
        if self.state != 'drag' and self.state != 'hungry' and self.satiety > 0:
            text = random.choice(IDLE_SPEECHES)
            self.show_speech(text, 3500)
        self.schedule_next_speech()

    def decide_behavior(self):
        # Don't interrupt active movement, stretching, or short animations.
        if self.state in ('drag', 'jump', 'fall', 'run', 'stretch',
                          'playful_look', 'playful_eat', 'eat',
                          'playful_sleep', 'playful_wave', 'playful_bounce'):
            return

        if self.satiety <= 0:
            if self.state != 'hungry':
                self.start_hungry()
            return

        # Check late night mode (>= 23:00 or < 05:00)
        from datetime import datetime
        current_hour = datetime.now().hour
        if current_hour >= 23 or current_hour < 5:
            now = time.time()
            if now - self.last_night_speech_time >= 1800:
                self.last_night_speech_time = now
                self.show_speech('太晚啦，不许熬夜，快去睡觉吧~', 4000)
            self.state = 'pajamas'
            self.update_image()
            return

        # Only change behavior sometimes, not every tick.
        if random.random() > 0.35:
            return

        r = random.random()
        if r < 0.18:
            self.start_idle()
        elif r < 0.30:
            self.start_jump()
        elif r < 0.42:
            self.start_dance()
        elif r < 0.54:
            self.start_playful_look()
        elif r < 0.66:
            self.start_playful_eat()
        elif r < 0.74:
            self.start_playful_chase()
        elif r < 0.82:
            self.start_playful_sleep()
        elif r < 0.91:
            self.start_playful_wave()
        else:
            self.start_playful_bounce()

    def start_idle(self):
        self.state = 'idle'
        self.vx = 0.0
        self.vy = 0.0
        self.target_x = None
        self.frame_index = 0
        self.update_image()

    def start_run(self):
        if self.state == 'drag' or self.satiety <= 0:
            if self.satiety <= 0:
                self.start_hungry()
            return
        self.state = 'run'
        margin = self.pet_size.width() // 2
        max_x = self.screen_rect.right() - self.pet_size.width()
        lo = self.screen_rect.left() + margin
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
        max_x = self.screen_rect.right() - self.pet_size.width()
        lo = self.screen_rect.left()
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

    def start_stretch(self):
        """Stretch 1-2-3 sequence with 1 second interval between frames."""
        self.state = 'stretch'
        self.stretch_step = 0
        self.vx = 0.0
        self.vy = 0.0
        self.show_speech('站起来活动一下脖子、喝口水吧~', 4500)
        self.update_image()
        QTimer.singleShot(1000, self._stretch_step_2)


    def _stretch_step_2(self):
        if self.state == 'stretch':
            self.stretch_step = 1
            self.update_image()
            QTimer.singleShot(1000, self._stretch_step_3)

    def _stretch_step_3(self):
        if self.state == 'stretch':
            self.stretch_step = 2
            self.update_image()
            QTimer.singleShot(2000, self._finish_stretch)

    def _finish_stretch(self):
        if self.state == 'stretch':
            self.start_idle()


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
        """Run toward the current mouse cursor position."""
        if self.satiety <= 0:
            self.start_hungry()
            return
        self.state = 'run'
        mouse = QCursor.pos()
        max_x = self.screen_rect.right() - self.pet_size.width()
        min_x = self.screen_rect.left()
        target = mouse.x() - self.pet_size.width() // 2
        self.target_x = max(min_x, min(target, max_x))
        dx = self.target_x - self.pos_f[0]
        self.facing_right = dx >= 0
        self.vx = self.run_speed if self.facing_right else -self.run_speed
        self.vy = 0.0
        self.update_image()

    def start_playful_sleep(self):
        self.state = 'playful_sleep'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.playful_sleep_timer = 0
        self.update_image()

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
        self.playful_bounce_timer = 0
        self.playful_bounce_base_y = int(self.pos_f[1])
        self.update_image()

    def start_eat(self):
        self.state = 'eat'
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.eat_timer = 0
        self.update_image()

    def start_hungry(self):
        self.state = 'hungry'
        self.working = False
        self.vx = 0.0
        self.vy = 0.0
        self.frame_index = 0
        self.update_image()
        self.show_speech('我饿了，快喂我吃东西...', 3000)

    def update_panel_position(self):
        if not self.panel_visible:
            return
        px = int(self.pos_f[0])
        py = int(self.pos_f[1])
        pw = self.status_panel.width()
        ph = self.status_panel.height()
        screen_right = self.screen_rect.right()
        if px + self.pet_size.width() + 10 + pw <= screen_right:
            ix = px + self.pet_size.width() + 10
        else:
            ix = px - pw - 10
        iy = py
        self.status_panel.move(ix, iy)
        self.status_panel.raise_()

    def get_work_elapsed(self):
        if not self.working:
            return 0
        return time.time() - self.work_start_time

    def refresh_panel(self):
        if not self.panel_visible:
            return
        elapsed = self.get_work_elapsed()
        self.status_panel.update_data(
            self.candy_count,
            self.burger_count,
            self.cake_count,
            self.satiety,
            self.working,
            elapsed,
        )
        self.update_panel_position()

    def toggle_panel(self):
        self.panel_visible = not self.panel_visible
        if self.panel_visible:
            self.refresh_panel()
            self.status_panel.show()
            self.status_panel.raise_()
        else:
            self.status_panel.hide()

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
        if self.state == 'hungry':
            self.start_idle()
        self.start_eat()
        self.show_speech(f'吃了一个{name}！+{amount}饱食度', 1800)
        self.save_data()
        self.refresh_panel()

    def start_work(self):
        if self.satiety <= 0:
            self.start_hungry()
            return
        self.working = True
        now = time.time()
        self.work_start_time = now
        self.last_candy = now
        self.last_burger = now
        self.last_cake = now
        self.last_work_duration_speech = now
        self.show_speech('开始工作啦！', 2000)
        self.refresh_panel()

    def end_work(self):
        if self.working:
            self.working = False
            elapsed = self.get_work_elapsed()
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self.show_speech(f'下班啦！本次工作{h}小时{m}分钟~', 3000)
            self.refresh_panel()

    def check_satiety(self):
        now = time.time()
        elapsed = now - self.last_satiety_check
        if elapsed > 0:
            # 180 seconds decay 0.5 points -> (0.5 / 180.0) points per second
            decay = elapsed * (0.5 / 180.0)
            self.satiety = max(0.0, self.satiety - decay)
            self.last_satiety_check = now
            if self.satiety <= 0 and self.state != 'hungry':
                self.start_hungry()

        if self.working and self.satiety > 0:
            work_elapsed = now - self.work_start_time
            # Continuous 45-minute work stretch reminder
            if work_elapsed >= 45 * 60 and (now - self.last_stretch_time >= 40 * 60):
                self.last_stretch_time = now
                self.start_stretch()

            if now - self.last_candy >= 15 * 60:
                self.candy_count += 1
                self.last_candy += 15 * 60
                self.show_speech('🍬 获得一颗糖果！可用来恢复饱食度', 2000)
            if now - self.last_burger >= 2 * 60 * 60:
                self.burger_count += 1
                self.last_burger += 2 * 60 * 60
                self.show_speech('🍔 获得一个汉堡！可用来恢复饱食度', 2500)
            if now - self.last_cake >= 5 * 60 * 60:
                self.cake_count += 1
                self.last_cake += 5 * 60 * 60
                self.show_speech('🎂 获得一个蛋糕！可用来恢复饱食度', 3000)


            # Report work duration every 30 minutes
            if now - self.last_work_duration_speech >= 30 * 60:
                self.last_work_duration_speech = now
                h = int(work_elapsed // 3600)
                m = int((work_elapsed % 3600) // 60)
                if h > 0:
                    self.show_speech(f'已经工作{h}小时{m}分钟啦，加油！', 2500)
                else:
                    self.show_speech(f'已经工作{m}分钟啦，加油！', 2500)


        self.save_data()
        self.refresh_panel()


    def update_physics(self):
        if self.state == 'drag':
            return

        if self.state == 'playful_bounce':
            # Small hops in place.
            t = self.playful_bounce_timer / 1000.0
            # Two small bounces per second.
            hop = abs(int(15 * (1 - 2 * abs((t * 2) % 1 - 0.5))))
            self.pos_f[1] = float(self.playful_bounce_base_y - hop)
            self.move(int(self.pos_f[0]), int(self.pos_f[1]))
            self.update_panel_position()
            return

        if self.state in ('jump', 'fall'):
            self.vy += self.gravity
            self.pos_f[1] += self.vy
            self.pos_f[0] += self.vx
            if self.pos_f[1] >= self.ground_y:
                self.pos_f[1] = float(self.ground_y)
                self.vy = 0.0
                self.vx = 0.0
                self.start_idle()
                return
        elif self.state == 'run':
            self.pos_f[0] += self.vx
            if (self.vx > 0 and self.pos_f[0] >= self.target_x) or \
               (self.vx < 0 and self.pos_f[0] <= self.target_x):
                self.pos_f[0] = float(self.target_x)
                self.start_idle()
                return
        elif self.state == 'dance':
            self.dance_timer += 16
            if self.dance_timer >= 3000:
                self.start_idle()
                return

        min_x = self.screen_rect.left()
        max_x = self.screen_rect.right() - self.pet_size.width()
        if self.pos_f[0] < min_x:
            self.pos_f[0] = float(min_x)
            if self.state == 'run':
                self.facing_right = True
                self.vx = abs(self.vx)
        elif self.pos_f[0] > max_x:
            self.pos_f[0] = float(max_x)
            if self.state == 'run':
                self.facing_right = False
                self.vx = -abs(self.vx)

        self.move(int(self.pos_f[0]), int(self.pos_f[1]))
        if self.state in ('run', 'jump'):
            self.update_image()
        self.update_panel_position()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.last_drag_pos = event.globalPosition().toPoint()
            self.drag_total_dx = 0
            self.state = 'drag'
            self.vx = 0.0
            self.vy = 0.0
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            self.bubble.hide()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None:
            current_pos = event.globalPosition().toPoint()
            dx = current_pos.x() - self.last_drag_pos.x()
            if abs(dx) > 1:
                self.facing_right = dx > 0
            self.last_drag_pos = current_pos
            self.drag_total_dx += dx

            new_pos = current_pos - self.drag_offset
            max_x = self.screen_rect.right() - self.pet_size.width()
            max_y = self.screen_rect.bottom() - self.pet_size.height()
            new_pos.setX(max(self.screen_rect.left(), min(new_pos.x(), max_x)))
            new_pos.setY(max(self.screen_rect.top(), min(new_pos.y(), max_y)))
            self.move(new_pos)
            self.pos_f = [float(new_pos.x()), float(new_pos.y())]
            self.ground_y = new_pos.y()
            self.update_panel_position()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            self.last_drag_pos = None
            self.drag_total_dx = 0
            self.unsetCursor()
            # Stop running animation when drag ends.
            self.start_idle()

    def closeEvent(self, event):
        logging.info('DesktopPet closing')
        self.save_data()
        self.anim_timer.stop()

        self.physics_timer.stop()
        self.behavior_timer.stop()
        self.satiety_timer.stop()
        self.panel_refresh_timer.stop()
        self.bubble.close()
        self.status_panel.close()
        event.accept()
        # Closing the pet window should always terminate the whole application.
        app = QApplication.instance()
        if app:
            app.quit()

    def show_context_menu(self, pos):
        menu = QMenu(self)
        work_text = '结束工作' if self.working else '开始工作'
        panel_text = '关闭状态栏' if self.panel_visible else '打开状态栏'
        actions = [
            ('跳跃', self.start_jump),
            ('跳舞', self.start_dance),
            ('伸懒腰', self.start_stretch),
            (None, None),
            (work_text, self.toggle_work),
            (panel_text, self.toggle_panel),
            (None, None),
            ('退出', self.close),
        ]

        for text, callback in actions:
            if text is None:
                menu.addSeparator()
            else:
                a = QAction(text, self)
                a.triggered.connect(callback)
                menu.addAction(a)
        menu.exec(pos)


    def toggle_work(self):
        if self.working:
            self.end_work()
        else:
            self.start_work()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = 10 if delta > 0 else -10
        new_w = max(80, min(400, self.pet_size.width() + step))
        self.pet_size = QSize(new_w, new_w)
        self.setFixedSize(self.pet_size)
        self.label.setFixedSize(self.pet_size)
        self.load_frames()
        self.update_image()


SINGLETON_NAME = 'CuteDesktopPetSingletonLock'


def handle_new_connection(server, pet):
    while server.hasPendingConnections():
        client = server.nextPendingConnection()
        if client.waitForReadyRead(500):
            data = bytes(client.readAll().data())
            if data == b'SHOW':
                pet.force_show()
        client.deleteLater()


def cleanup(local_server, tray):
    logging.info('Application cleanup')
    if tray is not None:
        tray.hide()
    local_server.close()
    QLocalServer.removeServer(SINGLETON_NAME)


def main():
    logging.info('Application starting')

    app = QApplication(sys.argv)
    # When the pet window closes, the whole application must quit.
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName('CuteDesktopPet')

    # Singleton: if another instance is running, tell it to show and exit.
    probe = QLocalSocket()
    probe.connectToServer(SINGLETON_NAME)
    if probe.waitForConnected(500):
        probe.write(b'SHOW')
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        probe.deleteLater()
        logging.info('Existing instance found; signaled it to show and exiting')
        sys.exit(0)
    probe.deleteLater()

    # Clean stale singleton pipe and claim it.
    QLocalServer.removeServer(SINGLETON_NAME)
    local_server = QLocalServer()
    if not local_server.listen(SINGLETON_NAME):
        logging.error(f'Unable to claim singleton: {local_server.errorString()}')
        sys.exit(1)

    pet = DesktopPet()
    local_server.newConnection.connect(lambda: handle_new_connection(local_server, pet))
    # Keep a reference so the server is not garbage collected.
    app.setProperty('singletonServer', local_server)

    pet.force_show()
    logging.info('Pet window shown')

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(app)
        tray.setToolTip('桌面宠物')
        tray.setVisible(True)
        menu = QMenu()

        show_action = QAction('显示', menu)
        show_action.triggered.connect(pet.force_show)
        menu.addAction(show_action)

        work_action = QAction('开始工作', menu)
        work_action.triggered.connect(pet.start_work)
        menu.addAction(work_action)

        end_work_action = QAction('结束工作', menu)
        end_work_action.triggered.connect(pet.end_work)
        menu.addAction(end_work_action)

        panel_action = QAction('状态栏', menu)
        panel_action.triggered.connect(pet.toggle_panel)
        menu.addAction(panel_action)

        menu.addSeparator()
        quit_action = QAction('退出', menu)
        quit_action.triggered.connect(app.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
    else:
        logging.warning('System tray is not available')
        tray = None

    app.aboutToQuit.connect(lambda: cleanup(local_server, tray))

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
