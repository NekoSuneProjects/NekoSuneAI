"""Generate original, dependency-free alert sounds for fresh installations."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 24_000


def _write_tone_sequence(path: Path, notes: list[tuple[float, float, float]]) -> None:
    """Write (frequency Hz, seconds, volume) notes with soft click-free edges."""
    frames = bytearray()
    for frequency, duration, volume in notes:
        count = int(SAMPLE_RATE * duration)
        edge = max(1, min(int(SAMPLE_RATE * 0.025), count // 4))
        for index in range(count):
            envelope = min(1.0, index / edge, (count - index - 1) / edge)
            sample = 0.0 if frequency <= 0 else math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
            frames.extend(struct.pack("<h", int(32767 * volume * max(0.0, envelope) * sample)))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def ensure_default_alert_sounds(audio_dir: Path) -> None:
    """Create safe defaults once; never overwrite sounds supplied by the user."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    warning = audio_dir / "warning.wav"
    danger = audio_dir / "danger.wav"
    if not warning.exists() or warning.stat().st_size == 0:
        _write_tone_sequence(warning, [
            (660, 0.20, 0.34), (0, 0.08, 0), (880, 0.28, 0.34),
            (0, 0.12, 0), (660, 0.20, 0.30), (880, 0.32, 0.32),
        ])
    if not danger.exists() or danger.stat().st_size == 0:
        _write_tone_sequence(danger, [
            (880, 0.24, 0.46), (587, 0.24, 0.46), (880, 0.24, 0.46), (587, 0.24, 0.46),
            (0, 0.10, 0),
            (988, 0.28, 0.48), (622, 0.28, 0.48), (988, 0.28, 0.48), (622, 0.40, 0.48),
        ])
