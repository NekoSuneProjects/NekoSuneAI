import unittest

from nekosuneai.android_gameplay.disney_solitaire import (
    PACKAGE, adjacent, classify_scene, legal_moves, parse_rank, propose_action, profile, payment_close_action,
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

    def test_payment_dialog_is_detected_before_other_scenes(self):
        self.assertEqual(classify_scene("SPECIAL OFFER $4.99 STREAK BONUS"), "payment_popup")
        self.assertEqual(classify_scene("BUY NOW £3.99"), "payment_popup")

    def test_payment_dialog_rejects_unknown_or_ambiguous_close_buttons(self):
        self.assertEqual(propose_action("payment_popup", screen_width=1536,
                                        screen_height=691)["action"], "wait")
        safe = {"label": "X", "x": 1100, "y": 124, "confidence": 0.99}
        self.assertEqual(payment_close_action([safe, safe], 1536, 691)["action"], "wait")
        self.assertEqual(payment_close_action([
            {"label": "X", "x": 1100, "y": 124, "confidence": 0.5}], 1536, 691)["action"], "wait")

    def test_payment_dialog_uses_only_verified_x(self):
        button = {"label": "X", "x": 1100, "y": 124, "confidence": 0.98}
        action = propose_action("payment_popup", screen_width=1536,
                                screen_height=691, close_buttons=[button])
        self.assertEqual(action["action"], "tap")
        self.assertEqual((action["x"], action["y"]), (1100, 124))
        self.assertTrue(action["requires_fresh_observation"])
        self.assertNotIn("purchase", action)

    def test_extra_cards_tutorial_requires_free_verified_button(self):
        self.assertEqual(classify_scene("You can get extra cards if you run out!"),
                         "extra_cards_hint")
        button = {"kind": "extra_cards", "x": 745, "y": 773,
                  "confidence": 0.98, "highlighted": True, "free": True}
        action = propose_action("extra_cards_hint", screen_width=1591,
                                screen_height=929, extra_cards_button=button)
        self.assertEqual(action["action"], "tap")
        self.assertEqual((action["x"], action["y"]), (745, 773))
        self.assertEqual(propose_action("extra_cards_hint", screen_width=1591,
                         screen_height=929,
                         extra_cards_button={**button, "free": False})["action"], "wait")
        self.assertEqual(propose_action("extra_cards_hint", screen_width=1591,
                         screen_height=929)["action"], "wait")

    def test_wild_tutorial_requires_available_highlighted_card(self):
        self.assertEqual(classify_scene(
            "Wild Card matches any card, complete your streak!"), "wild_card_hint")
        button = {"kind": "wild_card", "x": 1457, "y": 761,
                  "confidence": 0.99, "highlighted": True, "count": 1}
        action = propose_action("wild_card_hint", screen_width=1591,
                                screen_height=929, wild_button=button)
        self.assertEqual(action["action"], "tap")
        self.assertEqual((action["x"], action["y"]), (1457, 761))
        for invalid in ({**button, "count": 0},
                        {**button, "highlighted": False},
                        {**button, "confidence": 0.5}):
            self.assertEqual(propose_action(
                "wild_card_hint", screen_width=1591,
                screen_height=929, wild_button=invalid)["action"], "wait")

    def test_purchase_popup_has_priority_over_tutorial(self):
        text = "Buy now £2.99! Wild Card matches any card, complete your streak!"
        self.assertEqual(classify_scene(text), "payment_popup")
        self.assertEqual(propose_action("payment_popup", screen_width=1591,
                         screen_height=929)["action"], "wait")

    def test_no_blind_moves(self):
        self.assertEqual(propose_action("unknown")["action"], "wait")
        self.assertEqual(propose_action("board", foundation_rank="5")["action"], "wait")
        self.assertEqual(propose_action("stars_help")["action"], "wait")


if __name__ == "__main__":
    unittest.main()
