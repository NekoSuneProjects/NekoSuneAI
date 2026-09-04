from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

_INSTALLED = False
_YTDLP_GATE = threading.Semaphore(max(1, int(os.getenv("YOUTUBE_MUSIC_MAX_YTDLP", "1"))))


def _duration_seconds(value: str) -> float | None:
    """Best-effort parser for yt-search/yt-dlp duration strings such as 3:42."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [float(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def install_music_resource_guard_patch() -> None:
    """Keep Docker/Raspberry Pi music playback reliable and bounded.

    Besides preventing overlapping yt-dlp/ffplay workers, this wrapper now keeps
    a song alive across transient YouTube/CDN disconnects. ffplay is started with
    HTTP reconnect support; if it still exits well before the advertised track
    duration, NekoSuneAI resolves a fresh signed stream URL and resumes near the
    point where playback stopped instead of silently treating a half-played song
    as complete.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .youtube_music import YouTubeMusicPlayer

    if getattr(YouTubeMusicPlayer, "_neko_pi_resource_guard", False):
        return

    original_init = YouTubeMusicPlayer.__init__
    original_ytdlp = YouTubeMusicPlayer._run_ytdlp_json

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._music_generation = 0
        self._music_worker_lock = threading.RLock()

    def guarded_ytdlp(self, *args, **kwargs):
        # yt-dlp + Node signature extraction can briefly be expensive on a Pi.
        # Serialize it so searches/track changes cannot pile up CPU/RAM usage.
        with _YTDLP_GATE:
            return original_ytdlp(self, *args, **kwargs)

    def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2.5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.5)
            except Exception:
                pass

    def patched_stop(self, silent: bool = False) -> str:
        with self._music_worker_lock:
            self._music_generation += 1
            self._stop.set()
            self._skip.set()
            proc = self._process
            had_music = bool(self._now or self._queue or proc)
            _terminate_process(proc)
            with self._lock:
                self._queue = []
                self._now = None
                self._paused = False
                self._playlist_name = ""
                self._process = None
        return "Stopped the music." if had_music else ("" if silent else "No music is playing.")

    def patched_play_tracks(self, tracks, playlist_name: str = "") -> None:
        # Invalidate every older worker before starting the new one. Do not rely
        # on the shared Event remaining set, because the new worker clears it.
        patched_stop(self, silent=True)
        with self._music_worker_lock:
            self._music_generation += 1
            generation = self._music_generation
            with self._lock:
                self._queue = list(tracks)[:200]
                self._history = []
                self._playlist_name = playlist_name
                self._stop.clear()
                self._skip.clear()
                self._paused = False
            worker = threading.Thread(
                target=patched_run_queue,
                args=(self, generation),
                daemon=True,
                name=f"youtube-music-{generation}",
            )
            self._worker = worker
            worker.start()

    def patched_run_queue(self, generation: int | None = None) -> None:
        if generation is None:
            generation = getattr(self, "_music_generation", 0)

        while not self._stop.is_set() and generation == getattr(self, "_music_generation", -1):
            with self._lock:
                if generation != getattr(self, "_music_generation", -1) or not self._queue:
                    break
                track = self._queue.pop(0)
                self._now = track

            proc: subprocess.Popen[bytes] | None = None
            try:
                expected_duration = _duration_seconds(getattr(track, "duration", ""))
                resume_at = 0.0
                attempts = 0
                max_retries = max(0, min(5, int(os.getenv("YOUTUBE_MUSIC_STREAM_RETRIES", "2"))))
                announced = False

                while (
                    generation == getattr(self, "_music_generation", -1)
                    and not self._stop.is_set()
                    and not self._skip.is_set()
                ):
                    stream = self.resolve_stream(track.webpage_url)
                    if generation != getattr(self, "_music_generation", -1) or self._stop.is_set():
                        break

                    if not announced:
                        self.announce(f"Now playing {track.title}.")
                        announced = True
                    elif attempts:
                        self.announce(f"Resuming {track.title} after the stream disconnected.")

                    self._skip.clear()
                    self._paused = False
                    command = [
                        self._ffplay(),
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "-threads",
                        "1",
                        # HTTP/CDN streams occasionally close a socket before the
                        # track ends. Let FFmpeg reconnect before giving up.
                        "-reconnect",
                        "1",
                        "-reconnect_streamed",
                        "1",
                        "-reconnect_on_network_error",
                        "1",
                        "-reconnect_on_http_error",
                        "4xx,5xx",
                        "-reconnect_delay_max",
                        "8",
                    ]
                    if resume_at > 1.0:
                        command += ["-ss", f"{resume_at:.3f}"]
                    command += [
                        "-volume",
                        str(self._volume),
                        stream["url"],
                    ]

                    started = time.monotonic()
                    proc = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if generation == getattr(self, "_music_generation", -1):
                        self._process = proc

                    while (
                        proc.poll() is None
                        and generation == getattr(self, "_music_generation", -1)
                        and not self._stop.wait(0.35)
                        and not self._skip.is_set()
                    ):
                        pass

                    elapsed = max(0.0, time.monotonic() - started)
                    if proc.poll() is None:
                        _terminate_process(proc)

                    if (
                        generation != getattr(self, "_music_generation", -1)
                        or self._stop.is_set()
                        or self._skip.is_set()
                    ):
                        break

                    # Natural completion: either the expected duration was
                    # reached, or we do not know the duration and ffplay exited
                    # successfully. Do not loop/restart a song that actually ended.
                    exit_code = proc.poll()
                    played_until = resume_at + elapsed
                    if expected_duration is not None and played_until >= max(0.0, expected_duration - 8.0):
                        break
                    if expected_duration is None and exit_code == 0:
                        break

                    if attempts >= max_retries:
                        self.announce(f"Playback ended early for {track.title} after {attempts + 1} stream attempt(s).")
                        break

                    # A fresh yt-dlp resolution gives us a new signed CDN URL.
                    # Resume a little before the disconnect so short buffering
                    # gaps do not skip lyrics/music content.
                    resume_at = max(0.0, played_until - 2.0)
                    attempts += 1
                    _terminate_process(proc)
                    proc = None
                    if generation == getattr(self, "_music_generation", -1):
                        self._process = None

                if (
                    generation == getattr(self, "_music_generation", -1)
                    and not self._stop.is_set()
                    and not self._skip.is_set()
                ):
                    with self._lock:
                        self._history.append(track)
            except Exception as exc:
                if generation == getattr(self, "_music_generation", -1):
                    self.announce(f"I couldn't play {track.title}: {exc}")
            finally:
                _terminate_process(proc)
                if generation == getattr(self, "_music_generation", -1):
                    self._process = None
                    self._paused = False

        if generation == getattr(self, "_music_generation", -1):
            with self._lock:
                self._now = None
                self._queue = []
                self._playlist_name = ""
                self._paused = False
                self._process = None

    def patched_status_dict(self) -> dict[str, Any]:
        with self._lock:
            worker = self._worker
            proc = self._process
            return {
                "playing": bool(self._now and proc and proc.poll() is None),
                "paused": self._paused,
                "volume": self._volume,
                "playlist": self._playlist_name,
                "now": self._now.as_dict() if self._now else None,
                "queue": [track.as_dict() for track in self._queue],
                "history": [track.as_dict() for track in self._history[-10:]],
                "stream": dict(self._last_stream),
                "worker_alive": bool(worker and worker.is_alive()),
                "player_pid": proc.pid if proc and proc.poll() is None else None,
                "generation": getattr(self, "_music_generation", 0),
            }

    YouTubeMusicPlayer.__init__ = patched_init
    YouTubeMusicPlayer._run_ytdlp_json = guarded_ytdlp
    YouTubeMusicPlayer.stop = patched_stop
    YouTubeMusicPlayer.play_tracks = patched_play_tracks
    YouTubeMusicPlayer._run_queue = patched_run_queue
    YouTubeMusicPlayer.status_dict = patched_status_dict
    YouTubeMusicPlayer._neko_pi_resource_guard = True
