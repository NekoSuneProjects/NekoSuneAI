from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .config import Config
from .audio_input import resolve_input_device_info


class WakeWordListener:
    def __init__(self, config: Config, detected: Callable[[], None]) -> None:
        self.config, self.detected = config, detected
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.stream_idle = threading.Event()
        self.stream_idle.set()
        self.thread: threading.Thread | None = None
        self.last_score = 0.0
        self.error = ""
        self.device_index: int | None = None
        self.device_name = ""

    def start(self) -> None:
        if not self.config.wake_word_enabled or (self.thread and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="wake-word")
        self.thread.start()

    def pause(self, timeout: float = 1.5) -> None:
        """Release an exclusive ALSA microphone before STT/calibration uses it."""
        self.pause_event.set()
        self.stream_idle.wait(timeout)

    def resume(self) -> None:
        self.pause_event.clear()

    def _run(self) -> None:
        try:
            import sounddevice as sd
            import openwakeword.utils
            from openwakeword.model import Model

            model_name = self.config.wake_word_model
            framework = self.config.wake_word_framework
            suffix = Path(model_name).suffix.lower()
            if suffix == ".onnx":
                framework = "onnx"
            elif suffix == ".tflite":
                framework = "tflite"
            # The PyPI package intentionally does not include pretrained model
            # files. Download official named models once before loading them.
            # Explicit file paths are left alone for custom "Hey Neko" models.
            if not Path(model_name).expanduser().is_file():
                openwakeword.utils.download_models(model_names=[model_name])
            model = Model(wakeword_models=[model_name], inference_framework=framework)

            # Resolve the microphone once and keep the concrete PortAudio device
            # index.  Using config.mic_device_index directly is wrong when it is
            # intentionally blank/None for auto-detection: after a Bluetooth
            # speaker becomes the host default output, PortAudio can reshuffle
            # its default devices and wake-word capture may silently open the
            # wrong input.  STT already resolves the actual Kinect/USB device;
            # wake-word capture must use that same resolved index too.
            device_info = resolve_input_device_info(self.config.mic_device_index)
            resolved_device_index = device_info["index"]
            self.device_index = resolved_device_index
            self.device_name = device_info["name"]

            max_channels = device_info["max_input_channels"]
            auto_channels = (
                4
                if "kinect" in device_info["name"].lower() and max_channels >= 4
                else 1
            )
            input_channels = max(
                1,
                min(self.config.mic_input_channels or auto_channels, max_channels),
            )
            channel_index = min(self.config.mic_channel_index, input_channels - 1)

            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    self.stream_idle.set()
                    self.stop_event.wait(0.1)
                    continue
                triggered = False
                matching_frames = 0
                self.stream_idle.clear()
                try:
                    with sd.InputStream(
                        samplerate=16000,
                        channels=input_channels,
                        dtype="int16",
                        blocksize=1280,
                        device=resolved_device_index,
                    ) as stream:
                        while not self.stop_event.is_set() and not self.pause_event.is_set():
                            audio, _overflowed = stream.read(1280)
                            samples = np.asarray(audio, dtype=np.int16)
                            mono = (
                                samples[:, channel_index]
                                if samples.ndim > 1
                                else samples.reshape(-1)
                            )
                            prediction = model.predict(np.ascontiguousarray(mono))
                            self.last_score = max(
                                (float(v) for v in prediction.values()),
                                default=0.0,
                            )
                            if self.last_score >= self.config.wake_word_threshold:
                                matching_frames += 1
                                if matching_frames >= self.config.wake_word_confirmation_frames:
                                    triggered = True
                                    break
                            else:
                                matching_frames = 0
                finally:
                    self.stream_idle.set()
                # Kinect/ALSA devices are often exclusive. Invoke listening
                # only after the wake stream has closed, then reopen afterward.
                if triggered and not self.pause_event.is_set():
                    self.detected()
                    # openWakeWord retains rolling feature/model buffers. Reset
                    # them so the last "Hey Jarvis" cannot be rediscovered when
                    # the stream reopens, then leave time for acknowledgement and
                    # remote-speaker audio tails to go quiet.
                    reset = getattr(model, "reset", None)
                    if callable(reset):
                        try:
                            reset()
                        except Exception:
                            # Older openWakeWord backends do not all expose a
                            # fully compatible reset implementation. The
                            # cooldown and confirmation gate still protect the
                            # listener on those versions.
                            pass
                    self.last_score = 0.0
                    self.stop_event.wait(self.config.wake_word_cooldown_seconds)
        except Exception as exc:
            self.error = str(exc)

    def status(self) -> dict:
        return {
            "enabled": self.config.wake_word_enabled,
            "running": bool(self.thread and self.thread.is_alive()),
            "model": self.config.wake_word_model,
            "threshold": self.config.wake_word_threshold,
            "framework": self.config.wake_word_framework,
            "confirmation_frames": self.config.wake_word_confirmation_frames,
            "cooldown_seconds": self.config.wake_word_cooldown_seconds,
            "last_score": round(self.last_score, 3),
            "device_index": self.device_index,
            "device_name": self.device_name,
            "error": self.error,
        }
