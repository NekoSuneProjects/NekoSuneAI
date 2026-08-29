from __future__ import annotations

import os
import time
from collections import deque

from .local_affect import AffectCue


NEGATIVE = {"sadness", "fear", "anger", "disgust", "contempt"}


class SupportCheckinManager:
    """Turn repeated uncertain facial cues into occasional gentle check-ins.

    This intentionally never treats a classifier result as ground truth. Camera
    sharing itself is opt-in; while active, three reasonably-confident matching
    negative cues in a short window can produce one check-in, followed by a long
    cooldown so the assistant does not pester the user.
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("SUPPORT_CHECKINS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
        self.cooldown = max(300, int(os.getenv("SUPPORT_CHECKIN_COOLDOWN_SECONDS", "900")))
        self.min_confidence = min(0.95, max(0.25, float(os.getenv("SUPPORT_AFFECT_MIN_CONFIDENCE", "0.45"))))
        self._recent: deque[tuple[float, str, float]] = deque(maxlen=6)
        self._last_checkin = 0.0

    def observe(self, cue: AffectCue | None) -> str | None:
        if not self.enabled or cue is None:
            return None
        now = time.time()
        self._recent.append((now, cue.label, cue.confidence))
        while self._recent and now - self._recent[0][0] > 35:
            self._recent.popleft()
        if now - self._last_checkin < self.cooldown:
            return None
        lows = [(label, confidence) for _, label, confidence in self._recent if label in NEGATIVE and confidence >= self.min_confidence]
        if len(lows) < 3:
            return None
        # Do not state a specific inferred emotion as fact. Facial-expression
        # recognition is noisy and context-dependent.
        self._last_checkin = now
        self._recent.clear()
        return "Hey Neko, you seem a little down or tense right now. Are you okay?"


def support_context(cue: AffectCue | None) -> str:
    if cue is None:
        return ""
    if cue.label not in NEGATIVE or cue.confidence < 0.40:
        return cue.conversational_text()
    return (
        cue.conversational_text()
        + " If the user's words suggest they are having a difficult moment, respond warmly and gently. "
          "Ask rather than assume what happened. Their words override the visual cue. Do not diagnose mental health. "
          "If they describe grief, disappointment, loneliness, or another upsetting event, offer companionship and practical "
          "ways to feel a little better. If they ask for ideas/resources and web search is enabled, research reputable current "
          "suggestions. Do not pressure them to stay with the assistant or imply the assistant replaces human relationships."
    )
