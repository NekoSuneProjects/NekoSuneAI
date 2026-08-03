"""Image understanding — let NekoSuneAI *look at* an image and read it.

A small multimodal seam used by the "review this image" feature (and reusable
anywhere NekoSuneAI needs to see a still image rather than the live screen). It
returns a factual description + any text read from the image; the persona's
opinion/commentary is generated separately by the chat engine so NekoSuneAI stays
in character.

Two backends, picked automatically:
  * **Ollama vision** when ``vision_model`` is set (e.g. ``llava``, ``moondream``,
    ``qwen2.5vl``) — local, same path the game drivers use.
  * **OpenAI-compatible vision** when the provider is ``openai``/LiteLLM and the
    chat ``model`` is multimodal (e.g. ``gpt-4o``, ``qwen-vl``) — image sent as a
    data URI in the chat/completions payload.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import requests

from .config import Config

# What we ask the vision model: describe AND read text, so NekoSuneAI can react to
# memes/screenshots/art and to images of itself.
DEFAULT_VISION_PROMPT = (
    "Look at this image and describe it in detail: the subject, style, colors, mood, "
    "and anything notable. If there is any text, read it out exactly. Be concise but specific."
)


def vision_available(config: Config) -> bool:
    if getattr(config, "vision_model", None):
        return True
    return bool(getattr(config, "llm_provider", "") == "openai" and getattr(config, "llm_api_url", None))


def describe_image(config: Config, image_bytes: bytes, prompt: str = DEFAULT_VISION_PROMPT) -> str | None:
    """Return a factual description (incl. any readable text), or None if no vision backend."""
    if not image_bytes:
        return None
    if getattr(config, "vision_model", None):
        from .games.screen import caption
        text = caption(config, image_bytes, prompt)
        # caption() returns a friendly placeholder string when unconfigured.
        if text and not text.startswith("(no vision model") and not text.startswith("(vision model unavailable"):
            return text
        # Fall through to OpenAI vision if available.
    if getattr(config, "llm_provider", "") == "openai" and getattr(config, "llm_api_url", None):
        return _openai_vision(config, image_bytes, prompt)
    return None


def _openai_vision(config: Config, image_bytes: bytes, prompt: str) -> str | None:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    url = config.llm_api_url
    headers = {"Content-Type": "application/json"}
    key = config.llm_api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "stream": False,
        "max_tokens": 400,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except Exception:
        return None


def strip_data_uri(data: str) -> bytes:
    """Decode a base64 string or ``data:...;base64,...`` data URI into raw bytes."""
    raw = (data or "").split(",", 1)[-1] if "," in (data or "") else (data or "")
    try:
        return base64.b64decode(raw)
    except Exception:
        return b""
