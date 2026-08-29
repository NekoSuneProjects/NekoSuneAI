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
        # An Edge/Microsoft Neural voice name must never be sent to Piper. If
        # Emma is selected, use the Bridge's tts-stream route explicitly.
        if normalized.lower().endswith("neural"):
            config.bridge_tts_engine = "edge-stream"
        try:
            return original_synthesize(text, config)
        finally:
            config.bridge_tts_voice = old_voice
            config.bridge_tts_engine = old_engine

    bridge_voice.synthesize = synthesize_with_edge_voice

    # The old implementation silently dropped to Piper when the Bridge's Edge
    # route was missing. That is what makes a configured Emma voice suddenly
    # sound like an unrelated older/granny voice. Surface the Edge error instead
    # of silently changing speakers.
    bridge_voice._stream_route_unavailable = lambda _error: False

    voice = webgui.APP_SETTINGS_SCHEMA.setdefault("voice", {"label": "Voice (TTS)", "fields": []})
    keys = {f.get("key") for f in voice.get("fields", [])}
    additions = [
        {"key": "bridge_tts_engine", "label": "Bridge TTS engine", "type": "select", "options": ["edge-stream", "piper"]},
        {"key": "bridge_tts_voice", "label": "Bridge Edge voice", "type": "text"},
        {"key": "bridge_tts_rate", "label": "Bridge Edge speech rate (e.g. +10%)", "type": "text"},
    ]
    for field in additions:
        if field["key"] not in keys:
            voice["fields"].insert(1, field)
            webgui._APP_FIELD_TYPES[field["key"]] = field["type"]
    voice["description"] = "Spoken replies. For NekoAI Bridge, Edge streaming uses en-US-EmmaMultilingualNeural by default and does not silently fall back to Piper."

    # Avoid showing the same Bridge voice controls twice under MCP.
    mcp = webgui.APP_SETTINGS_SCHEMA.get("mcp")
    if mcp:
        mcp["fields"] = [f for f in mcp.get("fields", []) if f.get("key") not in {"bridge_tts_engine", "bridge_tts_voice", "bridge_tts_rate"}]

    _INSTALLED = True
