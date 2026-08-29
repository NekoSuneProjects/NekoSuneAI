from __future__ import annotations

import threading

_INSTALLED = False


def install_tts_busy_guard_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from .webgui import Api

    if getattr(Api, "_neko_tts_busy_guard", False):
        _INSTALLED = True
        return

    original_acquire = Api._acquire

    def acquire_with_generation(self) -> bool:
        ok = original_acquire(self)
        if ok:
            self._neko_busy_generation = int(getattr(self, "_neko_busy_generation", 0)) + 1
        return ok

    def speak_async_guarded(self, text: str, emotion: str = "neutral") -> None:
        generation = int(getattr(self, "_neko_busy_generation", 0))

        def worker() -> None:
            try:
                self._speak(text, emotion)
            finally:
                # Only clear Busy when the lock still belongs to the same turn
                # that started this TTS. If a newer request has acquired the
                # assistant while older audio is finishing, never unlock it.
                same_turn = int(getattr(self, "_neko_busy_generation", 0)) == generation
                if same_turn and getattr(self, "busy", False):
                    self._release()
                if same_turn or not getattr(self, "busy", False):
                    self._push_status("Ready.")
                try:
                    self._queue_web_event({"type": "avatar_speaking", "value": False})
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="neko-tts-output").start()

    Api._acquire = acquire_with_generation
    Api._speak_async = speak_async_guarded
    Api._neko_tts_busy_guard = True
    _INSTALLED = True
