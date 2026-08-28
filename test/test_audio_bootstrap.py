import os
import sys
import types
import unittest
from unittest.mock import patch

import nekosuneai


class _DefaultDevice:
    def __init__(self, value):
        self.device = value


class AudioBootstrapTests(unittest.TestCase):
    def _fake_sounddevice(self, default=(-1, -1)):
        module = types.ModuleType("sounddevice")
        module.default = _DefaultDevice(default)
        module.query_devices = lambda: [
            {"name": "USB Audio", "max_output_channels": 2},
            {"name": "pulse", "max_output_channels": 2},
        ]
        return module

    def test_repairs_minus_one_default_to_pulse_output(self):
        fake = self._fake_sounddevice()
        with patch.dict(os.environ, {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"}, clear=False), \
             patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (-1, 1))

    def test_keeps_valid_existing_output(self):
        fake = self._fake_sounddevice(default=(-1, 7))
        with patch.dict(os.environ, {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"}, clear=False), \
             patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (-1, 7))


if __name__ == "__main__":
    unittest.main()
