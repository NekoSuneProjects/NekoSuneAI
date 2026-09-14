"""Local music playback for a Pi Proxy node: resolve, queue, play, control.

Why this lives on the node rather than the backend, in full: YouTube's
bot/cookie verification blocks the datacenter IPs a VPS-hosted Docker backend
runs from ("confirm you're not a robot", "sign in to confirm your age"), but
not a home Raspberry Pi's residential IP. The backend still decides *what* to
play -- search, song selection and playlists stay a backend/assistant concern,
and it only ever hands this node a search query or a YouTube URL/id, never a
pre-resolved stream URL. Resolution and playback are the parts that have to
happen from the house, so they happen here.

Playback deliberately reuses tools the image already installs rather than
adding a Python audio dependency or an mpv/IPC stack:

* `yt-dlp` resolves a query or URL to a playable stream,
* `ffplay` (ffmpeg) plays it with no video output,
* SIGSTOP/SIGCONT pause and resume that process -- the stream is a live
  network read, so stopping the reader is what pausing means here,
* `pactl` sets the sink volume, the same audio server bluetooth_watchdog.py
  already drives.

A queue lives here rather than on the backend on purpose: the gap between
tracks would otherwise be a full network round trip (node reports idle ->
backend notices -> backend sends the next track), which is audible. The
backend can hand over a whole playlist in one `music.play`.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Callable

# A resolved YouTube stream URL is signed and expires. Re-resolve rather than
# reusing one across a long queue, and treat a very old "now playing" as stale.
MAX_QUEUE = 100
RESOLVE_TIMEOUT_SECONDS = 45

# SIGSTOP/SIGCONT are POSIX-only and simply absent on Windows, so resolve them
# once here rather than at each call site -- referencing signal.SIGSTOP inline
# raises AttributeError before the caller's error handling can run. The target
# is a Raspberry Pi, but the module still has to import and run elsewhere (the
# test suite included) with pause reported as unsupported instead of crashing.
_SIGSTOP = getattr(signal, "SIGSTOP", None)
_SIGCONT = getattr(signal, "SIGCONT", None)


class MusicController:
    def __init__(self, notify: Callable[[str], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._notify = notify or (lambda message: None)
        self._queue: list[str] = []
        self._history: list[str] = []
        self._current = ""
        self._current_title = ""
        self._paused = False
        self._volume = 100
        self._error = ""
        self._stop_watcher = threading.Event()
        self._watcher: threading.Thread | None = None

    # ── resolution ────────────────────────────────────────────────────────

    def _resolve(self, query: str) -> tuple[str, str]:
        """Return (stream_url, title) for a search query or YouTube URL/id."""
        import yt_dlp

        options = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
            "skip_download": True,
            "socket_timeout": 15,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
        if info is None:
            raise RuntimeError("yt-dlp returned no result for this query")
        if isinstance(info, dict) and "entries" in info:
            entries = [entry for entry in (info.get("entries") or []) if entry]
            if not entries:
                raise RuntimeError("yt-dlp search returned no playable entries")
            info = entries[0]
        url = info.get("url") if isinstance(info, dict) else None
        if not url:
            raise RuntimeError("yt-dlp did not return a playable stream URL")
        title = str((info or {}).get("title") or query)[:200]
        return str(url), title

    # ── process control ───────────────────────────────────────────────────

    def _kill_locked(self) -> None:
        if self._proc is None:
            return
        try:
            if self._paused:
                # A stopped process will not act on SIGTERM until it runs
                # again, so wake it first or terminate() hangs until timeout.
                self._signal_locked(_SIGCONT)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None
        self._paused = False

    def _signal_locked(self, sig: int | None) -> bool:
        if sig is None or self._proc is None or self._proc.poll() is not None:
            return False
        try:
            os.kill(self._proc.pid, sig)
            return True
        except (OSError, AttributeError, ValueError):
            return False

    def _start_locked(self, stream_url: str) -> None:
        if not shutil.which("ffplay"):
            raise RuntimeError("ffplay (part of ffmpeg) is required for music playback and was not found on PATH")
        self._kill_locked()
        self._proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", stream_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._paused = False
        self._ensure_watcher()

    # ── auto-advance ──────────────────────────────────────────────────────

    def _ensure_watcher(self) -> None:
        if self._watcher is not None and self._watcher.is_alive():
            return
        self._stop_watcher.clear()
        self._watcher = threading.Thread(
            target=self._watch, daemon=True, name="pi-proxy-music-queue",
        )
        self._watcher.start()

    def _watch_once(self) -> bool:
        """One poll of the auto-advance loop. Returns False when it should end.

        Only a track exiting on its own advances the queue: stop() and skip()
        clear or replace the process themselves, so this must not race them
        into playing something the owner just skipped past.
        """
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is None or self._paused:
                # Nothing playing and nothing waiting: the queue is finished.
                return not (proc is None and not self._queue)
            self._proc = None
            if not self._queue:
                self._current = ""
                self._current_title = ""
                return False
            self._advance_locked()
            return True

    def _watch(self) -> None:
        while not self._stop_watcher.wait(0.5):
            if not self._watch_once():
                return

    def _advance_locked(self) -> str:
        """Play the next queued track. Caller holds the lock."""
        while self._queue:
            query = self._queue.pop(0)
            try:
                stream_url, title = self._resolve(query)
            except Exception as exc:
                # One unplayable track must not strand the rest of a playlist.
                self._error = f"{query}: {exc}"[:200]
                self._notify(f"Skipping '{query[:60]}': {exc}"[:200])
                continue
            if self._current:
                self._history.append(self._current)
                del self._history[:-50]
            self._current = query
            self._current_title = title
            self._error = ""
            self._start_locked(stream_url)
            return title
        self._current = ""
        self._current_title = ""
        return ""

    # ── public capability surface ─────────────────────────────────────────

    def play(self, queries: list[str], replace: bool = True) -> dict[str, Any]:
        cleaned = [str(item).strip() for item in queries if str(item).strip()]
        if not cleaned:
            raise ValueError("music.play requires at least one query or url")
        with self._lock:
            if replace:
                self._kill_locked()
                self._queue = cleaned[:MAX_QUEUE]
                self._current = ""
                title = self._advance_locked()
                if not title:
                    raise RuntimeError(self._error or "nothing in that request could be played")
                return {"ok": True, "playing": True, "title": title, "queued": len(self._queue)}
            self._queue.extend(cleaned)
            del self._queue[MAX_QUEUE:]
            if self._proc is None or self._proc.poll() is not None:
                title = self._advance_locked()
                return {"ok": True, "playing": bool(title), "title": title, "queued": len(self._queue)}
            self._ensure_watcher()
            return {"ok": True, "playing": True, "title": self._current_title, "queued": len(self._queue)}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_watcher.set()
            self._kill_locked()
            self._queue.clear()
            self._current = ""
            self._current_title = ""
            return {"ok": True, "stopped": True}

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return {"ok": False, "message": "nothing is playing"}
            if self._paused:
                return {"ok": True, "paused": True}
            if not self._signal_locked(_SIGSTOP):
                return {"ok": False, "message": "this platform cannot pause playback"}
            self._paused = True
            return {"ok": True, "paused": True}

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if not self._paused:
                return {"ok": False, "message": "nothing is paused"}
            if not self._signal_locked(_SIGCONT):
                return {"ok": False, "message": "could not resume playback"}
            self._paused = False
            return {"ok": True, "paused": False}

    def skip(self) -> dict[str, Any]:
        with self._lock:
            if not self._queue:
                self.stop()
                return {"ok": True, "message": "that was the last track"}
            self._kill_locked()
            title = self._advance_locked()
            return {"ok": True, "title": title, "queued": len(self._queue)}

    def previous(self) -> dict[str, Any]:
        with self._lock:
            if not self._history:
                return {"ok": False, "message": "no previous track"}
            previous = self._history.pop()
            # Re-queue what is playing so "previous" then "skip" returns here.
            if self._current:
                self._queue.insert(0, self._current)
            self._kill_locked()
            self._queue.insert(0, previous)
            self._current = ""
            title = self._advance_locked()
            return {"ok": True, "title": title}

    def set_volume(self, percent: int) -> dict[str, Any]:
        level = max(0, min(int(percent), 100))
        if not shutil.which("pactl"):
            return {"ok": False, "message": "pactl is unavailable; cannot set the volume"}
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr or "pactl failed").strip()[:200]}
        self._volume = level
        return {"ok": True, "volume": level}

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None and not self._paused

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._proc is not None and self._proc.poll() is None
            return {
                "playing": active and not self._paused,
                "paused": self._paused and active,
                "title": self._current_title,
                "query": self._current,
                "queued": len(self._queue),
                "queue": list(self._queue[:10]),
                "volume": self._volume,
                "error": self._error,
            }
