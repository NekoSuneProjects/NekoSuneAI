import unittest
from unittest.mock import Mock

from nekosuneai.android_gameplay.game_detection import detect_foreground, identify_game


class GameDetectionTests(unittest.TestCase):
    def test_board_adventure(self):
        game = identify_game("com.moonactive.cmboard", ["com.moonactive.cmboard"])
        self.assertEqual(game["game_name"], "Coin Master – Board Adventure")
        self.assertTrue(game["playing"])
        self.assertTrue(game["known_game"])

    def test_unapproved_known_game(self):
        game = identify_game("com.moonactive.cmboard", [])
        self.assertFalse(game["playing"])
        self.assertFalse(game["approved"])

    def test_unknown_app_not_guessed(self):
        game = identify_game("com.example.unknown", ["com.example.unknown"])
        self.assertEqual(game["game_name"], "Unknown app")
        self.assertFalse(game["known_game"])

    def test_device_foreground(self):
        device = Mock()
        device.foreground_package.return_value = "com.moonactive.cmboard"
        game = detect_foreground(device, ["com.moonactive.cmboard"])
        self.assertEqual(game["package_id"], "com.moonactive.cmboard")


if __name__ == "__main__":
    unittest.main()
