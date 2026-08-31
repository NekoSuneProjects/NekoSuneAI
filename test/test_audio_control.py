import unittest

from nekosuneai import audio_control
from nekosuneai.audio_control import (
    AudioController,
    Sink,
    parse_audio_command,
    parse_short_sinks,
    parse_sink_descriptions,
    parse_volume_percent,
    clamp_percent,
)


class PactlParsingTests(unittest.TestCase):
    def test_parse_short_sinks(self):
        text = (
            "48\talsa_output.pci-0000_00_1b.0.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tRUNNING\n"
            "52\tbluez_output.AA_BB_CC_DD_EE_FF.1\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
        )
        self.assertEqual(
            parse_short_sinks(text),
            ["alsa_output.pci-0000_00_1b.0.analog-stereo", "bluez_output.AA_BB_CC_DD_EE_FF.1"],
        )

    def test_parse_sink_descriptions(self):
        text = (
            "Sink #52\n"
            "\tName: bluez_output.AA_BB_CC_DD_EE_FF.1\n"
            "\tDescription: Amazon Echo Dot\n"
            "Sink #48\n"
            "\tName: alsa_output.pci\n"
            "\tDescription: Built-in Audio\n"
        )
        desc = parse_sink_descriptions(text)
        self.assertEqual(desc["bluez_output.AA_BB_CC_DD_EE_FF.1"], "Amazon Echo Dot")
        self.assertEqual(desc["alsa_output.pci"], "Built-in Audio")

    def test_parse_volume_percent(self):
        text = "Volume: front-left: 45875 /  70% / -9.29 dB,   front-right: 45875 / 70% / -9.29 dB"
        self.assertEqual(parse_volume_percent(text), 70)

    def test_clamp(self):
        self.assertEqual(clamp_percent(-5), 0)
        self.assertEqual(clamp_percent(200), 150)
        self.assertEqual(clamp_percent(40), 40)


class CommandParsingTests(unittest.TestCase):
    def test_set_absolute(self):
        action, payload = parse_audio_command("set the kitchen speaker to 40%")
        self.assertEqual(action, "set")
        self.assertEqual(payload["percent"], 40)
        self.assertIn("kitchen", payload["targets"])

    def test_volume_up(self):
        action, payload = parse_audio_command("turn up the volume")
        self.assertEqual(action, "up")

    def test_volume_down_with_amount(self):
        action, payload = parse_audio_command("turn the volume down 20%")
        self.assertEqual(action, "down")
        self.assertEqual(payload["delta"], 20)

    def test_mute(self):
        action, payload = parse_audio_command("mute the echo")
        self.assertEqual(action, "mute")
        self.assertIn("echo", payload["targets"])

    def test_unmute(self):
        self.assertEqual(parse_audio_command("unmute the speakers")[0], "unmute")

    def test_group_define(self):
        action, payload = parse_audio_command("group the kitchen and living room as downstairs")
        self.assertEqual(action, "group_define")
        self.assertEqual(payload["name"], "downstairs")
        self.assertCountEqual(payload["rooms"], ["kitchen", "living room"])

    def test_whisper_on(self):
        self.assertEqual(parse_audio_command("turn on whisper mode")[0], "whisper_on")

    def test_whisper_off(self):
        self.assertEqual(parse_audio_command("night mode off")[0], "whisper_off")

    def test_unrelated(self):
        self.assertIsNone(parse_audio_command("what's the weather"))


class FakeBackend:
    def __init__(self, sinks):
        self._sinks = sinks
        self.volumes = {s.name: 50 for s in sinks}
        self.muted = {s.name: False for s in sinks}

    def list_sinks(self):
        return list(self._sinks)

    def default_sink(self):
        return self._sinks[0].name if self._sinks else None

    def get_volume(self, sink):
        return self.volumes.get(sink)

    def set_volume(self, sink, percent):
        if sink in self.volumes:
            self.volumes[sink] = clamp_percent(percent)
            return True
        return False

    def set_mute(self, sink, mute):
        if sink in self.muted:
            self.muted[sink] = mute
            return True
        return False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self._state = {}
        self._orig_get = audio_control.get_state
        self._orig_set = audio_control.set_state
        audio_control.get_state = lambda key, default="": self._state.get(key, default)
        audio_control.set_state = lambda key, value: self._state.update({key: value})
        self.backend = FakeBackend([
            Sink("bluez_output.AA_BB.1", "Amazon Echo Kitchen"),
            Sink("alsa_output.pci", "Living Room Built-in Audio"),
        ])
        self.ctl = AudioController(self.backend)

    def tearDown(self):
        audio_control.get_state = self._orig_get
        audio_control.set_state = self._orig_set

    def test_set_named_room(self):
        reply = self.ctl.handle("set the kitchen speaker to 30%")
        self.assertIn("30%", reply)
        self.assertEqual(self.backend.volumes["bluez_output.AA_BB.1"], 30)
        # untouched
        self.assertEqual(self.backend.volumes["alsa_output.pci"], 50)

    def test_remembered_level_and_restore(self):
        self.ctl.handle("set the echo to 25%")
        self.backend.volumes["bluez_output.AA_BB.1"] = 99  # simulate manual change
        self.ctl.handle("restore the echo volume")
        self.assertEqual(self.backend.volumes["bluez_output.AA_BB.1"], 25)

    def test_volume_up_relative(self):
        self.ctl.handle("set the kitchen to 40%")
        self.ctl.handle("turn up the kitchen volume 15%")
        self.assertEqual(self.backend.volumes["bluez_output.AA_BB.1"], 55)

    def test_mute_named(self):
        self.ctl.handle("mute the living room")
        self.assertTrue(self.backend.muted["alsa_output.pci"])

    def test_group_then_control(self):
        self.ctl.handle("group the kitchen and living room as downstairs")
        reply = self.ctl.handle("set downstairs to 20%")
        self.assertIn("2 speakers", reply)
        self.assertEqual(self.backend.volumes["bluez_output.AA_BB.1"], 20)
        self.assertEqual(self.backend.volumes["alsa_output.pci"], 20)

    def test_whisper_mode_lowers_all(self):
        reply = self.ctl.handle("whisper mode on")
        self.assertIn("Whisper", reply)
        self.assertEqual(self.backend.volumes["bluez_output.AA_BB.1"], audio_control.WHISPER_LEVEL)
        self.assertEqual(self.backend.volumes["alsa_output.pci"], audio_control.WHISPER_LEVEL)


if __name__ == "__main__":
    unittest.main()
