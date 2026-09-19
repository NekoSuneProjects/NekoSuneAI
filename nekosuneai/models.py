"""Shared dataclasses passed between the capture, engine and output layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

# torch, coqui-tts and SpeechRecognition are large, optional, voice-only
# dependencies. They appear here purely as annotations, and because
# ``from __future__ import annotations`` leaves annotations as unevaluated
# strings, importing them under TYPE_CHECKING keeps a text-only install (CLI or
# headless web) working with none of them present.
if TYPE_CHECKING:
    import speech_recognition as sr
    import torch
    from TTS.api import TTS


@dataclass
class SessionState:
    """Everything one conversation carries between turns.

    Besides the user-visible mode flags, this is where the expensive singletons
    live - the recogniser, the STT model and the XTTS voice - each paired with a
    signature describing the configuration it was built from. When a signature
    stops matching the current config the owning module rebuilds that object,
    which is what makes settings changes take effect without a restart.
    """

    voice_enabled: bool
    input_mode: str

    # Cleared automatically after the turn that consumes them.
    pending_web_context: str | None = None
    pending_web_query: str | None = None

    # A wake-phrase instruction ("...always speak to me in 0s and 1s") that keeps
    # applying to every reply until the user cancels it. Unlike the pending_web_*
    # pair above, this deliberately does not self-clear after a single turn.
    sticky_instruction: str | None = None

    # Speech recognition: recogniser plus the config signature it was built from.
    speech_recognizer: sr.Recognizer | None = None
    speech_recognizer_signature: tuple[Any, ...] | None = None
    mic_calibrated: bool = False
    stt_model_instance: Any = None
    stt_model_signature: tuple[Any, ...] | None = None

    # Speech synthesis: the loaded XTTS voice and its cached conditioning latents.
    xtts_model: TTS | None = None
    xtts_device: str | None = None
    xtts_speakers: list[str] | None = None
    xtts_cached_voice_key: str | None = None
    xtts_cached_conditioning: tuple[torch.Tensor, torch.Tensor] | None = None


@dataclass
class UserTurn:
    """One input from the user, tagged with how it arrived."""

    text: str
    from_voice: bool


@dataclass
class CommandResult:
    """What a slash-command handler decided.

    ``handled`` false means the input was not a command and should be treated as
    ordinary conversation. A handler may also feed a turn back into the loop via
    ``injected_turn``, or ask the session to end with ``should_exit``.
    """

    handled: bool
    injected_turn: UserTurn | None = None
    should_exit: bool = False


@dataclass
class SpeechCapture:
    """The outcome of one listen-and-transcribe attempt.

    ``status`` is ``"ok"`` for a usable transcript, ``"timeout"`` when no speech
    started, and ``"unknown"`` when audio arrived but could not be transcribed.
    """

    status: str
    text: str = ""
    confidence: float | None = None
    language: str = ""
    device_name: str = ""
    error: str = ""
