import tempfile
import unittest
import wave
from pathlib import Path

from nekosuneai.alert_sounds import ensure_default_alert_sounds


class AlertSoundTests(unittest.TestCase):
    def test_creates_valid_warning_and_danger_wav_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_default_alert_sounds(root)
            for name in ("warning.wav", "danger.wav"):
                path = root / name
                self.assertGreater(path.stat().st_size, 1_000)
                with wave.open(str(path), "rb") as audio:
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getframerate(), 24_000)

    def test_does_not_replace_a_user_sound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            warning = root / "warning.wav"
            warning.write_bytes(b"custom sound")
            ensure_default_alert_sounds(root)
            self.assertEqual(warning.read_bytes(), b"custom sound")


if __name__ == "__main__":
    unittest.main()
