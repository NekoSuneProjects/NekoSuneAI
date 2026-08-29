from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .database import get_state, set_state

PLAYLIST_STATE_KEY = "youtube_music_playlists_v1"


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


@dataclass
class Track:
    title: str
    webpage_url: str


class YouTubeMusicPlayer:
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

    def _yt_dlp(self) -> str:
        path = shutil.which("yt-dlp")
        if not path:
            raise RuntimeError("yt-dlp is not installed. Install the Pi/Docker requirements first.")
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
        return args

    def _json(self, args: list[str], timeout: int = 45) -> dict[str, Any]:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "yt-dlp failed").strip().splitlines()[-1]
            raise RuntimeError(message[:500])
        return json.loads(result.stdout)

    def search(self, query: str) -> Track:
        data = self._json(self._common_args() + ["--dump-single-json", "--flat-playlist", f"ytsearch8:{query} official video official audio"])
        entries = [x for x in data.get("entries", []) if isinstance(x, dict) and x.get("id")]
        if not entries:
            raise RuntimeError(f"I couldn't find {query} on YouTube.")
        qwords = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1}
        def score(item: dict[str, Any]) -> int:
            title = str(item.get("title") or "").lower(); channel = str(item.get("channel") or item.get("uploader") or "").lower()
            points = sum(3 for word in qwords if word in title)
            if "official video" in title or "official music video" in title: points += 10
            if "official audio" in title: points += 8
            if "vevo" in channel: points += 7
            if "topic" in channel: points += 3
            if any(x in title for x in ("nightcore", "slowed", "sped up", "cover", "reaction", "karaoke")): points -= 8
            return points
        best = max(entries, key=score)
        return Track(str(best.get("title") or query), str(best.get("webpage_url") or f"https://www.youtube.com/watch?v={best['id']}"))

    def _resolve_audio(self, page_url: str) -> str:
        result = subprocess.run(self._common_args() + ["-f", "bestaudio/best", "-g", "--no-playlist", page_url], capture_output=True, text=True, timeout=45, check=False)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "Could not resolve YouTube audio").strip().splitlines()[-1][:500])
        url = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if not url: raise RuntimeError("YouTube did not return a playable audio stream.")
        return url

    def play_query(self, query: str) -> str:
        track = self.search(query); self.play_tracks([track]); return f"Playing {track.title}."

    def play_tracks(self, tracks: list[Track], playlist_name: str = "") -> None:
        self.stop(silent=True)
        with self._lock:
            self._queue = list(tracks); self._history = []; self._playlist_name = playlist_name
            self._stop.clear(); self._skip.clear(); self._paused = False
            self._worker = threading.Thread(target=self._run_queue, daemon=True, name="youtube-music"); self._worker.start()

    def _run_queue(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._queue: break
                self._now = self._queue.pop(0); track = self._now
            try:
                stream = self._resolve_audio(track.webpage_url)
                self.announce(f"Now playing {track.title}.")
                self._skip.clear(); self._paused = False
                self._process = subprocess.Popen([self._ffplay(), "-nodisp", "-autoexit", "-loglevel", "error", "-volume", str(self._volume), stream], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while self._process.poll() is None and not self._stop.wait(0.3) and not self._skip.is_set():
                    pass
                if (self._stop.is_set() or self._skip.is_set()) and self._process.poll() is None:
                    self._process.terminate()
                    try: self._process.wait(timeout=3)
                    except Exception: self._process.kill()
                if not self._stop.is_set() and not self._skip.is_set():
                    with self._lock: self._history.append(track)
            except Exception as exc:
                self.announce(f"I couldn't play {track.title}: {exc}")
            finally:
                self._process = None; self._paused = False
        with self._lock:
            self._now = None; self._queue = []; self._playlist_name = ""; self._paused = False

    def stop(self, silent: bool = False) -> str:
        self._stop.set(); self._skip.set(); proc = self._process
        if proc and proc.poll() is None:
            try: proc.terminate()
            except Exception: pass
        with self._lock:
            had_music = bool(self._now or self._queue or proc); self._queue = []; self._paused = False
        return "Stopped the music." if had_music else ("" if silent else "No music is playing.")

    def skip(self) -> str:
        with self._lock:
            if not self._now: return "No music is playing."
            self._history.append(self._now); self._skip.set(); return "Skipping to the next song."

    def previous(self) -> str:
        with self._lock:
            if not self._now and not self._history: return "There isn't a previous song yet."
            previous = self._history.pop() if self._history else self._now
            if previous is None: return "There isn't a previous song yet."
            if self._now and self._now.webpage_url != previous.webpage_url:
                self._queue.insert(0, self._now)
            self._queue.insert(0, previous); self._skip.set()
            return f"Going back to {previous.title}."

    def pause(self) -> str:
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None or not self._now: return "No music is playing."
            if self._paused: return "The music is already paused."
            try:
                if os.name == "posix": os.kill(proc.pid, signal.SIGSTOP)
                else: return "Pause is currently supported on the Raspberry Pi/Linux player."
                self._paused = True; return "Paused the music."
            except Exception as exc: return f"I couldn't pause the music: {exc}"

    def resume(self) -> str:
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None or not self._now: return "There isn't paused music to resume."
            if not self._paused: return "The music is already playing."
            try:
                os.kill(proc.pid, signal.SIGCONT); self._paused = False; return "Resumed the music."
            except Exception as exc: return f"I couldn't resume the music: {exc}"

    def set_volume(self, percent: int) -> str:
        with self._lock:
            target = max(0, min(100, int(percent))); delta = target - self._volume; proc = self._process
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

    def status(self) -> str:
        with self._lock:
            if not self._now: return "No music is playing."
            extra = f" from your {self._playlist_name} playlist" if self._playlist_name else ""
            state = "paused" if self._paused else "playing"
            return f"Now {state}: {self._now.title}{extra}. Music volume is {self._volume}%. {len(self._queue)} song(s) remain."

    def create_playlist(self, name: str) -> str:
        playlists = _load_playlists(); playlists.setdefault(_key(name), []); _save_playlists(playlists); return f"Playlist {name.strip()} is ready."

    def add_to_playlist(self, name: str, query: str) -> str:
        track = self.search(query); playlists = _load_playlists(); playlists.setdefault(_key(name), []).append({"title": track.title, "webpage_url": track.webpage_url}); _save_playlists(playlists)
        return f"Added {track.title} to your {name.strip()} playlist."

    def import_playlist(self, name: str, url: str) -> str:
        data = self._json(self._common_args() + ["--dump-single-json", "--flat-playlist", url], timeout=90); tracks: list[dict[str, str]] = []
        for item in data.get("entries", []):
            if not isinstance(item, dict) or not item.get("id"): continue
            tracks.append({"title": str(item.get("title") or item["id"]), "webpage_url": str(item.get("webpage_url") or f"https://www.youtube.com/watch?v={item['id']}")})
        if not tracks: raise RuntimeError("That YouTube playlist did not contain any readable videos.")
        playlists = _load_playlists(); playlists[_key(name)] = tracks; _save_playlists(playlists); return f"Imported {len(tracks)} songs into your {name.strip()} playlist."

    def play_playlist(self, name: str) -> str:
        rows = _load_playlists().get(_key(name), []); tracks = [Track(str(x.get("title") or "YouTube track"), str(x.get("webpage_url") or "")) for x in rows if x.get("webpage_url")]
        if not tracks: return f"Your {name.strip()} playlist is empty or doesn't exist."
        self.play_tracks(tracks, name.strip()); return f"Playing your {name.strip()} playlist with {len(tracks)} songs."

    def list_playlists(self) -> str:
        playlists = _load_playlists()
        if not playlists: return "You don't have any saved YouTube playlists yet."
        return "Your playlists: " + ", ".join(f"{name} ({len(items)} songs)" for name, items in playlists.items()) + "."


def handle_music_request(text: str, player: YouTubeMusicPlayer) -> str | None:
    raw = text.strip(); lower = raw.lower()
    if re.search(r"\b(?:stop|turn off)\s+(?:the\s+)?music\b", lower): return player.stop()
    if re.search(r"\b(?:pause)(?:\s+(?:the\s+)?music)?\b", lower): return player.pause()
    if re.search(r"\b(?:resume|continue)(?:\s+(?:the\s+)?music)?\b", lower) or lower in {"play", "play music"}: return player.resume()
    if re.search(r"\b(?:skip|next)(?:\s+(?:song|track))?\b", lower): return player.skip()
    if re.search(r"\b(?:previous|last|go back)(?:\s+(?:song|track))?\b", lower): return player.previous()
    if re.search(r"\b(?:what(?:'s| is) playing|music status|now playing)\b", lower): return player.status()
    m = re.search(r"\b(?:set\s+)?(?:music\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?\b", lower)
    if m: return player.set_volume(int(m.group(1)))
    if re.search(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:up|louder)\b|\bmusic\s+(?:up|louder)\b", lower): return player.adjust_volume(10)
    if re.search(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:down|quieter|lower)\b|\bmusic\s+(?:down|quieter|lower)\b", lower): return player.adjust_volume(-10)
    m = re.search(r"\b(?:turn|set)\s+(?:the\s+)?music\s+(?:up|down)\s+(?:by\s+)?(\d{1,3})\b", lower)
    if m: return player.adjust_volume(int(m.group(1)) * (-1 if " down" in lower else 1))
    if re.search(r"\b(?:list|show)\s+(?:my\s+)?playlists\b", lower): return player.list_playlists()
    m = re.search(r"\bcreate\s+(?:a\s+)?playlist\s+(?:called\s+)?(.+)$", raw, re.I)
    if m: return player.create_playlist(m.group(1))
    m = re.search(r"\badd\s+(.+?)\s+to\s+(?:my\s+)?(.+?)\s+playlist\b", raw, re.I)
    if m: return player.add_to_playlist(m.group(2), m.group(1))
    m = re.search(r"\bimport\s+(?:youtube\s+)?playlist\s+(https?://\S+)(?:\s+(?:as|into)\s+(.+?))?$", raw, re.I)
    if m: return player.import_playlist((m.group(2) or "imported").strip(), m.group(1))
    m = re.search(r"\bplay\s+(?:my\s+)?(.+?)\s+playlist\b", raw, re.I)
    if m: return player.play_playlist(m.group(1))
    m = re.search(r"\bplay\s+(.+)$", raw, re.I)
    if m and not any(x in lower for x in ("play game", "play a game")): return player.play_query(m.group(1))
    return None
