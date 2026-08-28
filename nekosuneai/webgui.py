"""NekoSuneAI - pywebview desktop GUI with Tailwind CSS frontend."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

# pywebview is the native-desktop-GUI backend. Guard the import so the rest of
# this module (the Api class) can still be imported/tested without it installed.
try:
    import webview
except ImportError:  # pragma: no cover - desktop GUI extra not installed
    webview = None  # type: ignore[assignment]

from .audio_input import (
    describe_selected_microphone,
    describe_stt_backend,
    list_input_devices_compact,
    recalibrate_microphone,
    recognize_speech,
)
from .config import Config
from .engine import GenerationRequest, generate_reply
from .memory import MemoryStore
from .media import handle_media_request
from .media_player import start_thinking_sound, stop_thinking_sound
from .models import SessionState
from .monitors import MonitorManager
from .wakeword import WakeWordListener
from .home_assistant import HomeAssistantMqtt
from .sticky import is_reset_command, try_clear_sticky_instruction, try_set_sticky_instruction
from .storage import (
    _safe_profile_id,
    append_history,
    create_profile,
    delete_profile,
    ensure_runtime_dirs,
    get_active_profile_id,
    list_profiles,
    load_profile,
    load_profile_by_id,
    read_recent_history,
    reset_history,
    save_profile_by_id,
    set_active_profile,
)
from .tts import (
    describe_selected_speaker,
    describe_tts_voice,
    get_xtts_device,
    list_output_devices_compact,
    play_audio_file,
    play_alert_sound,
    should_play_audio_after_synthesis,
    speak_text,
)
from .web_search import (
    extract_web_query_from_request,
    fetch_web_context,
    should_auto_search,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PATH = Path(__file__).resolve().parent.parent / "data" / "logo.ico"
WINDOW_TITLE = "NekoSuneAI Studio"
WINDOWS_APP_ID = "NekoSuneProjects.NekoSuneAI.Studio"
_window: "webview.Window | None" = None


def _pulse_audio_status() -> dict[str, Any]:
    """Return host PipeWire/Pulse devices visible through the mounted socket."""
    status: dict[str, Any] = {"available": False, "sources": [], "sinks": []}
    try:
        info = subprocess.run(
            ["pactl", "info"], capture_output=True, text=True, timeout=4, check=True
        ).stdout
        values = {}
        for line in info.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                values[key.strip()] = value.strip()
        status.update({
            "available": True,
            "server": values.get("Server Name", "PulseAudio/PipeWire"),
            "default_source": values.get("Default Source", ""),
            "default_sink": values.get("Default Sink", ""),
        })
        for kind, target in (("sources", "sources"), ("sinks", "sinks")):
            output = subprocess.run(
                ["pactl", "list", "short", kind],
                capture_output=True, text=True, timeout=4, check=True,
            ).stdout
            status[target] = [
                fields[1] for line in output.splitlines()
                if len(fields := line.split("\t")) > 1
            ]
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        status["error"] = str(exc)
    return status

# Per-driver game settings shown in the Game panel (instead of editing .env).
# Each field maps to a Config attribute; values are persisted to app_state.
GAME_SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "vrchat": {
        "label": "VRChat (OSC)",
        "preview": False,
        "fields": [
            {"key": "vrchat_osc_host", "label": "OSC host", "type": "text"},
            {"key": "vrchat_osc_port", "label": "OSC send port", "type": "int"},
            {"key": "vrchat_osc_read_port", "label": "OSC listen port (avatar params)", "type": "int"},
            {"key": "vrchat_log_dir", "label": "VRChat log dir (blank = auto-detect)", "type": "text"},
            {"key": "vision_model", "label": "Vision model (optional)", "type": "text"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
}
_GAME_FIELD_TYPES: dict[str, str] = {
    f["key"]: f["type"] for meta in GAME_SETTINGS_SCHEMA.values() for f in meta["fields"]
}


# General app settings shown in the Settings panel (override .env, persisted).
# "model" fields render with an auto-detected dropdown for their category.
APP_SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "llm": {
        "label": "AI Provider & Models",
        "fields": [
            {"key": "llm_provider", "label": "Provider", "type": "select",
             "options": ["ollama", "openai", "claude-code", "codex", "cli"]},
            {"key": "model", "label": "Chat model", "type": "model", "category": "chat"},
            {"key": "vision_model", "label": "Vision model", "type": "model", "category": "vision"},
            {"key": "rag_embedding_provider", "label": "Embedding provider", "type": "select",
             "options": ["local", "ollama", "openai"]},
            {"key": "rag_embedding_model", "label": "Embedding model", "type": "model", "category": "embedding"},
            {"key": "llm_api_url", "label": "API URL (openai/LiteLLM)", "type": "text"},
            {"key": "llm_api_key", "label": "API key", "type": "password"},
            {"key": "temperature", "label": "Temperature", "type": "float"},
        ],
    },
    "voice": {
        "label": "Voice (TTS)",
        "fields": [
            {"key": "tts_provider", "label": "TTS engine", "type": "select", "options": ["bridge", "xtts", "gtts"]},
            {"key": "xtts_speaker", "label": "XTTS speaker", "type": "text"},
            {"key": "xtts_speaker_wav", "label": "Voice clone .wav (optional)", "type": "text"},
            {"key": "xtts_speed", "label": "Speed", "type": "float"},
            {"key": "tts_language", "label": "Language", "type": "text"},
            {"key": "tts_auto_language", "label": "Auto language per reply (speak each line in its own language)", "type": "bool"},
            {"key": "rvc_chat_enabled", "label": "Convert chat voice through RVC", "type": "bool"},
            {"key": "rvc_chat_model_path", "label": "RVC model .pth (chat voice)", "type": "text"},
            {"key": "rvc_chat_pitch", "label": "Pitch (semitones, +/-)", "type": "float"},
            {"key": "rvc_chat_index_rate", "label": "Index rate", "type": "float"},
            {"key": "rvc_chat_protect", "label": "Protect (consonant clarity)", "type": "float"},
        ],
    },
    "stt": {
        "label": "Speech-to-Text",
        "fields": [
            {"key": "stt_provider", "label": "STT engine", "type": "select",
             "options": ["bridge", "faster-whisper", "google"]},
            {"key": "stt_model", "label": "Whisper model", "type": "select",
             "options": ["tiny.en", "base.en", "small.en", "medium.en", "large-v3", "distil-large-v3"]},
            {"key": "stt_language", "label": "Language (Whisper base code, e.g. en)", "type": "text"},
            {"key": "stt_pause_threshold_seconds", "label": "Stop recording after silence (seconds)", "type": "float"},
            {"key": "stt_phrase_time_limit_seconds", "label": "Maximum command length (seconds)", "type": "float"},
            {"key": "stt_energy_threshold", "label": "Microphone speech threshold", "type": "int"},
            {"key": "stt_dynamic_energy_threshold", "label": "Automatically adapt to room noise", "type": "bool"},
        ],
    },
    "web": {
        "label": "Web Search",
        "fields": [
            {"key": "web_search_provider", "label": "Provider", "type": "select",
             "options": ["searxng", "duckduckgo", "gateway"]},
            {"key": "web_search_url", "label": "URL (SearXNG endpoint, or gateway base URL)", "type": "text"},
            {"key": "web_search_gateway_provider", "label": "Gateway backend (e.g. searxng-search)", "type": "text"},
            {"key": "web_search_api_key", "label": "Gateway API key", "type": "password"},
            {"key": "web_max_results", "label": "Max results", "type": "int"},
            {"key": "web_timeout_seconds", "label": "Timeout (sec)", "type": "int"},
            {"key": "web_region", "label": "Region (e.g. us-en)", "type": "text"},
            {"key": "web_safesearch", "label": "SafeSearch", "type": "select",
             "options": ["off", "moderate", "strict"]},
        ],
    },
    "mcp": {
        "label": "Remote MCP & NekoAI Bridge",
        "fields": [
            {"key": "mcp_enabled", "label": "Enable MCP tools", "type": "bool"},
            {"key": "mcp_auto_route", "label": "Automatically use tools for weather, aircraft and alerts", "type": "bool"},
            {"key": "mcp_servers_json", "label": "MCP servers (JSON; supports API key or OAuth)", "type": "textarea"},
            {"key": "mcp_timeout_seconds", "label": "MCP timeout (sec)", "type": "float"},
            {"key": "bridge_ws_url", "label": "NekoAI Bridge voice WebSocket URL", "type": "text"},
            {"key": "bridge_auth_token", "label": "Bridge voice bearer token (nai_...)", "type": "password"},
            {"key": "bridge_user_id", "label": "Bridge quota/user ID", "type": "text"},
            {"key": "bridge_tts_voice", "label": "Remote voice (Edge example: en-GB-SoniaNeural)", "type": "text"},
            {"key": "bridge_tts_engine", "label": "Remote TTS engine", "type": "select", "options": ["edge-stream", "piper"]},
            {"key": "bridge_tts_rate", "label": "Fast TTS speech rate (e.g. +10%)", "type": "text"},
        ],
    },
    "alerts": {
        "label": "Weather, Monitor & Emergency Alerts",
        "fields": [
            {"key": "warning_sound_path", "label": "Warning sound file", "type": "text"},
            {"key": "danger_sound_path", "label": "Danger sound file", "type": "text"},
            {"key": "emergency_broadcast_tts", "label": "Read government emergency broadcasts aloud", "type": "bool"},
            {"key": "monitor_tts_enabled", "label": "Read scheduled monitor updates aloud", "type": "bool"},
        ],
    },
    "bluetooth": {
        "label": "Alexa Bluetooth Output",
        "fields": [
            {"key": "bluetooth_reconnect_enabled", "label": "Automatically reconnect Alexa Bluetooth", "type": "bool"},
            {"key": "bluetooth_speaker_address", "label": "Alexa Bluetooth address (AA:BB:CC:DD:EE:FF)", "type": "text"},
            {"key": "bluetooth_reconnect_interval_seconds", "label": "Bluetooth reconnect check (seconds)", "type": "float"},
        ],
    },
    "home": {
        "label": "Wake Word & Home Assistant",
        "fields": [
            {"key": "wake_word_enabled", "label": "Enable local wake word", "type": "bool"},
            {"key": "wake_word_model", "label": "Wake-word model/name", "type": "text"},
            {"key": "wake_word_framework", "label": "Inference backend", "type": "select",
             "options": ["onnx", "tflite"]},
            {"key": "wake_word_threshold", "label": "Detection threshold", "type": "float"},
            {"key": "wake_word_confirmation_frames", "label": "Matching audio frames required", "type": "int"},
            {"key": "wake_word_cooldown_seconds", "label": "Cooldown after each command (seconds)", "type": "float"},
            {"key": "wake_word_sound_enabled", "label": "Play acknowledgement sound after wake word", "type": "bool"},
            {"key": "wake_word_sound_path", "label": "Wake acknowledgement sound file", "type": "text"},
            {"key": "home_assistant_mqtt_host", "label": "Home Assistant MQTT host", "type": "text"},
            {"key": "home_assistant_mqtt_port", "label": "MQTT port", "type": "int"},
            {"key": "home_assistant_mqtt_username", "label": "MQTT username", "type": "text"},
            {"key": "home_assistant_mqtt_password", "label": "MQTT password", "type": "password"},
        ],
    },
    "rag": {
        "label": "Memory (RAG)",
        "fields": [
            {"key": "rag_enabled", "label": "Remember facts across sessions", "type": "bool"},
            {"key": "rag_top_k", "label": "Memories recalled per reply", "type": "int"},
            {"key": "rag_min_score", "label": "Minimum relevance score", "type": "float"},
        ],
    },
    "media": {
        "label": "Media",
        "fields": [
            {"key": "music_provider_default", "label": "Music provider", "type": "select",
             "options": ["soundcloud", "deezer", "spotify"]},
            {"key": "soundcloud_stream_endpoint", "label": "Stream endpoint", "type": "text"},
            {"key": "thinking_sound_enabled", "label": "Play a sound during long waits", "type": "bool"},
            {"key": "thinking_sound_path", "label": "Thinking sound file or folder (random pick)", "type": "text"},
            {"key": "thinking_sound_delay_seconds", "label": "Delay before it plays (sec)", "type": "float"},
        ],
    },
    "singing": {
        "label": "Singing",
        "fields": [
            {"key": "singing_enabled", "label": "Enable singing", "type": "bool"},
            {"key": "singing_backend", "label": "Backend", "type": "select",
             "options": ["local", "rvc", "cloud"]},
            {"key": "rvc_model_path", "label": "RVC model .pth (rvc)", "type": "text"},
            {"key": "singing_api_url", "label": "Singing API URL (cloud)", "type": "text"},
            {"key": "singing_api_key", "label": "Singing API key (cloud)", "type": "password"},
        ],
    },
    "vrchat_friends": {
        "label": "VRChat Friends (opt-in, unofficial API — ToS risk, use a throwaway account)",
        "fields": [
            {"key": "vrchat_friends_enabled", "label": "Enable", "type": "bool"},
            {"key": "vrchat_username", "label": "VRChat username", "type": "text"},
            {"key": "vrchat_password", "label": "VRChat password", "type": "password"},
            {"key": "vrchat_totp_secret", "label": "TOTP 2FA secret (authenticator app only)", "type": "password"},
        ],
    },
}
_APP_FIELD_TYPES: dict[str, str] = {
    f["key"]: f["type"] for meta in APP_SETTINGS_SCHEMA.values() for f in meta["fields"]
}


def _coerce_game_setting(value: Any, ftype: str) -> Any:
    if ftype == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if ftype == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if ftype == "list":
        items = value if isinstance(value, (list, tuple)) else str(value).split(",")
        return tuple(str(s).strip() for s in items if str(s).strip())
    return str(value).strip()


class Api:
    """Python backend exposed to JavaScript via pywebview.api."""

    def __init__(self) -> None:
        # Bare minimum so the window can open instantly with the loading screen.
        # Heavy work (config, DB, profiles) is deferred to initialize().
        self.config: Config | None = None
        self.active_profile_id: str = ""
        self.profile: dict = {}
        self.state = SessionState(voice_enabled=False, input_mode="text")
        self.session_started = False
        self.hands_free_enabled = False
        self.mic_muted = False
        self.media_enabled = True   # music playback feature toggle
        self.busy = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._initialized = False
        self.memory: MemoryStore | None = None
        # Game agent
        self.game_agent: Any = None
        self.game_driver_key: str | None = None  # the actually-running driver
        # Watch & React — periodically glance at the screen and react in-character.
        self._watch_enabled = False
        self._watch_thread: threading.Thread | None = None
        # VRChat friends system — opt-in, separate from the OSC game driver.
        self._vrchat_friends: Any = None
        self.monitor_manager: MonitorManager | None = None
        self.wake_word: WakeWordListener | None = None
        self._wake_activation_lock = threading.Lock()
        self.home_assistant: HomeAssistantMqtt | None = None
        self.bluetooth_watchdog: Any = None
        self._web_events: list[dict[str, Any]] = []
        self._web_events_lock = threading.Lock()

    def initialize(self) -> dict[str, Any]:
        """Heavy init — called from JS once the loading screen is visible."""
        if self._initialized:
            return self.get_state()
        ensure_runtime_dirs()
        self.config = Config.from_env()
        self._apply_saved_app_settings()
        self._apply_saved_game_settings()
        self.memory = MemoryStore(self.config)
        self.active_profile_id = get_active_profile_id()
        self.profile = load_profile() or {}
        self.state = SessionState(
            voice_enabled=False,
            input_mode=self.config.input_mode,
        )
        self.config.voice_enabled = False
        self.hands_free_enabled = self.config.input_mode == "voice"
        # Restore the Voice & Input + Media toggles saved last session.
        self._apply_saved_ui_prefs()
        self._initialized = True
        self.monitor_manager = MonitorManager(self.config, self._monitor_notification)
        self.monitor_manager.start()
        self.wake_word = WakeWordListener(self.config, self._wake_detected)
        self.wake_word.start()
        self.home_assistant = HomeAssistantMqtt(self.config, self._home_assistant_command)
        self.home_assistant.start()
        from .bluetooth_watchdog import BluetoothSpeakerWatchdog
        self.bluetooth_watchdog = BluetoothSpeakerWatchdog(self.config, self._push_notification)
        self.bluetooth_watchdog.start()
        # Update window title with the loaded companion name
        global _window
        if _window:
            name = self.profile.get("companion_name", "NekoSuneAI")
            try:
                _window.set_title(f"{name} Studio")
            except Exception:
                pass
        return self.get_state()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _not_ready(self) -> dict[str, Any] | None:
        """Return an error dict if initialize() hasn't run yet, else None."""
        if not self._initialized:
            return {"ok": False, "msg": "Still loading, please wait..."}
        return None

    def _js(self, code: str) -> None:
        """Push JavaScript to the pywebview window."""
        global _window
        if _window:
            try:
                _window.evaluate_js(code)
            except Exception:
                pass

    def _push_state(self) -> None:
        self._queue_web_event({"type": "state", "value": self.get_state()})
        self._js(f"window.__onStateUpdate({json.dumps(self.get_state())})")

    def _push_chat(self, author: str, text: str, role: str) -> None:
        self._queue_web_event({"type": "chat", "value": {"author": author, "text": text, "role": role}})
        payload = json.dumps({"author": author, "text": text, "role": role})
        self._js(f"window.__onChatMessage({payload})")

    def _push_status(self, msg: str) -> None:
        self._queue_web_event({"type": "status", "value": msg})
        if self.home_assistant: self.home_assistant.publish_state(msg)
        safe = json.dumps(msg)
        self._js(f"window.__onStatusUpdate({safe})")

    def _push_notification(self, msg: str) -> None:
        self._queue_web_event({"type": "notification", "value": msg})
        safe = json.dumps(msg)
        self._js(f"window.__onNotification({safe})")

    def _queue_web_event(self, event: dict[str, Any]) -> None:
        with self._web_events_lock:
            self._web_events.append(event)
            if len(self._web_events) > 200: del self._web_events[:-200]

    def get_web_events(self) -> list[dict[str, Any]]:
        with self._web_events_lock:
            events, self._web_events = self._web_events, []
        return events

    def _wake_detected(self) -> None:
        # A noisy microphone or speaker echo can produce more than one model
        # hit for a single phrase. Only one activation may own the command
        # lifecycle at a time.
        if not self._wake_activation_lock.acquire(blocking=False):
            return
        try:
            if self.busy or self.mic_muted:
                return
            self._push_notification(f"Wake word detected: {self.config.wake_word_model}")
            if self.config.wake_word_sound_enabled:
                self._play_wake_sound()
            if not self.session_started:
                self.start_session()
            if not self.mic_muted and not self.busy:
                self.start_listen()
        finally:
            self._wake_activation_lock.release()

    def _wake_word_gates_commands(self) -> bool:
        """True when every voice command must begin with the wake phrase."""
        return bool(self.config and self.config.wake_word_enabled and self.wake_word)

    def _play_wake_sound(self) -> tuple[bool, str]:
        try:
            from .paths import AUDIO_DIR
            wake_path = Path(self.config.wake_word_sound_path or (AUDIO_DIR / "wake.wav"))
            if not wake_path.is_file():
                return False, f"Wake sound was not found: {wake_path}"
            play_audio_file(wake_path, self.config.speaker_device_index)
            return True, "Wake acknowledgement sound played."
        except Exception as exc:
            self._push_status(f"Wake sound error: {exc}")
            return False, f"Wake sound failed: {exc}"

    def test_wake_word_sound(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        ok, message = self._play_wake_sound()
        return {"ok": ok, "msg": message}

    def _home_assistant_command(self, text: str) -> None:
        if text == "WAKE": self._wake_detected(); return
        if not self.session_started: self.start_session()
        self.send_message(text)

    def get_wake_word_status(self) -> dict[str, Any]:
        return self.wake_word.status() if self.wake_word else {"enabled": False, "running": False}

    def start_mcp_oauth(self, redirect_uri: str) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        try:
            from .mcp_client import begin_oauth, load_servers
            servers = load_servers(self.config)
            if not servers:
                return {"ok": False, "msg": "Add the MCP server URL and save it first."}
            return {"ok": True, "authorization_url": begin_oauth(self.config, servers[0].name, redirect_uri)}
        except Exception as exc:
            return {"ok": False, "msg": f"Could not start OAuth: {exc}"}

    def complete_mcp_oauth(self, state: str, code: str) -> dict[str, Any]:
        try:
            from .mcp_client import complete_oauth
            complete_oauth(self.config, state, code)
            return {"ok": True, "msg": "NekoAI Bridge OAuth connected."}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def _monitor_notification(self, msg: str, level: str = "none") -> None:
        """Deliver background monitor updates into chat and the toast layer."""
        self._push_chat("Monitor", msg, "system")
        self._push_notification(msg)
        if not self.config:
            return
        if level != "none":
            try:
                play_alert_sound(level, self.config)
            except Exception:
                pass
        should_speak = self.config.monitor_tts_enabled or (
            self.config.emergency_broadcast_tts and msg.startswith("Government emergency broadcast")
        )
        if should_speak:
            # Run synthesis after any alarm cue on the monitor thread. Ordinary
            # aircraft and weather updates are spoken too when monitor TTS is on.
            self._speak(msg, "scared" if level == "danger" else "serious")

    # ── state ─────────────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "session_started": self.session_started,
            "voice_enabled": self.state.voice_enabled,
            "hands_free": self.hands_free_enabled,
            "mic_muted": self.mic_muted,
            "web_search": cfg.web_browsing_enabled if cfg else False,
            "web_auto_search": cfg.web_auto_search if cfg else False,
            "media_enabled": self.media_enabled,
            "busy": self.busy,
            "model": cfg.model if cfg else "--",
            "llm_provider": cfg.llm_provider if cfg else "--",
            "performance_profile": cfg.performance_profile if cfg else "--",
            "system_summary": cfg.system_summary if cfg else "--",
            "tts_provider": cfg.tts_provider if cfg else "--",
            "stt_provider": cfg.stt_provider if cfg else "--",
            "stt_model": cfg.stt_model if cfg else "--",
            "web_search_provider": cfg.web_search_provider if cfg else "--",
            "web_search_url": cfg.web_search_url if cfg else "--",
            "companion_name": self.profile.get("companion_name", "NekoSuneAI"),
            "user_name": self.profile.get("user_name", "Friend"),
            "description": self.profile.get("description", ""),
            "input_mode": "voice" if self.hands_free_enabled else "text",
            "active_profile_id": self.active_profile_id,
            "initialized": self._initialized,
        }

    # ── session controls ──────────────────────────────────────────────────────

    def start_session(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if self.session_started:
            return {"ok": False, "msg": "Session is already running."}
        self.session_started = True
        self._push_state()
        self._push_chat("System", "Session started. You can now chat and use voice controls.", "system")
        if self.hands_free_enabled and not self.mic_muted and not self._wake_word_gates_commands():
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"ok": True, "msg": "Session started."}

    def end_session(self) -> dict[str, Any]:
        if not self.session_started:
            return {"ok": False, "msg": "No session running."}
        if self.busy:
            self._stop_event.set()
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
        self.session_started = False
        self._push_state()
        self._push_chat("System", "Session ended.", "system")
        return {"ok": True, "msg": "Session ended."}

    def toggle_voice(self) -> dict[str, Any]:
        self.state.voice_enabled = not self.state.voice_enabled
        self._save_ui_pref("voice_enabled", self.state.voice_enabled)
        self._push_state()
        return {"voice_enabled": self.state.voice_enabled}

    def toggle_handsfree(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.hands_free_enabled = not self.hands_free_enabled
        self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        self._save_ui_pref("hands_free", self.hands_free_enabled)
        self._push_state()
        if self.hands_free_enabled and not self.busy and not self.mic_muted and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"hands_free": self.hands_free_enabled}

    def toggle_mic(self) -> dict[str, Any]:
        self.mic_muted = not self.mic_muted
        self._save_ui_pref("mic_muted", self.mic_muted)
        self._push_state()
        if not self.mic_muted and self.hands_free_enabled and not self.busy and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"mic_muted": self.mic_muted}

    def toggle_web_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_browsing_enabled = not self.config.web_browsing_enabled
        self._save_ui_pref("web_search", self.config.web_browsing_enabled)
        self._push_state()
        return {"web_search": self.config.web_browsing_enabled}

    def toggle_media(self) -> dict[str, Any]:
        self.media_enabled = not self.media_enabled
        self._save_ui_pref("media_enabled", self.media_enabled)
        self._push_state()
        return {"media_enabled": self.media_enabled}

    def toggle_auto_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_auto_search = not self.config.web_auto_search
        self._save_ui_pref("web_auto_search", self.config.web_auto_search)
        self._push_state()
        return {"web_auto_search": self.config.web_auto_search}

    # ── chat ──────────────────────────────────────────────────────────────────

    def send_message(self, text: str) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not text or not text.strip():
            return {"ok": False, "msg": "Empty message."}
        if not self.session_started:
            return {"ok": False, "msg": "Start a session first."}
        text = text.strip()
        if text.startswith("/"):
            return self._handle_command(text)
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        try:
            result = self._pipeline(text, from_voice=False)
            return {"ok": True, "msg": result}
        except Exception as exc:
            # Safety net: _pipeline handles the known failure points itself, but
            # anything that slips through here would otherwise vanish silently
            # into the JS console (pywebview swallows it, the frontend only
            # console.errors) with no sign anything went wrong in the chat UI.
            error_msg = f"[Companion error] {exc}"
            self._push_chat("System", error_msg, "system")
            return {"ok": False, "msg": error_msg}
        finally:
            self._release()


    def stop_generation(self) -> dict[str, Any]:
        """Interrupt the current pipeline (LLM / TTS / playback)."""
        if not self.busy:
            return {"ok": False, "msg": "Nothing to stop."}
        self._stop_event.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        return {"ok": True}

    def start_listen(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not self.session_started:
            return {"ok": False, "msg": "Start a session first."}
        if self.mic_muted:
            return {"ok": False, "msg": "Microphone is muted."}
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        if self.wake_word:
            self.wake_word.pause()
        try:
            self._push_status("Listening...")
            self._push_state()
            result = recognize_speech(self.config, self.state, announce=False)
            if result.status == "timeout":
                self._push_status("No speech detected.")
                return {"ok": False, "msg": "No speech detected."}
            if result.status == "unknown":
                self._push_status("Could not transcribe clearly.")
                return {"ok": False, "msg": "Could not transcribe clearly."}
            if result.status != "ok":
                msg = result.error or "Speech recognition failed."
                self._push_status(msg)
                return {"ok": False, "msg": msg}
            text = result.text.strip()
            if not text:
                self._push_status("No speech detected.")
                return {"ok": False, "msg": "No speech detected."}
            status = self._pipeline(text, from_voice=True)
            return {"ok": True, "msg": status, "text": text}
        except Exception as exc:
            msg = f"Audio error: {exc}"
            self._push_status(msg)
            return {"ok": False, "msg": msg}
        finally:
            if self.wake_word:
                self.wake_word.resume()
            self._release()
            # Re-arm hands-free listening no matter how the turn ended — normal
            # reply, early-handled request, timeout, or a backend error. Without
            # this, any failure mid-turn silently ends the conversation and
            # NekoSuneAI stops responding to speech after the first prompt.
            if (
                self.hands_free_enabled
                and not self.mic_muted
                and self.session_started
                and not self._stopped()
                and not self._wake_word_gates_commands()
            ):
                threading.Thread(target=self._auto_listen, daemon=True).start()

    def _auto_listen(self) -> None:
        time.sleep(0.3)
        if self.busy or self.mic_muted or not self.session_started or not self.hands_free_enabled:
            return
        self.start_listen()

    def _handle_command(self, cmd: str) -> dict[str, Any]:
        lower = cmd.strip().lower()
        if lower in {"/listen", "/ask", "/voiceask"}:
            return self.start_listen()
        if lower == "/reset":
            return self.clear_history()
        if lower == "/voice":
            return self.toggle_voice()
        self._push_chat("System", f"Unknown command: {cmd}", "system")
        return {"ok": False, "msg": f"Unknown command: {cmd}"}

    # ── pipeline (runs in api thread) ─────────────────────────────────────────

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    def _pipeline(self, user_text: str, from_voice: bool) -> str:
        self._stop_event.clear()
        user_name = self.profile.get("user_name", "You")
        companion = self.profile.get("companion_name", "NekoSuneAI")

        self._push_chat(user_name, user_text, "user")
        self._push_status("Thinking...")

        if self.monitor_manager:
            monitor_reply = self.monitor_manager.handle(user_text)
            if monitor_reply is not None:
                append_history("user", user_text)
                append_history("assistant", monitor_reply)
                self._push_chat(companion, monitor_reply, "assistant")
                self._push_status("Ready.")
                if self.state.voice_enabled and not self._stopped():
                    # Monitor setup/list/stop confirmations should never hold
                    # the global Busy lock while a remote speaker or Bridge TTS
                    # connection recovers.
                    self._speak_async(monitor_reply, "neutral")
                return monitor_reply

        # Sticky wake-instructions + reset/clear — checked before anything else
        # so they always short-circuit with a quick acknowledgement rather than
        # a full LLM turn.
        sticky_reply: str | None = None
        if is_reset_command(user_text):
            self.state.sticky_instruction = None
            if self.memory and self.config.rag_enabled:
                try:
                    self.memory.wipe(self.active_profile_id)
                except Exception:
                    pass
            sticky_reply = "Memory reset — back to a blank slate."
        elif try_clear_sticky_instruction(user_text):
            self.state.sticky_instruction = None
            sticky_reply = "Cleared — back to normal."
        elif try_set_sticky_instruction(user_text, self.profile, self.state):
            sticky_reply = "Got it — I'll stick to that until you say stop."

        if sticky_reply is not None:
            append_history("user", user_text)
            append_history("assistant", sticky_reply)
            self._push_chat(companion, sticky_reply, "assistant")
            if self.state.voice_enabled and not self._stopped():
                self._speak(sticky_reply, "neutral")
            self._push_status("Ready.")
            return sticky_reply

        # Media (music) — only when the feature is enabled.
        try:
            media_action = handle_media_request(user_text, self.profile, self.config) if self.media_enabled else None
        except Exception as exc:
            error_msg = f"[Media error] {exc}"
            self._push_chat("System", error_msg, "system")
            self._push_status("Ready.")
            return error_msg
        if media_action and media_action.handled:
            self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            append_history("user", user_text)
            append_history("assistant", media_action.response)
            self._push_chat(companion, media_action.response, "assistant")
            self._push_status("Media request handled.")
            return "Media request handled."

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        # Game command — if a game agent is running, route in-game orders to it
        # (combat, build, mine, follow, etc.) instead of just chatting about them.
        game_reply = self._maybe_handle_game_command(user_text)
        if game_reply is not None:
            append_history("user", user_text)
            append_history("assistant", game_reply)
            self._push_chat(companion, game_reply, "assistant")
            if self.state.voice_enabled and not self._stopped():
                self._speak(game_reply, "neutral")
            self._push_status("Ready.")
            return "Game command handled."

        # Web context
        web_context: str | None = None
        if self.config.web_browsing_enabled:
            web_query = self.state.pending_web_query
            if self.state.pending_web_context:
                web_context = self.state.pending_web_context
                self.state.pending_web_context = None
                self.state.pending_web_query = None
            else:
                if not web_query:
                    inferred = extract_web_query_from_request(user_text)
                    if inferred:
                        web_query = inferred
                        self._push_chat("System", f"Searching: {web_query}", "system")
                if not web_query and self.config.web_auto_search and should_auto_search(user_text):
                    web_query = user_text
                if web_query and not self._stopped():
                    try:
                        bundle = fetch_web_context(web_query, self.config)
                        web_context = bundle.context
                        self._push_chat("System", f"Web: {bundle.result_count} results for: {bundle.query}", "system")
                    except RuntimeError as exc:
                        self._push_chat("System", f"Web search skipped: {exc}", "system")
                    finally:
                        self.state.pending_web_query = None

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        self._push_status("Generating reply...")
        thinking_timer = start_thinking_sound(self.config)
        try:
            result = generate_reply(
                GenerationRequest(
                    user_text=user_text,
                    profile=self.profile,
                    config=self.config,
                    source="chat",
                    web_context=web_context,
                    extra_system=self._game_awareness() + self._recall(user_text) + self._sticky_system(),
                )
            )
        except Exception as exc:
            error_msg = f"[Companion error] {exc}"
            self._push_chat("System", error_msg, "system")
            self._push_status("Ready.")
            return error_msg
        finally:
            stop_thinking_sound(thinking_timer)
        reply = result.reply

        if result.alert_level != "none" and not self._stopped():
            try:
                play_alert_sound(result.alert_level, self.config)
            except Exception:
                pass

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        append_history("user", user_text)
        append_history("assistant", reply)
        self._push_chat(companion, reply, "assistant")
        self._remember_exchange(user_name, user_text, reply, source="chat")

        if self.state.voice_enabled and not self._stopped():
            self._push_status("Speaking...")
            self._speak(reply, result.emotion)

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        # Hands-free re-listen is re-armed by start_listen()'s finally block so
        # it fires on every exit path (including errors), not just here.
        if from_voice and self.hands_free_enabled and not self.mic_muted and not self._wake_word_gates_commands():
            self._push_status("Listening...")
            return "Hands-free listening."

        self._push_status("Ready.")
        return "Ready."

    # ── busy guard ────────────────────────────────────────────────────────────

    def _acquire(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
        self._push_state()
        return True

    def _release(self) -> None:
        with self._lock:
            self.busy = False
        self._push_state()

    def _sticky_system(self) -> list[str]:
        if not self.state.sticky_instruction:
            return []
        return [f"Standing rule from the user, follow it until they cancel it: {self.state.sticky_instruction}"]

    # ── memory (RAG) ────────────────────────────────────────────────────────────

    def _recall(self, query: str) -> list[str]:
        if not self.memory or not self.config or not self.config.rag_enabled:
            return []
        try:
            memories = self.memory.recall(query, self.active_profile_id)
        except Exception:
            return []
        if not memories:
            return []
        joined = "; ".join(memories)
        return [f"Relevant things you remember: {joined}"]

    def _remember_exchange(
        self, speaker: str, user_text: str, reply: str, source: str
    ) -> None:
        if not self.memory or not self.config or not self.config.rag_enabled:
            return
        try:
            self.memory.remember(
                self.active_profile_id,
                content=user_text,
                source=source,
                speaker=speaker,
            )
        except Exception:
            pass

    def get_memories(self) -> list[dict[str, Any]]:
        if not self.memory:
            return []
        try:
            return self.memory.list_recent(self.active_profile_id)
        except Exception:
            return []

    def reinforce_memory(self, memory_id: int, delta: float) -> dict[str, Any]:
        if not self.memory:
            return {"ok": False, "msg": "Memory not ready."}
        try:
            self.memory.reinforce(int(memory_id), float(delta))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def forget_memory(self, memory_id: int) -> dict[str, Any]:
        if not self.memory:
            return {"ok": False, "msg": "Memory not ready."}
        try:
            self.memory.forget(int(memory_id))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def clear_all_memories(self) -> dict[str, Any]:
        if not self.memory:
            return {"ok": False, "msg": "Memory not ready."}
        count = self.memory.wipe(self.active_profile_id)
        return {"ok": True, "msg": f"Deleted {count} memories for this profile.", "count": count}

    def get_scheduled_monitors(self) -> list[dict[str, Any]]:
        return self.monitor_manager.list_all() if self.monitor_manager else []

    def remove_scheduled_monitor(self, monitor_id: str) -> dict[str, Any]:
        if not self.monitor_manager:
            return {"ok": False, "msg": "Monitor manager is not ready."}
        removed = self.monitor_manager.remove(monitor_id)
        return {"ok": removed, "msg": f"Removed monitor {monitor_id}." if removed else f"Monitor {monitor_id} was not found."}

    def clear_scheduled_monitors(self) -> dict[str, Any]:
        if not self.monitor_manager:
            return {"ok": False, "msg": "Monitor manager is not ready."}
        count = self.monitor_manager.clear()
        return {"ok": True, "msg": f"Removed all {count} scheduled monitor(s).", "count": count}

    # ── voice output ────────────────────────────────────────────────────────────

    def _speak(self, text: str, emotion: str = "neutral") -> bool:
        """Speak text via TTS."""
        try:
            audio_path = speak_text(text, self.config, self.state)
            if should_play_audio_after_synthesis(self.config) and not self._stopped():
                play_audio_file(audio_path, self.config.speaker_device_index)
            return True
        except Exception as exc:
            self._push_status(f"TTS error: {exc}")
            self._push_notification(f"TTS error: {exc}")
            return False

    def _speak_async(self, text: str, emotion: str = "neutral") -> None:
        """Speak without keeping an API request or the dashboard Busy lock open."""
        threading.Thread(
            target=self._speak,
            args=(text, emotion),
            daemon=True,
            name="neko-background-tts",
        ).start()

    def test_tts_output(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        if not self._acquire():
            return {"ok": False, "msg": "NekoSuneAI is busy. Try the audio test again in a moment."}
        try:
            ok = self._speak("NekoSuneAI audio test. Your Alexa speaker output is connected.", "happy")
            return {"ok": ok, "msg": "TTS test sent to the selected output." if ok else "TTS test failed. See the status message for the exact error."}
        finally:
            self._release()

    def reconnect_bluetooth_speaker(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        if not self.bluetooth_watchdog:
            return {"ok": False, "msg": "Bluetooth watchdog is not ready."}
        ok, message = self.bluetooth_watchdog.reconnect_now()
        self._push_notification(message)
        return {"ok": ok, "msg": message}

    # ── game agent ────────────────────────────────────────────────────────────

    def _game_narrate(self, text: str, emotion: str = "neutral") -> None:
        companion = self.profile.get("companion_name", "NekoSuneAI")
        self._push_chat(companion, text, "assistant")
        # Mirror the thought to the game bridge's Live View dashboard.
        drv = getattr(self.game_agent, "driver", None) if self.game_agent else None
        if drv is not None and hasattr(drv, "push_thought"):
            try:
                drv.push_thought(text)
            except Exception:
                pass
        # Speak only when not busy with a chat/stream turn (don't block them).
        if self.state.voice_enabled:
            if self._acquire():
                try:
                    self._speak(text, emotion)
                finally:
                    self._release()

    def _game_update(self, raw: dict[str, Any]) -> None:
        try:
            self._js(f"window.__onGameUpdate({json.dumps(raw)})")
        except Exception:
            pass

    def _game_remember(self, content: str) -> None:
        if self.memory and self.config and self.config.rag_enabled:
            try:
                self.memory.remember(self.active_profile_id, content, source="game", speaker="game")
            except Exception:
                pass

    def _game_running(self) -> bool:
        return bool(self.game_agent and self.game_agent.is_running())

    def _game_awareness(self) -> list[str]:
        """Tell the chat persona it currently controls an in-game body."""
        if not self._game_running():
            return []
        driver = getattr(self.game_agent, "driver", None)
        game = getattr(driver, "name", "a game")
        return [
            f"You are RIGHT NOW controlling a character in {game} — you CAN move, "
            "fight, mine, build, eat, and act in the world through your game body. "
            "Never say you have no controls or can't fight/move. If the user tells you "
            "to do something in-game (fight back, defend, build, mine, follow, come, "
            "etc.), confirm you're doing it; the action is carried out by your game agent."
        ]

    # Phrases that mean "do this with your in-game body".
    _COMBAT_TRIGGERS = (
        "under attack", "being attacked", "attacked by", "attacking you", "attacking us",
        "fight back", "hit them", "hit him", "hit her", "hit back", "smack",
        "defend", "protect me", "protect us", "kill them", "kill him", "kill her",
        "punch", "they're hitting", "stop them", "fend them", "fight them",
    )
    _COMMAND_TRIGGERS = (
        "build", "mine", "dig", "chop", "gather", "farm", "plant", "harvest",
        "follow me", "come here", "come to me", "bring me", "find", "explore",
        "craft", "smelt", "cook", "fish", "hunt", "breed", "store", "go to",
        "make a", "make me", "place", "trade", "sleep", "equip", "collect", "kill",
        "attack",
    )

    def _maybe_handle_game_command(self, user_text: str) -> str | None:
        if not self._game_running():
            return None
        lower = f" {user_text.lower().strip()} "
        # Punish a named player -> punch them (pass the literal order so the agent
        # punches the right target).
        if "smack" in lower or "punch" in lower:
            self.game_agent.set_goal(user_text.strip())
            return f"On it — {user_text.strip()} 😤"
        if any(k in lower for k in self._COMBAT_TRIGGERS):
            self.game_agent.set_goal(
                "You are under attack by a player or mob. FIGHT BACK now: equip your "
                "best weapon and armor, then use the 'retaliate' verb to hit the "
                "attacker (nearest non-owner player, else hostiles) repeatedly until "
                "they stop. Eat to heal if low, and stay alive. Keep retaliating."
            )
            return "On it — fighting back! Equipping a weapon and hitting them until they stop."
        if any(k in lower for k in self._COMMAND_TRIGGERS):
            self.game_agent.set_goal(user_text.strip())
            return f"Got it — doing that in-game now: {user_text.strip()}"
        return None

    # ── general settings (Settings panel) ───────────────────────────────────────

    def _ollama_base(self) -> str:
        url = (self.config.llm_api_url if self.config else "") or ""
        # OLLAMA_API_URL env wins for the local daemon base.
        env_url = os.environ.get("OLLAMA_API_URL", "")
        for candidate in (env_url, url, "http://127.0.0.1:11434/api/chat"):
            if candidate and "/api/" in candidate:
                return candidate.split("/api/")[0].rstrip("/")
        return "http://127.0.0.1:11434"

    def _reresolve_llm_url(self) -> None:
        """Recompute llm_api_url after a provider/url change."""
        from .config import resolve_llm_api_url

        provider = self.config.llm_provider
        if provider == "ollama":
            raw = os.environ.get("OLLAMA_API_URL") or "http://127.0.0.1:11434/api/chat"
        elif provider == "openai":
            raw = self.config.llm_api_url or os.environ.get("OPENAI_API_URL")
        else:
            raw = None
        self.config.llm_api_url = resolve_llm_api_url(provider, raw)

    # ── persisted UI prefs (voice/input toggles + media) ──────────────────────────

    def _ui_prefs(self) -> dict[str, Any]:
        from . import database
        try:
            return json.loads(database.get_state("ui_prefs", "{}") or "{}")
        except Exception:
            return {}

    def _save_ui_pref(self, key: str, value: Any) -> None:
        from . import database
        try:
            prefs = self._ui_prefs()
            prefs[key] = value
            database.set_state("ui_prefs", json.dumps(prefs))
        except Exception:
            pass

    def _apply_saved_ui_prefs(self) -> None:
        """Restore the Voice & Input toggles + Media toggle from last session."""
        prefs = self._ui_prefs()
        if "voice_enabled" in prefs:
            self.state.voice_enabled = bool(prefs["voice_enabled"])
            if self.config:
                self.config.voice_enabled = self.state.voice_enabled
        if "hands_free" in prefs:
            self.hands_free_enabled = bool(prefs["hands_free"])
            if self.config:
                self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        if "mic_muted" in prefs:
            self.mic_muted = bool(prefs["mic_muted"])
        if self.config and "web_search" in prefs:
            self.config.web_browsing_enabled = bool(prefs["web_search"])
        if self.config and "web_auto_search" in prefs:
            self.config.web_auto_search = bool(prefs["web_auto_search"])
        if "media_enabled" in prefs:
            self.media_enabled = bool(prefs["media_enabled"])

    def _apply_saved_app_settings(self) -> None:
        if not self.config:
            return
        try:
            from . import database

            store = json.loads(database.get_state("app_settings", "{}") or "{}")
        except Exception:
            return
        for key, val in store.items():
            ftype = _APP_FIELD_TYPES.get(key)
            if ftype is not None:
                try:
                    setattr(self.config, key, _coerce_game_setting(val, ftype))
                except Exception:
                    pass
        self._reresolve_llm_url()

    def restart_app(self) -> dict[str, Any]:
        """Relaunch NekoSuneAI (applies any settings/code changes cleanly)."""
        def _do_restart() -> None:
            time.sleep(0.4)
            self._watch_enabled = False
            if self._vrchat_friends is not None:
                try:
                    self._vrchat_friends.stop()
                except Exception:
                    pass
            # Stop the game agent cleanly so ports free up before relaunch.
            try:
                if self.game_agent:
                    self.game_agent.stop()
            except Exception:
                pass
            try:
                cwd = str(Path(__file__).resolve().parent.parent)
                subprocess.Popen([sys.executable] + sys.argv, cwd=cwd)
            except Exception:
                pass
            os._exit(0)

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"ok": True, "msg": "Restarting NekoSuneAI..."}

    def get_app_settings(self) -> dict[str, Any]:
        sections: dict[str, Any] = {}
        for name, meta in APP_SETTINGS_SCHEMA.items():
            fields = []
            for f in meta["fields"]:
                val = getattr(self.config, f["key"], "") if self.config else ""
                if val is None:
                    val = ""
                fields.append({**f, "value": val})
            sections[name] = {"label": meta["label"], "fields": fields}
        return {"sections": sections}

    def save_app_settings(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        meta = APP_SETTINGS_SCHEMA.get(section)
        if not meta:
            return {"ok": False, "msg": f"Unknown section: {section}"}
        applied: dict[str, Any] = {}
        for f in meta["fields"]:
            if f["key"] in (values or {}):
                coerced = _coerce_game_setting(values[f["key"]], f["type"])
                setattr(self.config, f["key"], coerced)
                applied[f["key"]] = list(coerced) if isinstance(coerced, tuple) else coerced
        if section == "llm":
            self._reresolve_llm_url()
            if self.memory:
                self.memory.config = self.config  # pick up new embedding settings
        if section == "bluetooth" and self.bluetooth_watchdog:
            self.bluetooth_watchdog.start()
        try:
            from . import database

            store = json.loads(database.get_state("app_settings", "{}") or "{}")
            store.update(applied)
            database.set_state("app_settings", json.dumps(store))
        except Exception:
            pass
        self._push_state()
        return {"ok": True, "msg": "Settings saved."}

    # ── model auto-detect ───────────────────────────────────────────────────────

    _VISION_HINTS = ("llava", "moondream", "vision", "bakllava", "minicpm-v",
                     "qwen2-vl", "qwen2.5vl", "janus", "llama3.2-vision")
    _EMBED_HINTS = ("embed", "bge-", "bge:", "nomic-embed", "all-minilm", "minilm",
                    "gte-", "e5-", "mxbai-embed", "snowflake-arctic-embed", "embeddinggemma")

    @classmethod
    def _categorize_model(cls, name: str) -> str:
        ln = name.lower()
        if any(h in ln for h in cls._EMBED_HINTS) or "embedding" in ln:
            return "embedding"
        if any(h in ln for h in cls._VISION_HINTS):
            return "vision"
        return "chat"

    def _ollama_tags(self) -> list[str]:
        try:
            resp = requests.get(self._ollama_base() + "/api/tags", timeout=5)
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
        except Exception:
            return []

    def _openai_models(self) -> list[str]:
        """List models from the configured OpenAI-compatible / LiteLLM endpoint.

        Works whenever an API URL is set (e.g. a LiteLLM gateway), independent of
        the active provider, so the dropdowns can always show what's available.
        """
        if not self.config:
            return []
        raw = (
            os.environ.get("LLM_API_URL")
            or os.environ.get("OPENAI_API_URL")
            or (self.config.llm_api_url if self.config.llm_provider == "openai" else "")
        )
        if not raw or not raw.startswith("http"):
            return []
        base = raw.split("/chat/completions")[0].rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
        headers = {}
        key = self.config.llm_api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data if isinstance(data, list) else [])
            return [m.get("id", "") for m in items if isinstance(m, dict) and m.get("id")]
        except Exception:
            return []

    def get_models(self) -> dict[str, Any]:
        """Auto-detect available models live, grouped chat/vision/embedding.

        Always queries the API(s) fresh so newly-added models show up: the local
        Ollama daemon AND any configured OpenAI/LiteLLM gateway.
        """
        buckets: dict[str, set] = {"chat": set(), "vision": set(), "embedding": set()}
        for name in self._ollama_tags():
            buckets[self._categorize_model(name)].add(name)
        for name in self._openai_models():          # LiteLLM/OpenAI, if URL set
            buckets[self._categorize_model(name)].add(name)
        provider = self.config.llm_provider if self.config else "ollama"
        if provider == "claude-code":
            buckets["chat"].update(["sonnet", "opus", "haiku"])
        elif provider == "codex":
            buckets["chat"].update(["gpt-5-codex", "gpt-5", "o4-mini"])
        return {
            "provider": provider,
            "chat": sorted(buckets["chat"]),
            "vision": sorted(buckets["vision"]),
            "embedding": sorted(buckets["embedding"]),
        }

    def _apply_saved_game_settings(self) -> None:
        """Apply game settings saved from the panel (override .env)."""
        if not self.config:
            return
        try:
            from . import database

            store = json.loads(database.get_state("game_settings", "{}") or "{}")
        except Exception:
            return
        for key, val in store.items():
            ftype = _GAME_FIELD_TYPES.get(key)
            if ftype is not None:
                try:
                    setattr(self.config, key, _coerce_game_setting(val, ftype))
                except Exception:
                    pass

    def get_game_settings(self) -> dict[str, Any]:
        drivers: dict[str, Any] = {}
        for drv, meta in GAME_SETTINGS_SCHEMA.items():
            fields = []
            for f in meta["fields"]:
                val = getattr(self.config, f["key"], "") if self.config else ""
                if f["type"] == "list":
                    val = ", ".join(val) if isinstance(val, (list, tuple)) else (val or "")
                if val is None:
                    val = ""
                fields.append({**f, "value": val})
            drivers[drv] = {"label": meta["label"], "preview": meta["preview"], "fields": fields}
        return {
            "drivers": drivers,
            "current": "vrchat",
        }

    def save_game_settings(self, driver: str, values: dict[str, Any]) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        meta = GAME_SETTINGS_SCHEMA.get(driver)
        if not meta:
            return {"ok": False, "msg": f"Unknown driver: {driver}"}
        applied: dict[str, Any] = {}
        for f in meta["fields"]:
            if f["key"] in (values or {}):
                coerced = _coerce_game_setting(values[f["key"]], f["type"])
                setattr(self.config, f["key"], coerced)
                applied[f["key"]] = list(coerced) if isinstance(coerced, tuple) else coerced
        try:
            from . import database

            store = json.loads(database.get_state("game_settings", "{}") or "{}")
            store.update(applied)
            store["game_driver"] = driver
            database.set_state("game_settings", json.dumps(store))
        except Exception:
            pass
        return {"ok": True, "msg": "Game settings saved."}

    def get_game_status(self) -> dict[str, Any]:
        running = bool(self.game_agent and self.game_agent.is_running())
        viewer_url = ""
        # Report the actually-running driver when there is one, else the only
        # supported driver (VRChat).
        driver = getattr(self, "game_driver_key", None) or "vrchat"
        if running and self.game_agent is not None:
            drv = getattr(self.game_agent, "driver", None)
            if drv is not None and hasattr(drv, "viewer_url"):
                try:
                    viewer_url = drv.viewer_url()
                except Exception:
                    viewer_url = ""
        return {
            "running": running,
            "driver": driver,
            "goal": self.game_agent.goal if self.game_agent else "",
            "viewer_url": viewer_url,
        }

    def open_game_view(self) -> dict[str, Any]:
        status = self.get_game_status()
        url = status.get("viewer_url")
        if not url:
            return {"ok": False, "msg": "Live view is not available for this game."}
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
        return {"ok": True, "url": url}

    def _build_game_driver(self, driver_name: str):
        if driver_name == "vrchat":
            from .games.vrchat import VRChatDriver

            return VRChatDriver(self.config)
        return None

    def start_game(self, goal: str = "", driver: str = "") -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        driver_name = (driver or "vrchat").strip().lower()
        # If a game is already running, stop it first so switching drivers works
        # (otherwise the old game just keeps running).
        if self.game_agent and self.game_agent.is_running():
            if getattr(self, "game_driver_key", None) == driver_name:
                return {"ok": False, "msg": f"{driver_name} is already running."}
            self.stop_game()
            time.sleep(0.5)
        try:
            from .games.agent import GameAgent

            game_driver = self._build_game_driver(driver_name)
            if game_driver is None:
                return {"ok": False, "msg": f"Unknown game driver: {driver_name}"}
            # Remember + persist the chosen driver so status/UI reflect reality.
            self.game_driver_key = driver_name
            try:
                from . import database

                store = json.loads(database.get_state("game_settings", "{}") or "{}")
                store["game_driver"] = driver_name
                database.set_state("game_settings", json.dumps(store))
            except Exception:
                pass

            default_goal = "explore and survive"
            if hasattr(game_driver, "default_goal"):
                try:
                    default_goal = game_driver.default_goal()
                except Exception:
                    pass
            self.game_agent = GameAgent(
                driver=game_driver,
                config=self.config,
                profile_getter=lambda: self.profile,
                narrate=self._game_narrate,
                on_update=self._game_update,
                remember=self._game_remember,
                tick_seconds=self.config.game_tick_seconds,
                goal=(goal.strip() or default_goal),
            )
            self.game_agent.start()
            return {"ok": True, "msg": "Game agent started."}
        except Exception as exc:
            self.game_agent = None
            return {"ok": False, "msg": str(exc)}

    def stop_game(self) -> dict[str, Any]:
        agent = self.game_agent
        # Drop the reference first so status flips to stopped immediately; the
        # daemon thread unwinds on its own (stop() also aborts the bridge).
        self.game_agent = None
        self.game_driver_key = None
        if agent:
            try:
                agent.stop()
            except Exception:
                pass
        return {"ok": True, "msg": "Game agent stopped."}

    def set_game_goal(self, goal: str) -> dict[str, Any]:
        if not self.game_agent:
            return {"ok": False, "msg": "Game agent is not running."}
        self.game_agent.set_goal(goal)
        return {"ok": True}

    # ── watch & react (look at the screen and comment) ───────────────────────────

    _WATCH_DEFAULTS = {"interval_seconds": 20, "speak": True}

    def _watch_settings(self) -> dict[str, Any]:
        from . import database
        try:
            saved = json.loads(database.get_state("watch_react", "{}") or "{}")
        except Exception:
            saved = {}
        return {**self._WATCH_DEFAULTS, **(saved if isinstance(saved, dict) else {})}

    def _save_watch_settings(self, store: dict[str, Any]) -> None:
        from . import database
        try:
            database.set_state("watch_react", json.dumps(store))
        except Exception:
            pass

    def get_watch_react_status(self) -> dict[str, Any]:
        from . import vision
        return {
            "running": self._watch_enabled,
            "vision_ready": vision.vision_available(self.config) if self.config else False,
            **self._watch_settings(),
        }

    def start_watch_react(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        from . import vision
        if not vision.vision_available(self.config):
            return {"ok": False, "msg": (
                "No vision model configured. Set a Vision model in Settings → AI Provider "
                "(e.g. an Ollama model like 'llava' / 'qwen2.5vl' / 'moondream')."
            )}
        if self._watch_enabled:
            return {"ok": True, "msg": "Already watching."}
        self._watch_enabled = True
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True, name="NekoSuneAIWatchReact")
        self._watch_thread.start()
        self._push_chat("System", "👁️ Watch & React on — I'll glance at the screen and react.", "system")
        return {"ok": True, "msg": "Watching the screen."}

    def stop_watch_react(self) -> dict[str, Any]:
        self._watch_enabled = False
        self._push_chat("System", "Watch & React off.", "system")
        return {"ok": True}

    def save_watch_react_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        store = self._watch_settings()
        if "interval_seconds" in (values or {}):
            try:
                store["interval_seconds"] = max(5, int(float(values["interval_seconds"])))
            except (TypeError, ValueError):
                pass
        for key in ("speak",):
            if key in (values or {}):
                raw = values[key]
                store[key] = bool(raw) if isinstance(raw, bool) else str(raw).lower() in {"1", "true", "yes", "on"}
        self._save_watch_settings(store)
        return {"ok": True, "msg": "Saved.", "settings": store}

    def _watch_loop(self) -> None:
        from . import vision
        from .games import screen

        while self._watch_enabled:
            s = self._watch_settings()
            interval = max(5, int(s.get("interval_seconds", 20)))
            waited = 0.0
            while self._watch_enabled and waited < interval:
                time.sleep(0.5)
                waited += 0.5
            if not self._watch_enabled:
                break
            if self.busy:
                continue  # don't talk over a chat/stream/game turn
            try:
                png = screen.capture_png()
                if not png:
                    continue
                desc = vision.describe_image(
                    self.config, png,
                    "Briefly describe what's on screen right now: the game/app/video, what's "
                    "happening, and anything notable. One or two sentences.",
                )
                if not desc:
                    continue
                if not self._acquire():
                    continue
                try:
                    framing = (
                        "You're watching this on your own livestream right now. React in ONE "
                        "short, in-character sentence to what's on screen — give your take, don't "
                        "just narrate. Don't say you can't see."
                    )
                    result = generate_reply(
                        GenerationRequest(
                            user_text=f"[What's on screen now]: {desc}",
                            profile=self.profile,
                            config=self.config,
                            source="chat",
                            extra_system=[framing],
                        )
                    )
                    reply = result.reply
                    companion = self.profile.get("companion_name", "NekoSuneAI")
                    self._push_chat(companion, reply, "assistant")
                    if self.state.voice_enabled and s.get("speak", True):
                        self._speak(reply, result.emotion)
                finally:
                    self._release()
            except Exception:
                pass

    # ── VRChat friends system (opt-in, credential-gated) ─────────────────────────

    def _vrchat_friends_event(self, message: str) -> None:
        """on_event callback for VRChatFriendsService — narrate like the game/watch
        features do: push to chat, and speak it if voice is on and we're free."""
        self._push_chat("System", message, "system")
        if self.state.voice_enabled and not self.busy:
            try:
                self._speak(message, "neutral")
            except Exception:
                pass

    def get_vrchat_friends_status(self) -> dict[str, Any]:
        return {
            "running": bool(self._vrchat_friends and self._vrchat_friends.is_running()),
            "enabled": bool(self.config and self.config.vrchat_friends_enabled),
            "has_credentials": bool(
                self.config and self.config.vrchat_username and self.config.vrchat_password
            ),
        }

    def start_vrchat_friends(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        from .games.vrchat_friends import VRChatFriendsService

        if self._vrchat_friends is None:
            self._vrchat_friends = VRChatFriendsService(self.config, self._vrchat_friends_event)
        if self._vrchat_friends.is_running():
            return {"ok": True, "msg": "Already running."}
        try:
            self._vrchat_friends.start()
        except RuntimeError as exc:
            return {"ok": False, "msg": str(exc)}
        self._push_chat(
            "System",
            "VRChat friends system on — logging in and watching for friend activity.",
            "system",
        )
        return {"ok": True, "msg": "Starting."}

    def stop_vrchat_friends(self) -> dict[str, Any]:
        if self._vrchat_friends is not None:
            self._vrchat_friends.stop()
        self._push_chat("System", "VRChat friends system off.", "system")
        return {"ok": True}

    # ── singing ─────────────────────────────────────────────────────────────────

    def get_singing_status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.singing_enabled) if self.config else False,
            "backend": self.config.singing_backend if self.config else "cloud",
        }

    def sing(self, lyrics: str, melody_ref: str = "") -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        if not self.config.singing_enabled:
            return {"ok": False, "msg": "Singing is disabled. Set SINGING_ENABLED=true in .env."}
        if not lyrics or not lyrics.strip():
            return {"ok": False, "msg": "Give me some lyrics to sing."}

        def _job() -> None:
            if not self._acquire():
                return
            try:
                from .singing import make_singing_engine

                self._push_status("Composing a song...")
                engine = make_singing_engine(self.config)
                path = engine.sing(lyrics.strip(), melody_ref.strip() or None)
                self._push_status("Singing...")
                play_audio_file(path, self.config.speaker_device_index)
            except Exception as exc:
                self._push_chat("System", f"Singing failed: {exc}", "system")
            finally:
                self._release()
                self._push_status("Ready.")

        threading.Thread(target=_job, daemon=True).start()
        return {"ok": True, "msg": "Singing..."}

    # ── profiles ──────────────────────────────────────────────────────────────

    def get_profiles(self) -> list[dict[str, Any]]:
        return list_profiles()

    def switch_profile(self, profile_id: str) -> dict[str, Any]:
        try:
            self.profile = set_active_profile(profile_id)
            self.active_profile_id = profile_id
            self._push_state()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def create_new_profile(self, name: str) -> dict[str, Any]:
        try:
            p = create_profile(name)
            return {"ok": True, "profile_id": p["profile_id"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def clone_profile(self, source_id: str, name: str) -> dict[str, Any]:
        try:
            src = load_profile_by_id(source_id)
            p = create_profile(name, base_profile=src)
            return {"ok": True, "profile_id": p["profile_id"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def delete_profile_item(self, profile_id: str) -> dict[str, Any]:
        try:
            new_active = delete_profile(profile_id)
            if self.active_profile_id == profile_id:
                self.active_profile_id = new_active
                self.profile = load_profile_by_id(new_active)
                self._push_state()
            return {"ok": True, "new_active": new_active}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def export_profile(self, profile_id: str) -> dict[str, Any]:
        """Return a profile wrapped in a portable envelope for download.

        The frontend turns this into a .json file the user can move to another
        machine (e.g. local PC -> Raspberry Pi) and import there.
        """
        try:
            profile = load_profile_by_id(profile_id)
            name = str(profile.get("profile_name", profile_id)) or profile_id
            safe = _safe_profile_id(name)
            return {
                "ok": True,
                "filename": f"{safe}.nekosuneai-profile.json",
                "data": {
                    "nekosuneai_profile_export": True,
                    "version": 1,
                    "profile": profile,
                },
            }
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def import_profile(self, data: Any, name: str = "") -> dict[str, Any]:
        """Create a new profile from imported JSON (envelope or raw profile).

        Accepts either the export envelope produced by ``export_profile`` or a
        bare profile dict. The imported profile always becomes a NEW profile
        (its id is de-duplicated), so importing never overwrites an existing one.
        """
        try:
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                return {"ok": False, "msg": "Invalid profile file."}
            src = data.get("profile") if isinstance(data.get("profile"), dict) else data
            if not isinstance(src, dict) or not src:
                return {"ok": False, "msg": "Invalid profile file."}
            profile_name = (
                str(name).strip()
                or str(src.get("profile_name", "")).strip()
                or str(src.get("companion_name", "")).strip()
                or "Imported Profile"
            )
            p = create_profile(profile_name, base_profile=src)
            return {"ok": True, "profile_id": p["profile_id"], "profile_name": p["profile_name"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def get_profile_detail(self, profile_id: str) -> dict[str, Any]:
        try:
            return load_profile_by_id(profile_id)
        except Exception:
            return {}

    def save_profile_detail(self, profile_id: str, data: dict) -> dict[str, Any]:
        try:
            save_profile_by_id(profile_id, data)
            if profile_id == self.active_profile_id:
                self.profile = load_profile_by_id(profile_id)
                self._push_state()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── settings / devices ────────────────────────────────────────────────────

    def get_audio_devices(self) -> dict[str, Any]:
        if not self._initialized:
            return {"mics": [], "speakers": [], "current_mic": None, "current_speaker": None}
        errors: list[str] = []
        try:
            mics = list_input_devices_compact()
        except Exception as exc:
            mics = []
            errors.append(f"Microphone discovery: {exc}")
        try:
            speakers = list_output_devices_compact()
        except Exception as exc:
            speakers = []
            errors.append(f"Speaker discovery: {exc}")
        pulse = _pulse_audio_status()
        if not pulse.get("available"):
            errors.append(
                "Host Bluetooth audio is unavailable. Check PUID/PGID, "
                "XDG_RUNTIME_DIR, and the mounted PulseAudio/PipeWire socket."
            )
        return {
            "mics": mics,
            "speakers": speakers,
            "current_mic": self.config.mic_device_index,
            "current_speaker": self.config.speaker_device_index,
            "pulse": pulse,
            "errors": errors,
        }

    def apply_audio_devices(self, mic_index: Any, speaker_index: Any) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.mic_device_index = int(mic_index) if mic_index is not None else None
        self.config.speaker_device_index = int(speaker_index) if speaker_index is not None else None
        self.state.mic_calibrated = False
        self.state.speech_recognizer = None
        self.state.speech_recognizer_signature = None
        return {"ok": True, "msg": "Audio devices applied."}

    def recalibrate_mic(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        if self.wake_word:
            self.wake_word.pause()
        try:
            self._push_status("Calibrating microphone...")
            self.state.speech_recognizer = None
            self.state.speech_recognizer_signature = None
            self.state.mic_calibrated = False
            recalibrate_microphone(self.config, self.state, announce=False)
            self._push_status("Calibration complete.")
            return {"ok": True, "msg": "Microphone calibrated."}
        except Exception as exc:
            self._push_status(f"Calibration failed: {exc}")
            return {"ok": False, "msg": str(exc)}
        finally:
            if self.wake_word:
                self.wake_word.resume()
            self._release()

    def get_performance_info(self) -> list[str]:
        if not self._initialized:
            return ["Still loading..."]
        lines = [
            f"Model: {self.config.model}",
            f"Provider: {self.config.llm_provider}",
            f"Performance profile: {self.config.performance_profile}",
            f"System: {self.config.system_summary}",
            "",
        ] + list(self.config.performance_notes)
        return lines

    # ── history ───────────────────────────────────────────────────────────────

    def get_recent_history(self) -> list[dict[str, str]]:
        try:
            entries = read_recent_history(50)
            result = []
            for entry in entries:
                role = entry.get("role", "system")
                text = entry.get("content", "")
                if role == "user":
                    author = self.profile.get("user_name", "You")
                elif role == "assistant":
                    author = self.profile.get("companion_name", "NekoSuneAI")
                else:
                    author = "System"
                result.append({"author": author, "text": text, "role": role})
            return result
        except Exception:
            return []

    def clear_history(self) -> dict[str, Any]:
        reset_history()
        self._push_status("Chat history cleared.")
        return {"ok": True, "msg": "History cleared."}


def _set_windows_app_id() -> None:
    """Set the Windows taskbar app identity before the GUI window is created."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:
        pass


def _set_window_icon() -> None:
    """Set the taskbar and title-bar icon on Windows via Win32 API."""
    if sys.platform != "win32" or not ICON_PATH.exists():
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        IMAGE_ICON = 1

        icon_path = str(ICON_PATH)
        h_small = user32.LoadImageW(0, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        h_big = user32.LoadImageW(
            0,
            icon_path,
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )

        for _ in range(20):
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                if h_small:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
                if h_big:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
                return
            time.sleep(0.25)
    except Exception:
        pass


def main() -> None:
    global _window
    if webview is None:
        raise SystemExit(
            "The desktop GUI needs pywebview, which isn't installed.\n"
            "Install it with:  pip install -r requirements-gui.txt\n"
            "Or run the terminal chat loop instead:  python app.py"
        )
    _set_windows_app_id()

    api = Api()
    html_path = STATIC_DIR / "index.html"

    def _on_loaded():
        threading.Thread(target=_set_window_icon, daemon=True).start()

    _window = webview.create_window(
        title=WINDOW_TITLE,
        url=str(html_path),
        js_api=api,
        width=1340,
        height=860,
        min_size=(960, 600),
        background_color="#0f0f14",
        text_select=True,
    )
    _window.events.loaded += _on_loaded
    webview.start(debug=False)
