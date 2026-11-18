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

from PyQt6.QtCore import QDateTime, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QCursor, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import pet
from pet_core import behavior_weights, normalize_data, read_save, write_save


class StorageTests(unittest.TestCase):
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
