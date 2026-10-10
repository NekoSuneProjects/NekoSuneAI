"""Original Coin Master navigation; NEVER used for Board Adventure.

Coordinates are proportional to the current Android screen. Navigation is
read-only planning: actions must still pass the owner-approved session, current
foreground, expiry, and budget checks in the paired worker.
"""
from __future__ import annotations

PACKAGE = "com.moonactive.coinmaster"
SCENES = ("slots", "village", "reward_wheel", "popup", "unknown")

# Evidence extracted by screenshot vision/OCR, not a package-name guess.
_TEXT_CUES = (
    ("starter surprises", "popup"),
    ("village news", "popup"),
    ("join our channel", "popup"),
    ("wildland adventure", "popup"),
    ("merge rush", "popup"),
    ("make any purchase", "popup"),
    ("spin for bigger rewards", "reward_wheel"),
    ("free spin in", "reward_wheel"),
    ("village ", "village"),
    ("hold for autospin", "slots"),
    ("power boost is on", "slots"),
)

def classify_scene(visible_text):
    """Conservative text-based scene recognition; unknown is never a tap."""
    text = " ".join(str(s) for s in visible_text).lower() if not isinstance(visible_text, str) else visible_text.lower()
    for cue, scene in _TEXT_CUES:
        if cue in text:
            return scene
    return "unknown"


def navigation_plan(current_scene, destination, width, height):
    """Return a bounded swipe proposal; do not execute blindly.

    In original Coin Master the slot screen connects to the reward wheel by
    swiping DOWN, and to the village by swiping UP. Reverse from those scenes.
    """
    if type(width) is not int or type(height) is not int or width < 100 or height < 200:
        raise ValueError("Invalid screenshot dimensions")
    routes = {
        ("slots", "reward_wheel"): "down",
        ("reward_wheel", "slots"): "up",
        ("slots", "village"): "up",
        ("village", "slots"): "down",
    }
    if current_scene == destination:
        return {"action": "wait", "reason": "Already on requested scene"}
    if current_scene == "popup":
        return {"action": "wait", "reason": "Dismiss overlay only after identifying a safe close control"}
    direction = routes.get((current_scene, destination))
    if not direction:
        return {"action": "wait", "reason": "No verified direct route between these scenes"}
    # Central swipes avoid the top-right menu, side events, paid offers, and
    # bottom slot / reward controls. This is a proposal, not a click policy.
    x = round(width * 0.51)
    y1, y2 = (round(height * 0.36), round(height * 0.67)) if direction == "down" else (round(height * 0.67), round(height * 0.36))
    return {"action": "swipe", "x1": x, "y1": y1, "x2": x,
            "y2": y2, "duration_ms": 400, "direction": direction,
            "requires_confirmed_scene": current_scene,
            "destination": destination}


def scene_help():
    return {
        "package_id": PACKAGE,
        "game_name": "Coin Master",
        "supported_scenes": list(SCENES),
        "routes": ["slots -> reward_wheel: swipe down",
                   "reward_wheel -> slots: swipe up",
                   "slots -> village: swipe up",
                   "village -> slots: swipe down"],
        "purchase_actions_allowed": False,
        "auto_navigation_enabled": False,
    }
