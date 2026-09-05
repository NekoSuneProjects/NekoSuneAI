import base64
import io
import sys
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nekosuneai.node_media import NodeMediaService, decode_media, read_pcm_wav


def wav_data(channels=1, seconds=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * channels * 16000 * seconds)
    return output.getvalue()


def test_wav_validation():
    pcm, rate = read_pcm_wav(wav_data())
    assert rate == 16000 and len(pcm) == 32000
    for raw in (wav_data(2), wav_data(seconds=16), wav_data()[:-2], b"bad"):
        with pytest.raises(ValueError):
            read_pcm_wav(raw)


@pytest.mark.parametrize("value", ["!", "", "YWJjZA==", None])
def test_bounded_base64(value):
    with pytest.raises(ValueError):
        decode_media(value, 3)


def test_tts_returns_audio_without_mutating_server_configuration(tmp_path, monkeypatch):
    path = tmp_path / "voice.wav"
    path.write_bytes(wav_data())
    synth = Mock(return_value=path)
    monkeypatch.setitem(sys.modules, "nekosuneai.tts", SimpleNamespace(speak_text=synth))
    api = SimpleNamespace(config=SimpleNamespace(xtts_stream_output=True), state=object(),
                          _acquire=Mock(return_value=True), _release=Mock())
    result = NodeMediaService(api).handle("tts", {"text": "hello"})
    assert base64.b64decode(result["audio_base64"]) == path.read_bytes()
    config = synth.call_args.args[1]
    assert config.node_tts_no_playback and not config.xtts_stream_output
    assert api.config.xtts_stream_output
    assert not hasattr(api.config, "node_tts_no_playback")
    api._release.assert_called_once()


def test_media_busy_rejects_parallel_requests():
    service = NodeMediaService(SimpleNamespace())
    service._lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="busy"):
            service.handle("tts", {})
    finally:
        service._lock.release()


def test_stt_uses_pi_vosk_provider(monkeypatch):
    transcribe = Mock(return_value=("game dialogue", "en"))
    audio_data = Mock()
    monkeypatch.setitem(sys.modules, "nekosuneai.audio_input", SimpleNamespace(
        sr=SimpleNamespace(AudioData=audio_data), transcribe_audio_with_vosk=transcribe))
    api = SimpleNamespace(config=SimpleNamespace(stt_provider="vosk"), state=object())
    result = NodeMediaService(api).handle("stt", {"wav_base64": base64.b64encode(wav_data()).decode()})
    assert result["text"] == "game dialogue"
    assert audio_data.call_args.args[1:] == (16000, 2)
    transcribe.assert_called_once()


def test_vision_uses_configured_model(monkeypatch):
    from PIL import Image
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(data, "JPEG")
    describe = Mock(return_value="A game menu")
    monkeypatch.setitem(sys.modules, "nekosuneai.vision", SimpleNamespace(describe_image=describe))
    api = SimpleNamespace(config=SimpleNamespace())
    result = NodeMediaService(api).handle("vision", {"image_base64": base64.b64encode(data.getvalue()).decode()})
    assert result["description"] == "A game menu"
    assert "not instructions" in describe.call_args.args[2]


@pytest.mark.parametrize("authorized,expected", [(False, 401), (True, 200)])
def test_media_route_requires_node_token(authorized, expected):
    # Run the production handler method without booting optional assistant models.
    import ast
    import json
    from pathlib import Path
    from urllib.parse import urlparse
    tree = ast.parse(Path("nekosuneai/webserver.py").read_text("utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    registry = Mock()
    registry.authorize.return_value = authorized
    service = Mock()
    service.handle.return_value = {"ok": True}
    namespace = {"json": json, "urlparse": urlparse, "peripheral_nodes": registry, "node_media": service}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "webserver-route-test", "exec"), namespace)
    body = json.dumps({"node_id": "pc", "text": "hello"}).encode()
    handler = SimpleNamespace(path="/api/nodes/media/tts", rfile=io.BytesIO(body),
        headers={"Content-Length": str(len(body)), "X-Neko-Device-Token": "node-token"},
        _json=lambda status, result: (status, result))
    assert namespace["do_POST"](handler)[0] == expected
    registry.authorize.assert_called_once_with("pc", "node-token")
    assert service.handle.called == authorized
