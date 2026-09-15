"""Run one assistant turn on behalf of a device, and get back what it said.

Every remote surface -- a Pi Proxy node, the Android app, anything added later
-- wants the same thing from this backend: give it an utterance, get the
assistant's answer back to say on *its own* speaker and show in *its own* UI.
The backend is the brain; the device is where the conversation happens.

Two things made that harder than it should be, and both are handled here so no
caller has to rediscover them.

`_pipeline` is written for the desktop GUI. It pushes the real reply into the
chat panel through `_push_chat` and *returns a status string* -- "Ready.",
"Hands-free listening.", "Media request handled.". Callers that used the
return value as the reply sent "Ready." to the device and threw the actual
answer away. Both `/api/nodes/converse` and `/api/android/chat` did exactly
that. The reply has to be taken from the `_push_chat` call instead, which
every path makes -- webgui's own pipeline and webserver's routine/briefing/
stream handlers alike.

And a turn that belongs to a device must not also play on the backend host.
`_pipeline` otherwise speaks through the backend's own audio stack and can
start media there, which on a VPS means talking to an empty room while the
owner waits at home.
"""
from __future__ import annotations

import threading
from typing import Any

# Returned by `_pipeline` to drive the desktop UI, never as an answer to
# anyone. Treating one as a reply is how "hello" came back as "Ready.".
UI_STATUS_STRINGS = frozenset({
    "Ready.",
    "Stopped.",
    "Listening...",
    "Hands-free listening.",
    "Media request handled.",
    "Game command handled.",
    "Smart-home request handled.",
})

# `_pipeline` mutates shared state on the single Api object (the chat capture,
# the voice/media suppression), so device turns are serialised against each
# other. Two overlapping turns would otherwise steal each other's replies.
_TURN_LOCK = threading.Lock()


def run_turn(
    api: Any,
    text: str,
    *,
    from_voice: bool = False,
    speaker: str = "",
) -> str:
    """Run `text` through the assistant and return the reply it produced.

    `speaker`, when given, is shown in the backend dashboard in place of the
    owner's own name, so a turn that happened in the living room does not read
    as one typed at the backend.

    Returns "" when the pipeline produced no assistant line and only a UI
    status, which the caller should turn into its own fallback wording.
    """
    # Same reason as node_media: _pipeline needs a real config and session,
    # and a device turn may be the first thing this backend is ever asked to
    # do. Idempotent, so calling it per turn costs nothing after the first.
    # Optional for the same duck-typing reason node_media documents.
    initialize = getattr(api, "initialize", None)
    if callable(initialize):
        initialize()
    state = getattr(api, "state", None)
    spoken: list[str] = []
    original_push_chat = api._push_chat
    # Whether _push_chat was already an instance attribute. Assigning the bound
    # method back would otherwise leave one shadowing the class method forever,
    # which is not what we found and not ours to leave. webserver.py does
    # override some Api methods this way (see api._pipeline), so both cases are
    # real.
    had_own_push_chat = "_push_chat" in vars(api)

    def capture(author: str, message: str, role: str) -> Any:
        # Only the assistant's own lines. `_push_chat` also carries "System"
        # notices -- "Searching: …", "[Media error] …", the music announcer --
        # which are not an answer to the owner.
        if str(role) == "assistant":
            spoken.append(str(message))
        elif str(role) == "user" and speaker:
            author = speaker
        return original_push_chat(author, message, role)

    with _TURN_LOCK:
        previous_voice = getattr(state, "voice_enabled", False) if state is not None else False
        previous_media = getattr(api, "media_enabled", False)
        if state is not None:
            state.voice_enabled = False
        api.media_enabled = False
        api._push_chat = capture
        try:
            status = api._pipeline(text, from_voice)
        finally:
            if had_own_push_chat:
                api._push_chat = original_push_chat
            else:
                del api._push_chat
            if state is not None:
                state.voice_enabled = previous_voice
            api.media_enabled = previous_media

    if spoken:
        return spoken[-1].strip()
    # Nothing was pushed as the assistant. An error path returns its own
    # message ("[Companion error] …") which is worth relaying, but a bare UI
    # status is not an answer to anything.
    status_text = str(status or "").strip()
    return "" if status_text in UI_STATUS_STRINGS else status_text
