"""Remote TTS/STT adapter for nekoai-bridge's authenticated WebSocket."""
from __future__ import annotations

import base64
import json
import os
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Config
from .mcp_client import load_servers
from .paths import AUDIO_DIR


def _voice_timeout(config: Config) -> float:
    """Voice must never inherit a multi-minute LLM generation timeout."""
    return max(5.0, min(30.0, float(getattr(config, "mcp_timeout_seconds", 30.0))))


def _stream_route_unavailable(error: Exception) -> bool:
    """Identify deployment/version problems that can safely use Piper."""
    message = str(error).lower()
    return (
        'unsupported payload type "tts-stream"' in message
        or ("cannot find package" in message and "edge-tts-universal" in message)
        or ("cannot find module" in message and "edge-tts" in message)
    )


def _bridge_token(config: Config) -> str:
    if config.bridge_auth_token:
        return config.bridge_auth_token
    for server in load_servers(config):
        if server.bearer_token:
            return server.bearer_token
    raise RuntimeError(
        "Remote Bridge voice needs BRIDGE_AUTH_TOKEN (your nai_ Bridge User token). "
        "OAuth only authenticates the MCP tools."
    )


def _request(
    config: Config,
    payload: dict[str, Any],
    on_audio=None,
    timeout: float | None = None,
) -> dict[str, Any]:
    if not config.bridge_ws_url:
        raise RuntimeError("Set BRIDGE_WS_URL (for example wss://bridge.example/ws).")
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is required for remote bridge voice.") from exc
    request_id = str(uuid.uuid4())
    payload = {**payload, "requestId": request_id, "discordUserId": config.bridge_user_id}
    request_timeout = timeout if timeout is not None else _voice_timeout(config)
    try:
        ws = websocket.create_connection(
            config.bridge_ws_url,
            header=[f"Authorization: Bearer {_bridge_token(config)}"],
            timeout=request_timeout,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to the Bridge voice service at {config.bridge_ws_url}. {exc}"
        ) from exc
    try:
        ws.send(json.dumps(payload))
        try:
            while True:
                result = json.loads(ws.recv())
                if result.get("requestId") not in {None, request_id}:
                    continue
                if result.get("type") == "error":
                    raise RuntimeError(result.get("message", "Bridge voice request failed."))
                if result.get("type") == "audio-chunk" and on_audio:
                    on_audio(base64.b64decode(result["contentBase64"]))
                    continue
                if result.get("type") == "done":
                    return result
        except RuntimeError:
            raise
        except Exception as exc:
            operation = "Whisper transcription" if payload.get("type") == "transcribe" else "voice request"
            raise RuntimeError(
                f"Bridge {operation} timed out after {request_timeout:g} seconds. "
                "The remote voice service may still be loading its model."
            ) from exc
    finally:
        ws.close()


_LAST_STREAM_PLAYED = False
_ACTIVE_STREAM_PLAYER: subprocess.Popen | None = None


def stream_was_played() -> bool:
    return _LAST_STREAM_PLAYED


def stop_stream_playback() -> bool:
    """Terminate currently streaming Bridge TTS, if any."""
    global _ACTIVE_STREAM_PLAYER
    player=_ACTIVE_STREAM_PLAYER
    _ACTIVE_STREAM_PLAYER=None
    if player is None:return False
    try:
        player.kill();player.wait(timeout=3)
    except Exception:
        pass
    return True


def _ffplay_environment(platform_name: str | None = None) -> dict[str, str]:
    """Prefer the host desktop audio session when ffplay runs in Docker."""
    env = os.environ.copy()
    if (platform_name or os.name) == "nt" or env.get("SDL_AUDIODRIVER"):
        return env

    runtime_dir = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    pulse_server = env.get("PULSE_SERVER", "")
    if pulse_server or (runtime_dir / "pulse" / "native").exists():
        env["SDL_AUDIODRIVER"] = "pulseaudio"
    elif (runtime_dir / env.get("PIPEWIRE_REMOTE", "pipewire-0")).exists():
        env["SDL_AUDIODRIVER"] = "pipewire"
    return env


def _finish_stream_player(player: subprocess.Popen | None, *, timeout: float) -> bool:
    """Close/wait for ffplay and return True only when it really succeeded."""
    global _ACTIVE_STREAM_PLAYER
    if player is None:
        return False
    if player.stdin and not player.stdin.closed:
        try:
            player.stdin.close()
        except OSError:
            pass
    try:
        return player.wait(timeout=timeout) == 0
    except subprocess.TimeoutExpired:
        player.kill()
        try:
            player.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        return False
    finally:
        if _ACTIVE_STREAM_PLAYER is player:_ACTIVE_STREAM_PLAYER=None


def synthesize(text: str, config: Config) -> Path:
    global _LAST_STREAM_PLAYED, _ACTIVE_STREAM_PLAYER
    _LAST_STREAM_PLAYED = False
    fast = config.bridge_tts_engine in {"edge", "edge-stream", "fast", "stream"}
    output_path = AUDIO_DIR / ("latest_reply_remote.mp3" if fast else "latest_reply_remote.wav")
    chunks: list[bytes] = []
    ffplay = shutil.which("ffplay") if fast else None
    player: subprocess.Popen | None = None
    player_broken = False
    if ffplay:
        player = subprocess.Popen(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", "-i", "pipe:0"],
            stdin=subprocess.PIPE,
            env=_ffplay_environment(),
        )
        _ACTIVE_STREAM_PLAYER=player

    def receive_audio(chunk: bytes) -> None:
        nonlocal player_broken
        chunks.append(chunk)
        if player and player.stdin and not player_broken:
            try:
                player.stdin.write(chunk)
                player.stdin.flush()
            except (BrokenPipeError, OSError):
                player_broken = True

    payload = {
        "type": "tts-stream" if fast else "tts",
        "text": text,
        "language": config.tts_language,
        "voice": config.bridge_tts_voice,
        "rate": config.bridge_tts_rate,
        "provider": "piper",
    }
    try:
        result = _request(config, payload, on_audio=receive_audio if fast else None)
    except RuntimeError as exc:
        # Older Bridge deployments predate tts-stream. Fall back to their
        # built-in Piper route instead of requiring the optional Python gTTS
        # package. Do not pass the Edge voice name to Piper: the Bridge will use
        # its configured default Piper voice.
        if not fast or not _stream_route_unavailable(exc):
            _finish_stream_player(player, timeout=3)
            raise
        _finish_stream_player(player, timeout=3)
        player = None
        player_broken = False
        chunks.clear()
        fast = False
        fallback_payload = {
            key: value for key, value in payload.items() if key not in {"voice", "rate"}
        }
        result = _request(
            config,
            {**fallback_payload, "type": "tts", "provider": "piper"},
        )

    if fast:
        output_path.write_bytes(b"".join(chunks))
        played_ok = _finish_stream_player(
            player,
            timeout=max(10, _voice_timeout(config)),
        )
        # This flag controls whether tts.py skips its normal file playback.
        # Never claim success just because ffplay existed: if PipeWire/Pulse was
        # unreachable, let the caller retry the saved file through its fallback.
        _LAST_STREAM_PLAYED = bool(played_ok and not player_broken)
        return output_path

    files = result.get("files") or []
    if not files:
        raise RuntimeError("Bridge TTS returned no audio file.")
    item = files[0]
    suffix = ".mp3" if "mpeg" in str(item.get("contentType", "")) else ".wav"
    output_path = AUDIO_DIR / f"latest_reply_remote{suffix}"
    output_path.write_bytes(base64.b64decode(item["contentBase64"]))
    return output_path


def transcribe(wav_bytes: bytes, config: Config) -> tuple[str, str]:
    """Transcribe a WAV payload through the remote Bridge."""
    from .audio_input import normalize_stt_language_for_whisper

    whisper_language = normalize_stt_language_for_whisper(config.stt_language)
    result = _request(
        config,
        {
            "type": "transcribe",
            "language": whisper_language,
            "files": [
                {
                    "name": "speech.wav",
                    "contentType": "audio/wav",
                    "size": len(wav_bytes),
                    "contentBase64": base64.b64encode(wav_bytes).decode("ascii"),
                }
            ],
        },
        timeout=float(getattr(config, "bridge_stt_timeout_seconds", 90.0)),
    )
    detected = str(result.get("language") or whisper_language or "").strip()
    return str(result.get("text", "")).strip(), detected
