import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from nekosuneai.wakeword import WakeWordListener


class _FakeInputStream:
    opened_device = None

    def __init__(self, *, samplerate, channels, dtype, blocksize, device):
        type(self).opened_device = device
        self.channels = channels

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, frames):
        return np.zeros((frames, self.channels), dtype=np.int16), False


class _FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def predict(self, samples):
        return {"hey_jarvis": 1.0}

    def reset(self):
        pass


class WakeWordDeviceTests(unittest.TestCase):
    def test_wakeword_uses_resolved_microphone_index(self):
        cfg = SimpleNamespace(
            wake_word_enabled=True,
            wake_word_model="hey_jarvis",
            wake_word_framework="onnx",
            wake_word_threshold=0.5,
            wake_word_confirmation_frames=1,
            wake_word_cooldown_seconds=0.0,
            mic_device_index=None,
            mic_input_channels=0,
            mic_channel_index=0,
        )
        listener = WakeWordListener(cfg, Mock())

        fake_sd = types.ModuleType("sounddevice")
        fake_sd.InputStream = _FakeInputStream
        fake_utils = types.ModuleType("openwakeword.utils")
        fake_utils.download_models = Mock()
        fake_model_module = types.ModuleType("openwakeword.model")
        fake_model_module.Model = _FakeModel
        fake_pkg = types.ModuleType("openwakeword")
        fake_pkg.utils = fake_utils

        def detected():
            listener.stop_event.set()

        listener.detected = detected

        with patch.dict(
            sys.modules,
            {
                "sounddevice": fake_sd,
                "openwakeword": fake_pkg,
                "openwakeword.utils": fake_utils,
                "openwakeword.model": fake_model_module,
            },
        ), patch(
            "nekosuneai.wakeword.resolve_input_device_info",
            return_value={
                "index": 7,
                "name": "Xbox NUI Sensor / Kinect USB Audio",
                "default_sample_rate": 16000,
                "max_input_channels": 4,
            },
        ):
            listener._run()

        self.assertEqual(_FakeInputStream.opened_device, 7)
        self.assertEqual(listener.device_index, 7)
        self.assertIn("Kinect", listener.device_name)
        self.assertEqual(listener.error, "")


if __name__ == "__main__":
    unittest.main()
