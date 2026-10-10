"""Disney Solitaire / TriPeaks gameplay profile (landscape screenshots).

Only provides scene observations and move proposals. It never sends ADB input.
A move must be verified from a fresh screenshot and routed through the
existing session-bound action budget. Tutorial and purchases are not automated.
"""
from __future__ import annotations
import re

PACKAGE = "com.superplaystudios.disneysolitairedreams"

def classify_scene(texts):
    text = (" ".join(str(t) for t in texts) if not isinstance(texts, str) else texts).lower()
    if any(phrase in text for phrase in ("special offer", "limited offer", "purchase", "buy now", "no ads", "remove ads", "£", "$", "€", "usd", "gbp", "eur")):
        return "payment_popup"
    if "wild card matches any card" in text and "complete your streak" in text:
        return "wild_card_hint"
    if "extra cards" in text and "run out" in text:
        return "extra_cards_hint"
    if "tap anywhere to collect" in text and "you did it" in text:
        return "reward"
    if "need stars?" in text:
        return "stars_help"
    if "tale as old as time" in text or "scene progress" in text:
        return "scene_progress"
    if re.search(r"\blevel\s+\d+", text) and "play" in text:
        return "level_start"
    if "one rank higher or lower" in text:
        return "tutorial"
    if "streak bonus" in text or "stock" in text or "cards" in text:
        return "board"
    return "unknown"

RANKS = {"A": 1, "J": 11, "Q": 12, "K": 13}

def parse_rank(value):
    if type(value) is int:
        return value if 1 <= value <= 13 else None
    token = str(value or "").strip().upper()
    if token in RANKS:
        return RANKS[token]
    if token == "10":
        return 10
    if token.isdigit():
        n = int(token)
        return n if 2 <= n <= 9 else None
    return None

def adjacent(rank, foundation_rank):
    """TriPeaks adjacent values, including A/K wraparound."""
    a, b = parse_rank(rank), parse_rank(foundation_rank)
    return a is not None and b is not None and (abs(a - b) == 1 or {a, b} == {1, 13})

def legal_moves(foundation_rank, exposed_cards):
    """Exposed cards come from vision; occluded or uncertain cards are ignored.

    Card item: rank, x, y, exposed=True, confidence in [0,1].
    Coordinates are verified by action layer against the current frame.
    """
    moves = []
    for card in exposed_cards:
        if not isinstance(card, dict) or card.get("exposed") is not True:
            continue
        confidence = card.get("confidence", 0)
        if type(confidence) not in (float, int) or confidence < 0.85:
            continue
        if not adjacent(card.get("rank"), foundation_rank):
            continue
        if any(type(card.get(k)) is not int or card[k] < 0 for k in ("x", "y")):
            continue
        moves.append({"action": "tap", "x": card["x"], "y": card["y"],
                      "rank": str(card["rank"]), "confidence": confidence,
                      "requires_fresh_observation": True})
    return moves

def payment_close_action(close_buttons, width, height):
    """Only close a payment dialog using an independently detected X.

    The supplied button must come from fresh vision/OCR and fall in the upper
    portion of the screen; missing/ambiguous detections must never be guessed.
    """
    if type(width) is not int or type(height) is not int or width < 400 or height < 250:
        return {"action": "wait", "reason": "No verified screen dimensions"}
    valid = []
    for button in close_buttons:
        if not isinstance(button, dict) or str(button.get("label", "")).strip().lower() not in ("x", "×", "close"):
            continue
        x, y, confidence = button.get("x"), button.get("y"), button.get("confidence")
        if (type(x) is int and type(y) is int and
                type(confidence) in (float, int) and confidence >= 0.9 and
                width * 0.45 <= x < width * 0.98 and
                height * 0.03 <= y <= height * 0.45):
            valid.append((x, y))
    if len(valid) != 1:
        return {"action": "wait", "reason": "Cannot confidently identify a unique payment-popup X"}
    return {"action": "tap", "x": valid[0][0], "y": valid[0][1],
            "reason": "Dismiss payment offer via X; never accept purchases",
            "requires_fresh_observation": True}


def tutorial_button_action(button, width, height, kind):
    """Suggest only a verified, highlighted tutorial button in its safe area.

    Each button must have a fresh, positive detector result, not just the OCR
    instruction or hardcoded pixels from a particular emulator resolution.
    """
    if type(width) is not int or type(height) is not int or width < 400 or height < 250:
        return {"action": "wait", "reason": "No verified screen dimensions"}
    if not isinstance(button, dict):
        return {"action": "wait", "reason": "Tutorial button not observed"}
    if str(button.get("kind", "")).lower() != kind:
        return {"action": "wait", "reason": "Wrong tutorial button type"}
    x, y = button.get("x"), button.get("y")
    confidence = button.get("confidence")
    if (type(x) is not int or type(y) is not int or
            type(confidence) not in (int, float) or not 0.9 <= confidence <= 1.0 or
            button.get("highlighted") is not True or
            not (0 <= x < width and height * 0.64 <= y < height * 0.96)):
        return {"action": "wait", "reason": "Tutorial button is not safely identified"}
    if kind == "wild_card":
        # Must be available and on the right edge, not an ad/offer.
        if type(button.get("count")) is not int or button["count"] <= 0 or x < width * 0.78:
            return {"action": "wait", "reason": "No available confirmed WILD card"}
    elif kind == "extra_cards":
        if not width * 0.35 <= x <= width * 0.65 or button.get("free") is not True:
            return {"action": "wait", "reason": "Extra cards are not confirmed free"}
    else:
        return {"action": "wait", "reason": "Unsupported tutorial action"}
    return {"action": "tap", "x": x, "y": y, "requires_fresh_observation": True,
            "reason": "Use confirmed free tutorial " + kind}


def propose_action(scene, *, foundation_rank=None, exposed_cards=(), screen_width=0, screen_height=0,
                   close_buttons=(), extra_cards_button=None, wild_button=None):
    if scene == "extra_cards_hint":
        return tutorial_button_action(extra_cards_button, screen_width, screen_height, "extra_cards")
    if scene == "wild_card_hint":
        return tutorial_button_action(wild_button, screen_width, screen_height, "wild_card")
    if scene == "payment_popup":
        return payment_close_action(close_buttons, screen_width, screen_height)
    if scene == "board":
        moves = legal_moves(foundation_rank, exposed_cards)
        return moves[0] if len(moves) == 1 else {
            "action": "wait", "reason": "No unique, confident, legal uncovered card"}
    if scene == "reward":
        if screen_width >= 400 and screen_height >= 250:
            return {"action": "tap", "x": screen_width // 2,
                    "y": round(screen_height * 0.86),
                    "requires_fresh_observation": True, "reason": "Collect earned reward"}
    return {"action": "wait", "reason": "No safe automatic action for current scene"}

def profile():
    return {"package_id": PACKAGE, "game_name": "Disney Solitaire",
            "orientation": "landscape", "gameplay": "tripeaks",
            "supported_scenes": ["board", "tutorial", "reward", "level_start",
                                 "scene_progress", "stars_help", "payment_popup",
                                 "extra_cards_hint", "wild_card_hint", "unknown"],
            "purchases_enabled": False, "blind_auto_play": False}
