from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass


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
