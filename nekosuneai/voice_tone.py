from __future__ import annotations

import io
import json
import time
import wave
from dataclasses import dataclass, asdict

import numpy as np

from .database import get_state, set_state

STATE_KEY = "latest_voice_tone_v1"


@dataclass
class VoiceToneCue:
    energy: float
    pitch_hz: float
    pitch_variation: float
    speaking_rate_proxy: float
    label: str
    confidence: float

    def as_dict(self) -> dict:
        return asdict(self)


def save_latest(cue: VoiceToneCue | None) -> None:
    if cue is None:
        return
    set_state(STATE_KEY, json.dumps({"epoch": time.time(), "cue": cue.as_dict()}))


def load_latest(max_age_seconds: float = 30.0) -> VoiceToneCue | None:
    try:
        raw = json.loads(get_state(STATE_KEY, "{}"))
        if time.time() - float(raw.get("epoch") or 0) > max_age_seconds:
            return None
        cue = raw.get("cue")
        return VoiceToneCue(**cue) if isinstance(cue, dict) else None
    except (TypeError, ValueError):
        return None


def _decode_wav(data: bytes) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if width != 2 or sr <= 0:
            return None
        y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            usable = y.size - (y.size % channels)
            y = y[:usable].reshape(-1, channels).mean(axis=1)
        return y, sr
    except Exception:
        return None


def _pitch_track(y: np.ndarray, sr: int, frame: int = 1024, hop: int = 512) -> list[float]:
    out: list[float] = []
    if y.size < frame:
        return out
    for i in range(0, y.size - frame + 1, hop):
        x = y[i:i + frame]
        x = x - float(np.mean(x))
        rms = float(np.sqrt(np.mean(x * x) + 1e-9))
        if rms < 0.015:
            continue
        corr = np.correlate(x, x, mode="full")[frame - 1:]
        min_lag = max(1, int(sr / 350))
        max_lag = min(len(corr) - 1, int(sr / 70))
        if max_lag <= min_lag:
            continue
        lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
        if lag > 0:
            hz = sr / lag
            if 70 <= hz <= 350:
                out.append(float(hz))
    return out


def analyze_voice_wav(data: bytes) -> VoiceToneCue | None:
    """Return cheap acoustic cues from a short PCM16 WAV utterance.

    This is not an emotion classifier and never treats voice acoustics as proof of
    an internal emotional state. It exists to provide tentative context such as
    unusually quiet/flat or energetic speech.
    """
    decoded = _decode_wav(data)
    if not decoded:
        return None
    y, sr = decoded
    if y.size < sr // 3:
        return None

    abs_y = np.abs(y)
    energy = float(np.sqrt(np.mean(y * y) + 1e-9))
    voiced = abs_y > max(0.02, energy * 0.7)
    transitions = float(np.count_nonzero(np.diff(voiced.astype(np.int8)) > 0))
    duration = y.size / sr
    speaking_rate_proxy = transitions / max(duration, 0.1)

    pitches = _pitch_track(y, sr)
    pitch_hz = float(np.median(pitches)) if pitches else 0.0
    pitch_variation = float(np.std(pitches) / max(np.mean(pitches), 1.0)) if len(pitches) >= 3 else 0.0

    label = "neutral/uncertain"
    confidence = 0.25
    if energy < 0.035 and pitch_variation < 0.08:
        label, confidence = "quiet or subdued", 0.55
    elif energy < 0.045 and speaking_rate_proxy < 1.2:
        label, confidence = "slow or subdued", 0.50
    elif energy > 0.11 and pitch_variation > 0.16:
        label, confidence = "energetic or activated", 0.55
    elif pitch_variation > 0.22:
        label, confidence = "expressive or animated", 0.45

    cue = VoiceToneCue(
        energy=round(energy, 5),
        pitch_hz=round(pitch_hz, 1),
        pitch_variation=round(pitch_variation, 4),
        speaking_rate_proxy=round(speaking_rate_proxy, 3),
        label=label,
        confidence=confidence,
    )
    save_latest(cue)
    return cue
