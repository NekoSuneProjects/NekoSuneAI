from __future__ import annotations

import random
import re
import webbrowser
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

import requests

from .config import Config, normalize_media_region, normalize_music_provider
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
    r"\s+(?:on|using|via)\s+(soundcloud|spotify|deezer|radio)\s*$",
    flags=re.IGNORECASE,
)
RADIO_WORD_PATTERN = re.compile(r"\bradio\b", flags=re.IGNORECASE)
STOP_PATTERN = re.compile(r"^\s*(stop|stop music|stop radio|stop audio)\s*$", flags=re.IGNORECASE)
PAUSE_PATTERN = re.compile(r"^\s*(pause|pause music|pause radio|pause audio)\s*$", flags=re.IGNORECASE)
RESUME_PATTERN = re.compile(r"^\s*(resume|resume music|resume radio|resume audio)\s*$", flags=re.IGNORECASE)
STATUS_PATTERN = re.compile(r"^\s*(what is playing|what's playing|media status|music status)\s*$", flags=re.IGNORECASE)
VOLUME_PATTERN = re.compile(
    r"^\s*(?:set\s+)?(?:the\s+)?(?:(?:music|radio|audio)\s+)?volume\s*(?:to\s*)?(\d{1,3})\s*%?\s*$",
    flags=re.IGNORECASE,
)
SOUNDCLOUD_URL_PATTERN = re.compile(r"https?://(?:www\.)?soundcloud\.com/[^\s]+", flags=re.IGNORECASE)
IR_TITLE_PATTERN = re.compile(
    r'<h4 class="text-danger"[^>]*>(.*?)</h4>',
    flags=re.IGNORECASE | re.DOTALL,
)
IR_STREAM_BLOCK_PATTERN = re.compile(
    r"var\s+stream\d+\s*=\s*\{\s*(mp3|m4a)\s*:\s*\"([^\"]+)\"",
    flags=re.IGNORECASE | re.DOTALL,
)

RADIO_QUERY_CLEAN_PATTERN = re.compile(
    r"\b(?:play|listen|listen to|on|the|a|my|radio|station|fm|am|stream|streaming|channel)\b",
    flags=re.IGNORECASE,
)

RADIO_GENRE_ALIASES: dict[str, str] = {
    "bass": "bass",
    "chill": "chill",
    "chillout": "chill",
    "dnb": "drum and bass",
    "drum and bass": "drum and bass",
    "dubstep": "dubstep",
    "frenchcore": "frenchcore",
    "hardstyle": "hardstyle",
    "hardcore": "hardcore",
    "defqon1": "hardstyle",
    "defqon": "hardstyle",
    "house": "house",
    "jpop": "jpop",
    "kpop": "kpop",
    "lofi": "lofi",
    "monstercat": "monstercat",
    "pop": "pop",
    "psytrance": "psytrance",
    "rnb": "rnb",
    "rap": "rap",
    "rock": "rock",
    "techno": "techno",
    "trance": "trance",
}


@dataclass
class MediaActionResult:
    handled: bool
    response: str = ""


@dataclass
class RadioSearchResult:
    title: str
    stream_url: str
    page_url: str
    source: str


RADIO_STATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "capital-fm-uk",
        "name": "Capital FM",
        "region": "GB",
        "aliases": ("capital", "capital fm", "95.8 capital fm"),
        "url": "https://www.globalplayer.com/live/capital/uk/",
        "stream_url": "http://media-ice.musicradio.com/CapitalMP3",
    },
    {
        "id": "heart-uk",
        "name": "Heart",
        "region": "GB",
        "aliases": ("heart", "heart fm", "heart radio"),
        "url": "https://www.globalplayer.com/live/heart/uk/",
        "stream_url": "http://media-ice.musicradio.com/HeartUKMP3",
    },
    {
        "id": "kiss-uk",
        "name": "KISS",
        "region": "GB",
        "aliases": ("kiss", "kiss fm", "kiss uk"),
        "url": "https://www.globalplayer.com/live/kiss/uk/",
        "stream_url": "http://media-ice.musicradio.com/KissFMMP3",
    },
    {
        "id": "bbc-radio-1",
        "name": "BBC Radio 1",
        "region": "GB",
        "aliases": ("bbc radio 1", "radio 1", "bbc one radio"),
        "url": "https://www.bbc.co.uk/sounds/play/live:bbc_radio_one",
        "stream_url": "http://stream.live.vc.bbcmedia.co.uk/bbc_radio_one",
    },
    {
        "id": "bbc-radio-2",
        "name": "BBC Radio 2",
        "region": "GB",
        "aliases": ("bbc radio 2", "radio 2"),
        "url": "https://www.bbc.co.uk/sounds/play/live:bbc_radio_two",
        "stream_url": "http://stream.live.vc.bbcmedia.co.uk/bbc_radio_two",
    },
    {
        "id": "bbc-6-music",
        "name": "BBC Radio 6 Music",
        "region": "GB",
        "aliases": ("bbc 6 music", "radio 6 music", "bbc radio 6"),
        "url": "https://www.bbc.co.uk/sounds/play/live:bbc_6music",
        "stream_url": "http://stream.live.vc.bbcmedia.co.uk/bbc_6music",
    },
    {
        "id": "truckersfm",
        "name": "TruckersFM",
        "region": "GB",
        "aliases": ("truckersfm", "truckers fm", "truckers"),
        "url": "https://truckers.fm/radio",
        "stream_url": "https://radio.truckers.fm",
    },
    {
        "id": "triple-j",
        "name": "triple j",
        "region": "AU",
        "aliases": ("triple j", "triplej", "abc triple j"),
        "url": "https://www.abc.net.au/triplej/live/triplej",
        "stream_url": "http://live-radio01.mediahubaustralia.com/2TJW/mp3/",
    },
    {
        "id": "double-j",
        "name": "Double J",
        "region": "AU",
        "aliases": ("double j", "abc double j"),
        "url": "https://www.abc.net.au/doublej/live",
    },
    {
        "id": "abc-radio-australia",
        "name": "ABC Radio Australia",
        "region": "AU",
        "aliases": ("abc radio australia", "radio australia"),
        "url": "https://www.abc.net.au/pacific/programs/radio-australia",
    },
    {
        "id": "cbc-radio-one",
        "name": "CBC Radio One",
        "region": "CA",
        "aliases": ("cbc radio one", "cbc one", "radio one canada"),
        "url": "https://www.cbc.ca/listen/live-radio",
    },
    {
        "id": "cbc-music",
        "name": "CBC Music",
        "region": "CA",
        "aliases": ("cbc music", "cbc radio 2", "radio 2 canada"),
        "url": "https://www.cbc.ca/listen/live-radio",
    },
    {
        "id": "boom-97-3",
        "name": "boom 97.3",
        "region": "CA",
        "aliases": ("boom 97.3", "boom 973", "boom toronto"),
        "url": "https://boom973.com/",
    },
    {
        "id": "ilove-radio",
        "name": "I LOVE RADIO",
        "region": "DE",
        "aliases": ("i love radio", "ilove radio", "i love"),
        "url": "https://www.ilovemusic.de/radio",
        "stream_url": "https://stream01.iloveradio.de/iloveradio1.mp3",
    },
    {
        "id": "ilove-2dance",
        "name": "I LOVE 2 DANCE",
        "region": "DE",
        "aliases": ("i love 2 dance", "ilove 2 dance", "i love dance"),
        "url": "https://www.ilovemusic.de/radio",
        "stream_url": "https://stream01.iloveradio.de/iloveradio17.mp3",
    },
    {
        "id": "listen-moe-jpop",
        "name": "LISTEN.moe JPOP",
        "region": "JP",
        "aliases": ("listen.moe", "listen moe", "listen moe jpop", "jpop radio"),
        "url": "https://listen.moe/",
    },
    {
        "id": "listen-moe-kpop",
        "name": "LISTEN.moe KPOP",
        "region": "JP",
        "aliases": ("listen moe kpop", "listen.moe kpop", "kpop radio"),
        "url": "https://listen.moe/kpop",
    },
    {
        "id": "j1-gold",
        "name": "J1 Gold",
        "region": "DE",
        "aliases": ("j1 gold", "j1", "j1 radio"),
        "url": "https://www.j1.fm/",
    },
    {
        "id": "z100-ny",
        "name": "Z100",
        "region": "US",
        "aliases": ("z100", "z100 new york", "new york z100"),
        "url": "https://www.iheart.com/live/z100-new-york-2485/",
    },
    {
        "id": "kiis-fm-la",
        "name": "KIIS FM",
        "region": "US",
        "aliases": ("kiis fm", "102.7 kiis fm", "kiss fm la"),
        "url": "https://www.iheart.com/live/1027-kiis-fm-1739/",
    },
    {
        "id": "hot-97-ny",
        "name": "HOT 97",
        "region": "US",
        "aliases": ("hot 97", "hot97", "hot 97 ny"),
        "url": "https://www.hot97.com/listen-live/",
    },
    {
        "id": "kexp-seattle",
        "name": "KEXP",
        "region": "US",
        "aliases": ("kexp", "kexp seattle"),
        "url": "https://www.kexp.org/listen/",
    },
    {
        "id": "wnyc",
        "name": "WNYC",
        "region": "US",
        "aliases": ("wnyc", "wnyc radio"),
        "url": "https://www.wnyc.org/radio/",
    },
    {
        "id": "npr",
        "name": "NPR",
        "region": "US",
        "aliases": ("npr", "npr radio", "national public radio"),
        "url": "https://www.npr.org/live/",
    },
    {
        "id": "soma-groove-salad",
        "name": "SomaFM Groove Salad",
        "region": "US",
        "aliases": ("groove salad", "somafm groove salad", "soma fm"),
        "url": "https://somafm.com/groovesalad/",
        "stream_url": "https://ice2.somafm.com/groovesalad-128-mp3",
    },
    {
        "id": "soma-drone-zone",
        "name": "SomaFM Drone Zone",
        "region": "US",
        "aliases": ("drone zone", "somafm drone zone"),
        "url": "https://somafm.com/dronezone/",
        "stream_url": "https://ice2.somafm.com/dronezone-128-mp3",
    },
)


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


def _preferred_region(profile: dict[str, Any], config: Config) -> str:
    media = _get_profile_media(profile)
    region = str(media.get("preferred_radio_region", "")).strip()
    if region:
        return normalize_media_region(region)
    return config.media_region


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


def _score_station(query: str, station: dict[str, Any], preferred_region: str) -> float:
    query_lower = query.lower().strip()
    query_simple = re.sub(r"[^a-z0-9]+", "", query_lower)
    best = 0.0
    for alias in station["aliases"]:
        alias_lower = alias.lower()
        alias_simple = re.sub(r"[^a-z0-9]+", "", alias_lower)
        if query_lower == alias_lower:
            best = max(best, 200.0)
        elif query_simple and query_simple == alias_simple:
            best = max(best, 185.0)
        elif alias_lower in query_lower or query_lower in alias_lower:
            best = max(best, 130.0)
        elif alias_simple and (alias_simple in query_simple or query_simple in alias_simple):
            best = max(best, 120.0)
        else:
            best = max(best, SequenceMatcher(None, query_lower, alias_lower).ratio() * 100.0)
    if station["region"] == preferred_region:
        best += 25.0
    return best


def _score_radio_result(query: str, title: str) -> float:
    query_lower = query.lower().strip()
    title_lower = title.lower().strip()
    query_simple = re.sub(r"[^a-z0-9]+", "", query_lower)
    title_simple = re.sub(r"[^a-z0-9]+", "", title_lower)
    score = SequenceMatcher(None, query_lower, title_lower).ratio() * 100.0
    if query_lower == title_lower:
        score += 100.0
    if query_simple and query_simple == title_simple:
        score += 85.0
    elif query_simple and (query_simple in title_simple or title_simple in query_simple):
        score += 45.0
    for token in query_lower.split():
        if token in title_lower:
            score += 8.0
    return score


def _normalize_radio_query(query: str) -> str:
    cleaned = RADIO_QUERY_CLEAN_PATTERN.sub(" ", query).strip()
    return " ".join(cleaned.split())


def _lookup_genre_query(query: str) -> str | None:
    normalized = query.lower().strip()
    for alias, genre in RADIO_GENRE_ALIASES.items():
        if normalized == alias or alias in normalized:
            return genre
    return None


def _find_dynamic_radio_station(query: str, random_choice: bool = False) -> RadioSearchResult | None:
    candidates = _search_internet_radio(query)
    if not candidates:
        return None

    genre_query = _lookup_genre_query(query)
    if random_choice or genre_query:
        genre = genre_query or query
        matching = [item for item in candidates if genre.lower() in item.title.lower()]
        if matching:
            return random.choice(matching)

    ranked = sorted(
        candidates,
        key=lambda item: _score_radio_result(query, item.title),
        reverse=True,
    )
    best = ranked[0]
    if _score_radio_result(query, best.title) < 55.0:
        return None
    return best


def _search_internet_radio(query: str) -> list[RadioSearchResult]:
    url = f"https://www.internet-radio.com/search/?radio={quote_plus(query)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, timeout=20, headers=headers)
    except requests.RequestException as exc:
        raise RuntimeError(f"internet-radio.com search failed: {exc}") from exc

    if response.status_code not in {200, 404}:
        raise RuntimeError(
            f"internet-radio.com returned HTTP {response.status_code} for radio search."
        )

    html = response.text
    raw_titles = IR_TITLE_PATTERN.findall(html)
    titles = [
        re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", title))).strip()
        for title in raw_titles
    ]
    titles = [title for title in titles if title and "radio station directory" not in title.lower()]

    streams = IR_STREAM_BLOCK_PATTERN.findall(html)
    results: list[RadioSearchResult] = []
    for index, (stream_type, stream_url) in enumerate(streams):
        if index >= len(titles):
            break
        normalized_stream = stream_url.strip()
        if not normalized_stream:
            continue
        results.append(
            RadioSearchResult(
                title=titles[index],
                stream_url=normalized_stream,
                page_url=url,
                source=f"internet-radio.com ({stream_type.lower()})",
            )
        )
    return results


def _find_radio_station(query: str, preferred_region: str) -> dict[str, Any] | None:
    ranked = sorted(
        RADIO_STATIONS,
        key=lambda station: _score_station(query, station, preferred_region),
        reverse=True,
    )
    if not ranked:
        return None
    best = ranked[0]
    if _score_station(query, best, preferred_region) < 65.0:
        return None
    return best


def _music_search_url(query: str, provider: str) -> str:
    if provider == "spotify":
        return f"https://open.spotify.com/search/{quote_plus(query)}"
    if provider == "deezer":
        return f"https://www.deezer.com/search/{quote_plus(query)}"
    if provider == "radio":
        return f"https://www.google.com/search?q={quote_plus(query + ' live radio')}"
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


def _maybe_handle_radio_request(
    cleaned_request: str,
    profile: dict[str, Any],
    config: Config,
) -> MediaActionResult:
    preferred_region = _preferred_region(profile, config)
    lowered = cleaned_request.lower()
    is_radio_request = (
        " radio" in f" {lowered} "
        or any(token in lowered for token in ("fm", "am", "station"))
    )
    if not is_radio_request:
        station = _find_radio_station(cleaned_request, preferred_region)
        if station is None:
            return MediaActionResult(handled=False)
    else:
        station_query = RADIO_WORD_PATTERN.sub("", cleaned_request).strip() or cleaned_request
        station_query = _normalize_radio_query(station_query)
        if not station_query:
            station_query = "radio"

        station = _find_radio_station(station_query, preferred_region)
        if station is None:
            genre_query = _lookup_genre_query(station_query)
            random_choice = bool(
                genre_query
                or station_query.strip() in {"random", "shuffle", "surprise", "radio"}
            )
            if genre_query:
                search_query = genre_query
            elif station_query.strip() in {"random", "shuffle", "surprise"}:
                search_query = "radio"
            else:
                search_query = station_query
            dynamic_station = _find_dynamic_radio_station(
                search_query, random_choice=random_choice
            )
            if dynamic_station is None:
                return MediaActionResult(
                    handled=True,
                    response=(
                        f"I could not match a radio station for '{cleaned_request}' in region "
                        f"{preferred_region}. Edit MEDIA_REGION or profile_details.media.preferred_radio_region "
                        "if you want a different country."
                    ),
                )
            response = play_media_stream(
                dynamic_station.stream_url,
                title=dynamic_station.title,
                kind="radio",
            )
            media = _get_profile_media(profile)
            media["last_radio_station_id"] = dynamic_station.title
            return MediaActionResult(
                handled=True,
                response=f"{response} Resolved via {dynamic_station.source}.",
            )

    stream_url = str(station.get("stream_url", "")).strip()
    if stream_url:
        response = play_media_stream(
            stream_url,
            title=station["name"],
            kind="radio",
        )
    else:
        stop_media_playback()
        _open_url(station["url"])
        response = f"Opening {station['name']} for region {station['region']} in your browser."
    media = _get_profile_media(profile)
    media["preferred_radio_region"] = station["region"]
    media["last_radio_station_id"] = station["id"]
    return MediaActionResult(handled=True, response=response)


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
    lowered = cleaned_request.lower()

    if explicit_provider == "radio":
        return _maybe_handle_radio_request(cleaned_request, profile, config)

    if "radio" in lowered or any(token in lowered for token in (" fm", " am", "station")):
        return _maybe_handle_radio_request(cleaned_request, profile, config)

    station_match = _find_radio_station(cleaned_request, _preferred_region(profile, config))
    if station_match is not None and cleaned_request.lower() in {
        station_match["name"].lower(),
        *[alias.lower() for alias in station_match["aliases"]],
    }:
        return _maybe_handle_radio_request(cleaned_request, profile, config)

    return _handle_music_request(cleaned_request, explicit_provider, profile, config)
