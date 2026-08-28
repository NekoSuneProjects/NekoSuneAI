import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nekosuneai.bluetooth_watchdog import BluetoothSpeakerWatchdog


class BluetoothWatchdogTests(unittest.TestCase):
    def _watchdog(self, address=""):
        config = SimpleNamespace(
            bluetooth_reconnect_enabled=True,
            bluetooth_speaker_address=address,
            bluetooth_reconnect_interval_seconds=10,
        )
        return BluetoothSpeakerWatchdog(config, Mock())

    def test_blank_address_auto_discovers_and_routes_alexa(self):
        watchdog = self._watchdog("")
        watchdog._discover_paired_audio_device = Mock(
            return_value=("11:22:33:44:55:66", "Living Room Echo")
        )
        watchdog._is_connected = Mock(return_value=True)
        watchdog._set_default_sink = Mock(
            return_value="bluez_output.11_22_33_44_55_66.1"
        )

        ok, message = watchdog.reconnect_now()

        self.assertTrue(ok)
        self.assertIn("Living Room Echo", message)
        self.assertEqual(watchdog.status()["address"], "11:22:33:44:55:66")
        self.assertTrue(watchdog.status()["ready"])

    def test_example_placeholder_falls_back_to_auto_discovery(self):
        watchdog = self._watchdog("AA:BB:CC:DD:EE:FF")
        watchdog._device_info = Mock(return_value="")
        watchdog._discover_paired_audio_device = Mock(
            return_value=("11:22:33:44:55:66", "Alexa")
        )
        target = watchdog._resolve_target()
        self.assertEqual(target, ("11:22:33:44:55:66", "Alexa"))

    def test_prefers_alexa_echo_over_other_audio_device(self):
        watchdog = self._watchdog()
        device_list = SimpleNamespace(
            returncode=0,
            stdout=(
                "Device 10:10:10:10:10:10 Headphones\n"
                "Device 20:20:20:20:20:20 Kitchen Echo\n"
            ),
            stderr="",
        )
        info_headphones = (
            "Device 10:10:10:10:10:10\n"
            "\tName: Headphones\n"
            "\tAlias: Headphones\n"
            "\tPaired: yes\n"
            "\tTrusted: yes\n"
            "\tConnected: yes\n"
            "\tUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)\n"
        )
        info_echo = (
            "Device 20:20:20:20:20:20\n"
            "\tName: Kitchen Echo\n"
            "\tAlias: Kitchen Echo\n"
            "\tPaired: yes\n"
            "\tTrusted: yes\n"
            "\tConnected: no\n"
            "\tUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)\n"
        )

        def fake_run(args):
            if args == ["bluetoothctl", "devices"]:
                return device_list
            if args[-1] == "10:10:10:10:10:10":
                return SimpleNamespace(returncode=0, stdout=info_headphones, stderr="")
            if args[-1] == "20:20:20:20:20:20":
                return SimpleNamespace(returncode=0, stdout=info_echo, stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        watchdog._run = Mock(side_effect=fake_run)
        with patch("nekosuneai.bluetooth_watchdog.shutil.which", return_value="/usr/bin/bluetoothctl"):
            target = watchdog._discover_paired_audio_device()

        self.assertEqual(target, ("20:20:20:20:20:20", "Kitchen Echo"))

    def test_reconnects_then_waits_for_a2dp_sink(self):
        watchdog = self._watchdog()
        watchdog._resolve_target = Mock(
            return_value=("11:22:33:44:55:66", "Alexa")
        )
        watchdog._is_connected = Mock(side_effect=[False, True])
        watchdog._run = Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout="Connection successful",
                stderr="",
            )
        )
        watchdog._set_default_sink = Mock(
            return_value="bluez_output.11_22_33_44_55_66.1"
        )

        ok, message = watchdog.reconnect_now()

        self.assertTrue(ok)
        watchdog._set_default_sink.assert_called_once_with("11:22:33:44:55:66")
        self.assertIn("default Bluetooth output", message)

    def test_connected_without_a2dp_sink_is_not_reported_ready(self):
        watchdog = self._watchdog()
        watchdog._resolve_target = Mock(
            return_value=("11:22:33:44:55:66", "Alexa")
        )
        watchdog._is_connected = Mock(return_value=True)
        watchdog._set_default_sink = Mock(return_value=None)

        ok, message = watchdog.reconnect_now()

        self.assertFalse(ok)
        self.assertIn("A2DP audio sink is not ready", message)
        self.assertTrue(watchdog.status()["connected"])
        self.assertFalse(watchdog.status()["ready"])

    def test_no_paired_audio_device_explains_one_time_pairing(self):
        watchdog = self._watchdog()
        watchdog._resolve_target = Mock(return_value=None)
        ok, message = watchdog.reconnect_now()
        self.assertFalse(ok)
        self.assertIn("Pair Alexa on the host once", message)


if __name__ == "__main__":
    unittest.main()
