"""A2DP profile selection for the Bluetooth speaker.

The watchdog used to guess three hardcoded profile names. A card only accepts
a name from its own list, and that list is codec-specific -- an Echo Dot can
offer `a2dp-sink-sbc_xq` and `a2dp-sink-aac` and no plain `a2dp-sink` -- so
every guess was rejected, the card stayed on HFP, no sink was created, and the
owner got "connected, but its A2DP audio sink is not ready yet" forever.
"""
from __future__ import annotations

import pytest

from nekosuneai.bluetooth_watchdog import BluetoothSpeakerWatchdog
from nekosuneai.config import Config

ADDRESS = "AC:63:BE:11:22:33"

# `pactl list cards` for an Echo Dot sitting on the headset profile, with no
# plain "a2dp-sink" among its profiles -- exactly the case that used to fail.
ECHO_DOT_CARDS = """Card #0
\tName: alsa_card.platform-bcm2835_audio
\tDriver: alsa
\tProfiles:
\t\toutput:analog-stereo: Analog Stereo Output (sinks: 1, sources: 0, priority: 6500, available: yes)
\tActive Profile: output:analog-stereo

Card #42
\tName: bluez_card.AC_63_BE_11_22_33
\tDriver: module-bluez5-device.c
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\ta2dp-sink-sbc: High Fidelity Playback (A2DP Sink, SBC) (sinks: 1, sources: 0, priority: 514, available: yes)
\t\ta2dp-sink-sbc_xq: High Fidelity Playback (A2DP Sink, SBC-XQ) (sinks: 1, sources: 0, priority: 512, available: yes)
\t\ta2dp-sink-aac: High Fidelity Playback (A2DP Sink, AAC) (sinks: 1, sources: 0, priority: 516, available: no)
\t\theadset-head-unit-cvsd: Headset Head Unit (HSP/HFP, CVSD) (sinks: 1, sources: 1, priority: 1, available: yes)
\tActive Profile: headset-head-unit-cvsd
"""


# A host whose audio server is reachable and has hardware, but no Bluetooth
# support at all -- so BlueZ connects the speaker and no card ever appears.
ANALOG_ONLY_CARDS = """Card #0
	Name: alsa_card.platform-bcm2835_audio
	Profiles:
		output:analog-stereo: Analog Stereo (sinks: 1, sources: 0, priority: 6500, available: yes)
	Active Profile: output:analog-stereo
"""


@pytest.fixture
def watchdog(monkeypatch):
    """A watchdog whose pactl calls are faked and recorded."""
    config = Config.from_env()
    notes: list[str] = []
    dog = BluetoothSpeakerWatchdog(config, notify=notes.append)
    dog.notes = notes
    dog.commands: list[list[str]] = []
    dog.cards = ECHO_DOT_CARDS
    dog.profile_set_ok = True

    monkeypatch.setattr("nekosuneai.bluetooth_watchdog.shutil.which", lambda name: "/usr/bin/" + name)

    def fake_run(args):
        dog.commands.append(args)
        if args[:3] == ["pactl", "list", "cards"]:
            return type("R", (), {"returncode": 0, "stdout": dog.cards, "stderr": ""})()
        if args[:2] == ["pactl", "set-card-profile"]:
            return type("R", (), {"returncode": 0 if dog.profile_set_ok else 1, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(dog, "_run", fake_run)
    return dog


def test_card_profiles_are_read_from_the_audio_server(watchdog):
    card = watchdog._bluez_card(ADDRESS)

    assert card["card"] == "bluez_card.AC_63_BE_11_22_33"
    assert card["active"] == "headset-head-unit-cvsd"
    # Unavailable profiles (aac here) are excluded; the rest rank by priority.
    assert card["profiles"] == ["a2dp-sink-sbc", "a2dp-sink-sbc_xq", "headset-head-unit-cvsd", "off"]
    assert "a2dp-sink-aac" not in card["profiles"]


def test_the_right_card_is_picked_when_several_exist(watchdog):
    assert watchdog._bluez_card("11:22:33:44:55:66") is None


def test_a_codec_specific_a2dp_profile_is_selected(watchdog):
    """The old hardcoded list contained none of these names."""
    assert watchdog._activate_a2dp_profile(ADDRESS) is True

    switches = [c for c in watchdog.commands if c[:2] == ["pactl", "set-card-profile"]]
    assert switches == [["pactl", "set-card-profile", "bluez_card.AC_63_BE_11_22_33", "a2dp-sink-sbc"]]
    assert any("a2dp-sink-sbc" in note for note in watchdog.notes)


def test_a_card_already_on_a2dp_is_left_alone(watchdog):
    watchdog.cards = ECHO_DOT_CARDS.replace(
        "Active Profile: headset-head-unit-cvsd", "Active Profile: a2dp-sink-sbc",
    )

    assert watchdog._activate_a2dp_profile(ADDRESS) is True
    assert not [c for c in watchdog.commands if c[:2] == ["pactl", "set-card-profile"]]


def test_a_card_with_no_a2dp_profile_explains_itself(watchdog):
    watchdog.cards = """Card #42
\tName: bluez_card.AC_63_BE_11_22_33
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\theadset-head-unit-cvsd: Headset Head Unit (sinks: 1, sources: 1, priority: 1, available: yes)
\tActive Profile: headset-head-unit-cvsd
"""

    assert watchdog._activate_a2dp_profile(ADDRESS) is False
    assert "no A2DP sink profile" in watchdog._detected_profile_error
    assert "headset-head-unit-cvsd" in watchdog._detected_profile_error


def test_a_rejected_profile_switch_is_reported(watchdog):
    watchdog.profile_set_ok = False

    assert watchdog._activate_a2dp_profile(ADDRESS) is False
    assert "rejected every A2DP profile" in watchdog._detected_profile_error


def test_a_missing_card_is_reported_rather_than_crashing(watchdog):
    watchdog.cards = ""
    assert watchdog._activate_a2dp_profile(ADDRESS) is False


def test_profile_error_reaches_the_status_page(watchdog):
    watchdog.cards = ""
    watchdog._detected_profile_error = "something specific went wrong"
    assert watchdog.status()["profile_error"] == "something specific went wrong"


class TestMissingCardDiagnosis:
    """Why the speaker has no audio-server card.

    BlueZ reporting "Connected: yes" tells you nothing about whether the audio
    server made a card for it, and the causes need different fixes: an
    unreachable server, a server with no Bluetooth support at all, or a card
    that belongs to some other device. Saying "is PULSE_SERVER reachable?" for
    all of them sends the owner after the wrong one.
    """

    def _diagnose(self, watchdog, cards, returncode=0, stderr=""):
        watchdog.cards = cards
        watchdog._detected_profile_error = ""

        def fake_run(args):
            if args[:3] == ["pactl", "list", "cards"]:
                return type("R", (), {"returncode": returncode, "stdout": cards, "stderr": stderr})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        watchdog._run = fake_run
        assert watchdog._bluez_card(ADDRESS) is None
        return watchdog._detected_profile_error

    def test_unreachable_audio_server_quotes_the_real_error(self, watchdog, monkeypatch):
        monkeypatch.setenv("PULSE_SERVER", "unix:/run/pulse/native")

        message = self._diagnose(
            watchdog, "", returncode=1, stderr="Connection failure: Connection refused",
        )

        assert "Connection refused" in message
        assert "unix:/run/pulse/native" in message
        assert "container" in message

    def test_missing_pactl_says_so(self, watchdog, monkeypatch):
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.shutil.which", lambda name: None)
        watchdog._detected_profile_error = ""

        assert watchdog._bluez_card(ADDRESS) is None
        assert "pactl is not on PATH" in watchdog._detected_profile_error

    def test_a_server_with_no_bluetooth_module_is_named_as_the_cause(self, watchdog):
        """The common one: bluetoothctl connects fine, the audio server has no
        Bluetooth support, so no card is ever created and nothing says why."""
        message = self._diagnose(watchdog, ANALOG_ONLY_CARDS)

        assert "none from Bluetooth" in message
        assert "libspa-0.2-bluetooth" in message          # PipeWire
        assert "pulseaudio-module-bluetooth" in message   # PulseAudio
        assert "BlueZ will keep reporting the speaker as connected" in message

    ANALOG_ONLY = """Card #0
\tName: alsa_card.platform-bcm2835_audio
\tProfiles:
\t\toutput:analog-stereo: Analog Stereo (sinks: 1, sources: 0, priority: 6500, available: yes)
\tActive Profile: output:analog-stereo
"""

    def _only_analog(self, watchdog):
        return watchdog

    def test_no_cards_at_all_is_distinguished(self, watchdog):
        message = self._diagnose(watchdog, "")
        assert "no sound cards at all" in message

    def test_a_card_for_a_different_speaker_is_distinguished(self, watchdog):
        other = """Card #7
\tName: bluez_card.AA_BB_CC_DD_EE_FF
\tProfiles:
\t\ta2dp-sink: A2DP (sinks: 1, sources: 0, priority: 40, available: yes)
\tActive Profile: a2dp-sink
"""
        message = self._diagnose(watchdog, other)

        assert "bluez_card.AA_BB_CC_DD_EE_FF" in message
        assert ADDRESS in message
        assert "different host" in message
