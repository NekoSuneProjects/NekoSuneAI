import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock
from nekosuneai.windows_android_tools import (
    discover_bluestacks, find_adb, install_platform_tools, install_yolo_model)


class AndroidToolTests(unittest.TestCase):
    def test_adb_missing_then_found(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(find_adb(d, "/file/that/does/not/exist"), "")
            path = Path(d) / "platform-tools" / "adb.exe"
            path.parent.mkdir()
            path.touch()
            self.assertEqual(find_adb(d), str(path.resolve()))

    def test_platform_tools_safe_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            def fake_download(_url, path, _limit):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("platform-tools/adb.exe", b"adb executable test bytes")
                return "test"
            with patch("nekosuneai.windows_android_tools._download", side_effect=fake_download):
                path = install_platform_tools(d)
            self.assertEqual(Path(path).read_bytes(), b"adb executable test bytes")

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            def fake_download(_url, path, _limit):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("platform-tools/../outside", b"bad")
                    archive.writestr("platform-tools/adb.exe", b"test")
            with patch("nekosuneai.windows_android_tools._download", side_effect=fake_download):
                with self.assertRaises(ValueError):
                    install_platform_tools(d)
            self.assertFalse((Path(d) / "outside").exists())

    def test_yolo_checksum_required(self):
        with tempfile.TemporaryDirectory() as d:
            def fake_download(_url, path, _limit):
                path.write_bytes(b"not the model")
                return "bad"
            with patch("nekosuneai.windows_android_tools._download", side_effect=fake_download):
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    install_yolo_model(d)
            self.assertFalse((Path(d) / "yolov8n.onnx").exists())

    def test_local_discovery_ignores_offline(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "adb.exe"
            path.touch()
            with patch("nekosuneai.windows_android_tools.subprocess.run") as run:
                run.side_effect = [
                    Mock(stdout="List of devices attached\n127.0.0.1:5555\tdevice\n127.0.0.1:5556\toffline\n"),
                    Mock(returncode=0),
                    Mock(returncode=1, stdout="")
                ]
                found = discover_bluestacks(str(path), ports=(5555, 5556))
            self.assertEqual(found, ["127.0.0.1:5555"])

if __name__ == "__main__":
    unittest.main()
