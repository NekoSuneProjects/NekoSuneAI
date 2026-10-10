import tempfile
import unittest
from pathlib import Path

from nekosuneai.vrchat_world_learning import AmongUsObserver, detect_stage


class AmongUsWorldTests(unittest.TestCase):
    def test_stage_recognition(self):
        self.assertEqual(detect_stage("Emergency Meeting. Discussion")[0], "meeting")
        self.assertEqual(detect_stage("Skip Vote. Voting ends")[0], "voting")
        self.assertEqual(detect_stage("Complete task: Fix wiring")[0], "tasks")

    def test_requires_positive_world_confirmation(self):
        with tempfile.TemporaryDirectory() as path:
            observer = AmongUsObserver(Path(path) / "memory.json")
            frame = {"ok": True, "window_title": "VRChat", "ocr": "Complete task", "scene_hash": "a"}
            self.assertFalse(observer.observe(frame)["ok"])
            self.assertEqual(observer.summary()["samples"], 0)

    def test_rejects_non_vrchat_foreground(self):
        with tempfile.TemporaryDirectory() as path:
            observer = AmongUsObserver(Path(path) / "memory.json")
            self.assertFalse(observer.observe({"ok": True, "window_title": "Browser",
                "ocr": "complete task"}, world_confirmed=True)["ok"])

    def test_saves_read_only_memory_and_recovers(self):
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / "memory.json"
            obs = AmongUsObserver(file)
            result = obs.observe({"ok": True, "window_title": "VRChat", "ocr":
                "Complete task: Fix wiring", "scene_hash": "a"}, world_confirmed=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["stage"], "tasks")
            self.assertEqual(result["actions_executed"], 0)
            self.assertTrue(all(x["execute"] is False for x in result["suggestions"]))
            self.assertEqual(AmongUsObserver(file).summary()["stage_counts"]["tasks"], 1)

    def test_memory_bounded(self):
        with tempfile.TemporaryDirectory() as path:
            obs = AmongUsObserver(Path(path) / "memory.json")
            for i in range(255):
                obs.observe({"ok": True, "window_title": "VRChat",
                             "ocr": "TASKS", "scene_hash": str(i)},
                            world_confirmed=True)
            self.assertEqual(obs.summary()["samples"], 250)


if __name__ == "__main__":
    unittest.main()
