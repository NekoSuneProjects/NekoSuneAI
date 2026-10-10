import time
import unittest

from nekosuneai.android_game_sessions import AndroidGameSessions


class FakeRegistry:
    def __init__(self):
        self.queued = []
        self.nodes = [{"node_id": "android-1", "node_type": "android-gaming",
                       "online": True},
                      {"node_id": "windows-1", "node_type": "windows-gaming",
                       "online": True}]

    def list_nodes(self):
        return self.nodes

    def enqueue(self, node_id, capability, arguments, **kwargs):
        item = {"id": len(self.queued) + 1, "capability": capability,
                "arguments": arguments, "confirmed": kwargs.get("confirmed")}
        self.queued.append(item)
        return item


class AndroidSessionsTest(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.api = AndroidGameSessions(self.registry)

    def start(self):
        return self.api.command("start", {"node_id": "android-1",
                                         "game_id": "com.example.game",
                                         "duration_seconds": 300})

    def test_session_reports_queued_before_device_ack(self):
        started = self.start()
        status = self.api.status("android-1")
        self.assertEqual(status["phase"], "awaiting-device")
        self.assertFalse(status["device_confirmed"])
        self.assertEqual(status["start_command_id"], started["command"]["id"])

    def test_session_reports_device_confirmation(self):
        started = self.start()
        sid = started["session"]["session_id"]
        self.registry.nodes[0]["state"] = {"session_id": sid, "input_disabled": False}
        status = self.api.status("android-1")
        self.assertEqual(status["phase"], "active")
        self.assertTrue(status["device_confirmed"])

    def test_session_reports_rejected_start(self):
        started = self.start()
        self.registry.nodes[0]["state"] = {"last_command_result": {
            "command_id": started["command"]["id"], "ok": False}}
        self.assertEqual(self.api.status("android-1")["phase"], "start-rejected")
    def test_session_survives_backend_restart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "android-sessions.json"
            first = AndroidGameSessions(self.registry, state_file=path)
            started = first.command("start", {"node_id": "android-1",
                                              "game_id": "com.example.game"})
            recovered = AndroidGameSessions(self.registry, state_file=path)
            self.assertEqual(recovered.status("android-1")["session_id"],
                             started["session"]["session_id"])
            self.assertEqual(recovered.status("android-1")["phase"], "awaiting-device")
            recovered.command("emergency-stop", {"node_id": "android-1"})
            fresh = AndroidGameSessions(self.registry, state_file=path)
            self.assertIsNone(fresh.status("android-1"))

    def test_autoplay_requires_goal(self):
        sid = self.start()["session"]["session_id"]
        with self.assertRaises(ValueError):
            self.api.command("autoplay", {"node_id": "android-1",
                        "session_id": sid, "goal": ""})
        response = self.api.command("autoplay", {"node_id": "android-1",
                    "session_id": sid, "goal": "Play safely"})
        self.assertEqual(response["command"]["capability"], "game.autoplay.start")
        self.assertGreater(response["command"]["arguments"]["expires_epoch"], time.time())

    def test_emergency_stop_without_session_id(self):
        self.start()
        stopped = self.api.command("emergency-stop", {"node_id": "android-1"})
        self.assertEqual(stopped["command"]["capability"], "game.input.stop")
        self.assertIsNone(stopped["session"])

    def test_status_recovers_active_session(self):
        session = self.start()["session"]
        self.assertEqual(self.api.status("android-1")["session_id"],
                         session["session_id"])

    def test_devices_exclude_windows(self):
        self.assertEqual([n["node_id"] for n in self.api.devices()], ["android-1"])

    def test_start_and_stop(self):
        started = self.start()
        sid = started["session"]["session_id"]
        self.assertEqual(started["command"]["capability"], "game.session.start")
        ended = self.api.command("stop", {"node_id": "android-1", "session_id": sid})
        self.assertEqual(ended["command"]["capability"], "game.session.stop")
        self.assertIsNone(ended["session"])

    def test_expiring_typed_action(self):
        sid = self.start()["session"]["session_id"]
        action = self.api.command("action", {
            "node_id": "android-1", "session_id": sid,
            "action": {"type": "tap", "x": 500, "y": 150},
        })
        cmd = action["command"]
        self.assertEqual(cmd["capability"], "game.action")
        self.assertEqual(cmd["arguments"]["game_id"], "com.example.game")
        self.assertGreater(cmd["arguments"]["expires_epoch"], time.time())

    def test_reject_shell_and_wrong_node(self):
        sid = self.start()["session"]["session_id"]
        with self.assertRaises(ValueError):
            self.api.command("action", {"node_id": "android-1",
                       "session_id": sid, "action": {"type": "shell", "cmd": "whoami"}})
        with self.assertRaises(ValueError):
            self.api.command("start", {"node_id": "windows-1",
                                       "game_id": "com.example.game"})

    def test_session_mismatch(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.api.command("action", {"node_id": "android-1",
                          "session_id": "wrong", "action": {"type": "back"}})

    def test_bad_coordinates(self):
        sid = self.start()["session"]["session_id"]
        with self.assertRaises(ValueError):
            self.api.command("action", {"node_id": "android-1",
                "session_id": sid, "action": {"type": "tap", "x": -1, "y": 5}})

    def test_budget(self):
        self.api.command("start", {"node_id": "android-1",
                       "game_id": "com.example.game", "max_actions": 1})
        sid = self.api.sessions["android-1"]["session_id"]
        self.api.command("action", {"node_id": "android-1",
                        "session_id": sid, "action": {"type": "back"}})
        with self.assertRaises(PermissionError):
            self.api.command("action", {"node_id": "android-1",
                            "session_id": sid, "action": {"type": "back"}})


if __name__ == "__main__":
    unittest.main()
