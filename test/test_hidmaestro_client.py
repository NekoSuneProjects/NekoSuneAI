import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from nekosuneai.hidmaestro_client import HIDMaestroController


class HIDMaestroTests(unittest.TestCase):
    def test_rejects_invalid_backend_without_process(self):
        with self.assertRaises(ValueError):
            HIDMaestroController("unsupported")

    def test_absent_sidecar_never_installs_driver(self):
        with patch.dict(os.environ, {"NEKOSUNE_HIDMAESTRO_BRIDGE": "X:/nonexistent/bridge.exe"}):
            with self.assertRaises(RuntimeError):
                HIDMaestroController("xbox360")

    def test_allowlisted_commands(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "bridge.exe"
            exe.touch()
            fake = MagicMock()
            fake.poll.return_value = None
            fake.stdout = io.StringIO('{"ok": true}\n' * 5)
            fake.stdin = io.StringIO()
            with patch.dict(os.environ, {"NEKOSUNE_HIDMAESTRO_BRIDGE": str(exe)}), patch(
                    "nekosuneai.hidmaestro_client.subprocess.Popen", return_value=fake):
                pad = HIDMaestroController("dualshock4")
                pad.button("a", True)
                pad.axis("left_x", 0.3)
                pad.reset()
                with self.assertRaises(ValueError):
                    pad.button("guide", True)
                with self.assertRaises(ValueError):
                    pad.axis("left_x", 10)
                commands = [json.loads(s) for s in fake.stdin.getvalue().splitlines()]
                self.assertEqual([x["op"] for x in commands],
                                 ["ping", "button", "axis", "reset"])


if __name__ == "__main__":
    unittest.main()
