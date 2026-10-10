import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from nekosuneai.android_gameplay.lan_status import serve_status


class WindowsLanStatusTest(unittest.TestCase):
    def setUp(self):
        worker = Mock()
        worker.node_id = "android-bluestacks"
        worker.package = "com.superplaystudios.disneysolitairedreams"
        worker.session_id = "session-1"
        worker.paused = False
        worker.device.foreground_package.return_value = worker.package
        self.server = serve_status(worker, host="127.0.0.1", port=0, token="A"*40)
        self.url = "http://127.0.0.1:%d/v1/lan-game/status" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.url, timeout=3)
        self.assertEqual(error.exception.code, 403)

    def test_only_authenticated_status(self):
        request = urllib.request.Request(
            self.url, headers={"X-Neko-LAN-Bridge-Token": "A"*40})
        with urllib.request.urlopen(request, timeout=3) as response:
            state = json.load(response)
        self.assertTrue(state["online"])
        self.assertEqual(state["foreground_package"],
                         "com.superplaystudios.disneysolitairedreams")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(
                self.url.replace("/status", "/action"),
                headers={"X-Neko-LAN-Bridge-Token": "A"*40}), timeout=3)
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
