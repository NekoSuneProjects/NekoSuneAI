from __future__ import annotations

import json
import os
import random
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from .database import get_state, set_state

PLAYLIST_STATE_KEY = "youtube_music_playlists_v1"
YOUTUBE_FALLBACK_PLAYER_CLIENTS = (
    None,
    "mweb,android_vr",
    "tv,web_safari",
    "web_safari,web",
    "tv_simply,web_embedded",
    "android_vr,ios",
    "default",
)
RETRYABLE_PATTERNS = (
    "the page needs to be reloaded",
    "failed to extract any player response",
    "failed to parse signature function",
    "unable to extract video data",
    "precondition check failed",
    "sign in to confirm",
    "http error 403",
    "http error 429",
    "requested format is not available",
    "no video formats found",
    "fragment ",
    "unable to download api page",
    "players.youtube.com",
    "this video is unavailable",
    "nsig extraction failed",
    "some formats may be missing",
    "signature extraction failed",
    "unable to obtain po token",
    "only images are available",
)


def _load_playlists() -> dict[str, list[dict[str, str]]]:
    try:
        value = json.loads(get_state(PLAYLIST_STATE_KEY, "{}"))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _save_playlists(value: dict[str, list[dict[str, str]]]) -> None:
    set_state(PLAYLIST_STATE_KEY, json.dumps(value, ensure_ascii=False))


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _last_message(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "yt-dlp failed").strip()
    return (text.splitlines()[-1] if text else "yt-dlp failed")[:900]


def _is_retryable(message: str) -> bool:
    low = str(message or "").lower()
    return any(pattern in low for pattern in RETRYABLE_PATTERNS)


@dataclass
class Track:
    title: str
    webpage_url: str
    author: str = ""
    duration: str = ""
    thumbnail: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class YouTubeMusicPlayer:
    _update_lock = threading.Lock()

    def __init__(self, announce: Callable[[str], None] | None = None) -> None:
        self.announce = announce or (lambda _msg: None)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._skip = threading.Event()
        self._worker: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._queue: list[Track] = []
        self._history: list[Track] = []
        self._now: Track | None = None
        self._playlist_name = ""
        self._paused = False
        self._volume = max(0, min(100, int(os.getenv("YOUTUBE_MUSIC_VOLUME", "75"))))
        self._last_stream: dict[str, Any] = {}

    def _yt_dlp(self) -> str:
        path = shutil.which("yt-dlp")
        if not path:
            raise RuntimeError("yt-dlp is not installed in this Docker image.")
        return path

    def _node(self) -> str:
        path = shutil.which("node") or shutil.which("nodejs")
        if not path:
            raise RuntimeError("Node.js is not installed for yt-search.")
        return path

    def _ffplay(self) -> str:
        path = shutil.which("ffplay")
        if not path:
            raise RuntimeError("ffplay is not installed. Install FFmpeg first.")
        return path

    def _common_args(self) -> list[str]:
        args = [self._yt_dlp(), "--no-warnings", "--no-progress"]
        cookies = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        if cookies:
            args += ["--cookies", cookies]
        browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
        if browser:
            args += ["--cookies-from-browser", browser]
        proxy = os.getenv("YTDLP_PROXY", "").strip()
        if proxy:
            args += ["--proxy", proxy]
        user_agent = os.getenv("YTDLP_USER_AGENT", "").strip()
        if user_agent:
            args += ["--user-agent", user_agent]
        js_runtime = os.getenv("YTDLP_JS_RUNTIMES", "node").strip()
        if js_runtime:
            args += ["--js-runtimes", js_runtime]
        remote = os.getenv("YTDLP_REMOTE_COMPONENTS", "ejs:github").strip()
        if remote:
            args += ["--remote-components", remote]
        return args

    def _extractor_args(self, player_client: str | None) -> list[str]:
        pieces: list[str] = []
        configured = os.getenv("YTDLP_EXTRACTOR_ARGS", "youtube:player_js_variant=tv").strip()
        if configured:
            pieces.append(configured)
        if player_client and player_client != "default":
            pieces.append(f"youtube:player_client={player_client}")
        return ["--extractor-args", ";".join(pieces)] if pieces else []

    def _update_nightly(self) -> None:
        if os.getenv("YTDLP_AUTO_UPDATE", "true").strip().lower() in {"0", "false", "no", "off"}:
            return
        if not self._update_lock.acquire(blocking=False):
            return
        try:
            subprocess.run(
                [self._yt_dlp(), "--update-to", "nightly"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        finally:
            self._update_lock.release()

    def _run_ytdlp_json(self, tail: list[str], timeout: int = 60, allow_repair: bool = True) -> dict[str, Any]:
        last = "yt-dlp failed"
        for player_client in YOUTUBE_FALLBACK_PLAYER_CLIENTS:
            args = self._common_args() + self._extractor_args(player_client) + tail
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                except json.JSONDecodeError:
                    last = "yt-dlp returned invalid JSON"
                    continue
                formats = data.get("formats")
                if isinstance(formats, list):
                    playable = [f for f in formats if isinstance(f, dict) and (f.get("acodec") != "none" or f.get("vcodec") != "none")]
                    if len(playable) <= 1 and player_client != YOUTUBE_FALLBACK_PLAYER_CLIENTS[-1]:
                        last = "yt-dlp returned a degraded format list"
                        continue
                return data
            last = _last_message(result)
            if not _is_retryable(last):
                break

        if allow_repair:
            self._update_nightly()
            return self._run_ytdlp_json(tail, timeout=timeout, allow_repair=False)
        raise RuntimeError(last)

    def _node_search(self, query: str) -> list[Track]:
        helper = Path(__file__).resolve().parent.parent / "tools" / "yt_search.js"
        result = subprocess.run(
            [self._node(), str(helper), query],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "yt-search failed").strip()[:900])
        payload = json.loads(result.stdout)
        tracks: list[Track] = []
        for item in payload.get("videos", []):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            tracks.append(
                Track(
                    title=str(item.get("title") or "YouTube video"),
                    webpage_url=str(item["url"]),
                    author=str(item.get("author") or ""),
                    duration=str(item.get("duration") or ""),
                    thumbnail=str(item.get("thumbnail") or ""),
                )
            )
        return tracks

    def search_many(self, query: str, limit: int = 10) -> list[Track]:
        query = query.strip()
        if not query:
            return []
        try:
            tracks = self._node_search(query)
            if tracks:
                return tracks[: max(1, min(20, int(limit)))]
        except Exception:
            pass

        data = self._run_ytdlp_json(
            ["--dump-single-json", "--flat-playlist", f"ytsearch{max(3, min(20, int(limit)))}:{query}"],
            timeout=45,
        )
        tracks = []
        for item in data.get("entries", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            tracks.append(
                Track(
                    str(item.get("title") or query),
                    str(item.get("webpage_url") or f"https://www.youtube.com/watch?v={item['id']}"),
                    str(item.get("channel") or item.get("uploader") or ""),
                    str(item.get("duration_string") or ""),
                    str(item.get("thumbnail") or ""),
                )
            )
        return tracks

    def search(self, query: str) -> Track:
        entries = self.search_many(f"{query} official video official audio", 10)
        if not entries:
            raise RuntimeError(f"I couldn't find {query} on YouTube.")
        qwords = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1}

        def score(item: Track) -> int:
            title = item.title.lower()
            author = item.author.lower()
            points = sum(3 for word in qwords if word in title)
            if "official video" in title or "official music video" in title:
                points += 10
            if "official audio" in title:
                points += 8
            if "vevo" in author:
                points += 7
            if "topic" in author:
                points += 3
            if any(x in title for x in ("nightcore", "slowed", "sped up", "cover", "reaction", "karaoke")):
                points -= 8
            return points

        return max(entries, key=score)

    def _stream_from_info(self, data: dict[str, Any]) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for item in data.get("requested_downloads") or []:
            if isinstance(item, dict):
                candidates.append(item)
        if data.get("url"):
            candidates.append(data)
        for item in data.get("formats") or []:
            if isinstance(item, dict) and item.get("url"):
                candidates.append(item)
        if not candidates:
            raise RuntimeError("YouTube did not return a playable stream URL.")

        def rank(item: dict[str, Any]) -> tuple[int, int, int, int]:
            protocol = str(item.get("protocol") or "")
            ext = str(item.get("ext") or "")
            acodec = str(item.get("acodec") or "none")
            vcodec = str(item.get("vcodec") or "none")
            audio = 1 if acodec != "none" else 0
            audio_only = 1 if audio and vcodec == "none" else 0
            directish = 1 if protocol in {"https", "http", "m3u8", "m3u8_native"} else 0
            preferred = 1 if ext in {"m4a", "mp4", "webm"} or "m3u8" in protocol else 0
            return (audio_only, audio, directish, preferred)

        picked = max(candidates, key=rank)
        return {
            "url": str(picked.get("url") or ""),
            "protocol": str(picked.get("protocol") or ""),
            "ext": str(picked.get("ext") or ""),
            "format_id": str(picked.get("format_id") or ""),
            "acodec": str(picked.get("acodec") or ""),
            "vcodec": str(picked.get("vcodec") or ""),
            "title": str(data.get("title") or ""),
            "webpage_url": str(data.get("webpage_url") or ""),
        }

    def resolve_stream(self, page_url: str) -> dict[str, Any]:
        data = self._run_ytdlp_json(
            [
                "--dump-single-json",
                "--no-playlist",
                "-f",
                "bestaudio[ext=m4a]/bestaudio/best",
                page_url,
            ],
            timeout=55,
        )
        stream = self._stream_from_info(data)
        self._last_stream = stream
        return stream

    def _resolve_audio(self, page_url: str) -> str:
        return self.resolve_stream(page_url)["url"]

    def play_query(self, query: str) -> str:
        track = self.search(query)
        self.play_tracks([track])
        return f"Playing {track.title}."

    def play_url(self, url: str, title: str = "YouTube track") -> str:
        self.play_tracks([Track(title.strip() or "YouTube track", url.strip())])
        return f"Playing {title.strip() or 'YouTube track'}."

    def play_tracks(self, tracks: list[Track], playlist_name: str = "") -> None:
        self.stop(silent=True)
        with self._lock:
            self._queue = list(tracks)
            self._history = []
            self._playlist_name = playlist_name
            self._stop.clear()
            self._skip.clear()
            self._paused = False
            self._worker = threading.Thread(target=self._run_queue, daemon=True, name="youtube-music")
            self._worker.start()

    def _run_queue(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._queue:
                    break
                self._now = self._queue.pop(0)
                track = self._now
            try:
                stream = self.resolve_stream(track.webpage_url)
                self.announce(f"Now playing {track.title}.")
                self._skip.clear()
                self._paused = False
                self._process = subprocess.Popen(
                    [
                        self._ffplay(),
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "-volume",
                        str(self._volume),
                        stream["url"],
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                while self._process.poll() is None and not self._stop.wait(0.3) and not self._skip.is_set():
                    pass
                if (self._stop.is_set() or self._skip.is_set()) and self._process.poll() is None:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=3)
                    except Exception:
                        self._process.kill()
                if not self._stop.is_set() and not self._skip.is_set():
                    with self._lock:
                        self._history.append(track)
            except Exception as exc:
                self.announce(f"I couldn't play {track.title}: {exc}")
            finally:
                self._process = None
                self._paused = False
        with self._lock:
            self._now = None
            self._queue = []
            self._playlist_name = ""
            self._paused = False

    def stop(self, silent: bool = False) -> str:
        self._stop.set()
        self._skip.set()
        proc = self._process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        with self._lock:
            had_music = bool(self._now or self._queue or proc)
            self._queue = []
            self._paused = False
        return "Stopped the music." if had_music else ("" if silent else "No music is playing.")

    def skip(self) -> str:
        with self._lock:
            if not self._now:
                return "No music is playing."
            self._history.append(self._now)
            self._skip.set()
            return "Skipping to the next song."

    def previous(self) -> str:
        with self._lock:
            if not self._now and not self._history:
                return "There isn't a previous song yet."
            previous = self._history.pop() if self._history else self._now
            if previous is None:
                return "There isn't a previous song yet."
            if self._now and self._now.webpage_url != previous.webpage_url:
                self._queue.insert(0, self._now)
            self._queue.insert(0, previous)
            self._skip.set()
            return f"Going back to {previous.title}."

    def pause(self) -> str:
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None or not self._now:
                return "No music is playing."
            if self._paused:
                return "The music is already paused."
            try:
                if os.name != "posix":
                    return "Pause is currently supported on Linux/Docker."
                os.kill(proc.pid, signal.SIGSTOP)
                self._paused = True
                return "Paused the music."
            except Exception as exc:
                return f"I couldn't pause the music: {exc}"

    def resume(self) -> str:
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None or not self._now:
                return "There isn't paused music to resume."
            if not self._paused:
                return "The music is already playing."
            try:
                os.kill(proc.pid, signal.SIGCONT)
                self._paused = False
                return "Resumed the music."
            except Exception as exc:
                return f"I couldn't resume the music: {exc}"

    def set_volume(self, percent: int) -> str:
        with self._lock:
            target = max(0, min(100, int(percent)))
            delta = target - self._volume
            proc = self._process
            if proc and proc.poll() is None and proc.stdin and delta:
                key = b"0" if delta > 0 else b"9"
                try:
                    for _ in range(abs(delta)):
                        proc.stdin.write(key + b"\n")
                    proc.stdin.flush()
                except Exception:
                    pass
            self._volume = target
            return f"Music volume is {target}%."

    def adjust_volume(self, amount: int) -> str:
        return self.set_volume(self._volume + amount)

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "playing": bool(self._now),
                "paused": self._paused,
                "volume": self._volume,
                "playlist": self._playlist_name,
                "now": self._now.as_dict() if self._now else None,
                "queue": [track.as_dict() for track in self._queue],
                "history": [track.as_dict() for track in self._history[-10:]],
                "stream": dict(self._last_stream),
            }

    def status(self) -> str:
        data = self.status_dict()
        now = data["now"]
        if not now:
            return "No music is playing."
        extra = f" from your {data['playlist']} playlist" if data["playlist"] else ""
        state = "paused" if data["paused"] else "playing"
        return f"Now {state}: {now['title']}{extra}. Music volume is {data['volume']}%. {len(data['queue'])} song(s) remain."

    def create_playlist(self, name: str) -> str:
        playlists = _load_playlists()
        playlists.setdefault(_key(name), [])
        _save_playlists(playlists)
        return f"Playlist {name.strip()} is ready."

    def delete_playlist(self, name: str) -> str:
        playlists = _load_playlists()
        key = _key(name)
        if key not in playlists:
            return f"Playlist {name.strip()} does not exist."
        playlists.pop(key, None)
        _save_playlists(playlists)
        return f"Deleted playlist {name.strip()}."

    def add_to_playlist(self, name: str, query: str) -> str:
        track = self.search(query)
        return self.add_track_to_playlist(name, track)

    def add_track_to_playlist(self, name: str, track: Track) -> str:
        playlists = _load_playlists()
        playlists.setdefault(_key(name), []).append(track.as_dict())
        _save_playlists(playlists)
        return f"Added {track.title} to your {name.strip()} playlist."

    def import_playlist(self, name: str, url: str) -> str:
        data = self._run_ytdlp_json(["--dump-single-json", "--flat-playlist", url], timeout=90)
        tracks: list[dict[str, str]] = []
        for item in data.get("entries", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            tracks.append(
                Track(
                    str(item.get("title") or item["id"]),
                    str(item.get("webpage_url") or f"https://www.youtube.com/watch?v={item['id']}"),
                    str(item.get("channel") or item.get("uploader") or ""),
                    str(item.get("duration_string") or ""),
                    str(item.get("thumbnail") or ""),
                ).as_dict()
            )
        if not tracks:
            raise RuntimeError("That YouTube playlist did not contain any readable videos.")
        playlists = _load_playlists()
        playlists[_key(name)] = tracks
        _save_playlists(playlists)
        return f"Imported {len(tracks)} songs into your {name.strip()} playlist."

    def play_playlist(self, name: str, shuffle: bool = False) -> str:
        rows = _load_playlists().get(_key(name), [])
        tracks = [
            Track(
                str(x.get("title") or "YouTube track"),
                str(x.get("webpage_url") or ""),
                str(x.get("author") or ""),
                str(x.get("duration") or ""),
                str(x.get("thumbnail") or ""),
            )
            for x in rows
            if x.get("webpage_url")
        ]
        if not tracks:
            return f"Your {name.strip()} playlist is empty or doesn't exist."
        if shuffle:
            random.shuffle(tracks)
        self.play_tracks(tracks, name.strip())
        return f"Playing your {name.strip()} playlist with {len(tracks)} songs."

    def playlists_snapshot(self) -> dict[str, list[dict[str, str]]]:
        return _load_playlists()

    def list_playlists(self) -> str:
        playlists = _load_playlists()
        if not playlists:
            return "You don't have any saved YouTube playlists yet."
        return "Your playlists: " + ", ".join(f"{name} ({len(items)} songs)" for name, items in playlists.items()) + "."


def handle_music_request(text: str, player: YouTubeMusicPlayer) -> str | None:
    raw = text.strip()
    lower = raw.lower()
    if re.search(r"\b(?:stop|turn off)\s+(?:the\s+)?music\b", lower):
        return player.stop()
    if re.search(r"\bpause(?:\s+(?:the\s+)?music)?\b", lower):
        return player.pause()
    if re.search(r"\b(?:resume|continue)(?:\s+(?:the\s+)?music)?\b", lower) or lower in {"play", "play music"}:
        return player.resume()
    if re.search(r"\b(?:skip|next)(?:\s+(?:song|track))?\b", lower):
        return player.skip()
    if re.search(r"\b(?:previous|last|go back)(?:\s+(?:song|track))?\b", lower):
        return player.previous()
    if re.search(r"\b(?:what(?:'s| is) playing|music status|now playing)\b", lower):
        return player.status()
    m = re.search(r"\b(?:set\s+)?(?:music\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?\b", lower)
    if m:
        return player.set_volume(int(m.group(1)))
    if re.search(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:up|louder)\b|\bmusic\s+(?:up|louder)\b", lower):
        return player.adjust_volume(10)
    if re.search(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:down|quieter|lower)\b|\bmusic\s+(?:down|quieter|lower)\b", lower):
        return player.adjust_volume(-10)
    if re.search(r"\b(?:list|show)\s+(?:my\s+)?playlists\b", lower):
        return player.list_playlists()
    m = re.search(r"\bcreate\s+(?:a\s+)?playlist\s+(?:called\s+)?(.+)$", raw, re.I)
    if m:
        return player.create_playlist(m.group(1))
    m = re.search(r"\badd\s+(.+?)\s+to\s+(?:my\s+)?(.+?)\s+playlist\b", raw, re.I)
    if m:
        return player.add_to_playlist(m.group(2), m.group(1))
    m = re.search(r"\bimport\s+(?:youtube\s+)?playlist\s+(https?://\S+)(?:\s+(?:as|into)\s+(.+?))?$", raw, re.I)
    if m:
        return player.import_playlist((m.group(2) or "imported").strip(), m.group(1))
    m = re.search(r"\bplay\s+(?:my\s+)?(.+?)\s+playlist\b", raw, re.I)
    if m:
        return player.play_playlist(m.group(1))
    m = re.search(r"\bplay\s+(.+)$", raw, re.I)
    if m and not any(x in lower for x in ("play game", "play a game")):
        return player.play_query(m.group(1))
    return None
