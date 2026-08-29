from __future__ import annotations

import json

_INSTALLED = False
_TTS_DEFAULTS = {
    "tts_provider": "bridge",
    "bridge_tts_engine": "edge-stream",
    "bridge_tts_voice": "en-US-EmmaMultilingualNeural",
    "bridge_tts_rate": "+10%",
    "tts_language": "en-US",
}
_TTS_KEYS = set(_TTS_DEFAULTS) | {
    "tts_auto_language",
    "xtts_speaker",
    "xtts_speaker_wav",
    "xtts_speed",
    "rvc_chat_enabled",
    "rvc_chat_model_path",
    "rvc_chat_pitch",
    "rvc_chat_index_rate",
    "rvc_chat_protect",
}


def _load_saved() -> dict:
    try:
        from . import database
        value = json.loads(database.get_state("app_settings", "{}") or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_values(values: dict) -> None:
    try:
        from . import database
        store = _load_saved()
        store.update(values)
        database.set_state("app_settings", json.dumps(store))
    except Exception:
        pass


def _apply(config, values: dict) -> None:
    if config is None:
        return
    for key, value in values.items():
        if key in _TTS_KEYS and hasattr(config, key):
            setattr(config, key, value)


def install_dashboard_tts_config_patch() -> None:
    """Make Dashboard Settings authoritative for TTS instead of Docker env vars."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import webgui
    Api = webgui.Api

    original_initialize = Api.initialize
    original_get = Api.get_app_settings
    original_save = Api.save_app_settings

    def initialize(self, *args, **kwargs):
        result = original_initialize(self, *args, **kwargs)
        saved = _load_saved()
        values = dict(_TTS_DEFAULTS)
        values.update({k: v for k, v in saved.items() if k in _TTS_KEYS})
        _apply(getattr(self, "config", None), values)
        return result

    def get_app_settings(self):
        result = original_get(self)
        sections = result.get("sections", {}) if isinstance(result, dict) else {}
        voice = sections.get("voice", {})
        saved = _load_saved()
        for field in voice.get("fields", []):
            key = field.get("key")
            if key in _TTS_KEYS:
                if key in saved:
                    field["value"] = saved[key]
                elif key in _TTS_DEFAULTS:
                    field["value"] = _TTS_DEFAULTS[key]
        return result

    def save_app_settings(self, section: str, values: dict):
        result = original_save(self, section, values)
        if section == "voice" and isinstance(values, dict):
            chosen = {k: v for k, v in values.items() if k in _TTS_KEYS}
            if chosen:
                # Normalize the common Emma aliases before they become runtime config.
                voice = str(chosen.get("bridge_tts_voice", "") or "").strip()
                if voice.lower().replace(" ", "").replace("_", "-") in {
                    "emma", "emmamultilingual", "emma-multilingual",
                    "en-us-emmamultilingual", "en-us-emmamultilingualneural",
                }:
                    chosen["bridge_tts_voice"] = "en-US-EmmaMultilingualNeural"
                _save_values(chosen)
                _apply(getattr(self, "config", None), chosen)
                try:
                    self._push_notification("Voice settings saved and applied immediately.")
                except Exception:
                    pass
        return result

    Api.initialize = initialize
    Api.get_app_settings = get_app_settings
    Api.save_app_settings = save_app_settings
    Api._neko_dashboard_tts_config = True
    _INSTALLED = True
