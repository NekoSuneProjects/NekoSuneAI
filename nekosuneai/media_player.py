from __future__ import annotations

import os
import random
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .config import Config

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus", ".aac", ".wma"}


@dataclass
class MediaPlaybackState:
    kind: str = ""
    title: str = ""
    source_url: str = ""
    is_paused: bool = False
    position_seconds: float = 0.0


class MediaPlayer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._current = MediaPlaybackState()
        self._paused = MediaPlaybackState()
        self._volume = 100
        self._started_monotonic = 0.0
        self._history: list[MediaPlaybackState] = []
        self._queue: list[MediaPlaybackState] = []

    def _resolve_ffplay(self) -> str:
        ffplay_path = shutil.which("ffplay")
        if not ffplay_path:
            raise RuntimeError(
                "Direct media playback requires ffplay in PATH. Install FFmpeg or add ffplay to PATH."
            )
        return ffplay_path

    def _position_locked(self) -> float:
        base = float(self._current.position_seconds or 0.0)
        if self._process is not None and self._started_monotonic > 0 and not self._current.is_paused:
            base += max(0.0, time.monotonic() - self._started_monotonic)
        return base

    def _terminate_locked(self, *, clear_current: bool = True) -> bool:
        stopped = False
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            stopped = True
        self._process = None
        self._started_monotonic = 0.0
        if clear_current:
            self._current = MediaPlaybackState()
        return stopped

    def _start_locked(self, state: MediaPlaybackState, *, remember_previous: bool) -> str:
        ffplay_path = self._resolve_ffplay()
        if remember_previous and self._current.source_url:
            previous = MediaPlaybackState(
                kind=self._current.kind,
                title=self._current.title,
                source_url=self._current.source_url,
                position_seconds=0.0,
            )
            if not self._history or self._history[-1].source_url != previous.source_url:
                self._history.append(previous)
                del self._history[:-50]
        self._terminate_locked(clear_current=True)
        command = [ffplay_path, "-nodisp", "-autoexit", "-loglevel", "error"]
        if urlparse(state.source_url).scheme.lower() in {"http", "https"}:
            command += [
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_on_network_error", "1",
                "-reconnect_on_http_error", "4xx,5xx",
                "-reconnect_delay_max", "8",
            ]
        if state.position_seconds > 0:
            command += ["-ss", f"{state.position_seconds:.3f}"]
        command += ["-volume", str(self._volume), state.source_url]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start ffplay for {state.title}. {exc}") from exc
        self._current = MediaPlaybackState(
            kind=state.kind,
            title=state.title,
            source_url=state.source_url,
            is_paused=False,
            position_seconds=max(0.0, float(state.position_seconds or 0.0)),
        )
        self._paused = MediaPlaybackState()
        self._started_monotonic = time.monotonic()
        return f"Playing {state.title}."

    def play_stream(self, url: str, *, title: str, kind: str) -> str:
        with self._lock:
            return self._start_locked(MediaPlaybackState(kind=kind, title=title, source_url=url), remember_previous=True)

    def stop(self) -> bool:
        with self._lock:
            stopped = self._terminate_locked(clear_current=True)
            self._paused = MediaPlaybackState()
            return stopped

    def pause(self) -> str:
        with self._lock:
            if self._process is None or not self._current.source_url:
                return "Nothing is playing right now."
            position = self._position_locked()
            if os.name != "nt":
                try:
                    os.kill(self._process.pid, signal.SIGSTOP)
                    self._current.is_paused = True
                    self._current.position_seconds = position
                    self._started_monotonic = 0.0
                    self._paused = MediaPlaybackState(**self._current.__dict__)
                    return f"Paused {self._current.title}."
                except Exception:
                    pass
            self._paused = MediaPlaybackState(
                kind=self._current.kind,
                title=self._current.title,
                source_url=self._current.source_url,
                is_paused=True,
                position_seconds=position,
            )
            title = self._paused.title
            self._terminate_locked(clear_current=True)
            return f"Paused {title}."

    def resume(self) -> str:
        with self._lock:
            if self._process is not None and self._current.is_paused and os.name != "nt":
                try:
                    os.kill(self._process.pid, signal.SIGCONT)
                    self._current.is_paused = False
                    self._started_monotonic = time.monotonic()
                    self._paused = MediaPlaybackState()
                    return f"Resumed {self._current.title}."
                except Exception:
                    pass
            if not self._paused.source_url:
                return "Nothing is paused right now."
            paused = self._paused
            return self._start_locked(paused, remember_previous=False).replace("Playing ", "Resumed ", 1)

    def seek(self, seconds: float, *, relative: bool = False) -> str:
        with self._lock:
            state = self._current if self._current.source_url else self._paused
            if not state.source_url:
                return "Nothing is playing right now."
            current_pos = self._position_locked() if self._current.source_url else float(state.position_seconds or 0.0)
            target = max(0.0, current_pos + float(seconds) if relative else float(seconds))
            was_paused = bool(self._current.is_paused or self._paused.source_url)
            replacement = MediaPlaybackState(kind=state.kind, title=state.title, source_url=state.source_url, position_seconds=target)
            if was_paused:
                self._terminate_locked(clear_current=True)
                self._paused = MediaPlaybackState(
                    kind=replacement.kind,
                    title=replacement.title,
                    source_url=replacement.source_url,
                    is_paused=True,
                    position_seconds=replacement.position_seconds,
                )
                return f"Seeked {replacement.title} to {int(target)} seconds; it remains paused."
            self._start_locked(replacement, remember_previous=False)
            return f"Seeked {replacement.title} to {int(target)} seconds."

    def enqueue(self, url: str, *, title: str, kind: str = "music") -> None:
        with self._lock:
            self._queue.append(MediaPlaybackState(kind=kind, title=title, source_url=url))

    def next(self) -> str:
        with self._lock:
            if not self._queue:
                return "There is no next queued track."
            nxt = self._queue.pop(0)
            return self._start_locked(nxt, remember_previous=True).replace("Playing ", "Skipped to ", 1)

    def previous(self) -> str:
        with self._lock:
            if not self._history:
                return "There is no previous track in local playback history."
            previous = self._history.pop()
            if self._current.source_url:
                self._queue.insert(0, MediaPlaybackState(kind=self._current.kind, title=self._current.title, source_url=self._current.source_url))
            return self._start_locked(previous, remember_previous=False).replace("Playing ", "Returned to ", 1)

    def set_volume(self, percent: int) -> str:
        with self._lock:
            target = max(0, min(100, int(percent)))
            if target == self._volume:
                return f"Volume already at {self._volume}%."
            state = self._current if self._current.source_url else self._paused
            self._volume = target
            if not state.source_url:
                return f"Volume set to {self._volume}% for the next track."
            position = self._position_locked() if self._current.source_url else float(state.position_seconds or 0.0)
            was_paused = bool(self._current.is_paused or self._paused.source_url)
            replacement = MediaPlaybackState(kind=state.kind, title=state.title, source_url=state.source_url, position_seconds=position)
            if was_paused:
                self._terminate_locked(clear_current=True)
                self._paused = MediaPlaybackState(
                    kind=replacement.kind,
                    title=replacement.title,
                    source_url=replacement.source_url,
                    is_paused=True,
                    position_seconds=replacement.position_seconds,
                )
            else:
                self._start_locked(replacement, remember_previous=False)
            return f"Volume adjusted to {self._volume}% without losing the track position."

    def current_kind(self) -> str:
        with self._lock:
            return self._current.kind if self._process is not None else (self._paused.kind if self._paused.source_url else "")

    def status_text(self) -> str:
        with self._lock:
            if self._process is not None and self._current.title:
                position = int(self._position_locked())
                prefix = "Paused" if self._current.is_paused else "Now playing"
                return f"{prefix}: {self._current.title} ({self._current.kind}) at {position}s, volume {self._volume}%."
            if self._paused.title:
                return f"Paused: {self._paused.title} ({self._paused.kind}) at {int(self._paused.position_seconds)}s, volume {self._volume}%."
            return "No media is playing."


_PLAYER = MediaPlayer()


def play_media_stream(url: str, *, title: str, kind: str) -> str:
    return _PLAYER.play_stream(url, title=title, kind=kind)


def stop_media_playback() -> str:
    stopped = _PLAYER.stop()
    return "Stopped current media." if stopped else "Nothing is playing right now."


def pause_media_playback() -> str:
    return _PLAYER.pause()


def resume_media_playback() -> str:
    return _PLAYER.resume()


def seek_media_playback(seconds: float, *, relative: bool = False) -> str:
    return _PLAYER.seek(seconds, relative=relative)


def next_media_playback() -> str:
    return _PLAYER.next()


def previous_media_playback() -> str:
    return _PLAYER.previous()


def queue_media_stream(url: str, *, title: str, kind: str = "music") -> None:
    _PLAYER.enqueue(url, title=title, kind=kind)


def set_media_volume(percent: int) -> str:
    return _PLAYER.set_volume(percent)


def media_status_text() -> str:
    return _PLAYER.status_text()


def current_media_kind() -> str:
    return _PLAYER.current_kind()


def _resolve_thinking_sound_path(configured_path: str) -> str | None:
    candidate = Path(configured_path)
    if candidate.is_dir():
        tracks = [entry for entry in candidate.iterdir() if entry.is_file() and entry.suffix.lower() in _AUDIO_EXTENSIONS]
        if not tracks:
            return None
        return str(random.choice(tracks))
    if candidate.is_file():
        return str(candidate)
    return None


def _play_thinking_sound(config: "Config") -> None:
    try:
        resolved_path = _resolve_thinking_sound_path(config.thinking_sound_path)
        if not resolved_path:
            return
        play_media_stream(resolved_path, title="Thinking...", kind="thinking")
    except Exception as exc:
        print(f"[ThinkingSound] Could not play: {exc}")


def start_thinking_sound(config: "Config") -> threading.Timer | None:
    if not config.thinking_sound_enabled or not config.thinking_sound_path:
        return None
    if current_media_kind():
        return None
    timer = threading.Timer(config.thinking_sound_delay_seconds, _play_thinking_sound, args=(config,))
    timer.daemon = True
    timer.start()
    return timer


def stop_thinking_sound(timer: threading.Timer | None) -> None:
    if timer is None:
        return
    timer.cancel()
    if current_media_kind() == "thinking":
        stop_media_playback()
