import unittest

from nekosuneai.android_gameplay.original_coinmaster import (
    PACKAGE, classify_scene, navigation_plan, scene_help,
)


class OriginalCoinMasterTests(unittest.TestCase):
    def test_original_not_board_adventure(self):
        self.assertEqual(PACKAGE, "com.moonactive.coinmaster")
        self.assertNotEqual(PACKAGE, "com.moonactive.cmboard")

    def test_scenes_from_screenshot_text(self):
        self.assertEqual(classify_scene("Spin for BIGGER Rewards! Free spin in 23:59:51"),
                         "reward_wheel")
        self.assertEqual(classify_scene("Village 18"), "village")
        self.assertEqual(classify_scene("POWER BOOST IS ON Hold for AutoSpin"), "slots")
        self.assertEqual(classify_scene("Make ANY purchase"), "popup")
        self.assertEqual(classify_scene("unrecognised text"), "unknown")

    def test_swipe_directions(self):
        down = navigation_plan("slots", "reward_wheel", 690, 1536)
        self.assertEqual(down["action"], "swipe")
        self.assertLess(down["y1"], down["y2"])
        up = navigation_plan("slots", "village", 690, 1536)
        self.assertGreater(up["y1"], up["y2"])
        self.assertEqual(navigation_plan("village", "slots", 690, 1536)["direction"], "down")

    def test_popup_and_unrecognised_screens_cannot_navigate(self):
        for scene in ("popup", "unknown"):
            self.assertEqual(navigation_plan(scene, "slots", 690, 1536)["action"], "wait")

    def test_no_purchase_automation(self):
        self.assertFalse(scene_help()["purchase_actions_allowed"])
        self.assertFalse(scene_help()["auto_navigation_enabled"])

    def test_size_validation(self):
        with self.assertRaises(ValueError):
            navigation_plan("slots", "village", 0, 0)


if __name__ == "__main__":
    unittest.main()
