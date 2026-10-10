import unittest

from nekosuneai.android_gameplay.disney_solitaire import (
    PACKAGE, adjacent, classify_scene, legal_moves, parse_rank, propose_action, profile,
)


class DisneySolitaireTests(unittest.TestCase):
    def test_package_and_profile(self):
        self.assertEqual(PACKAGE, "com.superplaystudios.disneysolitairedreams")
        self.assertEqual(profile()["gameplay"], "tripeaks")
        self.assertFalse(profile()["purchases_enabled"])

    def test_card_rank_rules(self):
        self.assertEqual(parse_rank("J"), 11)
        self.assertTrue(adjacent("J", "10"))
        self.assertTrue(adjacent("A", "K"))
        self.assertTrue(adjacent("6", "5"))
        self.assertFalse(adjacent("8", "5"))
        self.assertFalse(adjacent("invalid", "5"))

    def test_move_safety(self):
        cards = [{"rank": "6", "x": 450, "y": 200, "exposed": True, "confidence": 0.99},
                 {"rank": "4", "x": 550, "y": 200, "exposed": False, "confidence": 1},
                 {"rank": "7", "x": 650, "y": 200, "exposed": True, "confidence": 1},
                 {"rank": "4", "x": 300, "y": 200, "exposed": True, "confidence": 0.75}]
        moves = legal_moves("5", cards)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["rank"], "6")
        self.assertTrue(moves[0]["requires_fresh_observation"])

    def test_scenes(self):
        self.assertEqual(classify_scene("YOU DID IT! TAP ANYWHERE TO COLLECT"), "reward")
        self.assertEqual(classify_scene("NEED STARS? Win Levels"), "stars_help")
        self.assertEqual(classify_scene("TALE AS OLD AS TIME SCENE PROGRESS 3/6"), "scene_progress")
        self.assertEqual(classify_scene("LEVEL 2 PLAY"), "level_start")
        self.assertEqual(classify_scene("Tap a card one rank higher or lower"), "tutorial")

    def test_no_blind_moves(self):
        self.assertEqual(propose_action("unknown")["action"], "wait")
        self.assertEqual(propose_action("board", foundation_rank="5")["action"], "wait")
        self.assertEqual(propose_action("stars_help")["action"], "wait")


if __name__ == "__main__":
    unittest.main()
