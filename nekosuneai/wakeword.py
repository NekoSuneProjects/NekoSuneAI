from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

from .config import Config


class WakeWordListener:
    def __init__(self, config: Config, detected: Callable[[], None]) -> None:
        self.config, self.detected = config, detected
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_score = 0.0
        self.error = ""

    def start(self) -> None:
        if not self.config.wake_word_enabled or (self.thread and self.thread.is_alive()): return
        self.thread = threading.Thread(target=self._run, daemon=True, name="wake-word")
        self.thread.start()

    def _run(self) -> None:
        try:
            import sounddevice as sd
            from openwakeword.model import Model
            model = Model(wakeword_models=[self.config.wake_word_model])
            while not self.stop_event.is_set():
                triggered = False
                with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                    blocksize=1280, device=self.config.mic_device_index) as stream:
                    while not self.stop_event.is_set():
                        audio, _overflowed = stream.read(1280)
                        prediction = model.predict(np.asarray(audio, dtype=np.int16).reshape(-1))
                        self.last_score = max((float(v) for v in prediction.values()), default=0.0)
                        if self.last_score >= self.config.wake_word_threshold:
                            triggered = True
                            break
                # Kinect/ALSA devices are often exclusive. Invoke listening
                # only after the wake stream has closed, then reopen afterward.
                if triggered:
                    self.detected()
                    time.sleep(2.0)
        except Exception as exc:
            self.error = str(exc)

    def status(self) -> dict:
        return {"enabled": self.config.wake_word_enabled, "running": bool(self.thread and self.thread.is_alive()),
                "model": self.config.wake_word_model, "threshold": self.config.wake_word_threshold,
                "last_score": round(self.last_score, 3), "error": self.error}
