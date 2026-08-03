from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

from .config import Config, normalize_music_provider
from .media_player import (
    media_status_text,
    pause_media_playback,
    play_media_stream,
    resume_media_playback,
    set_media_volume,
    stop_media_playback,
)
from .web_search import search_web

PLAY_VERB_PATTERN = re.compile(
    r"^\s*(play|listen to|listen|put on|start|tune into|tune in to|tune in)\s+",
    flags=re.IGNORECASE,
)
PROVIDER_SUFFIX_PATTERN = re.compile(
    r"\s+(?:on|using|via)\s+(soundcloud|spotify|deezer)\s*$",
    flags=re.IGNORECASE,
)
STOP_PATTERN = re.compile(r"^\s*(stop|stop music|stop audio)\s*$", flags=re.IGNORECASE)
PAUSE_PATTERN = re.compile(r"^\s*(pause|pause music|pause audio)\s*$", flags=re.IGNORECASE)
RESUME_PATTERN = re.compile(r"^\s*(resume|resume music|resume audio)\s*$", flags=re.IGNORECASE)
STATUS_PATTERN = re.compile(r"^\s*(what is playing|what's playing|media status|music status)\s*$", flags=re.IGNORECASE)
VOLUME_PATTERN = re.compile(
    r"^\s*(?:set\s+)?(?:the\s+)?(?:(?:music|audio)\s+)?volume\s*(?:to\s*)?(\d{1,3})\s*%?\s*$",
    flags=re.IGNORECASE,
)
SOUNDCLOUD_URL_PATTERN = re.compile(r"https?://(?:www\.)?soundcloud\.com/[^\s]+", flags=re.IGNORECASE)


@dataclass
class MediaActionResult:
    handled: bool
    response: str = ""


def _get_profile_media(profile: dict[str, Any]) -> dict[str, Any]:
    details = profile.get("profile_details")
    if not isinstance(details, dict):
        details = {}
        profile["profile_details"] = details
    media = details.get("media")
    if not isinstance(media, dict):
        media = {}
        details["media"] = media
    return media


def _preferred_music_provider(profile: dict[str, Any], config: Config) -> str:
    media = _get_profile_media(profile)
    provider = str(media.get("default_music_provider", "")).strip()
    if provider:
        return normalize_music_provider(provider)
    return config.music_provider_default


def _strip_play_prefix(text: str) -> str:
    cleaned = PLAY_VERB_PATTERN.sub("", text.strip(), count=1)
    return " ".join(cleaned.split())


def _extract_requested_provider(text: str) -> tuple[str | None, str]:
    match = PROVIDER_SUFFIX_PATTERN.search(text)
    if not match:
        return None, text
    provider = normalize_music_provider(match.group(1))
    stripped = text[: match.start()].strip()
    return provider, stripped


def _looks_like_media_request(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith(("play ", "listen ", "listen to ", "put on ", "start ", "tune in ", "tune into "))


def _music_search_url(query: str, provider: str) -> str:
    # Fallback for providers with no direct-stream resolution (SoundCloud tracks
    # get one via _find_soundcloud_track_url/_build_soundcloud_stream_url below;
    # a future YouTube search/download provider would plug in here too — see
    # TODO.md).
    if provider == "spotify":
        return f"https://open.spotify.com/search/{quote_plus(query)}"
    if provider == "deezer":
        return f"https://www.deezer.com/search/{quote_plus(query)}"
    return f"https://soundcloud.com/search/sounds?q={quote_plus(query)}"


def _normalize_soundcloud_track_url(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    if host != "soundcloud.com":
        return None
    path = parsed.path.strip("/")
    if not path:
        return None
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    if parts[0].lower() in {"discover", "search", "you", "charts", "upload"}:
        return None
    return f"https://soundcloud.com/{parts[0]}/{parts[1]}"


def _score_soundcloud_result(query: str, result: dict[str, str]) -> float:
    normalized_query = " ".join(query.lower().split())
    title = str(result.get("title", "")).lower()
    url = str(result.get("url", "")).lower()
    snippet = str(result.get("snippet", "")).lower()
    combined = " ".join((title, snippet, url))
    score = SequenceMatcher(None, normalized_query, title).ratio() * 100.0
    if normalized_query in combined:
        score += 55.0
    for token in normalized_query.split():
        if token in title:
            score += 9.0
        if token in snippet:
            score += 4.0
        if token in url:
            score += 6.0
    if "/sets/" in url or "/albums/" in url:
        score -= 10.0
    return score


def _find_soundcloud_track_url(query: str, config: Config) -> str | None:
    direct_match = SOUNDCLOUD_URL_PATTERN.search(query)
    if direct_match:
        return _normalize_soundcloud_track_url(direct_match.group(0))

    search_query = f"site:soundcloud.com {query} soundcloud"
    results = search_web(search_query, config)
    candidates: list[tuple[float, str]] = []
    for result in results:
        normalized_url = _normalize_soundcloud_track_url(str(result.get("url", "")))
        if not normalized_url:
            continue
        candidates.append((_score_soundcloud_result(query, result), normalized_url))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_url = candidates[0]
    if best_score < 40.0:
        return None
    return best_url


def _build_soundcloud_stream_url(track_url: str, config: Config) -> str:
    base = config.soundcloud_stream_endpoint.rstrip("/")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}url={quote(track_url, safe='')}&format=mp3"


def _open_url(url: str) -> None:
    opened = webbrowser.open(url, new=2)
    if not opened:
        raise RuntimeError(f"Could not open {url} in the default browser.")


def _handle_music_request(
    cleaned_request: str,
    explicit_provider: str | None,
    profile: dict[str, Any],
    config: Config,
) -> MediaActionResult:
    query = cleaned_request.strip()
    if not query or query.lower() in {"music", "some music", "a song", "songs"}:
        query = "trending music"
    provider = explicit_provider or _preferred_music_provider(profile, config)
    stop_media_playback()
    if provider == "soundcloud":
        track_url = _find_soundcloud_track_url(query, config)
        if track_url:
            stream_url = _build_soundcloud_stream_url(track_url, config)
            response = play_media_stream(
                stream_url,
                title=f"SoundCloud: {query}",
                kind="music",
            )
            media = _get_profile_media(profile)
            media["default_music_provider"] = provider
            media["last_music_query"] = query
            return MediaActionResult(
                handled=True,
                response=f"{response} Resolved track: {track_url}",
            )
    url = _music_search_url(query, provider)
    _open_url(url)
    media = _get_profile_media(profile)
    media["default_music_provider"] = provider
    media["last_music_query"] = query
    return MediaActionResult(
        handled=True,
        response=f"Opening {provider} results for '{query}' in your browser.",
    )


def handle_media_request(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
) -> MediaActionResult:
    if STOP_PATTERN.match(user_text):
        return MediaActionResult(handled=True, response=stop_media_playback())
    if PAUSE_PATTERN.match(user_text):
        return MediaActionResult(handled=True, response=pause_media_playback())
    if RESUME_PATTERN.match(user_text):
        return MediaActionResult(handled=True, response=resume_media_playback())
    if STATUS_PATTERN.match(user_text):
        return MediaActionResult(handled=True, response=media_status_text())

    volume_match = VOLUME_PATTERN.match(user_text)
    if volume_match:
        percent = int(volume_match.group(1))
        return MediaActionResult(handled=True, response=set_media_volume(percent))

    if not _looks_like_media_request(user_text):
        return MediaActionResult(handled=False)

    cleaned_request = _strip_play_prefix(user_text)
    explicit_provider, cleaned_request = _extract_requested_provider(cleaned_request)

    return _handle_music_request(cleaned_request, explicit_provider, profile, config)
