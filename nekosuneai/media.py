from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

from .config import Config, normalize_music_provider
from .media_devices import (
    MediaTargetError,
    control_remote_media,
    default_media_target,
    normalize_media_target,
    play_remote_media,
)
from .media_player import (
    media_status_text,
    next_media_playback,
    pause_media_playback,
    play_media_stream,
    previous_media_playback,
    resume_media_playback,
    seek_media_playback,
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
TARGET_SUFFIX_PATTERN = re.compile(
    r"\s+(?:on|using|via)\s+(local(?: speaker)?|speaker|chromecast|google cast|cast|dlna|upnp|android tv|androidtv|adb|lg tv|lg webos|webos|samsung tv|samsung)\s*$",
    flags=re.IGNORECASE,
)
STOP_PATTERN = re.compile(r"^\s*(stop|stop music|stop audio)\s*$", flags=re.IGNORECASE)
PAUSE_PATTERN = re.compile(r"^\s*(pause|pause music|pause audio)\s*$", flags=re.IGNORECASE)
RESUME_PATTERN = re.compile(r"^\s*(resume|resume music|resume audio|continue|continue music)\s*$", flags=re.IGNORECASE)
NEXT_PATTERN = re.compile(r"^\s*(next|next track|next song|skip|skip track|skip song)\s*$", flags=re.IGNORECASE)
PREVIOUS_PATTERN = re.compile(r"^\s*(previous|previous track|previous song|last track|back a track)\s*$", flags=re.IGNORECASE)
STATUS_PATTERN = re.compile(r"^\s*(what is playing|what's playing|media status|music status)\s*$", flags=re.IGNORECASE)
VOLUME_PATTERN = re.compile(
    r"^\s*(?:set\s+)?(?:the\s+)?(?:(?:music|audio)\s+)?volume\s*(?:to\s*)?(\d{1,3})\s*%?\s*$",
    flags=re.IGNORECASE,
)
SEEK_ABSOLUTE_PATTERN = re.compile(
    r"^\s*(?:seek|jump|go)\s+(?:to\s+)?(?:(\d+)\s*:\s*(\d{1,2})|(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m))\s*$",
    flags=re.IGNORECASE,
)
SEEK_RELATIVE_PATTERN = re.compile(
    r"^\s*(?:seek|skip|jump)\s+(forward|ahead|back|backward)\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\s*$",
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
    return provider, text[: match.start()].strip()


def _extract_target(text: str) -> tuple[str | None, str]:
    match = TARGET_SUFFIX_PATTERN.search(text)
    if not match:
        return None, text
    return normalize_media_target(match.group(1)), text[: match.start()].strip()


def _effective_target(explicit_target: str | None) -> str:
    return normalize_media_target(explicit_target or default_media_target())


def _looks_like_media_request(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith(("play ", "listen ", "listen to ", "put on ", "start ", "tune in ", "tune into "))


def _music_search_url(query: str, provider: str) -> str:
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
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2 or parts[0].lower() in {"discover", "search", "you", "charts", "upload"}:
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
        if token in title: score += 9.0
        if token in snippet: score += 4.0
        if token in url: score += 6.0
    if "/sets/" in url or "/albums/" in url:
        score -= 10.0
    return score


def _find_soundcloud_track_url(query: str, config: Config) -> str | None:
    direct_match = SOUNDCLOUD_URL_PATTERN.search(query)
    if direct_match:
        return _normalize_soundcloud_track_url(direct_match.group(0))
    results = search_web(f"site:soundcloud.com {query} soundcloud", config)
    candidates: list[tuple[float, str]] = []
    for result in results:
        normalized_url = _normalize_soundcloud_track_url(str(result.get("url", "")))
        if normalized_url:
            candidates.append((_score_soundcloud_result(query, result), normalized_url))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_url = candidates[0]
    return best_url if best_score >= 40.0 else None


def _build_soundcloud_stream_url(track_url: str, config: Config) -> str:
    base = config.soundcloud_stream_endpoint.rstrip("/")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}url={quote(track_url, safe='')}&format=mp3"


def _open_url(url: str) -> None:
    opened = webbrowser.open(url, new=2)
    if not opened:
        raise RuntimeError(f"Could not open {url} in the default browser.")


def _seconds(value: float, unit: str) -> float:
    return value * 60.0 if unit.lower().startswith("m") else value


def _control(action: str, target: str, value: float | int | None = None) -> str:
    if target == "local":
        if action == "play": return resume_media_playback()
        if action == "pause": return pause_media_playback()
        if action == "stop": return stop_media_playback()
        if action == "next": return next_media_playback()
        if action == "previous": return previous_media_playback()
        if action == "seek": return seek_media_playback(float(value or 0), relative=False)
        if action == "seek-relative": return seek_media_playback(float(value or 0), relative=True)
        if action == "volume": return set_media_volume(int(value or 0))
        raise RuntimeError(f"Unsupported local media action: {action}")
    remote_action = "play" if action == "resume" else action
    if remote_action == "seek-relative":
        # Remote protocols generally expose absolute seek. Relative seek needs a
        # position query per vendor, so keep this explicit rather than guessing.
        raise MediaTargetError("Relative seek is currently local-only; use 'seek to 2:15' for remote renderers.")
    return control_remote_media(remote_action, target=target, value=value)


def _handle_music_request(
    cleaned_request: str,
    explicit_provider: str | None,
    target: str,
    profile: dict[str, Any],
    config: Config,
) -> MediaActionResult:
    query = cleaned_request.strip()
    if not query or query.lower() in {"music", "some music", "a song", "songs"}:
        query = "trending music"
    provider = explicit_provider or _preferred_music_provider(profile, config)
    if target == "local":
        stop_media_playback()
    if provider == "soundcloud":
        track_url = _find_soundcloud_track_url(query, config)
        if track_url:
            stream_url = _build_soundcloud_stream_url(track_url, config)
            title = f"SoundCloud: {query}"
            response = (
                play_media_stream(stream_url, title=title, kind="music")
                if target == "local"
                else play_remote_media(stream_url, target=target, title=title, content_type="audio/mpeg")
            )
            media = _get_profile_media(profile)
            media["default_music_provider"] = provider
            media["last_music_query"] = query
            media["last_media_target"] = target
            return MediaActionResult(handled=True, response=f"{response} Resolved track: {track_url}")
    if target != "local":
        return MediaActionResult(
            handled=True,
            response=f"I can control {target}, but {provider} search did not provide a directly castable media URL. Use SoundCloud/direct media for remote playback or start the provider app on that device first.",
        )
    url = _music_search_url(query, provider)
    _open_url(url)
    media = _get_profile_media(profile)
    media["default_music_provider"] = provider
    media["last_music_query"] = query
    media["last_media_target"] = target
    return MediaActionResult(handled=True, response=f"Opening {provider} results for '{query}' in your browser.")


def handle_media_request(user_text: str, profile: dict[str, Any], config: Config) -> MediaActionResult:
    explicit_target, command = _extract_target(user_text.strip())
    target = _effective_target(explicit_target)

    try:
        if STOP_PATTERN.match(command):
            return MediaActionResult(True, _control("stop", target))
        if PAUSE_PATTERN.match(command):
            return MediaActionResult(True, _control("pause", target))
        if RESUME_PATTERN.match(command):
            return MediaActionResult(True, _control("play", target))
        if NEXT_PATTERN.match(command):
            return MediaActionResult(True, _control("next", target))
        if PREVIOUS_PATTERN.match(command):
            return MediaActionResult(True, _control("previous", target))
        if STATUS_PATTERN.match(command):
            if target == "local":
                return MediaActionResult(True, media_status_text())
            return MediaActionResult(True, f"Remote target selected: {target}. Status queries vary by renderer; media controls are available.")

        volume_match = VOLUME_PATTERN.match(command)
        if volume_match:
            return MediaActionResult(True, _control("volume", target, int(volume_match.group(1))))

        absolute = SEEK_ABSOLUTE_PATTERN.match(command)
        if absolute:
            if absolute.group(1) is not None:
                seconds = int(absolute.group(1)) * 60 + int(absolute.group(2))
            else:
                seconds = _seconds(float(absolute.group(3)), absolute.group(4))
            return MediaActionResult(True, _control("seek", target, seconds))

        relative = SEEK_RELATIVE_PATTERN.match(command)
        if relative:
            amount = _seconds(float(relative.group(2)), relative.group(3))
            if relative.group(1).lower() in {"back", "backward"}:
                amount *= -1
            return MediaActionResult(True, _control("seek-relative", target, amount))

        if not _looks_like_media_request(command):
            return MediaActionResult(handled=False)

        cleaned_request = _strip_play_prefix(command)
        explicit_provider, cleaned_request = _extract_requested_provider(cleaned_request)
        return _handle_music_request(cleaned_request, explicit_provider, target, profile, config)
    except (MediaTargetError, RuntimeError, ValueError) as exc:
        return MediaActionResult(handled=True, response=f"Media control failed: {exc}")
