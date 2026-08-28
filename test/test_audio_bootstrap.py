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
    def _fake_sounddevice(self, default=(-1, -1), devices=None):
        module = types.ModuleType("sounddevice")
        module.default = _DefaultDevice(default)
        module.query_devices = lambda: devices or [
            {
                "name": "Xbox NUI Sensor / Kinect USB Audio",
                "max_input_channels": 4,
                "max_output_channels": 0,
            },
            {
                "name": "pulse",
                "max_input_channels": 0,
                "max_output_channels": 2,
            },
        ]
        return module

    def test_repairs_both_kinect_input_and_pulse_output(self):
        fake = self._fake_sounddevice()
        with patch.dict(
            os.environ,
            {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"},
            clear=False,
        ), patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (0, 1))

    def test_keeps_valid_existing_devices(self):
        fake = self._fake_sounddevice(default=(0, 1))
        with patch.dict(
            os.environ,
            {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"},
            clear=False,
        ), patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (0, 1))

    def test_prefers_kinect_over_bluetooth_input(self):
        fake = self._fake_sounddevice(
            devices=[
                {
                    "name": "bluez_input.AA_BB_CC_DD_EE_FF",
                    "max_input_channels": 1,
                    "max_output_channels": 0,
                },
                {
                    "name": "Xbox NUI Sensor Kinect USB Audio",
                    "max_input_channels": 4,
                    "max_output_channels": 0,
                },
                {
                    "name": "pulse",
                    "max_input_channels": 1,
                    "max_output_channels": 2,
                },
            ]
        )
        with patch.dict(
            os.environ,
            {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"},
            clear=False,
        ), patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (1, 2))

    def test_repairs_invalid_input_without_changing_valid_output(self):
        fake = self._fake_sounddevice(default=(-1, 1))
        with patch.dict(
            os.environ,
            {"PULSE_SERVER": "unix:/run/user/1000/pulse/native"},
            clear=False,
        ), patch.dict(sys.modules, {"sounddevice": fake}):
            nekosuneai._repair_session_audio_default()
        self.assertEqual(fake.default.device, (0, 1))


if __name__ == "__main__":
    unittest.main()
