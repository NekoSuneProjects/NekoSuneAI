import unittest

from nekosuneai.interruptions import is_global_stop_command


class GlobalStopParsingTests(unittest.TestCase):
    def test_clear_stop_commands(self):
        for text in ("Neko stop", "stop everything", "be quiet", "Hey Neko, stop now"):
            self.assertTrue(is_global_stop_command(text), text)

    def test_does_not_capture_normal_requests(self):
        for text in ("stop the timer", "stop by the shop", "how do I stop music buffering?"):
            self.assertFalse(is_global_stop_command(text), text)


if __name__ == "__main__":
    unittest.main()
