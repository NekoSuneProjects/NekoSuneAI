import unittest
from nekosuneai.local_vision_fallback import select_provider, model_status


class LocalVisionFallbackTests(unittest.TestCase):
    def test_prefers_gpu_when_available(self):
        available = ["CPUExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider"]
        self.assertEqual(select_provider("auto", available), "CUDAExecutionProvider")
        self.assertEqual(select_provider("directml", available), "DmlExecutionProvider")

    def test_cpu_fallback_when_gpu_unavailable(self):
        self.assertEqual(select_provider("cuda", ["CPUExecutionProvider"]), "CPUExecutionProvider")
        self.assertEqual(select_provider("auto", ["CPUExecutionProvider"]), "CPUExecutionProvider")
        self.assertIsNone(select_provider("auto", []))

    def test_no_unverified_detector(self):
        self.assertFalse(model_status("", "auto")["enabled"])
        self.assertFalse(model_status("not-a-real-file.onnx")["enabled"])

    def test_reject_unknown_provider(self):
        with self.assertRaises(ValueError):
            select_provider("unsafe", ["CPUExecutionProvider"])


if __name__ == "__main__":
    unittest.main()
