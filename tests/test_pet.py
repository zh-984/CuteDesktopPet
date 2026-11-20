"""Run with: python -m unittest discover -s tests -v (no desktop or real save touched)."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt6.QtCore import QDate, QDateTime, QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QCursor, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QTableView

import pet
import startup_windows
from desktop_layout import DesktopLayout, Display, match_windows_display
from pet_core import (AFFECTION_THRESHOLDS, DAILY_PET_AFFECTION_LIMIT, WORK_AFFECTION_INTERVAL,
                      affection_tier, behavior_weights, normalize_data, read_save, write_save)


class DisplayTests(unittest.TestCase):
    def test_mixed_dpi_mapping_uses_origins_and_accepts_pixel_rounding(self):
        physical = {'display1': (0, 0, 2560, 1600), 'display2': (-1920, -200, 1920, 1080)}
        self.assertEqual(match_windows_display(QRect(0, 0, 1707, 1067), 1.5, physical), 'display1')
        self.assertEqual(match_windows_display(QRect(-1920, -200, 1920, 1080), 1, physical), 'display2')
        self.assertIsNone(match_windows_display(QRect(0, 0, 1707, 1067), 1, physical))
        display = Display('display1', QRect(0, 0, 1707, 1067), QRect(*physical['display1']))
        point = QPointF(520, 700)
        self.assertAlmostEqual(display.to_logical(display.to_physical(point)).x(), point.x())
        self.assertAlmostEqual(display.to_logical(display.to_physical(point)).y(), point.y())

    def test_staggered_route_uses_shared_edges_and_can_cross_via_third_display(self):
        a = QRect(-1200, -400, 1200, 800)
        b = QRect(0, 0, 1200, 800)
        c = QRect(400, 800, 800, 900)
        layout = DesktopLayout([Display(name, rect, rect) for name, rect in zip('abc', [a, b, c])])
        target = QPointF(800, 1300)
        entry = layout.next_waypoint(QPointF(-800, -200), target)
        self.assertEqual(entry, QPointF(0, 399))
        next_entry = layout.next_waypoint(entry, target)
        self.assertEqual(next_entry, QPointF(800, 800))
        self.assertEqual(layout.next_waypoint(next_entry, target), target)
        self.assertEqual(layout.next_waypoint(QPointF(500, 700), QPointF(-700, -200)), QPointF(-1, 0))


class StorageTests(unittest.TestCase):
    def test_unsupported_coordinates_do_not_prevent_loading_other_save_data(self):
        data = normalize_data({'position': [1e30, -10], 'candy_count': 7}, time.time())
        self.assertIsNone(data['position'])
        self.assertEqual(data['candy_count'], 7)

    def test_affection_thresholds_and_old_save_migration(self):
        self.assertEqual(affection_tier(0), 0)
        for rank, threshold in enumerate(AFFECTION_THRESHOLDS, start=1):
            self.assertEqual(affection_tier(threshold - 1), rank - 1)
            self.assertEqual(affection_tier(threshold), rank)
        save = normalize_data({'affection': 4500}, time.time())
        self.assertEqual(save['affection'], 4500)
        self.assertEqual(affection_tier(save['affection']), 10)
        self.assertEqual(save['work_affection_claimed'], 0)

    def test_offline_sleep_is_capped_and_future_save_does_not_add_food(self):
        self.assertEqual(normalize_data({'satiety': 100, 'last_save_time': 0}, 100000)['satiety'], 80)
        self.assertEqual(normalize_data({'satiety': 50, 'last_save_time': 100}, 0)['satiety'], 50)

    def test_bad_fields_and_legacy_completed_reward_are_normalized(self):
        data = normalize_data({'satiety': 'NaN', 'candy_count': -5, 'reward_marks': [],
                               'todo_list': [None, {'text': 'done', 'completed': True}]}, time.time())
        self.assertEqual(data['satiety'], 100)
        self.assertEqual(data['candy_count'], 0)
        self.assertTrue(data['todo_list'][0]['reward_claimed'])

    def test_backup_recovers_a_corrupt_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'save.json'
            write_save(path, {'satiety': 75, 'last_save_time': time.time()})
            write_save(path, {'satiety': 90, 'last_save_time': time.time()})
            path.write_text('{broken', encoding='utf-8')
            data, errors = read_save(path, Path(tmp) / 'missing.json', time.time())
            self.assertAlmostEqual(data['satiety'], 75, places=2)
            self.assertEqual(len(errors), 1)

    def test_failed_replace_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'save.json'
            write_save(path, {'satiety': 70})
            with patch('pet_core.os.replace', side_effect=OSError('simulated failure')):
                with self.assertRaises(OSError):
                    write_save(path, {'satiety': 5})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['satiety'], 70)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_contextual_behavior_does_not_run_around_during_work(self):
        working = behavior_weights(80, 50, True, None)
        self.assertEqual(working['chase'], 0)
        self.assertEqual(working['bounce'], 0)
        self.assertLess(behavior_weights(80, 50, False, 'wave')['wave'],
                        behavior_weights(80, 50, False, None)['wave'])


class PetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = patch.multiple(pet, SAVE_DATA_PATH=str(Path(self.tmp.name) / 'save.json'),
                                    LEGACY_DATA_PATH=str(Path(self.tmp.name) / 'legacy.json'))
        self.paths.start()
        self.p = pet.DesktopPet()

    def tearDown(self):
        self.p.shutdown()
        self.p.hide()
        self.p.deleteLater()
        self.app.processEvents()
        self.paths.stop()
        self.tmp.cleanup()

    def test_idle_stops_high_frequency_timers_and_reuses_frame(self):
        self.p.start_idle()
        self.assertFalse(self.p.anim_timer.isActive())
        self.assertFalse(self.p.physics_timer.isActive())
        key = self.p.label.pixmap().cacheKey()
        self.p.update_image()
        self.assertEqual(self.p.label.pixmap().cacheKey(), key)

    def test_single_click_plays_but_drag_does_not_click(self):
        self.p.show()
        self.app.processEvents()
        QTest.mouseClick(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertTrue(self.p.click_timer.isActive())
        self.assertEqual(self.p.state, 'idle')
        # Exercise the real callback with a shorter interval for this test.
        self.p.click_timer.start(10)
        QTest.qWait(30)
        self.assertEqual(self.p.state, 'playful_bounce')
        self.assertEqual(self.p.affection, 0)
        QTest.mousePress(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        QTest.mouseMove(self.p, QPoint(140, 100))
        self.assertEqual(self.p.state, 'drag')
        self.assertFalse(self.p.anim_timer.isActive())
        self.assertFalse(self.p.physics_timer.isActive())
        QTest.mouseRelease(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertFalse(self.p.click_timer.isActive())
        self.assertEqual(self.p.affection, 0)

    def test_double_click_pets_without_pending_single_click(self):
        self.p.show()
        QTest.mouseClick(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertTrue(self.p.click_timer.isActive())
        QTest.mouseDClick(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        QTest.mouseRelease(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(self.p.state, 'petted')
        self.assertEqual(self.p.affection, 1)
        self.assertFalse(self.p.click_timer.isActive())
        self.assertFalse(self.p.physics_timer.isActive())

    def test_click_jitter_is_not_a_drag_and_freezes_running(self):
        self.p.show()
        self.p.start_run()
        QTest.mousePress(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(self.p.state, 'idle')
        self.assertFalse(self.p.physics_timer.isActive())
        QTest.mouseMove(self.p, QPoint(106, 106))
        self.assertEqual(self.p.state, 'idle')
        self.p.decide_behavior()
        self.assertEqual(self.p.state, 'idle')
        QTest.mouseRelease(self.p, Qt.MouseButton.LeftButton, pos=QPoint(106, 106))
        self.assertTrue(self.p.click_timer.isActive())

    def test_hover_after_lost_release_cannot_start_drag(self):
        self.p.show()
        QTest.mousePress(self.p, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        before = self.p.pos()
        hover = QMouseEvent(QEvent.Type.MouseMove, QPointF(140, 100),
                            QPointF(self.p.mapToGlobal(QPoint(140, 100))),
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.p, hover)
        self.assertEqual(self.p.state, 'idle')
        self.assertEqual(self.p.pos(), before)
        self.assertIsNone(self.p.press_pos)
        self.assertFalse(self.p.click_timer.isActive())
        QTest.mouseRelease(self.p, Qt.MouseButton.LeftButton, pos=QPoint(140, 100))

    def test_single_click_still_plays_when_hungry(self):
        self.p.satiety = 0
        self.p.play_with_pet()
        self.assertEqual(self.p.state, 'playful_wave')

    def test_snack_once_per_day_and_quiet_suppresses_only_ambient_speech(self):
        self.p.daily_snack()
        self.p.daily_snack()
        self.assertEqual((self.p.candy_count, self.p.burger_count), (3, 2))
        self.p.toggle_quiet()
        self.p.bubble.hide()
        self.p.show_speech('ambient', ambient=True)
        self.assertFalse(self.p.bubble.isVisible())
        self.p.pet_head()
        self.assertTrue(self.p.bubble.isVisible())

    def test_calendar_selects_dates_across_year_boundary(self):
        edit = self.p.todo_panel.time_edit
        edit.setDate(QDate(2026, 12, 31))
        calendar = edit.calendarWidget()
        calendar.setSelectedDate(QDate(2027, 1, 1))
        calendar.activated.emit(QDate(2027, 1, 1))
        self.assertEqual(edit.date(), QDate(2027, 1, 1))
        self.assertIn('2027-01-01', edit.text())

    def test_calendar_header_text_opens_month_and_year_lists(self):
        panel = self.p.todo_panel
        edit = panel.time_edit
        edit.setDate(QDate(2026, 11, 19))
        panel.show()
        QTest.mouseClick(edit, Qt.MouseButton.LeftButton, pos=QPoint(edit.width() - 6, edit.height() // 2))
        calendar = edit.calendarWidget()
        self.assertTrue(calendar.isVisible())
        days = calendar.findChild(QTableView)
        last_row = days.model().index(days.model().rowCount() - 1, 0)
        self.assertTrue(days.viewport().rect().contains(days.visualRect(last_row)))
        month = calendar.findChild(QComboBox, 'todoCalendarMonth')
        year = calendar.findChild(QComboBox, 'todoCalendarYear')
        for control in (month, year):
            QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=control.rect().center())
            self.assertTrue(control.view().isVisible())
            QTest.keyClick(control.view(), Qt.Key.Key_Down)
            QTest.keyClick(control.view(), Qt.Key.Key_Return)
            self.assertTrue(calendar.isVisible())
        self.assertEqual((calendar.yearShown(), calendar.monthShown()), (2027, 12))
        self.assertEqual(edit.date(), QDate(2026, 11, 19))
        calendar.setSelectedDate(QDate(2027, 12, 4))
        calendar.activated.emit(calendar.selectedDate())
        self.assertEqual(edit.date(), QDate(2027, 12, 4))

    def test_todo_deadlines_outside_1970_to_2099_round_trip(self):
        panel = self.p.todo_panel
        chosen = (QDate(1955, 4, 12), QDate(2120, 7, 8))
        for date in chosen:
            panel.input_edit.setText('Date round trip')
            panel.time_edit.setDate(date)
            panel.add_todo()
        before = [item['due_at'] for item in self.p.todo_list]
        self.p.load_data()
        after = [item['due_at'] for item in self.p.todo_list]
        self.assertEqual(after, before)
        self.assertEqual([QDateTime.fromSecsSinceEpoch(value).date() for value in after], list(chosen))

    def test_clicking_the_same_submenu_toggles_without_closing_root(self):
        def wait_for_visibility(submenu, visible):
            for _ in range(20):
                if submenu.isVisible() == visible:
                    break
                QTest.qWait(50)
            self.assertEqual(submenu.isVisible(), visible)

        def move_over(menu, position):
            event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position),
                                QPointF(menu.mapToGlobal(position)), Qt.MouseButton.NoButton,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(menu, event)

        menu = self.p.create_menu()
        self.addCleanup(menu.close)
        menu.popup(QPoint(90, 90))
        self.app.processEvents()
        for name in ('互动', '设置'):
            action = next(a for a in menu.actions() if a.text() == name)
            pos = menu.actionGeometry(action).center()
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=pos)
            wait_for_visibility(action.menu(), True)
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=pos)
            self.assertFalse(action.menu().isVisible())
            self.assertTrue(menu.isVisible())
            move_over(menu, pos + QPoint(1, 0))
            self.assertFalse(action.menu().isVisible())
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=pos)
            wait_for_visibility(action.menu(), True)
            other = next(a for a in menu.actions() if a.text() == '开始工作')
            move_over(menu, menu.actionGeometry(other).center())
            wait_for_visibility(action.menu(), False)

    def test_open_submenu_can_receive_the_click_over_its_parent_row(self):
        menu = self.p.create_menu()
        self.addCleanup(menu.close)
        menu.popup(QPoint(90, 90))
        self.app.processEvents()
        for name in ('设置', '互动'):
            action = next(a for a in menu.actions() if a.text() == name)
            menu.setActiveAction(action)
            child = action.menu()
            self.assertTrue(child.isVisible())
            global_pos = QPointF(menu.mapToGlobal(menu.actionGeometry(action).center()))
            local_pos = QPointF(child.mapFromGlobal(global_pos.toPoint()))
            press = QEvent.Type.MouseButtonDblClick if name == '互动' else QEvent.Type.MouseButtonPress
            for event_type, buttons in (
                (press, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
            ):
                event = QMouseEvent(event_type, local_pos, global_pos, Qt.MouseButton.LeftButton,
                                    buttons, Qt.KeyboardModifier.NoModifier)
                self.app.sendEvent(child, event)
            self.assertFalse(child.isVisible())
            self.assertTrue(menu.isVisible())

    def test_submenu_click_uses_visibility_at_press_even_if_hover_changes_it(self):
        menu = self.p.create_menu()
        self.addCleanup(menu.close)
        menu.popup(QPoint(90, 90))
        self.app.processEvents()
        for name in ('设置', '互动'):
            action = next(a for a in menu.actions() if a.text() == name)
            child = action.menu()
            pos = menu.actionGeometry(action).center()
            menu.setActiveAction(action)
            self.assertTrue(child.isVisible())
            QTest.mousePress(menu, Qt.MouseButton.LeftButton, pos=pos)
            # Qt's hover timer can close the child before the button is released.
            child.hide()
            QTest.mouseRelease(menu, Qt.MouseButton.LeftButton, pos=pos)
            self.assertFalse(child.isVisible())
            self.assertTrue(menu.isVisible())

            QTest.mousePress(menu, Qt.MouseButton.LeftButton, pos=pos)
            # A pending hover can also open it during a click intended to open.
            menu.setActiveAction(action)
            QTest.mouseRelease(menu, Qt.MouseButton.LeftButton, pos=pos)
            self.assertTrue(child.isVisible())
            child.hide()
            menu.setActiveAction(None)

    def test_bounce_advances_on_physics_ticks_and_lands_at_start_height(self):
        self.p.start_playful_bounce()
        start = self.p.bounce_started_at
        baseline = self.p.playful_bounce_base_y
        self.assertFalse(self.p.anim_timer.isActive())
        positions = []
        for elapsed in (0.04, 0.08, 0.12):
            with patch('pet.time.monotonic', return_value=start + elapsed):
                self.p.update_physics()
                positions.append(self.p.y())
        self.assertGreater(positions[0], positions[1])
        self.assertGreater(positions[1], positions[2])
        with patch('pet.time.monotonic', return_value=start + 3.1):
            self.p.update_physics()
        self.assertEqual(self.p.y(), baseline)
        self.assertFalse(self.p.physics_timer.isActive())

    def test_wheel_burst_rebuilds_assets_and_saves_only_once(self):
        origin = self.p.width()
        with patch.object(self.p, 'load_frames', wraps=self.p.load_frames) as load, \
             patch.object(self.p, 'save_data', wraps=self.p.save_data) as save:
            for _ in range(3):
                event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
                self.p.wheelEvent(event)
            self.assertEqual(self.p.width(), origin + 30)
            load.assert_not_called()
            save.assert_not_called()
            QTest.qWait(160)
            load.assert_called_once()
            save.assert_called_once()

    def test_menu_order_and_persisted_automatic_settings(self):
        menu = self.p.create_menu()
        labels = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(labels[-4:], ['打开待办清单', '开启专注模式', '设置', '退出'])
        settings = next(action.menu() for action in menu.actions() if action.text() == '设置')
        actions = {action.text(): action for action in settings.actions()}
        interaction = next(action.menu() for action in menu.actions() if action.text() == '互动')
        self.assertEqual([action.text() for action in interaction.actions() if not action.isSeparator()][-5:],
                         ['追鼠标', '睡一会儿', '伸懒腰', '跳跃', '跳舞'])
        self.assertIn('亲密度说明', actions)
        self.assertNotIn('其他动作', actions)
        self.assertTrue(actions['自动追鼠标'].isChecked())
        actions['自动追鼠标'].trigger()
        actions['自动小睡'].trigger()
        stored, _ = read_save(pet.SAVE_DATA_PATH, pet.LEGACY_DATA_PATH, time.time())
        self.assertFalse(stored['auto_chase'])
        self.assertFalse(stored['auto_nap'])

    def test_startup_menu_toggle_and_boot_greeting(self):
        with patch.object(startup_windows, 'registered_command', side_effect=[None, None, 'registered']), \
             patch.object(startup_windows, 'set_enabled') as change:
            settings = next(action.menu() for action in self.p.create_menu().actions() if action.text() == '设置')
            startup = next(action for action in settings.actions() if action.text() == '开机自启动')
            self.assertTrue(startup.isCheckable())
            self.assertFalse(startup.isChecked())
            startup.trigger()
            settings.aboutToShow.emit()
            change.assert_called_once_with(True)
            self.assertTrue(startup.isChecked())
        boot_pet = pet.DesktopPet(autostart=True)
        self.addCleanup(boot_pet.deleteLater)
        with patch.object(boot_pet, 'show_speech') as speak:
            boot_pet.startup_timer.timeout.emit()
            speak.assert_called_once_with(pet.AUTOSTART_GREETING, 4500, ambient=True)
        boot_pet.shutdown()

    def test_petting_cap_survives_reload_and_resets_next_day(self):
        with patch('pet.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 19, 12)
            for _ in range(DAILY_PET_AFFECTION_LIMIT + 1):
                self.p.last_pet_time = -100.0
                self.p.pet_head()
            self.assertEqual(self.p.affection, DAILY_PET_AFFECTION_LIMIT)
            self.p.load_data()
            self.p.pet_head()
            self.assertEqual(self.p.affection, DAILY_PET_AFFECTION_LIMIT)
            clock.now.return_value = datetime(2026, 11, 20, 12)
            self.p.last_pet_time = -100.0
            self.p.pet_head()
            self.assertEqual(self.p.affection, DAILY_PET_AFFECTION_LIMIT + 1)
            self.assertEqual(self.p.pet_affection_today, 1)

    def test_work_affection_accrues_across_sessions_without_daily_or_rank_cap(self):
        self.p.affection = 4000
        self.p.pet_affection_today = DAILY_PET_AFFECTION_LIMIT
        self.p.start_work()
        self.p.work_total_seconds = WORK_AFFECTION_INTERVAL - 5
        self.p.end_work()
        self.assertEqual(self.p.affection, 4000)
        self.p.start_work()
        self.p.work_last_tick -= 6
        self.p.check_satiety()
        self.assertEqual(self.p.affection, 4001)
        self.assertEqual(self.p.pet_affection_today, DAILY_PET_AFFECTION_LIMIT)
        self.p.load_data()
        self.p.check_satiety()
        self.assertEqual(self.p.affection, 4001)

    def test_autonomous_rotation_includes_chase_and_stretch_without_duplicates(self):
        self.p.satiety = 80
        with patch('pet.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 19, 12)
            actions = []
            for _ in range(9):
                self.p.start_idle()
                self.p.decide_behavior()
                actions.append(self.p.recent_behavior)
            self.assertEqual(len(set(actions[:8])), 8)
            self.assertIn('chase', actions[:8])
            self.assertIn('stretch', actions[:8])
            self.assertNotEqual(actions[7], actions[8])
            self.p.auto_chase = self.p.auto_nap = False
            for _ in range(12):
                self.p.start_idle()
                self.p.decide_behavior()
                self.assertNotIn(self.p.recent_behavior, ('chase', 'sleep'))

    def test_todo_cross_midnight_and_reward_only_once(self):
        tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=30, second=0)
        panel = self.p.todo_panel
        panel.input_edit.setText('看星星')
        panel.time_edit.setDateTime(QDateTime(tomorrow))
        panel.add_todo()
        item = self.p.todo_list[0]
        self.assertEqual(datetime.fromtimestamp(item['due_at']).date(), tomorrow.date())
        panel.on_item_completed(item, True)
        panel.on_item_completed(item, False)
        panel.on_item_completed(item, True)
        self.assertEqual(self.p.candy_count, 1)

    def test_restarting_restores_active_work_but_excludes_offline_time(self):
        self.p.start_work()
        self.p.work_last_tick -= 30
        self.p.save_data()
        saved = self.p.work_session_seconds
        self.p.shutdown()
        self.p.deleteLater()
        self.app.processEvents()
        self.p = pet.DesktopPet()
        self.assertTrue(self.p.working)
        self.assertAlmostEqual(self.p.work_session_seconds, saved, delta=0.1)

    def test_work_reward_progress_survives_break_and_repeated_start(self):
        self.p.start_work()
        self.p.work_total_seconds = 899
        self.p.work_last_tick -= 0.5
        self.p.start_work()
        self.assertGreater(self.p.get_work_elapsed(), 0.4)
        self.p.end_work()
        self.p.start_work()
        self.p.work_last_tick -= 1
        self.p.check_satiety()
        self.assertEqual(self.p.candy_count, 1)
        self.p.check_satiety()
        self.assertEqual(self.p.candy_count, 1)

    def test_work_reminders_are_45_minutes_apart_and_do_not_interrupt_drag(self):
        self.p.start_work()
        self.p.work_session_seconds = 2700
        self.p.state = 'drag'
        self.p.check_satiety()
        self.assertEqual(self.p.state, 'drag')
        self.p.start_idle()
        self.p.check_satiety()
        self.assertEqual(self.p.state, 'stretch')
        self.assertEqual(self.p.next_stretch_seconds, 5400)
        self.p.start_idle()
        self.assertFalse(self.p.stretch_timer.isActive())
        self.p.work_session_seconds = 5100
        self.p.check_satiety()
        self.assertEqual(self.p.state, 'idle')

    def test_sleep_and_window_edges(self):
        self.p.toggle_nap()
        self.p.decide_behavior()
        self.assertEqual(self.p.state, 'sleeping')
        self.assertFalse(self.p.anim_timer.isActive())
        self.p.pet_head()
        self.assertEqual(self.p.state, 'petted')
        bounds = self.p.current_bounds()
        point = self.p.clamp_position(QPoint(-100000, -100000))
        self.assertTrue(bounds.contains(point))
        self.p.move(bounds.bottomRight() - QPoint(self.p.width(), self.p.height()))
        self.p.pos_f = [float(self.p.x()), float(self.p.y())]
        self.p.toggle_panel()
        self.p.toggle_todo_panel()
        self.assertTrue(bounds.contains(self.p.status_panel.geometry()))
        self.assertTrue(bounds.contains(self.p.todo_panel.geometry()))
        self.assertFalse(self.p.status_panel.geometry().intersects(self.p.todo_panel.geometry()))

    def test_motion_accounts_for_elapsed_time_and_caps_resume_gap(self):
        self.p.move(300, 250)
        self.p.pos_f = [300.0, 250.0]
        self.p.state = 'run'
        self.p.vx = -4
        self.p.target_x = 100
        self.p.physics_last_tick = 1000.0
        with patch('pet.time.monotonic', return_value=1000.032):
            self.p.update_physics()
        self.assertAlmostEqual(self.p.pos_f[0], 292, places=3)
        with patch('pet.time.monotonic', return_value=1010.0):
            self.p.update_physics()
        self.assertAlmostEqual(self.p.pos_f[0], 279.5, places=3)

    def test_chase_retargets_both_axes_and_stops_at_cursor(self):
        self.p.move(80, 70)
        self.p.pos_f = [80.0, 70.0]
        pointer = QPoint(380, 420)
        with patch.object(QCursor, 'pos', side_effect=lambda: pointer):
            self.p.start_playful_chase()
            now = time.monotonic()
            for tick in range(10):
                self.p.update_walk(now + tick * 0.016, 0.016)
            self.assertGreater(self.p.x(), 80)
            self.assertGreater(self.p.y(), 70)
            pointer = QPoint(260, 350)
            for tick in range(10, 260):
                if self.p.state != 'chase':
                    break
                self.p.update_walk(now + tick * 0.016, 0.016)
        self.assertEqual(self.p.pos() + QPoint(self.p.width() // 2, self.p.height() // 2), pointer)
        self.assertEqual(self.p.state, 'idle')
        self.assertFalse(self.p.physics_timer.isActive())

    def test_cross_screen_walk_keeps_native_anchor_on_displays_in_both_directions(self):
        left = Display('left', QRect(0, 0, 800, 600), QRect(0, 0, 1200, 900))
        right = Display('right', QRect(1200, 400, 800, 700), QRect(1200, 400, 800, 700))
        self.p.desktop_layout = DesktopLayout([left, right])
        self.p.show()
        for source, target, frame, logical_target in (
            (left, right, (100, 100, 300, 300), QPoint(1360, 850)),
            (right, left, (1600, 850, 200, 200), QPoint(180, 100)),
        ):
            visited = []
            with patch('pet.physical_window_rect', return_value=frame), \
                 patch('pet.move_window_anchor', side_effect=lambda handle, x, y: visited.append(QPointF(x, y)) or True):
                self.p.begin_walk(logical_target)
                self.p.walk_speed = 155
                for tick in range(1400):
                    if self.p.state != 'walk':
                        break
                    self.p.update_walk(tick * 0.016, 0.016)
            self.assertEqual(self.p.state, 'idle')
            self.assertEqual(self.p.pos(), logical_target)
            self.assertTrue(source.physical.contains(visited[0].toPoint()))
            self.assertTrue(target.physical.contains(visited[-1].toPoint()))
            self.assertTrue(all(left.physical.contains(p.toPoint()) or right.physical.contains(p.toPoint())
                                for p in visited))
            for before, after in zip(visited, visited[1:]):
                self.assertLessEqual((after - before).manhattanLength(), 4)

    def test_drag_keeps_fractional_grab_point_when_the_cursor_crosses_screens(self):
        left = QRect(0, 0, 800, 600)
        right = QRect(800, -100, 1024, 700)
        self.p.desktop_layout = DesktopLayout([Display('left', left, left), Display('right', right, right)])
        self.p.show()
        with patch('pet.physical_cursor', side_effect=[(100, 150), (900, 150), (900, 150)]), \
             patch('pet.physical_window_rect', return_value=(75, 75, 200, 200)), \
             patch('pet.move_window_anchor', return_value=True) as move:
            QTest.mousePress(self.p, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
            QTest.mouseMove(self.p, QPoint(140, 90))
            move.assert_called_once_with(int(self.p.winId()), 900, 150, 0.125, 0.375)
            QTest.mouseRelease(self.p, Qt.MouseButton.LeftButton, pos=QPoint(140, 90))
        self.assertEqual(self.p.state, 'idle')
        self.assertIsNone(self.p.drag_anchor)

    def test_focus_short_switch_recovery_and_single_knock(self):
        clock = 100.0
        foreground = (11, 21, False)
        with patch('pet.time.monotonic', side_effect=lambda: clock), \
             patch('pet.foreground_window', side_effect=lambda: foreground), \
             patch('pet.window_pid', return_value=21) as pid:
            self.p.toggle_focus()
            clock += 2.9
            self.p.check_focus()
            self.assertIsNone(self.p.focus_target)
            clock += 0.2
            self.p.check_focus()
            self.assertEqual(self.p.focus_target, (11, 21))
            self.assertEqual(self.p.state, 'focus_sleep')
            self.assertFalse(self.p.physics_timer.isActive())
            corner = self.p.pos()
            foreground = (12, 21, False)  # Switching windows in the same app also counts.
            self.p.check_focus()
            clock += 1
            foreground = (11, 21, False)
            self.p.check_focus()
            self.assertEqual(self.p.state, 'focus_sleep')
            foreground = (12, 21, False)
            self.p.check_focus()
            clock += 2.1
            self.p.check_focus()
            self.assertEqual(self.p.state, 'walk')
            for _ in range(220):
                if self.p.state != 'walk':
                    break
                clock += 0.016
                self.p.update_walk(clock, 0.016)
            self.assertEqual(self.p.state, 'focus_knock')
            clock += 2.6
            self.p.check_focus()
            self.assertEqual(self.p.state, 'focus_sleep')
            self.assertEqual(self.p.pos(), corner)
            clock += 10
            self.p.check_focus()
            self.assertEqual(self.p.state, 'focus_sleep')
            foreground = (11, 21, False)
            self.p.check_focus()
            self.assertFalse(self.p.focus_warned)
            pid.return_value = 0
            self.p.check_focus()
            self.assertFalse(self.p.focus_timer.isActive())

    def test_bubble_replaces_previous_hide_timer(self):
        self.p.show_speech('first', 20)
        self.p.show_speech('second', 250)
        QTest.qWait(40)
        self.assertTrue(self.p.bubble.isVisible())
        self.assertEqual(self.p.bubble.label.text(), 'second')


if __name__ == '__main__':
    unittest.main()
