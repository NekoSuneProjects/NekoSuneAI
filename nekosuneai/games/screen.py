"""Screen sampling and optional captioning for the universal game driver.

Grabs the primary display, shrinks it to something a model will accept, and
optionally asks a multimodal model what is on screen so the text-only brain has
something to reason about. Every dependency here is lazy and optional: with no
vision model configured the driver still runs, just with a thinner observation.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import requests

from ..config import Config

_DEFAULT_MAX_WIDTH = 768
_CAPTION_TIMEOUT_SECONDS = 90
_DEFAULT_OLLAMA_ROOT = "http://127.0.0.1:11434"
_NO_VISION_NOTICE = "(no vision model configured — playing without screen analysis)"


def _grab_with_mss() -> Any:
    """Fast path: mss blits the primary monitor without a round-trip through the WM."""
    import mss  # type: ignore
    from PIL import Image  # type: ignore

    with mss.mss() as sct:
        frame = sct.grab(sct.monitors[1])
    return Image.frombytes("RGB", frame.size, frame.bgra, "raw", "BGRX")


def _grab_with_pil() -> Any:
    """Fallback for hosts without mss."""
    from PIL import ImageGrab  # type: ignore

    return ImageGrab.grab()


def _grab_screen() -> Any:
    for grab in (_grab_with_mss, _grab_with_pil):
        try:
            return grab()
        except Exception:
            continue
    return None


def _shrink_to_width(image: Any, max_width: int) -> Any:
    if image.width <= max_width:
        return image
    scale = max_width / float(image.width)
    return image.resize((max_width, int(image.height * scale)))


def capture_png(max_width: int = _DEFAULT_MAX_WIDTH) -> bytes | None:
    """Return the primary display as PNG bytes, capped at ``max_width``."""
    image = _grab_screen()
    if image is None:
        return None

    try:
        buffer = io.BytesIO()
        _shrink_to_width(image, max_width).save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def screen_size() -> tuple[int, int] | None:
    try:
        return _grab_with_pil().size
    except Exception:
        return None


def _ollama_base(config: Config) -> str:
    """Strip an Ollama chat URL back to its origin."""
    url = config.llm_api_url or f"{_DEFAULT_OLLAMA_ROOT}/api/chat"
    if "/api/" in url:
        return url.split("/api/")[0].rstrip("/")
    return _DEFAULT_OLLAMA_ROOT


def caption(config: Config, png_bytes: bytes, prompt: str) -> str:
    """Describe a screenshot using a local Ollama vision model such as moondream."""
    model = config.vision_model
    if not model or not png_bytes:
        return _NO_VISION_NOTICE

    # Vision models (moondream, llava, ...) are served by Ollama, so this call
    # goes to the local Ollama endpoint no matter which provider backs chat.
    request = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(png_bytes).decode("ascii")],
            }
        ],
        "stream": False,
    }

    try:
        response = requests.post(
            _ollama_base(config) + "/api/chat",
            json=request,
            timeout=_CAPTION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except Exception as exc:
        return f"(vision model unavailable: {exc})"
