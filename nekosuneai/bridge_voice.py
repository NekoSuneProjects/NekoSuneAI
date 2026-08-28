"""Remote TTS/STT adapter for nekoai-bridge's authenticated WebSocket."""
from __future__ import annotations

import base64
import json
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


def _request(config: Config, payload: dict[str, Any], on_audio=None) -> dict[str, Any]:
    if not config.bridge_ws_url:
        raise RuntimeError("Set BRIDGE_WS_URL (for example wss://bridge.example/ws).")
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is required for remote bridge voice.") from exc
    request_id = str(uuid.uuid4())
    payload = {**payload, "requestId": request_id, "discordUserId": config.bridge_user_id}
    ws = websocket.create_connection(
        config.bridge_ws_url,
        header=[f"Authorization: Bearer {_bridge_token(config)}"],
        timeout=_voice_timeout(config),
    )
    try:
        ws.send(json.dumps(payload))
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
    finally:
        ws.close()


_LAST_STREAM_PLAYED = False


def stream_was_played() -> bool:
    return _LAST_STREAM_PLAYED


def synthesize(text: str, config: Config) -> Path:
    global _LAST_STREAM_PLAYED
    _LAST_STREAM_PLAYED = False
    fast = config.bridge_tts_engine in {"edge", "edge-stream", "fast", "stream"}
    output_path = AUDIO_DIR / ("latest_reply_remote.mp3" if fast else "latest_reply_remote.wav")
    chunks: list[bytes] = []
    ffplay = shutil.which("ffplay") if fast else None
    player = None
    if ffplay:
        player = subprocess.Popen([ffplay, "-nodisp", "-autoexit", "-loglevel", "error", "-i", "pipe:0"], stdin=subprocess.PIPE)

    def receive_audio(chunk: bytes) -> None:
        nonlocal player
        chunks.append(chunk)
        if player and player.stdin:
            try: player.stdin.write(chunk); player.stdin.flush()
            except (BrokenPipeError, OSError): player = None

    payload = {"type": "tts-stream" if fast else "tts", "text": text,
        "language": config.tts_language, "voice": config.bridge_tts_voice,
        "rate": config.bridge_tts_rate, "provider": "piper"}
    try:
        result = _request(config, payload, on_audio=receive_audio if fast else None)
    except RuntimeError as exc:
        # Older Bridge deployments predate tts-stream. Fall back to their fast
        # gTTS route instead of leaving voice completely silent while the Bridge
        # image is being upgraded.
        if not fast or 'Unsupported payload type "tts-stream"' not in str(exc):
            raise
        if player and player.stdin:
            player.stdin.close()
            try:
                player.wait(timeout=3)
            except subprocess.TimeoutExpired:
                player.kill()
        player = None
        chunks.clear()
        fast = False
        result = _request(config, {**payload, "type": "tts", "provider": "gtts"})
    if fast:
        output_path.write_bytes(b"".join(chunks))
        if player and player.stdin:
            player.stdin.close(); player.wait(timeout=max(10, _voice_timeout(config)))
            _LAST_STREAM_PLAYED = True
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
    result = _request(config, {"type": "transcribe", "language": config.stt_language,
        "files": [{"name": "speech.wav", "contentType": "audio/wav", "size": len(wav_bytes),
                   "contentBase64": base64.b64encode(wav_bytes).decode("ascii")} ]})
    return str(result.get("text", "")).strip(), config.stt_language
