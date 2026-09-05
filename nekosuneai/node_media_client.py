from __future__ import annotations

import base64
import threading
import time

import requests

from .node_audio import NodeAudio


class NodeMediaClient:
    def __init__(self, config):
        self.config = config
        self.audio = NodeAudio()
        self._lock = threading.RLock()
        self._audio_generation = 0
        self._speech_lock = threading.Lock()
        self.speech_pending = threading.Event()
        self.closed = threading.Event()
        self.state = {"description": "", "transcript": "", "vision_epoch": 0, "stt_epoch": 0, "error": ""}

    def snapshot(self):
        with self._lock:
            return dict(self.state)

    def update(self, **values):
        with self._lock:
            self.state.update(values)

    def request(self, operation, **payload):
        if self.closed.is_set():
            raise RuntimeError("Node media stopped")
        token = self.config.get("device_token")
        if not token:
            raise RuntimeError("Pair this PC first")
        response = requests.post(str(self.config["server_url"]).rstrip("/") + "/api/nodes/media/" + operation,
                                 json={"node_id": self.config["node_id"], **payload},
                                 headers={"X-Neko-Device-Token": token},
                                 timeout=(10, 120), verify=bool(self.config.get("verify_tls", True)))
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Docker returned HTTP {response.status_code} without a media response") from exc
        if not response.ok:
            raise RuntimeError(str(result.get("error") or f"HTTP {response.status_code}"))
        if self.closed.is_set():
            raise RuntimeError("Node media stopped")
        return result

    def vision(self, capture):
        if not capture.get("ok") or not capture.get("screenshot_jpeg_base64"):
            self.update(description="", vision_epoch=0)
            raise RuntimeError(capture.get("reason") or "No gameplay image is available")
        result = self.request("vision", image_base64=capture["screenshot_jpeg_base64"])
        self.update(description=result["description"], vision_epoch=capture.get("epoch", time.time()), error="")
        return result["description"]

    def listen(self):
        if self.speech_pending.is_set():
            raise RuntimeError("Listening paused for speech playback")
        generation = self._audio_generation
        device = self.config.get("audio_input_device")
        if device is None:
            raise RuntimeError("Select a microphone or game-audio loopback device")
        raw = self.audio.capture(device, self.config.get("audio_record_seconds", 5))
        if generation != self._audio_generation or self.closed.is_set():
            raise RuntimeError("Recording cancelled")
        result = self.request("stt", wav_base64=base64.b64encode(raw).decode("ascii"))
        if generation != self._audio_generation:
            raise RuntimeError("Transcription cancelled")
        self.update(transcript=result.get("text", ""), stt_epoch=time.time(), error="")
        return result.get("text", "")

    def speak(self, text):
        if not self._speech_lock.acquire(blocking=False):
            raise RuntimeError("Speech output is busy")
        generation = self._audio_generation
        self.speech_pending.set()
        self.audio.stop()
        try:
            result = self.request("tts", text=text)
            encoded = result.get("audio_base64", "")
            if not isinstance(encoded, str) or len(encoded) > 10_666_680:
                raise RuntimeError("Oversized TTS response")
            if generation != self._audio_generation or self.closed.is_set():
                raise RuntimeError("Speech cancelled")
            raw = base64.b64decode(encoded, validate=True)
            self.audio.play(raw, self.config.get("audio_output_device"),
                            cancelled=lambda: generation != self._audio_generation or self.closed.is_set())
            return {"ok": True, "played": True}
        finally:
            self.speech_pending.clear()
            self._speech_lock.release()

    def cancel_audio(self):
        with self._lock:
            self._audio_generation += 1
            self.audio.stop()

    def close(self):
        self.closed.set()
        self.cancel_audio()
