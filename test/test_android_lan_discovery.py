import unittest
from unittest.mock import patch

from nekosuneai.android_lan_discovery import AndroidLanDiscovery


class AndroidLanTests(unittest.TestCase):
    def test_disabled_by_default(self):
        discovery = AndroidLanDiscovery({"game_lan_devices": [
            {"id": "android-1", "ip": "192.168.1.22", "port": 8765}]})
        self.assertEqual(discovery.inventory(), [])
        with self.assertRaises(PermissionError):
            discovery.status("android-1")

    def test_reject_public_address(self):
        with self.assertRaises(ValueError):
            AndroidLanDiscovery({"game_lan_devices": [
                {"id": "public", "ip": "8.8.8.8", "port": 5555}]})

    def test_reject_duplicate(self):
        device = {"id": "android-1", "ip": "192.168.1.22", "port": 8765}
        with self.assertRaises(ValueError):
            AndroidLanDiscovery({"game_lan_devices": [device, device]})

    def test_cached_status_and_batch_probe(self):
        discovery = AndroidLanDiscovery({"game_lan_enabled": True,
            "game_lan_probe_cache_seconds": 30,
            "game_lan_devices": [{"id": "android-1", "ip": "127.0.0.1", "port": 8765, "token": "a" * 40}]})
        with patch("nekosuneai.android_lan_discovery.urllib.request.urlopen") as connect:
            connect.return_value.__enter__.return_value.status = 200
            connect.return_value.__enter__.return_value.read.return_value = b'{"online":true,"node_id":"android-1","foreground_package":"com.superplaystudios.disneysolitairedreams"}'
            first = discovery.status("android-1")
            second = discovery.status("android-1")
            all_devices = discovery.statuses()
        self.assertTrue(first["reachable"])
        self.assertEqual(first, second)
        self.assertEqual(all_devices, [first])
        connect.assert_called_once()
    def test_known_device_reachability(self):
        discovery = AndroidLanDiscovery({"game_lan_enabled": True,
            "game_lan_devices": [{"id": "android-1", "ip": "127.0.0.1", "port": 8765, "token": "a" * 40}]})
        self.assertEqual(len(discovery.inventory()), 1)
        with patch("nekosuneai.android_lan_discovery.socket.create_connection") as connect:
            self.assertTrue(discovery.status("android-1")["reachable"])
            connect.assert_called_once()
        with self.assertRaises(PermissionError):
            discovery.status("unknown")


if __name__ == "__main__":
    unittest.main()
