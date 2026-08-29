from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterable

from .database import get_state, set_state

STATE_KEY = "owner_learning_profile_v1"


@dataclass
class LearnedItem:
    category: str
    value: str
    confidence: float = 0.35
    positive: float = 0.0
    comfort: float = 0.0
    mentions: int = 1
    last_seen: float = 0.0

    def touch(self, *, positive: float = 0.0, comfort: float = 0.0) -> None:
        self.mentions += 1
        self.last_seen = time.time()
        self.confidence = min(1.0, self.confidence + 0.10)
        self.positive = max(-1.0, min(1.0, self.positive * 0.75 + positive * 0.25))
        self.comfort = max(0.0, min(1.0, self.comfort * 0.75 + comfort * 0.25))


def _load() -> list[LearnedItem]:
    try:
        raw = json.loads(get_state(STATE_KEY, "[]"))
        return [LearnedItem(**row) for row in raw if isinstance(row, dict)]
    except (TypeError, ValueError):
        return []


def _save(items: list[LearnedItem]) -> None:
    set_state(STATE_KEY, json.dumps([asdict(x) for x in items], ensure_ascii=False))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,!?:;\"'"))[:180]


def _upsert(category: str, value: str, *, positive: float = 0.0, comfort: float = 0.0) -> None:
    value = _clean(value)
    if len(value) < 2:
        return
    items = _load()
    key = value.casefold()
    for item in items:
        if item.category == category and item.value.casefold() == key:
            item.touch(positive=positive, comfort=comfort)
            _save(items)
            return
    items.append(LearnedItem(category, value, 0.35, positive, comfort, 1, time.time()))
    _save(items[-250:])


def learn_from_text(text: str) -> None:
    """Extract explicit preference facts conservatively from normal conversation.

    This intentionally learns only direct first-person statements. It does not infer
    sensitive traits, medical state, or private facts from camera/audio signals.
    """
    s = text.strip()
    low = s.lower()
    patterns: list[tuple[str, str, float, float]] = [
        ("favorite", r"\b(?:my favourite|my favorite)\s+(.{2,100})", 0.9, 0.35),
        ("like", r"\bi (?:really )?(?:like|love|enjoy)\s+(.{2,100})", 0.8, 0.30),
        ("dislike", r"\bi (?:really )?(?:dislike|hate|don't like|do not like)\s+(.{2,100})", -0.9, 0.0),
        ("hobby", r"\b(?:my hobby is|one of my hobbies is|i like doing)\s+(.{2,100})", 0.75, 0.25),
        ("comfort", r"\b(.{2,100}?)\s+(?:cheers me up|makes me feel better|calms me down|helps me relax|comforts me)\b", 0.85, 0.95),
        ("comfort", r"\bwhen i'm (?:sad|down|upset|stressed),?\s+(.{2,100}?)\s+(?:helps|cheers me up|makes me feel better)\b", 0.8, 1.0),
    ]
    for category, pattern, positive, comfort in patterns:
        for m in re.finditer(pattern, low, flags=re.I):
            value = s[m.start(1):m.end(1)]
            # Trim common trailing clauses to avoid storing whole paragraphs.
            value = re.split(r"\b(?:because|but|although|and then|when)\b", value, 1, flags=re.I)[0]
            _upsert(category, value, positive=positive, comfort=comfort)


def reinforce_effect(activity: str, before_score: float, after_score: float) -> None:
    """Learn that an activity appears useful when the user explicitly reports improvement."""
    delta = max(-1.0, min(1.0, after_score - before_score))
    if delta > 0.1:
        _upsert("comfort", activity, positive=min(1.0, delta), comfort=min(1.0, 0.5 + delta / 2))


def best_comforts(limit: int = 5) -> list[LearnedItem]:
    items = [x for x in _load() if x.positive >= 0 and x.category != "dislike"]
    items.sort(key=lambda x: (x.comfort * 2.0 + x.positive + x.confidence + min(x.mentions, 8) * 0.05), reverse=True)
    return items[:limit]


def summary_for_prompt() -> str:
    items = _load()
    if not items:
        return ""
    reliable = [x for x in items if x.confidence >= 0.35]
    reliable.sort(key=lambda x: (x.confidence, x.mentions, x.comfort), reverse=True)
    lines = []
    for item in reliable[:18]:
        extra = ""
        if item.comfort >= 0.55:
            extra = " (often comforting/helpful)"
        elif item.positive <= -0.45:
            extra = " (disliked)"
        lines.append(f"- {item.category}: {item.value}{extra}")
    if not lines:
        return ""
    return (
        "Learned owner preferences from explicit conversation. Treat these as fallible, updateable memories; "
        "do not pretend to know more than recorded. Use positive/comfort items naturally when helpful, without "
        "repeating them mechanically:\n" + "\n".join(lines)
    )


def list_profile() -> list[dict]:
    return [asdict(x) for x in _load()]
