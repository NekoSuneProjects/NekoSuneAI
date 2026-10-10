import unittest
import time
from unittest.mock import Mock

from nekosuneai.android_gameplay.main_bridge import AndroidGameWorker


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.device = Mock()
        self.device.list_packages.return_value = ["com.example.game"]
        self.device.foreground_package.return_value = "com.example.game"
        self.device.screenshot.return_value = Mock(shape=(1080, 1920, 3))
        self.worker = AndroidGameWorker(
            "https://example.invalid", "android-1", "test-token",
            ["com.example.game"], device=self.device,
        )

    def start(self):
        return self.worker.execute("game.session.start", {
            "session_id": "session-one", "game_id": "com.example.game",
            "expires_epoch": time.time() + 10,
        })


    def test_expired_session_disarms(self):
        self.start()
        self.worker.session_deadline = 0
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() + 10,
                "action": {"type": "tap", "x": 2, "y": 2},
            })
        self.assertFalse(self.worker.session_id)

    def test_action_budget(self):
        self.start()
        self.worker.max_actions = 1
        action = {"session_id": "session-one", "game_id": "com.example.game",
                  "expires_epoch": time.time() + 10,
                  "action": {"type": "back"}}
        self.worker.execute("game.action", action)
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", action)
        self.device.back.assert_called_once()

    def test_persistent_receipts_reload(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "receipts.json"
            self.worker.state_file = state
            self.worker.ack_id = 23
            self.worker.last_result = {"command_id": 23, "ok": True}
            self.worker._persist()
            other = AndroidGameWorker(
                "https://example.invalid", "android-1", "test-token",
                ["com.example.game"], device=self.device, state_file=state,
            )
            self.assertEqual(other.ack_id, 23)
            self.assertEqual(other.last_result["command_id"], 23)


    def test_autoplay_requires_opt_in(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.worker.execute("game.autoplay.start", {
                "session_id": "session-one", "goal": "Play safely",
                "expires_epoch": time.time() + 10,
            })

    def test_autoplay_is_session_scoped(self):
        self.start()
        autoplay = Mock()
        autoplay.status.return_value = {"running": True}
        autoplay.start.return_value = {"autoplay": "started"}
        self.worker.autoplay = autoplay
        with self.assertRaises(PermissionError):
            self.worker.execute("game.autoplay.start", {
                "session_id": "wrong", "goal": "Play safely",
                "expires_epoch": time.time() + 10,
            })
        with self.assertRaises(PermissionError):
            self.worker.execute("game.autoplay.start", {
                "session_id": "session-one", "goal": "Play safely",
                "expires_epoch": time.time() - 10,
            })
        result = self.worker.execute("game.autoplay.start", {
            "session_id": "session-one", "goal": "Play safely",
            "expires_epoch": time.time() + 10,
        })
        self.assertEqual(result["autoplay"], "started")
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() + 10,
                "action": {"type": "back"},
            })
        self.worker.execute("game.input.stop", {})
        autoplay.stop.assert_called_once()

    def test_expired_start_is_blocked(self):
        with self.assertRaises(PermissionError):
            self.worker.execute("game.session.start", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() - 10,
            })

    def test_pause_resume(self):
        self.start()
        self.worker.execute("game.session.pause", {"session_id": "session-one"})
        self.assertTrue(self.worker.paused)
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() + 5,
                "action": {"type": "back"},
            })
        self.worker.execute("game.session.resume", {"session_id": "session-one"})
        self.assertFalse(self.worker.paused)

    def test_stale_action_rejected(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() - 5,
                "action": {"type": "back"},
            })
        self.device.back.assert_not_called()

    def test_missing_expiry_rejected(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "action": {"type": "back"},
            })

    def test_rejects_unapproved_package(self):
        with self.assertRaises(PermissionError):
            self.worker.execute("game.session.start", {
                "session_id": "session-one", "game_id": "com.other.game",
                "expires_epoch": time.time() + 10,
            })

    def test_game_bound_tap(self):
        self.start()
        result = self.worker.execute("game.action", {
            "session_id": "session-one", "game_id": "com.example.game",
            "expires_epoch": time.time() + 10,
            "action": {"type": "tap", "x": 500, "y": 250},
        })
        self.assertEqual(result["executed"], "tap")
        self.device.tap.assert_called_once_with(500, 250)

    def test_wrong_session_blocked(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "other", "game_id": "com.example.game",
                "expires_epoch": time.time() + 10,
                "action": {"type": "tap", "x": 10, "y": 10},
            })
        self.device.tap.assert_not_called()

    def test_out_of_bounds_rejected(self):
        self.start()
        with self.assertRaises(ValueError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "expires_epoch": time.time() + 10,
                "action": {"type": "tap", "x": 9999, "y": 10},
            })
        self.device.tap.assert_not_called()

    def test_focus_loss_stops_session(self):
        self.start()
        self.device.foreground_package.return_value = "com.other.app"
        with self.assertRaises(PermissionError):
            self.worker.execute("game.observe", {})
        self.assertFalse(self.worker.session_id)

    def test_stop(self):
        self.start()
        self.worker.execute("game.input.stop", {})
        self.assertFalse(self.worker.session_id)

    def test_unsupported_shell_blocked(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.worker.execute("game.action", {
                "session_id": "session-one", "game_id": "com.example.game",
                "action": {"type": "shell", "command": "rm -rf /"},
            })


if __name__ == "__main__":
    unittest.main()
