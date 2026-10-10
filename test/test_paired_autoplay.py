import time
import unittest
from unittest.mock import Mock

from nekosuneai.android_gameplay.paired_autoplay import GuardedAndroidDevice, PairedAutoplay


class GuardedAutoplayTests(unittest.TestCase):
    def setUp(self):
        self.device = Mock()
        self.device.foreground_package.return_value = "com.example.game"
        self.worker = Mock()
        self.worker.session_id = "session-1"
        self.worker.package = "com.example.game"
        self.worker.paused = False
        self.worker.stop_event.is_set.return_value = False
        self.worker.session_deadline = time.monotonic() + 60
        self.worker.max_actions = 2
        self.worker.actions_used = 0
        self.autoplay = PairedAutoplay(self.worker, "http://127.0.0.1:11434", "test-model")
        self.guarded = GuardedAndroidDevice(
            self.device, self.worker.package,
            lambda: bool(self.worker.session_id) and not self.worker.paused
            and time.monotonic() < self.worker.session_deadline
            and self.worker.actions_used < self.worker.max_actions,
            on_action=self.autoplay._account_action,
        )

    def test_counts_real_actions_and_enforces_budget(self):
        self.guarded.tap(10, 20)
        self.assertEqual(self.worker.actions_used, 1)
        self.guarded.back()
        self.assertEqual(self.worker.actions_used, 2)
        with self.assertRaises(PermissionError):
            self.guarded.tap(11, 22)
        self.assertEqual(self.device.tap.call_count, 1)

    def test_session_deadline_blocks_autoplay(self):
        self.worker.session_deadline = time.monotonic() - 1
        with self.assertRaises(PermissionError):
            self.guarded.tap(10, 20)
        self.device.tap.assert_not_called()

    def test_pause_blocks_autoplay(self):
        self.worker.paused = True
        with self.assertRaises(PermissionError):
            self.guarded.swipe(1, 2, 3, 4, 200)

    def test_changed_foreground_blocks_autoplay(self):
        self.device.foreground_package.return_value = "com.other.app"
        with self.assertRaises(PermissionError):
            self.guarded.tap(10, 20)

    def test_restricts_text_and_home(self):
        for method in ("type_text", "home"):
            with self.assertRaises(PermissionError):
                getattr(self.guarded, method)("secret") if method == "type_text" else self.guarded.home()

    def test_guards_launch_package(self):
        with self.assertRaises(PermissionError):
            self.guarded.launch_package("com.other.app")


if __name__ == "__main__":
    unittest.main()
