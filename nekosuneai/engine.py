"""NekoSuneAI - shared response-generation engine.

A single place that turns an input (from chat or a game agent) into a reply,
regardless of source. It orchestrates the LLM call in ``chat.py`` plus
lightweight emotion/danger tagging used to color voice delivery and narration.

It deliberately performs **no** side effects: it does not append history, push
to the frontend, or speak. Callers own those concerns so each source (chat,
game) can react differently.
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


_SAD_WORDS = ("sad", "upset", "hurt", "depressed", "annoyed", "lonely", "cry")
_HAPPY_WORDS = ("happy", "joy", "awesome", "great", "lol", "haha", "yay", "glad")
_ANXIOUS_WORDS = ("nervous", "worried", "anxious", "uneasy")
_ANGRY_WORDS = ("angry", "mad", "furious", "irritated", "rage")
_LOVE_WORDS = ("love you", "i love", "adore", "my crush", "sweetheart", "darling", "♥", "❤")
_BLUSH_WORDS = ("blush", "shy", "embarrassed", "flustered", "senpai", "cutie", "you're cute", "so cute")
_EXCITED_WORDS = ("excited", "can't wait", "cant wait", "so hyped", "amazing", "let's go", "lets go", "woohoo")
_SURPRISED_WORDS = ("surprised", "what?!", "no way", "really?!", "omg", "whoa", "wow")
_SCARED_WORDS = ("scared", "afraid", "terrified", "creepy", "frightened")
_SLEEPY_WORDS = ("sleepy", "tired", "yawn", "exhausted", "goodnight", "good night")
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


def detect_emotion(text: str) -> str:
    """Keyword-based emotion tag used to color voice delivery and narration."""
    normalized = str(text or "").lower()
    # Order matters: more specific/feminine cues first, then the broad buckets,
    # and angry before sad so "angry" isn't absorbed by sad.
    if any(word in normalized for word in _LOVE_WORDS):
        return "love"
    if any(word in normalized for word in _BLUSH_WORDS):
        return "blush"
    if any(word in normalized for word in _EXCITED_WORDS):
        return "excited"
    if any(word in normalized for word in _ANGRY_WORDS):
        return "angry"
    if any(word in normalized for word in _SCARED_WORDS):
        return "scared"
    if any(word in normalized for word in _ANXIOUS_WORDS):
        return "anxious"
    if any(word in normalized for word in _SURPRISED_WORDS):
        return "surprised"
    if any(word in normalized for word in _SLEEPY_WORDS):
        return "sleepy"
    if any(word in normalized for word in _SAD_WORDS):
        return "sad"
    if any(word in normalized for word in _HAPPY_WORDS):
        return "happy"
    return "neutral"


def detect_danger(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(keyword in normalized for keyword in _DANGER_WORDS)


def generate_reply(req: GenerationRequest) -> GenerationResult:
    """Generate a reply for any source. No side effects."""
    # When sharing the chat history, pass None so request_reply reads it itself.
    # Otherwise use the caller-provided history (an empty list means "no history").
    if req.use_shared_history:
        history = None
    else:
        history = req.history if req.history is not None else []
    mcp_context = None
    alert_level = "none"
    try:
        from .mcp_client import fetch_mcp_context
        mcp_context, alert_level = fetch_mcp_context(req.user_text, req.config)
    except Exception as exc:
        mcp_context = f"The configured MCP service could not be used: {exc}"
    extra_system = list(req.extra_system)
    if mcp_context:
        extra_system.append(mcp_context)
    reply = request_reply(
        req.user_text,
        req.profile,
        req.config,
        web_context=req.web_context,
        extra_system=extra_system or None,
        history=history,
        speaker_label=req.speaker_label,
        max_tokens=req.max_tokens,
        system_override=req.system_override,
    )
    combined = f"{req.user_text} {reply}"
    return GenerationResult(
        reply=reply,
        emotion=detect_emotion(combined),
        danger=detect_danger(combined),
        alert_level=alert_level,
    )
