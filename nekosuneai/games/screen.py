"""Screen capture + optional vision captioning for the universal game driver.

Captures the screen (mss or PIL), optionally downscales it, and asks a
multimodal model for a compact scene description so the text LLM brain can
decide actions. All deps are optional/lazy; if vision isn't configured the
driver still runs with a minimal observation.
"""
from __future__ import annotations

import base64
import io
from typing import Any

import requests

from ..config import Config


def capture_png(max_width: int = 768) -> bytes | None:
    """Grab the primary screen as PNG bytes, downscaled to max_width."""
    img = None
    try:
        import mss  # type: ignore
        from PIL import Image  # type: ignore

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception:
        try:
            from PIL import ImageGrab  # type: ignore

            img = ImageGrab.grab()
        except Exception:
            return None

    try:
        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(img.height * ratio)))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def screen_size() -> tuple[int, int] | None:
    try:
        from PIL import ImageGrab  # type: ignore

        img = ImageGrab.grab()
        return img.size
    except Exception:
        return None


def _ollama_base(config: Config) -> str:
    url = config.llm_api_url or "http://127.0.0.1:11434/api/chat"
    if "/api/" in url:
        return url.split("/api/")[0].rstrip("/")
    return "http://127.0.0.1:11434"


def caption(config: Config, png_bytes: bytes, prompt: str) -> str:
    """Describe a screenshot via a local Ollama vision model (e.g. moondream)."""
    model = config.vision_model
    if not model or not png_bytes:
        return "(no vision model configured — playing without screen analysis)"
    b64 = base64.b64encode(png_bytes).decode("ascii")
    # Vision models like moondream/llava run in Ollama, so always hit the local
    # Ollama chat endpoint with the image, regardless of the chat LLM provider.
    url = _ollama_base(config) + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as exc:
        return f"(vision model unavailable: {exc})"
