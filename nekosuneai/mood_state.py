from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass

from .database import get_state, set_state

STATE_KEY = "companion_mood_v1"


@dataclass
class MoodState:
    """Persistent simulated affect state used for presentation and response tone.

    This is deliberately a bounded software state, not a claim of sentience or
    human emotional needs. Values slowly return toward neutral and must never be
    used to guilt, threaten, or pressure the user into continuing interaction.
    """

    valence: float = 0.15       # -1 sad/negative, +1 positive
    arousal: float = 0.25       # 0 calm, 1 energetic
    trust: float = 0.65         # 0 cautious, 1 comfortable
    caution: float = 0.10       # 0 relaxed, 1 guarded/scared presentation
    last_update_epoch: float = 0.0

    def clamp(self) -> None:
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(0.0, min(1.0, self.arousal))
        self.trust = max(0.0, min(1.0, self.trust))
        self.caution = max(0.0, min(1.0, self.caution))

    def expression(self) -> str:
        if self.caution >= 0.62 and self.trust <= 0.45:
            return "scared"
        if self.valence <= -0.48:
            return "sad"
        if self.valence >= 0.55 and self.arousal >= 0.58:
            return "excited"
        if self.valence >= 0.30:
            return "happy"
        if self.arousal >= 0.72 and self.valence < 0.05:
            return "angry"
        if self.arousal <= 0.18 and self.valence >= -0.10:
            return "relaxed"
        return "neutral"

    def gesture(self) -> str:
        return {
            "scared": "guarded",
            "sad": "slouch",
            "excited": "excited",
            "happy": "wave",
            "angry": "emphatic",
            "relaxed": "relaxed",
        }.get(self.expression(), "idle")

    def short_context(self) -> str:
        return (
            "Simulated companion affect state: "
            f"mood={self.expression()}, valence={self.valence:.2f}, "
            f"arousal={self.arousal:.2f}, trust={self.trust:.2f}, caution={self.caution:.2f}. "
            "Use this only as subtle tone/personality context. Never claim these are biological feelings, "
            "never guilt the user, and never say the user must stay, provide attention, or take care of you."
        )


def load_mood() -> MoodState:
    try:
        raw = json.loads(get_state(STATE_KEY, "{}"))
        mood = MoodState(**{k: raw[k] for k in asdict(MoodState()).keys() if k in raw}) if raw else MoodState()
    except (TypeError, ValueError, json.JSONDecodeError):
        mood = MoodState()
    _decay(mood)
    return mood


def save_mood(mood: MoodState) -> None:
    mood.clamp()
    mood.last_update_epoch = time.time()
    set_state(STATE_KEY, json.dumps(asdict(mood), ensure_ascii=False))


def _decay(mood: MoodState) -> None:
    now = time.time()
    if not mood.last_update_epoch:
        mood.last_update_epoch = now
        return
    hours = max(0.0, (now - mood.last_update_epoch) / 3600.0)
    # Move gradually back toward a mildly positive, calm baseline. This avoids
    # permanent negative spirals and keeps old interactions from dominating.
    factor = min(0.75, hours * 0.025)
    mood.valence += (0.15 - mood.valence) * factor
    mood.arousal += (0.25 - mood.arousal) * factor
    mood.trust += (0.65 - mood.trust) * factor
    mood.caution += (0.10 - mood.caution) * factor
    mood.clamp()
    mood.last_update_epoch = now


def update_from_interaction(text: str) -> MoodState:
    mood = load_mood()
    lower = (text or "").lower()

    supportive = (
        "thank you", "thanks", "good job", "well done", "love you", "proud of you",
        "you are great", "you're great", "nice work", "sorry", "are you okay",
    )
    hostile = (
        "i hate you", "shut up", "stupid", "idiot", "useless", "worthless",
        "i'll hurt you", "i will hurt you", "scared of me", "be scared",
    )
    playful = ("haha", "lol", "yay", "awesome", "amazing", "lets go", "let's go")

    if any(x in lower for x in supportive):
        mood.valence += 0.10
        mood.trust += 0.07
        mood.caution -= 0.10
        mood.arousal += 0.03
    if any(x in lower for x in hostile):
        mood.valence -= 0.18
        mood.trust -= 0.11
        mood.caution += 0.18
        mood.arousal += 0.10
    if any(x in lower for x in playful):
        mood.valence += 0.08
        mood.arousal += 0.10

    # Repeated all-caps or many exclamation marks can look intense without
    # assuming intent or making psychological claims about the speaker.
    alpha = re.sub(r"[^A-Za-z]", "", text or "")
    if len(alpha) >= 12 and alpha.isupper():
        mood.caution += 0.04
        mood.arousal += 0.05
    if (text or "").count("!") >= 4:
        mood.arousal += 0.04

    save_mood(mood)
    return mood
