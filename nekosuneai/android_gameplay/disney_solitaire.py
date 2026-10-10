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

def propose_action(scene, *, foundation_rank=None, exposed_cards=(), screen_width=0, screen_height=0):
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
                                 "scene_progress", "stars_help", "unknown"],
            "purchases_enabled": False, "blind_auto_play": False}
