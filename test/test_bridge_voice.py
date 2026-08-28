import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nekosuneai import bridge_voice


class BridgeVoiceTests(unittest.TestCase):
    def test_voice_timeout_is_bounded_below_long_llm_timeout(self):
        config = SimpleNamespace(request_timeout=300, mcp_timeout_seconds=30)
        self.assertEqual(bridge_voice._voice_timeout(config), 30)

    def test_old_bridge_falls_back_from_stream_to_builtin_piper(self):
        config = SimpleNamespace(
            bridge_tts_engine="edge-stream", tts_language="en", bridge_tts_voice="en-GB-SoniaNeural",
            bridge_tts_rate="+10%", request_timeout=10,
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


if __name__ == "__main__":
    unittest.main()
