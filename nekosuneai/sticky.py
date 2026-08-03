"""NekoSuneAI - wake-phrase sticky instructions + memory reset.

Replaces the old manual "/remember <fact>" command. Long-term memory is already
automatic (every chat exchange is written to the RAG MemoryStore) — what this
module adds is a *session mode* mechanic: say the companion's name followed by
an instruction ("NekoSuneAI, always speak to me in 0s and 1s") and it sticks,
applied to every reply, until a stop keyword cancels it. "reset"/"clear" cancels
the sticky instruction AND wipes the profile's long-term RAG memories back to
blank.

Detection is deliberately simple keyword/regex matching, same style as
media.py's STOP_PATTERN etc. — no LLM call needed to recognize these.
"""
from __future__ import annotations

import re
from typing import Any

from .models import SessionState

# A sticky instruction must contain one of these cues so a plain "<name>, what's
# the weather" doesn't get mistaken for "set a standing rule" — the whole point
# of the wake phrase is to *durably* change behavior, which these phrases signal.
_STICKY_CUE_PATTERN = re.compile(
    r"\b(always|from now on|every sentence|every reply|every message|every time|"
    r"until i say|until i tell you)\b",
    flags=re.IGNORECASE,
)

_WAKE_PREFIX_PATTERN = re.compile(r"^\s*(?:hey|ok|okay)?\s*", flags=re.IGNORECASE)

_CLEAR_STICKY_PATTERN = re.compile(
    r"^\s*(stop|stop that|stop it|go back to normal|back to normal|normal now)\s*[.!]?\s*$",
    flags=re.IGNORECASE,
)

_RESET_PATTERN = re.compile(
    r"^\s*(reset|clear|reset memory|clear memory|clear your memory|reset your memory|"
    r"forget everything|forget everything you know)\s*[.!]?\s*$",
    flags=re.IGNORECASE,
)


def _wake_instruction(text: str, companion_name: str) -> str | None:
    """Return the instruction text if *text* opens with the companion's name and
    reads like a standing rule, else None."""
    name = (companion_name or "").strip()
    if not name:
        return None
    stripped = _WAKE_PREFIX_PATTERN.sub("", text.strip(), count=1)
    lowered = stripped.lower()
    name_lower = name.lower()
    if not lowered.startswith(name_lower):
        return None
    remainder = stripped[len(name):].lstrip(" ,:-").strip()
    if not remainder or not _STICKY_CUE_PATTERN.search(remainder):
        return None
    return remainder


def try_set_sticky_instruction(
    text: str, profile: dict[str, Any], state: SessionState
) -> bool:
    """If *text* is a wake-phrase instruction, store it on *state* and return True."""
    companion_name = profile.get("companion_name", "")
    instruction = _wake_instruction(text, companion_name)
    if instruction is None:
        return False
    state.sticky_instruction = instruction
    return True


def try_clear_sticky_instruction(text: str) -> bool:
    return bool(_CLEAR_STICKY_PATTERN.match(text))


def is_reset_command(text: str) -> bool:
    return bool(_RESET_PATTERN.match(text))
