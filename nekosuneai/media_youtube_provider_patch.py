from __future__ import annotations

import re
from urllib.parse import quote_plus

_INSTALLED = False


def install_media_youtube_provider_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import config, media, webgui

    def normalize_music_provider(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"youtube", "youtube-music", "youtube_music", "yt", "ytmusic"}:
            return "youtube"
        if normalized in {"soundcloud", "sc"}:
            return "soundcloud"
        if normalized == "deezer":
            return "deezer"
        if normalized == "spotify":
            return "spotify"
        return "soundcloud"

    # Keep both modules in sync because media.py imports the normalizer directly.
    config.normalize_music_provider = normalize_music_provider
    media.normalize_music_provider = normalize_music_provider

    media.PROVIDER_SUFFIX_PATTERN = re.compile(
        r"\s+(?:on|using|via)\s+(youtube(?:\s+music)?|ytmusic|yt|soundcloud|spotify|deezer)\s*$",
        flags=re.IGNORECASE,
    )

    original_search_url = media._music_search_url

    def music_search_url(query: str, provider: str) -> str:
        if normalize_music_provider(provider) == "youtube":
            return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        return original_search_url(query, provider)

    media._music_search_url = music_search_url

    media_section = webgui.APP_SETTINGS_SCHEMA.get("media")
    if media_section:
        for field in media_section.get("fields", []):
            if field.get("key") == "music_provider_default":
                field["options"] = ["youtube", "soundcloud", "deezer", "spotify"]
                field["label"] = "Music provider"
                break
        media_section["description"] = (
            "Choose the default music source. YouTube uses the built-in yt-search + yt-dlp nightly "
            "stream player and does not require a YouTube API key."
        )

    _INSTALLED = True
