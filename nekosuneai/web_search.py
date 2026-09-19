"""Web search and page-excerpt gathering.

Three interchangeable backends - SearXNG, DuckDuckGo and a generic POST gateway
- all reduce to the same ``{title, url, snippet}`` record shape. Results are
then enriched with a short excerpt pulled from the page itself, re-ranked for
relevance and recency, and formatted into the context block handed to the model.

Also decides, from the user's own wording, whether a search is warranted at all
and what to actually search for.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import requests

from .config import Config

AUTO_SEARCH_HINTS = (
    "latest",
    "current",
    "today",
    "news",
    "update",
    "release",
    "version",
    "price",
    "weather",
    "score",
    "stocks",
    "crypto",
    "breaking",
    "this week",
    "right now",
    "happening",
)

URL_PATTERN = re.compile(r"https?://", flags=re.IGNORECASE)
WEATHER_HINT_PATTERN = re.compile(
    r"\b(weather|forecast|temperature|rain|wind|humidity)\b",
    flags=re.IGNORECASE,
)
LOOKUP_VERB_PATTERN = re.compile(
    r"\b(check|look up|lookup|search|find|google|browse|pull up)\b",
    flags=re.IGNORECASE,
)
SCRIPT_STYLE_PATTERN = re.compile(
    r"<(script|style|noscript)\b.*?>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

WEB_EXCERPT_MAX_RESULTS = 2
WEB_EXCERPT_MAX_CHARS = 420
CURRENT_YEAR = date.today().year
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

RECENCY_TOKENS = (
    "today",
    "tonight",
    "tomorrow",
    "current",
    "latest",
    "new",
    "news",
    "update",
    "updated",
    "release",
    "price",
    "weather",
    "forecast",
    "score",
    "stocks",
    "crypto",
    "right now",
    "live",
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
QUERY_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "about", "into",
    "can", "you", "your", "please", "check", "search", "find", "look",
    "lookup", "google", "browse", "pull", "latest", "current", "today",
    "tomorrow", "now",
}

LOW_TRUST_HOST_HINTS = (
    "tokencalculator",
    "llm-stats",
    "chatgptimagegenerator",
    "buildfastwithai",
    "pasqualepillitteri",
)
WEATHER_TRUSTED_DOMAINS = (
    "bom.gov.au",
    "weather.gov",
    "metoffice.gov.uk",
    "accuweather.com",
    "weather.com",
    "wunderground.com",
)
OPENAI_TRUSTED_DOMAINS = (
    "openai.com",
    "platform.openai.com",
    "help.openai.com",
)
TECH_NEWS_DOMAINS = (
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "reuters.com",
    "fortune.com",
)

# Same-day / this-week / this-month cues used to bound a search window.
_SAME_DAY_TOKENS = ("today", "tonight", "tomorrow", "right now", "live")
_THIS_WEEK_TOKENS = ("weather", "forecast", "score", "stocks", "crypto", "price")
_OPENAI_QUERY_TOKENS = ("openai", "chatgpt", "gpt")
_WEATHER_QUERY_TOKENS = ("weather", "forecast", "temperature", "rain", "wind")
_IMMEDIACY_TOKENS = ("today", "current", "latest", "right now")
_FRESH_PAGE_TOKENS = ("today", "tonight", "tomorrow", "live", "updated", "current")

# Where a query token can appear, and what a hit there is worth.
_TOKEN_FIELD_WEIGHTS = (
    ("host", 24),
    ("title", 10),
    ("url", 6),
    ("snippet", 4),
    ("excerpt", 3),
)

_MAX_RESULT_LIMIT = 10
_OVERFETCH_CEILING = 12
_MIN_EXCERPT_CHARS = 80
_EXCERPT_TIMEOUT_FLOOR = 4
_EXCERPT_TIMEOUT_CEILING = 12

_USER_AGENT = "NekoSuneAI/1.0 (+https://github.com/)"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_READABLE_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

_EMPTY_QUERY_ERROR = "Please provide a web search query after /web."


@dataclass
class WebContextBundle:
    query: str
    context: str
    result_count: int


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


@contextmanager
def _suppress_native_output() -> object:
    """Silence writes from C extensions by swapping the real fds for devnull.

    Some search clients print directly to the process's stdout/stderr, which
    would otherwise corrupt the console UI mid-conversation.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    try:
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
    except Exception:
        # No real file descriptors (pythonw, captured streams): nothing to do.
        yield
        return

    saved_stdout_fd: int | None = None
    saved_stderr_fd: int | None = None
    devnull_fd: int | None = None
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stdout_fd = os.dup(stdout_fd)
        saved_stderr_fd = os.dup(stderr_fd)
        os.dup2(devnull_fd, stdout_fd)
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        if saved_stdout_fd is not None:
            os.dup2(saved_stdout_fd, stdout_fd)
            os.close(saved_stdout_fd)
        if saved_stderr_fd is not None:
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stderr_fd)
        if devnull_fd is not None:
            os.close(devnull_fd)


def _load_ddgs_client() -> type:
    """Import DDGS from whichever package name is installed."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError(
                "DuckDuckGo search requires the 'duckduckgo-search' package. "
                "Run: pip install duckduckgo-search"
            ) from exc
    return DDGS


def _clean_text(value: object, fallback: str) -> str:
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        if cleaned:
            return cleaned
    return fallback


def _trim_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    clipped = compact[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return (clipped or compact[: max_chars - 3]).rstrip(" ,.;:") + "..."


def _as_result_line(title: str, url: str, snippet: str, index: int) -> list[str]:
    host = urlparse(url).netloc or "unknown-source"
    return [
        f"{index}. {title}",
        f"   Source: {host}",
        f"   URL: {url}",
        f"   Snippet: {snippet}",
    ]


def _normalize_host(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


# --------------------------------------------------------------------------
# Page excerpts
# --------------------------------------------------------------------------


def _extract_page_excerpt(url: str, timeout_seconds: int) -> str | None:
    """Fetch a page and reduce it to a short plain-text excerpt."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _BROWSER_USER_AGENT},
            timeout=max(
                _EXCERPT_TIMEOUT_FLOOR, min(timeout_seconds, _EXCERPT_TIMEOUT_CEILING)
            ),
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    content_type = response.headers.get("Content-Type", "").lower()
    if not any(kind in content_type for kind in _READABLE_CONTENT_TYPES):
        return None

    raw_text = response.text
    if not raw_text:
        return None

    text = SCRIPT_STYLE_PATTERN.sub(" ", raw_text)
    text = TAG_PATTERN.sub(" ", text)
    text = unescape(text)
    text = WHITESPACE_PATTERN.sub(" ", text).strip()

    if len(text) < _MIN_EXCERPT_CHARS:
        return None
    return _trim_text(text, WEB_EXCERPT_MAX_CHARS)


def _enrich_results_with_page_excerpts(
    results: list[dict[str, str]],
    timeout_seconds: int,
) -> None:
    for result in results[:WEB_EXCERPT_MAX_RESULTS]:
        url = result.get("url", "").strip()
        if not url:
            continue
        excerpt = _extract_page_excerpt(url, timeout_seconds)
        if excerpt:
            result["page_excerpt"] = excerpt


# --------------------------------------------------------------------------
# Query shaping
# --------------------------------------------------------------------------


def _has_explicit_year(query: str) -> bool:
    return bool(YEAR_PATTERN.search(query))


def _is_recency_focused_query(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in RECENCY_TOKENS)


def _infer_time_range(query: str) -> str | None:
    """Narrow the search window when the wording implies one."""
    if _has_explicit_year(query):
        return None

    lowered = query.lower()
    if any(token in lowered for token in _SAME_DAY_TOKENS):
        return "day"
    if any(token in lowered for token in _THIS_WEEK_TOKENS):
        return "week"
    if _is_recency_focused_query(query):
        return "month"
    return None


def _expand_query_for_recency(query: str) -> str:
    """Append the current year to a time-sensitive query that lacks one."""
    if _has_explicit_year(query):
        return query
    if not _is_recency_focused_query(query):
        return query
    if str(CURRENT_YEAR) in query:
        return query
    return f"{query} {CURRENT_YEAR}"


def _query_tokens(query: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(query.lower())
        if len(token) > 2 and token not in QUERY_STOPWORDS
    ]


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def _host_in(host: str, domains: Iterable[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _domain_trust_score(query: str, host: str) -> int:
    """Nudge well-known authoritative hosts up and known junk hosts down."""
    if not host:
        return 0

    query_lower = query.lower()
    score = 0

    if _host_in(host, OPENAI_TRUSTED_DOMAINS):
        on_topic = any(token in query_lower for token in _OPENAI_QUERY_TOKENS)
        score += 120 if on_topic else 20

    if _host_in(host, WEATHER_TRUSTED_DOMAINS):
        on_topic = any(token in query_lower for token in _WEATHER_QUERY_TOKENS)
        score += 90 if on_topic else 25

    if _host_in(host, TECH_NEWS_DOMAINS):
        score += 18

    if host.endswith(".gov") or ".gov." in host:
        score += 22
    if host.endswith(".edu") or ".edu." in host:
        score += 16

    if any(hint in host for hint in LOW_TRUST_HOST_HINTS):
        score -= 30

    return score


def _result_relevance_score(
    result: dict[str, str],
    tokens: list[str],
    query: str,
) -> int:
    if not tokens:
        return 0

    title = result.get("title", "").lower()
    url = result.get("url", "").lower()
    snippet = result.get("snippet", "").lower()
    excerpt = result.get("page_excerpt", "").lower()
    host = _normalize_host(url)

    fields = {
        "host": host,
        "title": title,
        "url": url,
        "snippet": snippet,
        "excerpt": excerpt,
    }
    score = sum(
        weight
        for token in tokens
        for field, weight in _TOKEN_FIELD_WEIGHTS
        if token in fields[field]
    )
    score += _domain_trust_score(query, host)

    # Penalise archival pages when the question is clearly about right now.
    query_lower = query.lower()
    combined = " ".join((title, snippet, excerpt, url))
    if any(token in query_lower for token in _IMMEDIACY_TOKENS):
        if "history" in combined or "archive" in combined:
            score -= 18
    if "weather" in query_lower and "history" in combined and "forecast" not in combined:
        score -= 12

    return score


def _result_recency_score(result: dict[str, str]) -> int:
    joined = " ".join(
        (
            result.get("title", ""),
            result.get("snippet", ""),
            result.get("page_excerpt", ""),
            result.get("url", ""),
        )
    )
    lowered = joined.lower()
    score = 0

    years = [int(match.group(1)) for match in YEAR_PATTERN.finditer(joined)]
    if years:
        newest = max(years)
        if newest >= CURRENT_YEAR:
            score += 40
        elif newest == CURRENT_YEAR - 1:
            score += 20
        elif newest <= CURRENT_YEAR - 3:
            score -= 25

    if any(token in lowered for token in _FRESH_PAGE_TOKENS):
        score += 15
    if "weather" in lowered or "forecast" in lowered:
        score += 5

    return score


def _rerank_results_for_recency(
    records: list[dict[str, str]],
    query: str,
) -> list[dict[str, str]]:
    if not records:
        return records

    query_tokens = _query_tokens(query)
    recency_focused = _is_recency_focused_query(query)

    def sort_key(result: dict[str, str]) -> tuple[int, int]:
        relevance = _result_relevance_score(result, query_tokens, query)
        recency = _result_recency_score(result) if recency_focused else 0
        return (relevance, recency)

    return sorted(records, key=sort_key, reverse=True)


# --------------------------------------------------------------------------
# Shared backend pipeline
# --------------------------------------------------------------------------


def _require_query(query: str) -> str:
    normalized = " ".join(query.strip().split())
    if not normalized:
        raise RuntimeError(_EMPTY_QUERY_ERROR)
    return normalized


def _result_limit(config: Config) -> int:
    return max(1, min(config.web_max_results, _MAX_RESULT_LIMIT))


def _overfetch_limit(limit: int) -> int:
    """Pull extra results so re-ranking has something to choose between."""
    return max(limit, min(_OVERFETCH_CEILING, limit * 2))


def _first_key(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return None


def _collect_records(
    raw_results: Iterable[Any],
    cap: int,
    url_keys: tuple[str, ...],
    title_keys: tuple[str, ...],
    snippet_keys: tuple[str, ...],
) -> list[dict[str, str]]:
    """Normalise provider-specific result dicts into our common shape."""
    records: list[dict[str, str]] = []
    for raw in raw_results or []:
        if not isinstance(raw, dict):
            continue

        url = _clean_text(_first_key(raw, url_keys), "")
        if not url:
            continue

        records.append(
            {
                "title": _clean_text(_first_key(raw, title_keys), "Untitled result"),
                "url": url,
                "snippet": _clean_text(
                    _first_key(raw, snippet_keys), "No snippet provided."
                ),
            }
        )
        if len(records) >= cap:
            break
    return records


def _finalize_records(
    records: list[dict[str, str]],
    query: str,
    config: Config,
    limit: int,
) -> list[dict[str, str]]:
    """Add page excerpts, re-rank, and cut back to the requested count."""
    if not records:
        return records
    _enrich_results_with_page_excerpts(records, config.web_timeout_seconds)
    return _rerank_results_for_recency(records, query)[:limit]


# --------------------------------------------------------------------------
# SearXNG
# --------------------------------------------------------------------------


def _searxng_language(region: str) -> str:
    normalized = region.strip().lower()
    mapping = {
        "us-en": "en-US",
        "uk-en": "en-GB",
        "gb-en": "en-GB",
        "en-us": "en-US",
        "en-gb": "en-GB",
        "all": "all",
    }
    return mapping.get(normalized, region or "en-US")


def _searxng_safesearch(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "off":
        return 0
    if normalized in {"strict", "high"}:
        return 2
    return 1


def _search_web_via_searxng(query: str, *, config: Config) -> list[dict[str, str]]:
    normalized_query = _require_query(query)
    limit = _result_limit(config)

    params: dict[str, Any] = {
        "q": _expand_query_for_recency(normalized_query),
        "format": "json",
        "language": _searxng_language(config.web_region),
        "safesearch": _searxng_safesearch(config.web_safesearch),
    }
    time_range = _infer_time_range(normalized_query)
    if time_range:
        params["time_range"] = time_range

    try:
        response = requests.get(
            config.web_search_url,
            params=params,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            timeout=config.web_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"SearXNG request failed for {config.web_search_url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"SearXNG returned HTTP {response.status_code} from {config.web_search_url}."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"SearXNG returned invalid JSON from {config.web_search_url}."
        ) from exc

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    records = _collect_records(
        raw_results,
        _overfetch_limit(limit),
        url_keys=("url",),
        title_keys=("title",),
        snippet_keys=("content", "snippet"),
    )
    return _finalize_records(records, normalized_query, config, limit)


# --------------------------------------------------------------------------
# DuckDuckGo
# --------------------------------------------------------------------------

_DDG_TIMELIMITS = {"day": "d", "week": "w", "month": "m"}


def _search_web_via_duckduckgo(query: str, *, config: Config) -> list[dict[str, str]]:
    normalized_query = _require_query(query)
    limit = _result_limit(config)
    cap = _overfetch_limit(limit)

    DDGS = _load_ddgs_client()
    timelimit = _DDG_TIMELIMITS.get(_infer_time_range(normalized_query) or "")

    try:
        with _suppress_native_output():
            with DDGS(timeout=config.web_timeout_seconds) as client:
                raw_results = client.text(
                    _expand_query_for_recency(normalized_query),
                    region=config.web_region,
                    safesearch=config.web_safesearch,
                    timelimit=timelimit,
                    backend="html",
                    max_results=cap,
                )
            records = _collect_records(
                raw_results,
                cap,
                url_keys=("href", "url"),
                title_keys=("title",),
                snippet_keys=("body", "snippet"),
            )
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc

    return _finalize_records(records, normalized_query, config, limit)


# --------------------------------------------------------------------------
# Generic gateway
# --------------------------------------------------------------------------


def _search_web_via_gateway(query: str, *, config: Config) -> list[dict[str, str]]:
    """Multi-backend search gateway (POST {query, provider} -> {results: [...]}).

    Typically a self-hosted proxy in front of SearXNG/Brave/Tavily behind one
    OpenAI-style API. NOTE: the exact field names inside each result item are
    unconfirmed - live testing only ever returned an empty ``results`` list, so
    the common key-name variants other providers here use are all accepted
    (title/name, url/link, snippet/content/description) rather than assuming one
    exact shape. Verify against a real non-empty response and adjust if the
    gateway uses different names.
    """
    normalized_query = _require_query(query)
    if not config.web_search_url:
        raise RuntimeError(
            "No search gateway URL set - configure it in Settings -> Web Search."
        )

    body: dict[str, Any] = {"query": _expand_query_for_recency(normalized_query)}
    if config.web_search_gateway_provider:
        body["provider"] = config.web_search_gateway_provider

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
    }
    if config.web_search_api_key:
        headers["Authorization"] = f"Bearer {config.web_search_api_key}"

    try:
        response = requests.post(
            config.web_search_url,
            json=body,
            headers=headers,
            timeout=config.web_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Search gateway request failed for {config.web_search_url}: {exc}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Search gateway returned invalid JSON from {config.web_search_url}."
        ) from exc

    # A gateway may report the failure in-band, so check that before the status.
    error = payload.get("error") if isinstance(payload, dict) else None
    if error:
        detail = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"Search gateway error: {detail}")
    if response.status_code >= 400:
        raise RuntimeError(
            f"Search gateway returned HTTP {response.status_code} from {config.web_search_url}."
        )

    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return []

    limit = _result_limit(config)
    records = _collect_records(
        raw_results,
        _overfetch_limit(limit),
        url_keys=("url", "link"),
        title_keys=("title", "name"),
        snippet_keys=("snippet", "content", "description"),
    )
    return _finalize_records(records, normalized_query, config, limit)


_SEARCH_BACKENDS: dict[str, Callable[..., list[dict[str, str]]]] = {
    "searxng": _search_web_via_searxng,
    "duckduckgo": _search_web_via_duckduckgo,
    "gateway": _search_web_via_gateway,
}


def search_web(query: str, config: Config) -> list[dict[str, str]]:
    backend = _SEARCH_BACKENDS.get(config.web_search_provider)
    if backend is None:
        raise RuntimeError(
            f"Unsupported web search provider '{config.web_search_provider}'."
        )
    return backend(query, config=config)


# --------------------------------------------------------------------------
# Deciding whether, and what, to search
# --------------------------------------------------------------------------

_MIN_QUERY_CHARS = 8

_LEADING_PUNCTUATION = re.compile(r"^[,.\-:;!? ]+")
_TRAILING_PUNCTUATION = re.compile(r"[,.\-:;!? ]+$")

# Applied in order to strip politeness before the real query.
_FILLER_PATTERNS = (
    re.compile(r"^\s*(hey|hi|hello)\b[,\s]*", re.IGNORECASE),
    re.compile(r"^\s*(can|could|would|will)\s+you\b[,\s]*", re.IGNORECASE),
    re.compile(r"^\s*please\b[,\s]*", re.IGNORECASE),
    re.compile(r"\bfor\s+me\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
)

# Applied after the filler pass, to drop the lookup verb itself.
_QUERY_PREFIX_PATTERNS = (
    re.compile(r"^\s*(check|look up|lookup|search|find|google|browse|pull up)\s+", re.IGNORECASE),
    re.compile(r"^\s*(for|about)\s+", re.IGNORECASE),
    re.compile(r"^\s*me\s+", re.IGNORECASE),
)

_WEATHER_NOISE = re.compile(
    r"\b(today|tonight|tomorrow|right now|please|thanks|thank you)\b", re.IGNORECASE
)
_FOR_ME = re.compile(r"\bfor\s+me\b", re.IGNORECASE)

_NON_LOCATIONS = {"me", "my", "my area", "here"}
_VAGUE_QUERIES = {"anything", "something", "it", "that", "this"}
_LOCATION_SPLITTERS = (" in ", " for ", " at ")


def _is_searchable_request(text: str) -> bool:
    """Shared gate: long enough, not a command, and not already a URL."""
    if len(text) < _MIN_QUERY_CHARS:
        return False
    if text.startswith("/"):
        return False
    return not URL_PATTERN.search(text)


def should_auto_search(user_text: str) -> bool:
    text = user_text.strip()
    if not _is_searchable_request(text):
        return False

    lowered = text.lower()
    return any(hint in lowered for hint in AUTO_SEARCH_HINTS)


def _normalize_query_text(text: str) -> str:
    compact = " ".join(text.strip().split())
    compact = _LEADING_PUNCTUATION.sub("", compact)
    return _TRAILING_PUNCTUATION.sub("", compact)


def _strip_conversational_filler(text: str) -> str:
    cleaned = text.strip()
    for pattern in _FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return _normalize_query_text(cleaned)


def _extract_weather_location(text: str) -> str | None:
    """Pull a place name out of "weather in X" style phrasing."""
    for splitter in _LOCATION_SPLITTERS:
        if splitter not in text:
            continue

        candidate = text.split(splitter, 1)[1]
        candidate = _WEATHER_NOISE.sub("", candidate)
        candidate = _FOR_ME.sub("", candidate)
        candidate = _normalize_query_text(candidate)

        if not candidate or candidate.lower() in _NON_LOCATIONS:
            continue
        return candidate
    return None


def extract_web_query_from_request(user_text: str) -> str | None:
    text = user_text.strip()
    if not _is_searchable_request(text):
        return None

    lowered = text.lower()
    if WEATHER_HINT_PATTERN.search(lowered):
        location = _extract_weather_location(text)
        return f"weather {location}" if location else "weather forecast today"

    if not LOOKUP_VERB_PATTERN.search(lowered):
        return None

    stripped = _strip_conversational_filler(text)
    for pattern in _QUERY_PREFIX_PATTERNS:
        stripped = pattern.sub("", stripped)
    stripped = _normalize_query_text(stripped)

    if stripped.lower() in _VAGUE_QUERIES:
        return None
    return stripped or None


# --------------------------------------------------------------------------
# Context block
# --------------------------------------------------------------------------

_NO_CONTEXT_MESSAGE = (
    "Web context is unavailable right now. "
    "Be transparent and answer from existing knowledge only."
)
_CONTEXT_FOOTER = (
    "If you reference these results, mention the source URL plainly and do not "
    "invent details that are not supported."
)


def build_web_context(
    query: str, results: list[dict[str, str]], config: Config
) -> str:
    if not results:
        return _NO_CONTEXT_MESSAGE

    lines = [
        "Fresh web context for the next answer:",
        f"Search provider: {config.web_search_provider}",
        f"Search query: {query}",
        "Results:",
    ]

    for index, result in enumerate(results, start=1):
        result_lines = _as_result_line(
            title=result["title"],
            url=result["url"],
            snippet=result["snippet"],
            index=index,
        )
        page_excerpt = _clean_text(result.get("page_excerpt"), "")
        if page_excerpt:
            result_lines.append(f"   Website excerpt: {page_excerpt}")
        lines.extend(result_lines)

    lines.append(_CONTEXT_FOOTER)
    return "\n".join(lines)


def fetch_web_context(query: str, config: Config) -> WebContextBundle:
    results = search_web(query, config)
    if not results:
        raise RuntimeError("No web results were returned for that query.")
    return WebContextBundle(
        query=query,
        context=build_web_context(query, results, config),
        result_count=len(results),
    )
