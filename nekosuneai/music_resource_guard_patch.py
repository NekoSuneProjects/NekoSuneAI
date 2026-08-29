from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

_INSTALLED = False
_YTDLP_GATE = threading.Semaphore(max(1, int(os.getenv("YOUTUBE_MUSIC_MAX_YTDLP", "1"))))


def install_music_resource_guard_patch() -> None:
    """Keep Docker/Raspberry Pi music playback from spawning overlapping workers.

    The original player reused one shared stop event. Starting a new song called
    stop(), then immediately cleared that same event for the new worker. An older
    worker could therefore wake back up and continue resolving/playing, leaving
    multiple yt-dlp/ffplay processes alive after a few song changes.
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
                stream = self.resolve_stream(track.webpage_url)
                if generation != getattr(self, "_music_generation", -1) or self._stop.is_set():
                    break

                self.announce(f"Now playing {track.title}.")
                self._skip.clear()
                self._paused = False
                proc = subprocess.Popen(
                    [
                        self._ffplay(),
                        "-nodisp",
                        "-autoexit",
                        "-loglevel",
                        "error",
                        "-threads",
                        "1",
                        "-volume",
                        str(self._volume),
                        stream["url"],
                    ],
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

                if proc.poll() is None:
                    _terminate_process(proc)

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
