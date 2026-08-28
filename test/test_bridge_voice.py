import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nekosuneai import bridge_voice
from nekosuneai.config import normalize_stt_provider


class _FakeStdin:
    def __init__(self):
        self.closed = False
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class _FakePlayer:
    def __init__(self, returncode=0):
        self.stdin = _FakeStdin()
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


class BridgeVoiceTests(unittest.TestCase):
    def test_vosk_aliases_select_local_light_stt(self):
        self.assertEqual(normalize_stt_provider("vosk"), "vosk")
        self.assertEqual(normalize_stt_provider("local-lite"), "vosk")

    def test_voice_timeout_is_bounded_below_long_llm_timeout(self):
        config = SimpleNamespace(request_timeout=300, mcp_timeout_seconds=30)
        self.assertEqual(bridge_voice._voice_timeout(config), 30)

    @patch("nekosuneai.bridge_voice._request")
    def test_transcription_uses_dedicated_long_timeout(self, request):
        request.return_value = {"type": "done", "text": "hello", "language": "en"}
        config = SimpleNamespace(stt_language="en-GB", bridge_stt_timeout_seconds=90)
        bridge_voice.transcribe(b"wav", config)
        self.assertEqual(request.call_args.kwargs["timeout"], 90)

    def test_missing_edge_package_is_a_safe_fallback_condition(self):
        error = RuntimeError("Cannot find package 'edge-tts-universal' imported from /root/nekoai-bridge/lib/providers/edge-tts.js")
        self.assertTrue(bridge_voice._stream_route_unavailable(error))
        self.assertFalse(bridge_voice._stream_route_unavailable(RuntimeError("unauthorized bridge token")))

    def test_bridge_transcription_normalizes_regional_language_for_whisper(self):
        config = SimpleNamespace(stt_language="en-GB")
        with patch.object(bridge_voice, "_request", return_value={"text": "hello"}) as request:
            text, language = bridge_voice.transcribe(b"wav", config)
        self.assertEqual(text, "hello")
        self.assertEqual(language, "en")
        self.assertEqual(request.call_args.args[1]["language"], "en")

    def test_old_bridge_falls_back_from_stream_to_builtin_piper(self):
        config = SimpleNamespace(
            bridge_tts_engine="edge-stream", tts_language="en", bridge_tts_voice="en-GB-SoniaNeural",
            bridge_tts_rate="+10%", request_timeout=10, mcp_timeout_seconds=10,
        )
        calls = []

        def request(_config, payload, on_audio=None):
            calls.append(payload)
            if payload["type"] == "tts-stream":
                raise RuntimeError('Unsupported payload type "tts-stream".')
            return {"files": [{"contentType": "audio/wav", "contentBase64": base64.b64encode(b"wav-data").decode()}]}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(bridge_voice, "AUDIO_DIR", Path(directory)), \
             patch.object(bridge_voice, "_request", side_effect=request), \
             patch.object(bridge_voice.shutil, "which", return_value=None):
            output = bridge_voice.synthesize("hello", config)
        self.assertEqual(output.suffix, ".wav")
        self.assertEqual(calls[0]["type"], "tts-stream")
        self.assertEqual(calls[1]["type"], "tts")
        self.assertEqual(calls[1]["provider"], "piper")
        self.assertNotIn("voice", calls[1])

    def test_failed_stream_player_is_not_marked_as_played(self):
        config = SimpleNamespace(
            bridge_tts_engine="edge-stream",
            tts_language="en",
            bridge_tts_voice="en-GB-SoniaNeural",
            bridge_tts_rate="+10%",
            request_timeout=10,
            mcp_timeout_seconds=10,
        )
        player = _FakePlayer(returncode=1)

        def request(_config, payload, on_audio=None):
            self.assertEqual(payload["type"], "tts-stream")
            self.assertIsNotNone(on_audio)
            on_audio(b"audio-one")
            on_audio(b"audio-two")
            return {"type": "done"}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(bridge_voice, "AUDIO_DIR", Path(directory)), \
             patch.object(bridge_voice, "_request", side_effect=request), \
             patch.object(bridge_voice.shutil, "which", return_value="/usr/bin/ffplay"), \
             patch.object(bridge_voice.subprocess, "Popen", return_value=player):
            output = bridge_voice.synthesize("hello", config)
            self.assertEqual(output.read_bytes(), b"audio-oneaudio-two")
            self.assertFalse(bridge_voice.stream_was_played())

    def test_successful_stream_player_is_marked_as_played(self):
        config = SimpleNamespace(
            bridge_tts_engine="edge-stream",
            tts_language="en",
            bridge_tts_voice="en-GB-SoniaNeural",
            bridge_tts_rate="+10%",
            request_timeout=10,
            mcp_timeout_seconds=10,
        )
        player = _FakePlayer(returncode=0)

        def request(_config, payload, on_audio=None):
            on_audio(b"audio")
            return {"type": "done"}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(bridge_voice, "AUDIO_DIR", Path(directory)), \
             patch.object(bridge_voice, "_request", side_effect=request), \
             patch.object(bridge_voice.shutil, "which", return_value="/usr/bin/ffplay"), \
             patch.object(bridge_voice.subprocess, "Popen", return_value=player):
            bridge_voice.synthesize("hello", config)
            self.assertTrue(bridge_voice.stream_was_played())

    def test_ffplay_prefers_pulse_inside_host_audio_session(self):
        with patch.dict(bridge_voice.os.environ, {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"}, clear=True):
            env = bridge_voice._ffplay_environment()
        self.assertEqual(env.get("SDL_AUDIODRIVER"), "pulseaudio")


if __name__ == "__main__":
    unittest.main()
