import unittest
from unittest.mock import patch
from nekosuneai.windows_encoder_probe import probe_encoders

class EncoderProbeTests(unittest.TestCase):
    def test_prioritizes_nvidia_when_advertised(self):
        listing = " V..... h264_qsv Intel Quick Sync\n V..... h264_nvenc NVIDIA NVENC\n"
        with patch("nekosuneai.windows_encoder_probe.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = listing
            result = probe_encoders("ffmpeg")
        self.assertEqual(result["preferred"], "h264_nvenc")
        self.assertIn("h264_qsv", result["available"])

    def test_no_ffmpeg_is_safe(self):
        with patch("nekosuneai.windows_encoder_probe.shutil.which", return_value=None):
            self.assertIsNone(probe_encoders()["preferred"])

if __name__ == "__main__":
    unittest.main()
