from __future__ import annotations

import random
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus", ".aac", ".wma"}


@dataclass
class MediaPlaybackState:
    kind: str = ""
    title: str = ""
    source_url: str = ""
    is_paused: bool = False


class MediaPlayer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._current = MediaPlaybackState()
        self._paused = MediaPlaybackState()
        self._volume = 100

    def _resolve_ffplay(self) -> str:
        ffplay_path = shutil.which("ffplay")
        if not ffplay_path:
            raise RuntimeError(
                "Direct media playback requires ffplay in PATH. Install FFmpeg or add ffplay to PATH."
            )
        return ffplay_path

    def play_stream(self, url: str, *, title: str, kind: str) -> str:
        ffplay_path = self._resolve_ffplay()
        with self._lock:
            self.stop()
            command = [
                ffplay_path,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-volume",
                str(self._volume),
                url,
            ]
            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise RuntimeError(f"Could not start ffplay for {title}. {exc}") from exc
            self._current = MediaPlaybackState(
                kind=kind,
                title=title,
                source_url=url,
                is_paused=False,
            )
            self._paused = MediaPlaybackState()
        return f"Playing {title}."

    def stop(self) -> bool:
        with self._lock:
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
            self._current = MediaPlaybackState()
            return stopped

    def pause(self) -> str:
        with self._lock:
            if self._process is None or not self._current.source_url:
                return "Nothing is playing right now."
            self._paused = MediaPlaybackState(
                kind=self._current.kind,
                title=self._current.title,
                source_url=self._current.source_url,
                is_paused=True,
            )
            self.stop()
            return f"Paused {self._paused.title}."

    def resume(self) -> str:
        with self._lock:
            if not self._paused.source_url:
                return "Nothing is paused right now."
            paused = self._paused
            self._paused = MediaPlaybackState()
        return self.play_stream(paused.source_url, title=paused.title, kind=paused.kind)

    def _send_ffplay_key(self, key: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            return
        try:
            self._process.stdin.write(key + b'\n')
            self._process.stdin.flush()
        except Exception:
            pass

    def set_volume(self, percent: int) -> str:
        with self._lock:
            target = max(0, min(100, percent))
            if self._process is None or not self._current.source_url:
                self._volume = target
                return f"Volume set to {self._volume}% for the next track."

            difference = target - self._volume
            if difference == 0:
                return f"Volume already at {self._volume}% ."

            step_count = abs(difference)
            step_key = b'0' if difference > 0 else b'9'
            for _ in range(step_count):
                self._send_ffplay_key(step_key)
            self._volume = target
            return f"Volume adjusted to {self._volume}% without restarting playback."

    def current_kind(self) -> str:
        with self._lock:
            return self._current.kind if self._process is not None else ""

    def status_text(self) -> str:
        with self._lock:
            if self._process is not None and self._current.title:
                return f"Now playing: {self._current.title} ({self._current.kind})."
            if self._paused.title:
                return f"Paused: {self._paused.title} ({self._paused.kind})."
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


def set_media_volume(percent: int) -> str:
    return _PLAYER.set_volume(percent)


def media_status_text() -> str:
    return _PLAYER.status_text()


def current_media_kind() -> str:
    return _PLAYER.current_kind()


def _resolve_thinking_sound_path(configured_path: str) -> str | None:
    """*configured_path* may be a single audio file OR a folder of tracks to
    pick a random one from each time — ffplay itself can't play a directory,
    so a folder has to be resolved to one file's path first."""
    candidate = Path(configured_path)
    if candidate.is_dir():
        tracks = [
            entry for entry in candidate.iterdir()
            if entry.is_file() and entry.suffix.lower() in _AUDIO_EXTENSIONS
        ]
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
        # Runs on a background Timer thread with nothing watching stderr in the
        # GUI (pythonw.exe) — an uncaught exception here would otherwise just
        # vanish, making a bad thinking-sound path look like "nothing happens".
        print(f"[ThinkingSound] Could not play: {exc}")


def start_thinking_sound(config: "Config") -> threading.Timer | None:
    """Start a delayed one-shot "thinking" cue — plays only if *config* enables
    it, a sound file/folder is set, and nothing else is already playing (never
    interrupts music the user started). Callers must always pass the returned
    timer to stop_thinking_sound() in a ``finally`` block."""
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
    # Only stop playback if it's actually our cue — avoids clobbering music that
    # started (e.g. a media request) while we were thinking.
    if current_media_kind() == "thinking":
        stop_media_playback()
