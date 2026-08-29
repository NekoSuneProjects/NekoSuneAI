from __future__ import annotations

_INSTALLED = False

EMMA_US = "en-US-EmmaMultilingualNeural"


def _normalize_voice(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return EMMA_US
    key = raw.lower().replace("_", "-").replace(" ", "")
    aliases = {
        "emma": EMMA_US,
        "emmamultilingual": EMMA_US,
        "emma-multilingual": EMMA_US,
        "en-us-emmamultilingual": EMMA_US,
        "en-us-emmamultilingualneural": EMMA_US,
    }
    return aliases.get(key, raw)


def install_bridge_edge_voice_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import bridge_voice, webgui

    original_synthesize = bridge_voice.synthesize

    def synthesize_with_edge_voice(text, config):
        old_voice = getattr(config, "bridge_tts_voice", None)
        old_engine = getattr(config, "bridge_tts_engine", "edge-stream")
        normalized = _normalize_voice(old_voice)
        config.bridge_tts_voice = normalized
        if normalized.lower().endswith("neural"):
            config.bridge_tts_engine = "edge-stream"
        try:
            return original_synthesize(text, config)
        finally:
            config.bridge_tts_voice = old_voice
            config.bridge_tts_engine = old_engine

    bridge_voice.synthesize = synthesize_with_edge_voice
    bridge_voice._stream_route_unavailable = lambda _error: False

    voice = webgui.APP_SETTINGS_SCHEMA.setdefault("voice", {"label": "Voice (TTS)", "fields": []})
    voice["fields"] = [f for f in voice.get("fields", []) if f.get("key") not in {"bridge_tts_engine", "bridge_tts_voice", "bridge_tts_rate"}]
    voice["fields"][1:1] = [
        {"key": "bridge_tts_engine", "label": "Bridge TTS engine", "type": "select", "options": ["edge-stream", "piper"]},
        {"key": "bridge_tts_voice", "label": "Bridge Edge voice", "type": "text"},
        {"key": "bridge_tts_rate", "label": "Bridge Edge speech rate (e.g. +10%)", "type": "text"},
    ]
    for key, typ in (("bridge_tts_engine", "select"), ("bridge_tts_voice", "text"), ("bridge_tts_rate", "text")):
        webgui._APP_FIELD_TYPES[key] = typ
    voice["description"] = "Spoken replies. For NekoAI Bridge, Edge streaming uses en-US-EmmaMultilingualNeural by default and does not silently fall back to Piper."

    mcp = webgui.APP_SETTINGS_SCHEMA.get("mcp")
    if mcp:
        mcp["fields"] = [f for f in mcp.get("fields", []) if f.get("key") not in {"bridge_tts_engine", "bridge_tts_voice", "bridge_tts_rate"}]

    _INSTALLED = True
