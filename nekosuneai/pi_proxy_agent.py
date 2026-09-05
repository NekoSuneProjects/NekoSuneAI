"""Lightweight paired Raspberry Pi node: Bluetooth speaker management, local
audio capture/playback, and relaying media/commands to the Docker/Pi backend.

Pi Proxy never runs a local LLM/vision/STT/TTS model. `audio.speak` and
`audio.listen` relay through the backend's existing
`/api/nodes/media/tts`/`/api/nodes/media/stt` endpoints (see node_media.py /
node_media_client.py for the shared request/response shape).

The one deliberate exception is `music.play`: the backend hands this node a
search query or a YouTube URL/video id (NOT a pre-resolved stream URL),
because YouTube's bot/cookie verification blocks the datacenter/VPS IPs the
Docker backend may run from, but not a home Raspberry Pi's residential IP.
This node resolves the actual playable stream with `yt-dlp` locally and plays
it back -- the backend still decides *what* to play (search/song selection
stays a backend/assistant concern), Pi Proxy only does the resolution step
that has to happen from a residential IP, plus local playback.

There is no game-skill/window-capture/OBS surface here -- this is not a game
node -- and no keyboard/mouse to release on an emergency stop, only audio
streams.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import requests

from .alert_sounds import ensure_default_alert_sounds
from .bluetooth_watchdog import BluetoothSpeakerWatchdog
from .config import Config
from .console_control import console_capabilities, console_command, console_status
from .kinect_vision_patch import KinectVisionService
from .wakeword import WakeWordListener

# node_media.py's STT endpoint (see nekosuneai/node_media.py:read_pcm_wav)
# accepts mono PCM16 WAV at 16/24/48 kHz, at most 15 seconds. Recording longer
# than that locally would just be rejected by the backend, so clamp here too.
DEFAULT_LISTEN_SECONDS = 5.0
MAX_LISTEN_SECONDS = 15.0
STT_SAMPLE_RATE = 16000

# console_status() does a LAN discovery/reachability probe per platform (PS5
# UDP discovery + an Xbox TCP reachability hint). The status page polls every
# 2s, so cache console_status("all") briefly rather than re-probing the LAN
# on every single poll.
CONSOLE_STATUS_CACHE_SECONDS = 5.0


class LocalAudioPlayer:
    """Subprocess-based playback; no new audio library dependency.

    Assumption (Raspberry Pi OS): `paplay` (PipeWire-pulse/PulseAudio) is
    used when present, since bluetooth_watchdog.py already drives the same
    Bluetooth sink through `pactl`, i.e. the same audio server. Falls back to
    plain ALSA `aplay` if `paplay` is unavailable. `music.play` streams
    through `ffplay` (ships with ffmpeg, commonly installed on Raspberry Pi
    OS) with no video output, since it needs to play a resolved network
    stream URL rather than a local file.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def _stop_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def play_wav_bytes(self, raw: bytes) -> None:
        fd, path = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        player = "paplay" if shutil.which("paplay") else "aplay"
        if not shutil.which(player):
            os.unlink(path)
            raise RuntimeError("neither paplay nor aplay is available on PATH for local playback")
        with self._lock:
            self._stop_locked()
            self._proc = subprocess.Popen(
                [player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            proc = self._proc

        def _cleanup() -> None:
            try:
                proc.wait()
            except Exception:
                pass
            try:
                os.unlink(path)
            except OSError:
                pass

        threading.Thread(target=_cleanup, daemon=True, name="pi-proxy-audio-cleanup").start()

    def play_url(self, url: str) -> None:
        if not shutil.which("ffplay"):
            raise RuntimeError("ffplay (part of ffmpeg) is required for music.play and was not found on PATH")
        with self._lock:
            self._stop_locked()
            self._proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )


class PiProxyAgent:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.server = str(config["server_url"]).rstrip("/")
        self.node_id = str(config.get("node_id") or platform.node() or "pi-proxy")
        self.token = str(config.get("device_token") or "")
        self.verify_tls = bool(config.get("verify_tls", True))
        self.session = requests.Session()

        # BluetoothSpeakerWatchdog wants a full backend Config, but Pi Proxy
        # drives it from its own node config (bluetooth target device, enable
        # flag, poll interval) rather than the Docker deployment's env vars /
        # docker-compose.yml BLUETOOTH_RECONNECT_ENABLED flag -- see
        # BRANCH_MAP.md's note that Bluetooth hardware access is now a Pi
        # Proxy responsibility, not the backend's.
        bt_config = Config.from_env()
        bt_config.bluetooth_reconnect_enabled = bool(config.get("bluetooth_reconnect_enabled", True))
        overlay_address = config.get("bluetooth_speaker_address")
        if overlay_address:
            bt_config.bluetooth_speaker_address = str(overlay_address)
        bt_config.bluetooth_reconnect_interval_seconds = max(
            3.0,
            float(config.get("bluetooth_reconnect_interval_seconds", bt_config.bluetooth_reconnect_interval_seconds)),
        )
        self.bt_config = bt_config
        self.bt_event_log: deque[str] = deque(maxlen=20)
        self.bt = BluetoothSpeakerWatchdog(self.bt_config, notify=self._on_bluetooth_event)

        self.player = LocalAudioPlayer()
        self.music_player = LocalAudioPlayer()
        self._disabled = threading.Event()
        self._stop = threading.Event()
        self._last_command = 0
        self._last_result: dict[str, Any] = {}
        self.command_log: deque[str] = deque(maxlen=20)

        # Wake word is off by default (needs a real microphone + a real
        # wake-word model file); this node's own config overlays the shared
        # Config.from_env() defaults the same way the Bluetooth config above
        # does, rather than being forced on for every deployment.
        wake_config = Config.from_env()
        wake_config.wake_word_enabled = bool(config.get("wake_word_enabled", False))
        if config.get("wake_word_model"):
            wake_config.wake_word_model = str(config.get("wake_word_model"))
        if config.get("wake_word_framework"):
            wake_config.wake_word_framework = str(config.get("wake_word_framework"))
        wake_config.wake_word_threshold = float(
            config.get("wake_word_threshold", wake_config.wake_word_threshold)
        )
        wake_config.wake_word_confirmation_frames = int(
            config.get("wake_word_confirmation_frames", wake_config.wake_word_confirmation_frames)
        )
        wake_config.wake_word_cooldown_seconds = float(
            config.get("wake_word_cooldown_seconds", wake_config.wake_word_cooldown_seconds)
        )
        if config.get("mic_device_index") is not None:
            wake_config.mic_device_index = int(config["mic_device_index"])
        self.wake_config = wake_config
        self.wake_last_transcript = ""
        self.wake_last_transcript_at = 0.0
        self.wakeword = WakeWordListener(wake_config, self._on_wake_word_detected)

        self._console_status_cache: dict[str, Any] = {}
        self._console_status_cached_at = 0.0

        # Wake-word ack chime + warning/danger alert tones (Alexa-style "I
        # heard you" feedback, and audible+spoken errors) -- generated once,
        # dependency-free (pure math/wave), never overwritten if the owner
        # supplies their own sounds under the same names.
        self.sounds_dir = Path(config.get("alert_sounds_dir") or "sounds")
        try:
            ensure_default_alert_sounds(self.sounds_dir)
        except Exception:
            pass  # best-effort; missing sounds just means no chime, not a crash

        # Kinect camera vision is off by default (needs real libfreenect
        # hardware/drivers); "describe" frames relay through this node's own
        # backend media call rather than calling a vision provider directly.
        self.kinect = KinectVisionService(config, describe_callback=self._describe_camera_frame)

        # Fallback local TTS (espeak-ng) covers the case the Docker backend
        # itself is unreachable -- e.g. a VPS outage, a network blip -- so the
        # Pi can still say *something* (connection-lost/error announcements)
        # instead of going silently mute. Never used as a substitute for the
        # backend's real TTS in normal operation.
        self._heartbeat_failures = 0
        self._backend_down_announced = False

        self.web_status = None
        if config.get("web_status_enabled"):
            from .pi_proxy_web import PiProxyWebStatusServer
            self.web_status = PiProxyWebStatusServer(
                self, port=int(config.get("web_status_port", 8799)),
            )

    def capabilities(self) -> dict[str, dict[str, str]]:
        return {
            "bluetooth.status": {"kind": "read"},
            "bluetooth.reconnect": {"kind": "write"},
            "audio.speak": {"kind": "write"},
            "audio.listen": {"kind": "write"},
            "music.play": {"kind": "write"},
            "music.stop": {"kind": "write"},
            "console.status": {"kind": "read"},
            "console.capabilities": {"kind": "read"},
            "console.command": {"kind": "write"},
            "camera.status": {"kind": "read"},
            "camera.snapshot": {"kind": "write"},
        }

    def _on_bluetooth_event(self, message: str) -> None:
        self.bt_event_log.append(f"{time.strftime('%H:%M:%S')}  {message}"[:240])

    def pair(self, pairing_id: str, pairing_code: str) -> str:
        response = self.session.post(
            self.server + "/api/nodes/register",
            json={
                "pairing_id": pairing_id, "pairing_code": pairing_code, "node_id": self.node_id,
                "name": str(self.config.get("name", "Pi Proxy Node")), "node_type": "pi-proxy",
                "capabilities": self.capabilities(),
            }, timeout=10, verify=self.verify_tls,
        )
        if not response.ok:
            try:
                detail = str(response.json().get("error") or response.reason)
            except (ValueError, AttributeError):
                detail = str(response.reason)
            raise RuntimeError(f"Node registration HTTP {response.status_code}: {detail}")
        self.token = str(response.json().get("device_token") or "")
        if not self.token:
            raise RuntimeError("Node registration returned no device token")
        return self.token

    def _headers(self) -> dict[str, str]:
        return {"X-Neko-Device-Token": self.token}

    def _media_request(self, operation: str, **payload: Any) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("pair this node first")
        response = self.session.post(
            f"{self.server}/api/nodes/media/{operation}",
            json={"node_id": self.node_id, **payload},
            headers=self._headers(), timeout=(10, 60), verify=self.verify_tls,
        )
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"backend returned HTTP {response.status_code} without a JSON response") from exc
        if not response.ok:
            raise RuntimeError(str(result.get("error") or f"HTTP {response.status_code}"))
        return result

    def _play_alert(self, name: str) -> None:
        """Play wake/warning/danger.wav (see alert_sounds.py). Best-effort --
        a missing/unreadable sound file should never break the caller."""
        path = self.sounds_dir / f"{name}.wav"
        try:
            self.player.play_wav_bytes(path.read_bytes())
        except Exception:
            pass

    def _speak_local_fallback(self, text: str) -> None:
        """Offline TTS via espeak-ng -- used only when the Docker backend's
        own TTS is unreachable. A tiny formant synthesizer, not a real voice
        model; this does not make Pi Proxy a local-TTS node in normal use."""
        if not shutil.which("espeak-ng"):
            return
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(
                ["espeak-ng", "-w", path, text[:500]],
                check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.player.play_wav_bytes(Path(path).read_bytes())
        except Exception:
            pass
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _describe_camera_frame(self, jpeg: bytes) -> str | None:
        """KinectVisionService's describe_callback -- relays a captured frame
        through the backend's existing vision endpoint. Pi Proxy never calls
        a vision provider directly (see module docstring)."""
        result = self._media_request("vision", image_base64=base64.b64encode(jpeg).decode("ascii"))
        return result.get("description")

    def _record_wav(self, seconds: float) -> bytes:
        # Bounded local mic capture via ALSA's `arecord` (alsa-utils), which
        # ships on virtually every Raspberry Pi OS image -- avoids adding a
        # new Python audio-capture dependency for a single bounded recording.
        if not shutil.which("arecord"):
            raise RuntimeError("arecord (alsa-utils) is required for audio.listen and was not found on PATH")
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(
                ["arecord", "-q", "-f", "S16_LE", "-c", "1", "-r", str(STT_SAMPLE_RATE),
                 "-d", str(max(1, int(round(seconds)))), path],
                check=True, timeout=seconds + 10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return Path(path).read_bytes()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _resolve_stream_url(self, query: str) -> str:
        # The Docker backend may run on a VPS whose datacenter IP gets
        # blocked by YouTube's bot/cookie verification; a Pi's residential
        # IP does not, so the *resolution* step runs here, not on the
        # backend. The backend still decides what to play -- it only ever
        # hands this node a search query or a YouTube URL/video id, never a
        # pre-resolved stream URL.
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
            "skip_download": True,
            "socket_timeout": 15,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
        return str(url)

    def _dispatch(self, capability: str, args: dict[str, Any]) -> dict[str, Any]:
        if capability == "bluetooth.status":
            return self.bt.status()
        if capability == "bluetooth.reconnect":
            ok, message = self.bt.reconnect_now()
            return {"ok": ok, "message": message}
        if capability == "audio.speak":
            if self._disabled.is_set():
                raise PermissionError("audio output is locally disabled")
            text = str(args.get("text", "")).strip()
            if not text:
                raise ValueError("audio.speak requires non-empty text")
            try:
                result = self._media_request("tts", text=text)
                encoded = result.get("audio_base64", "")
                if not isinstance(encoded, str) or not encoded:
                    raise RuntimeError("backend returned no TTS audio")
                raw = base64.b64decode(encoded, validate=True)
                self.player.play_wav_bytes(raw)
                return {"ok": True, "speaking": True}
            except Exception as exc:
                # The backend's own TTS failed (down, network blip, etc.) --
                # fall back to local espeak-ng rather than dropping the line
                # this node was specifically asked to speak.
                self._speak_local_fallback(text)
                return {"ok": True, "speaking": True, "fallback": True, "reason": str(exc)[:200]}
        if capability == "audio.listen":
            if self._disabled.is_set():
                raise PermissionError("audio input is locally disabled")
            requested = args.get("seconds", self.config.get("audio_listen_seconds", DEFAULT_LISTEN_SECONDS))
            seconds = max(1.0, min(float(requested), MAX_LISTEN_SECONDS))
            wav_bytes = self._record_wav(seconds)
            result = self._media_request("stt", wav_base64=base64.b64encode(wav_bytes).decode("ascii"))
            return {"ok": True, "text": result.get("text", "")}
        if capability == "music.play":
            if self._disabled.is_set():
                raise PermissionError("audio output is locally disabled")
            query = str(args.get("query") or args.get("url") or "").strip()
            if not query:
                raise ValueError("music.play requires a query or url")
            stream_url = self._resolve_stream_url(query)
            self.music_player.play_url(stream_url)
            return {"ok": True, "playing": True, "query": query[:300]}
        if capability == "music.stop":
            self.music_player.stop()
            return {"ok": True, "stopped": True}
        if capability == "console.status":
            return console_status(str(args.get("platform", "all")))
        if capability == "console.capabilities":
            return console_capabilities(str(args.get("platform", "all")))
        if capability == "console.command":
            platform_name = str(args.get("platform", "")).strip()
            action = str(args.get("action", "")).strip()
            if not platform_name or not action:
                raise ValueError("console.command requires platform and action")
            message = console_command(
                platform_name, action, str(args.get("value", "")),
                confirmed=bool(args.get("confirmed", False)),
            )
            return {"ok": True, "message": message}
        if capability == "camera.status":
            return self.kinect.status()
        if capability == "camera.snapshot":
            if self._disabled.is_set():
                raise PermissionError("camera capture is locally disabled")
            device = args.get("device")
            jpeg = self.kinect.capture_jpeg_once(int(device) if device is not None else None)
            description = self._describe_camera_frame(jpeg)
            return {"ok": True, "description": description}
        raise ValueError("command capability is not handled locally")

    def _on_wake_word_detected(self) -> None:
        """WakeWordListener's own worker thread calls this synchronously once
        the wake word is confirmed. Capture a short utterance and relay it
        through the same /api/nodes/media/stt path audio.listen already uses
        -- there is no backend endpoint yet for turning a transcript into an
        actual spoken reply (see TODO.md's NODE-CONVERSE-01), so this only
        detects, captures, transcribes and logs/exposes the transcript."""
        if self._disabled.is_set():
            return
        # Audible "I heard you" acknowledgement, Alexa/Echo-style, so there's
        # feedback before the (up to several seconds) capture-and-transcribe
        # round trip completes.
        self._play_alert("wake")
        time.sleep(0.35)  # let the short chime finish before recording
        # Kinect/ALSA input devices are commonly exclusive; pause() (already
        # provided by WakeWordListener for exactly this reason) lets arecord
        # open the microphone without fighting the wake-word stream for it.
        self.wakeword.pause()
        try:
            requested = self.config.get("wake_word_listen_seconds", DEFAULT_LISTEN_SECONDS)
            seconds = max(1.0, min(float(requested), MAX_LISTEN_SECONDS))
            wav_bytes = self._record_wav(seconds)
            result = self._media_request("stt", wav_base64=base64.b64encode(wav_bytes).decode("ascii"))
            text = str(result.get("text", ""))
            self.wake_last_transcript = text
            self.wake_last_transcript_at = time.time()
            self.command_log.append(f"{time.strftime('%H:%M:%S')}  wake-word -> {text}"[:200])
        except Exception as exc:
            self.command_log.append(f"{time.strftime('%H:%M:%S')}  wake-word error: {exc}"[:200])
        finally:
            self.wakeword.resume()

    def _console_status_cached(self) -> dict[str, Any]:
        now = time.time()
        if now - self._console_status_cached_at < CONSOLE_STATUS_CACHE_SECONDS and self._console_status_cache:
            return self._console_status_cache
        try:
            self._console_status_cache = console_status("all")
        except Exception as exc:
            self._console_status_cache = {"error": str(exc)[:300]}
        self._console_status_cached_at = now
        return self._console_status_cache

    def stop_all(self, disable: bool = False) -> None:
        self.player.stop()
        self.music_player.stop()
        if disable:
            self._disabled.set()

    def enable(self) -> None:
        self._disabled.clear()

    def _telemetry(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "input_disabled": self._disabled.is_set(),
            "bluetooth": self.bt.status(),
            "audio_speaking": self.player.is_playing(),
            "music_playing": self.music_player.is_playing(),
            "last_command_result": self._last_result,
            "recent_commands": list(self.command_log),
            "camera": self.kinect.status(),
            "backend_reachable": not self._backend_down_announced,
        }
        try:
            import psutil
            state["cpu_percent"] = psutil.cpu_percent()
            state["memory_percent"] = psutil.virtual_memory().percent
        except Exception:
            pass
        return state

    def status(self) -> dict[str, Any]:
        """Read-only snapshot for pi_proxy_web.py; safe to expose on the LAN."""
        wake_status = self.wakeword.status()
        wake_status["last_transcript"] = self.wake_last_transcript
        wake_status["last_transcript_at"] = self.wake_last_transcript_at
        return {
            "epoch": time.time(),
            "node_id": self.node_id,
            "paired": bool(self.token),
            "input_disabled": self._disabled.is_set(),
            "bluetooth": self.bt.status(),
            "bluetooth_events": list(self.bt_event_log),
            "audio_speaking": self.player.is_playing(),
            "music_playing": self.music_player.is_playing(),
            "recent_commands": list(self.command_log),
            "wake_word": wake_status,
            "console": self._console_status_cached(),
            "camera": self.kinect.status(),
            "backend_reachable": not self._backend_down_announced,
        }

    def heartbeat_once(self) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("pair the agent first and store device_token in its config")
        response = self.session.post(
            self.server + "/api/nodes/heartbeat", headers=self._headers(), verify=self.verify_tls, timeout=10,
            json={
                "node_id": self.node_id, "state": self._telemetry(), "capabilities": self.capabilities(),
                "ack_command_id": self._last_command or None,
            },
        )
        response.raise_for_status()
        poll = self.session.post(
            self.server + "/api/nodes/poll", headers=self._headers(), verify=self.verify_tls, timeout=30,
            json={"node_id": self.node_id, "after": self._last_command, "wait_seconds": 5},
        )
        poll.raise_for_status()
        for command in poll.json().get("commands", []):
            capability = str(command.get("capability", ""))
            try:
                self._last_result = self._dispatch(capability, dict(command.get("arguments") or {}))
                self.command_log.append(f"{time.strftime('%H:%M:%S')}  {capability} -> ok")
            except Exception as exc:
                self._last_result = {"ok": False, "error": str(exc)[:300]}
                self.command_log.append(f"{time.strftime('%H:%M:%S')}  {capability} -> error: {exc}"[:200])
            self._last_command = max(self._last_command, int(command.get("id", 0)))
        if self._backend_down_announced:
            self._backend_down_announced = False
            self._play_alert("wake")  # short, cheerful "back online" cue
        self._heartbeat_failures = 0
        return response.json()

    def stop(self) -> None:
        self._stop.set()
        self.stop_all(disable=True)
        self.wakeword.stop_event.set()
        self.kinect._stop.set()
        if self.web_status is not None:
            self.web_status.stop()

    def run(self) -> None:
        if not self.token:
            raise RuntimeError("pair the agent first and store device_token in its config")
        try:
            self.bt.start()
            # start() itself no-ops when wake_config.wake_word_enabled is
            # False (off by default -- needs a real mic + wake-word model).
            self.wakeword.start()
            # KinectVisionService's own loop no-ops (just sleeps) whenever
            # kinect_vision_enabled is false in this node's config, same
            # off-by-default-needs-real-hardware pattern as wake word.
            self.kinect.start()
            if self.web_status is not None:
                self.web_status.start()
            while not self._stop.is_set():
                try:
                    self.heartbeat_once()
                except Exception:
                    self._heartbeat_failures += 1
                    # A few consecutive misses before announcing -- a single
                    # dropped heartbeat is normal network noise, not an
                    # outage worth interrupting audio for.
                    if self._heartbeat_failures >= 3 and not self._backend_down_announced:
                        self._backend_down_announced = True
                        self._play_alert("warning")
                        self._speak_local_fallback(
                            "Connection to the main server has been lost. Running in offline mode."
                        )
                    if self._stop.wait(3):
                        break
        finally:
            self.stop()


def _install_signal_handlers(agent: PiProxyAgent) -> None:
    """A Pi node has no desktop hotkey listener, so SIGINT/SIGTERM is the
    local emergency stop: immediately release any audio/music playback and
    disarm further audio commands, then let run()'s loop exit."""

    def _handler(signum: int, _frame: Any) -> None:
        agent.stop_all(disable=True)
        agent._stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _env_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Optional .env-driven overrides, mirroring the Docker backend's
# Config.from_env() pattern for container/compose deployments (see
# compose.pi-proxy.yml's `env_file: .env`). The JSON config file remains
# authoritative and is what gets written back to disk (e.g. the device token
# after pairing) -- these env vars only override values in-memory for this
# run and are never persisted into the JSON file, so removing a .env entry
# falls back to whatever the JSON file already has.
_ENV_OVERRIDE_KEYS: dict[str, tuple[str, Any]] = {
    "PI_PROXY_SERVER_URL": ("server_url", str),
    "PI_PROXY_NODE_ID": ("node_id", str),
    "PI_PROXY_NAME": ("name", str),
    "PI_PROXY_DEVICE_TOKEN": ("device_token", str),
    "PI_PROXY_VERIFY_TLS": ("verify_tls", _env_bool),
    "BLUETOOTH_RECONNECT_ENABLED": ("bluetooth_reconnect_enabled", _env_bool),
    "BLUETOOTH_SPEAKER_ADDRESS": ("bluetooth_speaker_address", str),
    "BLUETOOTH_RECONNECT_INTERVAL_SECONDS": ("bluetooth_reconnect_interval_seconds", float),
    "AUDIO_LISTEN_SECONDS": ("audio_listen_seconds", float),
    "WAKE_WORD_ENABLED": ("wake_word_enabled", _env_bool),
    "WAKE_WORD_MODEL": ("wake_word_model", str),
    "WAKE_WORD_FRAMEWORK": ("wake_word_framework", str),
    "WAKE_WORD_THRESHOLD": ("wake_word_threshold", float),
    "WAKE_WORD_CONFIRMATION_FRAMES": ("wake_word_confirmation_frames", int),
    "WAKE_WORD_COOLDOWN_SECONDS": ("wake_word_cooldown_seconds", float),
    "WAKE_WORD_LISTEN_SECONDS": ("wake_word_listen_seconds", float),
    "MIC_DEVICE_INDEX": ("mic_device_index", int),
    "WEB_STATUS_ENABLED": ("web_status_enabled", _env_bool),
    "WEB_STATUS_PORT": ("web_status_port", int),
    "ALERT_SOUNDS_DIR": ("alert_sounds_dir", str),
    "KINECT_VISION_ENABLED": ("kinect_vision_enabled", _env_bool),
    "KINECT_DEVICE_INDEX": ("kinect_device_index", int),
    "KINECT_VISION_INTERVAL_SECONDS": ("kinect_vision_interval_seconds", float),
    "KINECT_FACE_EMOTION": ("kinect_face_emotion", _env_bool),
    "KINECT_VISION_DESCRIBE": ("kinect_vision_describe", _env_bool),
}


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_name, (key, caster) in _ENV_OVERRIDE_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        try:
            overrides[key] = caster(raw)
        except (TypeError, ValueError):
            continue
    return overrides


def main() -> None:
    parser = argparse.ArgumentParser(description="NekoSuneAI paired Pi Proxy node agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--pairing-id", default="")
    parser.add_argument("--pairing-code", default="")
    # No --install-startup here (that flow is Windows-specific). A production
    # Raspberry Pi deployment should instead run this under a systemd unit,
    # e.g. /etc/systemd/system/pi-proxy-agent.service invoking
    # `python -m nekosuneai.pi_proxy_agent --config /path/to/pi-proxy-agent.json`
    # with Restart=on-failure -- see PiProxy/TODO.md's Packaging section.
    # Writing that unit file is a separate, lower-priority task.
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text("utf-8"))
    runtime_config = {**config, **_env_overrides()}

    needs_interactive_pairing = (
        not runtime_config.get("device_token") and not (args.pairing_id and args.pairing_code)
    )
    if needs_interactive_pairing and not runtime_config.get("server_url"):
        print("No device token found; let's pair this node.")
        server_url = input(
            "Server address (e.g. https://your-server.example.com or https://1.2.3.4:8788): "
        ).strip()
        if not server_url:
            print("A server address is required to pair.", file=sys.stderr)
            sys.exit(1)
        runtime_config["server_url"] = server_url
        config["server_url"] = server_url

    agent = PiProxyAgent(runtime_config)
    _install_signal_handlers(agent)

    if args.pairing_id and args.pairing_code:
        config["server_url"] = runtime_config.get("server_url", config.get("server_url", ""))
        config["device_token"] = agent.pair(args.pairing_id, args.pairing_code)
        config_path.write_text(json.dumps(config, indent=2), "utf-8")
        print("Paired successfully; the device token was saved locally.")
    elif needs_interactive_pairing:
        pairing_id = input("Pairing ID: ").strip()
        pairing_code = input("Pairing code: ").strip()
        if not pairing_id or not pairing_code:
            print("Pairing ID and pairing code are both required.", file=sys.stderr)
            sys.exit(1)
        try:
            config["server_url"] = runtime_config.get("server_url", config.get("server_url", ""))
            config["device_token"] = agent.pair(pairing_id, pairing_code)
        except Exception as exc:
            print(f"Pairing failed: {exc}", file=sys.stderr)
            sys.exit(1)
        config_path.write_text(json.dumps(config, indent=2), "utf-8")
        print("Paired successfully; the server address and device token were saved locally.")

    agent.run()


if __name__ == "__main__":
    main()
