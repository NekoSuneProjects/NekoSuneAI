from __future__ import annotations

import re
import threading
import time
from typing import Callable


_VIS = {
    "a": "aa", "e": "ee", "i": "ih", "o": "oh", "u": "ou", "y": "ih",
}


def _viseme_stream(text: str) -> list[str]:
    chars = [c.lower() for c in text if c.isalpha()]
    result: list[str] = []
    last = ""
    for c in chars:
        vis = _VIS.get(c)
        if not vis:
            continue
        if vis != last:
            result.append(vis)
            last = vis
    return result or ["aa"]


def drive_tts_avatar(
    text: str,
    emit: Callable[[dict], None],
    *,
    gesture: str = "idle",
    estimated_chars_per_second: float = 14.0,
) -> threading.Thread:
    """Drive mouth visemes and a body gesture alongside asynchronous TTS.

    The current TTS engines do not expose phoneme timestamps consistently, so
    this uses the exact text being spoken and a bounded speech-rate estimate.
    It is therefore synchronized to the TTS utterance rather than being a fake
    random mouth flap. Engines that later expose real viseme timestamps can feed
    the same event protocol without changing either renderer.
    """

    def run() -> None:
        clean = re.sub(r"\s+", " ", text or "").strip()
        if not clean:
            return
        visemes = _viseme_stream(clean)
        duration = max(0.7, min(30.0, len(clean) / max(6.0, estimated_chars_per_second)))
        step = max(0.055, min(0.16, duration / max(1, len(visemes))))
        emit({"type": "avatar_speaking", "value": True})
        emit({"type": "avatar_gesture", "value": gesture or "idle"})
        started = time.monotonic()
        index = 0
        while time.monotonic() - started < duration:
            viseme = visemes[index % len(visemes)]
            emit({"type": "avatar_viseme", "value": {"name": viseme, "weight": 0.72}})
            time.sleep(step * 0.55)
            emit({"type": "avatar_viseme", "value": {"name": viseme, "weight": 0.12}})
            time.sleep(step * 0.45)
            index += 1
        emit({"type": "avatar_viseme", "value": {"name": "", "weight": 0.0}})
        emit({"type": "avatar_speaking", "value": False})
        emit({"type": "avatar_gesture", "value": "idle"})

    thread = threading.Thread(target=run, daemon=True, name="vrm-tts-motion")
    thread.start()
    return thread
