from __future__ import annotations

import re
from urllib.parse import quote_plus

_INSTALLED = False

_PROVIDER_SUFFIX = re.compile(
    r"\s+(?:on|using|via)\s+(?:youtube(?:\s+music)?|ytmusic|yt)\s*$",
    flags=re.IGNORECASE,
)
_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "in",
    "music",
    "of",
    "on",
    "official",
    "the",
    "to",
    "video",
    "audio",
    "youtube",
    "yt",
}
_BAD_VARIANTS = (
    "nightcore",
    "slowed",
    "sped up",
    "cover",
    "reaction",
    "karaoke",
    "remix",
)


def _clean_youtube_query(query: str) -> str:
    """Remove spoken provider words without changing the requested song name."""
    cleaned = _PROVIDER_SUFFIX.sub("", str(query or "").strip())
    return " ".join(cleaned.split())


def _search_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 1 and token not in _SEARCH_STOP_WORDS
    ]


def _score_youtube_track(query: str, title: str, author: str = "") -> int:
    """Prefer candidates that contain every meaningful requested word.

    This is intentionally strict about distinctive words such as a country or
    song subtitle. Without the missing-token penalty, a very popular track such
    as "Trip to Valhalla" can beat "Trip to USA" just because both contain the
    artist name and "Trip" and the former has an official-video bonus.
    """
    query_tokens = _search_tokens(query)
    title_tokens = set(_search_tokens(title))
    author_tokens = set(_search_tokens(author))
    combined_tokens = title_tokens | author_tokens

    score = 0
    for token in query_tokens:
        if token in title_tokens:
            score += 14
        elif token in author_tokens:
            score += 8
        else:
            score -= 28

    normalized_query = " ".join(_search_tokens(query))
    normalized_title = " ".join(_search_tokens(title))
    if normalized_query and normalized_query in normalized_title:
        score += 40

    title_lower = str(title or "").lower()
    author_lower = str(author or "").lower()
    if "official video" in title_lower or "official music video" in title_lower:
        score += 7
    if "official audio" in title_lower:
        score += 6
    if "vevo" in author_lower:
        score += 4
    if "topic" in author_lower:
        score += 2
    if any(variant in title_lower for variant in _BAD_VARIANTS):
        score -= 12

    # Extra reward for complete token coverage. This makes exact requested
    # variants win over more popular near-matches.
    if query_tokens and all(token in combined_tokens for token in query_tokens):
        score += 50
    return score


def install_media_youtube_provider_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import config, media, webgui, youtube_music

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

    # The normal YouTube player used by Docker previously rewarded generic
    # "official video" matches too heavily. Patch search ranking so all
    # meaningful requested words (for example "USA") matter more than a
    # popular near-match such as "Valhalla".
    if not getattr(youtube_music.YouTubeMusicPlayer, "_neko_exact_search_patch", False):
        original_search_many = youtube_music.YouTubeMusicPlayer.search_many

        def exact_search(self, query: str):
            cleaned = _clean_youtube_query(query)
            if not cleaned:
                raise RuntimeError("I couldn't find an empty YouTube search.")

            # Search the user's words first and use more candidates. Appending
            # "official video official audio" can bias yt-search toward a
            # popular song by the same artist before the requested track appears.
            entries = original_search_many(self, cleaned, 20)
            if not entries:
                entries = original_search_many(self, f"{cleaned} official audio", 20)
            if not entries:
                raise RuntimeError(f"I couldn't find {cleaned} on YouTube.")

            return max(
                entries,
                key=lambda item: _score_youtube_track(
                    cleaned,
                    getattr(item, "title", ""),
                    getattr(item, "author", ""),
                ),
            )

        youtube_music.YouTubeMusicPlayer.search = exact_search
        youtube_music.YouTubeMusicPlayer._neko_exact_search_patch = True

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
