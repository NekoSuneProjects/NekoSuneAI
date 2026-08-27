import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from nekosuneai.bluetooth_watchdog import BluetoothSpeakerWatchdog


class BluetoothWatchdogTests(unittest.TestCase):
    def _watchdog(self, address="AA:BB:CC:DD:EE:FF"):
        config = SimpleNamespace(
            bluetooth_reconnect_enabled=True,
            bluetooth_speaker_address=address,
            bluetooth_reconnect_interval_seconds=10,
        )
        return BluetoothSpeakerWatchdog(config, Mock())

    def test_rejects_invalid_address(self):
        ok, message = self._watchdog("Alexa speaker").reconnect_now()
        self.assertFalse(ok)
        self.assertIn("AA:BB:CC:DD:EE:FF", message)

    def test_reconnects_and_restores_default_sink(self):
        watchdog = self._watchdog()
        watchdog._is_connected = Mock(side_effect=[False, True])
        watchdog._run = Mock(return_value=SimpleNamespace(returncode=0, stdout="Connection successful", stderr=""))
        watchdog._set_default_sink = Mock()
        ok, message = watchdog.reconnect_now()
        self.assertTrue(ok)
        watchdog._set_default_sink.assert_called_once_with("AA:BB:CC:DD:EE:FF")
        self.assertIn("default output", message)


if __name__ == "__main__":
    unittest.main()
