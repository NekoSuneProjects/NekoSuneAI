import unittest
from unittest.mock import Mock

from nekosuneai.android_gameplay.game_detection import detect_foreground, identify_game


class GameDetectionTests(unittest.TestCase):
    def test_other_supported_android_games(self):
        expected = {
            "com.moonactive.coinmaster": "Coin Master",
            "com.superplaystudios.disneysolitairedreams": "Disney Solitaire",
            "com.superplaystudios.dicedreams": "Dice Dreams",
        }
        for package, title in expected.items():
            with self.subTest(package=package):
                game = identify_game(package, [package])
                self.assertEqual(game["game_name"], title)
                self.assertEqual(game["game_id"], package)
                self.assertTrue(game["known_game"])
                self.assertTrue(game["playing"])

    def test_original_coin_master_is_distinct_from_board_adventure(self):
        original = identify_game("com.moonactive.coinmaster",
                                 ["com.moonactive.coinmaster"])
        board = identify_game("com.moonactive.cmboard",
                              ["com.moonactive.cmboard"])
        self.assertNotEqual(original["game_id"], board["game_id"])
        self.assertNotEqual(original["game_name"], board["game_name"])

    def test_eight_new_known_games_are_registered(self):
        expected = {
            "com.global.pnck": "Puzzles & Chaos: Frozen Castle",
            "com.global.mus": "MU: Dark Epoch",
            "com.yottagames.gameofmafia": "The Grand Mafia",
            "air.com.buffalo_studios.newflashbingo": "Bingo Blitz",
            "com.innplaylabs.animalkingdomraid": "Animals & Coins Adventure Game",
            "com.lilithgame.roc.gp": "Rise of Kingdoms: Lost Crusade",
            "com.supersolid.cookandmerge": "Cook & Merge Kate's Adventure",
            "com.pocketchamps.game": "Pocket Champs: 3D Racing Games",
        }
        for package, name in expected.items():
            with self.subTest(package=package):
                game = identify_game(package, [package])
                self.assertEqual(game["game_name"], name)
                self.assertEqual(game["package_id"], package)
                self.assertEqual(game["game_id"], package)
                self.assertTrue(game["known_game"])
                self.assertTrue(game["playing"])

    def test_raid_shadow_legends_package(self):
        package = "com.plarium.raidlegends"
        game = identify_game(package, [package])
        self.assertEqual(game["game_name"], "RAID: Shadow Legends")
        self.assertEqual(game["game_id"], package)
        self.assertTrue(game["known_game"])

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
