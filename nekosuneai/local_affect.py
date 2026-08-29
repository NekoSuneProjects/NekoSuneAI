from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LABELS = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
DEFAULT_MODEL = Path(os.getenv("LOCAL_AFFECT_MODEL", "/app/data/models/emotion-ferplus-8.onnx"))


@dataclass
class AffectCue:
    label: str
    confidence: float
    face_found: bool = True

    def conversational_text(self) -> str:
        friendly = {
            "happiness": "smiling/happy-looking",
            "sadness": "down/sad-looking",
            "anger": "tense/angry-looking",
            "fear": "uneasy/startled-looking",
            "surprise": "surprised-looking",
            "disgust": "uncomfortable/displeased-looking",
            "contempt": "displeased-looking",
            "neutral": "neutral-looking",
        }.get(self.label, self.label)
        return (
            f"A tiny local facial-expression model tentatively classified the visible face as {friendly} "
            f"({self.confidence:.0%} confidence). Treat this only as an uncertain visual cue, not the person's true feelings."
        )


class LocalAffectDetector:
    """Very small CPU fallback for visible facial-expression cues.

    Uses OpenCV's bundled Haar face detector plus a FER+ ONNX model. No raw
    frames are persisted. The model sees only a 64x64 grayscale face crop.
    This is deliberately an *affect cue*, not a mental-state diagnosis.
    """

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL)
        self._cv2: Any = None
        self._np: Any = None
        self._net: Any = None
        self._face: Any = None
        self._error = ""
        self._load()

    @property
    def available(self) -> bool:
        return self._net is not None and self._face is not None

    @property
    def error(self) -> str:
        return self._error

    def _load(self) -> None:
        if not self.model_path.is_file():
            self._error = f"model not found: {self.model_path}"
            return
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            self._cv2 = cv2
            self._np = np
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
            cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            self._face = cv2.CascadeClassifier(str(cascade))
            if self._face.empty():
                raise RuntimeError("OpenCV face cascade could not be loaded")
        except Exception as exc:
            self._error = str(exc)
            self._net = None
            self._face = None

    def detect(self, image_bytes: bytes) -> AffectCue | None:
        if not self.available or not image_bytes:
            return None
        cv2, np = self._cv2, self._np
        try:
            encoded = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if image is None:
                return None
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # Downscale before face detection if a phone sends a large frame.
            max_side = max(gray.shape[:2])
            if max_side > 640:
                scale = 640.0 / max_side
                gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            faces = self._face.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(48, 48))
            if len(faces) == 0:
                return None
            # Prefer the largest face (usually the user holding the phone).
            x, y, w, h = max(faces, key=lambda r: int(r[2]) * int(r[3]))
            crop = gray[y:y+h, x:x+w]
            crop = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
            blob = crop.reshape(1, 1, 64, 64)
            self._net.setInput(blob)
            raw = self._net.forward().reshape(-1).astype(np.float64)
            raw -= raw.max()
            probs = np.exp(raw)
            probs /= probs.sum() or 1.0
            index = int(probs.argmax())
            return AffectCue(LABELS[index] if index < len(LABELS) else "neutral", float(probs[index]))
        except Exception as exc:
            self._error = str(exc)
            return None
