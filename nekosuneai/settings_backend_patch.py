from __future__ import annotations

import os

_INSTALLED = False


def install_settings_backend_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import webgui
    from .settings_dashboard_patch import _read_saved_app_settings

    Api = webgui.Api
    if getattr(Api, "_neko_settings_backend_patched", False):
        _INSTALLED = True
        return

    original_get = Api.get_app_settings

    def get_app_settings(self):
        result = original_get(self)
        sections = result.get("sections", {}) if isinstance(result, dict) else {}
        saved = _read_saved_app_settings()
        for key, section in sections.items():
            meta = webgui.APP_SETTINGS_SCHEMA.get(key, {})
            if meta.get("description"):
                section["description"] = meta["description"]
            if key == "youtube":
                for field in section.get("fields", []):
                    if field.get("key") == "youtube_music_volume" and field.get("value") in ("", None):
                        field["value"] = saved.get("youtube_music_volume", os.getenv("YOUTUBE_MUSIC_VOLUME", "75"))
                    elif field.get("key") == "ytdlp_cookies_file" and field.get("value") in ("", None):
                        field["value"] = saved.get("ytdlp_cookies_file", os.getenv("YTDLP_COOKIES_FILE", ""))
        return result

    Api.get_app_settings = get_app_settings
    Api._neko_settings_backend_patched = True
    _INSTALLED = True
