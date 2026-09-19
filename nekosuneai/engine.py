"""Shared response generation.

One entry point that turns an input - from the chat loop or from the game
agent - into a reply, so both sources get identical behaviour. It drives the
LLM call in :mod:`nekosuneai.chat` and adds the lightweight emotion and danger
tagging that voice delivery and narration key off.

Deliberately free of side effects: nothing here appends to history, pushes to
the frontend, or speaks. Those belong to the caller, so each source can respond
to a result in its own way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .chat import request_reply
from .config import Config


@dataclass
class GenerationRequest:
    user_text: str
    profile: dict[str, Any]
    config: Config
    source: str = "chat"  # "chat" | "game"
    web_context: str | None = None
    extra_system: list[str] = field(default_factory=list)
    use_shared_history: bool = True
    history: list[dict[str, str]] | None = None
    speaker_label: str | None = None
    max_tokens: int | None = None  # cap reply length (smaller = faster, e.g. game)
    system_override: str | None = None  # replace the full persona prompt (lean game prompt)


@dataclass
class GenerationResult:
    reply: str
    emotion: str
    danger: bool
    alert_level: str = "none"


# Checked top to bottom, so the first match wins. Ordering is deliberate: the
# narrower, more characterful cues come before the broad buckets, and "angry"
# sits above "sad" so an angry line is not swallowed by the sad bucket.
_EMOTION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("love", ("love you", "i love", "adore", "my crush", "sweetheart", "darling", "♥", "❤")),
    ("blush", ("blush", "shy", "embarrassed", "flustered", "senpai", "cutie",
               "you're cute", "so cute")),
    ("excited", ("excited", "can't wait", "cant wait", "so hyped", "amazing",
                 "let's go", "lets go", "woohoo")),
    ("angry", ("angry", "mad", "furious", "irritated", "rage")),
    ("scared", ("scared", "afraid", "terrified", "creepy", "frightened")),
    ("anxious", ("nervous", "worried", "anxious", "uneasy")),
    ("surprised", ("surprised", "what?!", "no way", "really?!", "omg", "whoa", "wow")),
    ("sleepy", ("sleepy", "tired", "yawn", "exhausted", "goodnight", "good night")),
    ("sad", ("sad", "upset", "hurt", "depressed", "annoyed", "lonely", "cry")),
    ("happy", ("happy", "joy", "awesome", "great", "lol", "haha", "yay", "glad")),
)

_NEUTRAL_EMOTION = "neutral"

_DANGER_WORDS = (
    "danger",
    "fire",
    "help",
    "emergency",
    "attack",
    "threat",
    "warning",
    "alarm",
)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def detect_emotion(text: str) -> str:
    """Keyword-based emotion tag used to color voice delivery and narration."""
    normalized = str(text or "").lower()
    for emotion, cues in _EMOTION_CUES:
        if _contains_any(normalized, cues):
            return emotion
    return _NEUTRAL_EMOTION


def detect_danger(text: str) -> bool:
    return _contains_any(str(text or "").lower(), _DANGER_WORDS)


def _resolve_history(req: GenerationRequest) -> list[dict[str, str]] | None:
    """Pick the history to send.

    Sharing the chat history means handing ``request_reply`` None so it reads
    the store itself. Otherwise the caller's list is used verbatim - and an
    empty list genuinely means "no history", not "go and fetch some".
    """
    if req.use_shared_history:
        return None
    return req.history if req.history is not None else []


def _collect_mcp_context(req: GenerationRequest) -> tuple[str | None, str]:
    """Fetch MCP context, degrading to an explanatory note when it is unusable."""
    try:
        from .mcp_client import fetch_mcp_context

        return fetch_mcp_context(req.user_text, req.config)
    except Exception as exc:
        return f"The configured MCP service could not be used: {exc}", "none"


def generate_reply(req: GenerationRequest) -> GenerationResult:
    """Generate a reply for any source. No side effects."""
    mcp_context, alert_level = _collect_mcp_context(req)

    extra_system = list(req.extra_system)
    if mcp_context:
        extra_system.append(mcp_context)

    reply = request_reply(
        req.user_text,
        req.profile,
        req.config,
        web_context=req.web_context,
        extra_system=extra_system or None,
        history=_resolve_history(req),
        speaker_label=req.speaker_label,
        max_tokens=req.max_tokens,
        system_override=req.system_override,
    )

    # Tag against both sides of the exchange so the user's tone colours delivery.
    combined = f"{req.user_text} {reply}"
    return GenerationResult(
        reply=reply,
        emotion=detect_emotion(combined),
        danger=detect_danger(combined),
        alert_level=alert_level,
    )
