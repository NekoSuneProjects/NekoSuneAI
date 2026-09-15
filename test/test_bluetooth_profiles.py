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


def test_a_headset_only_card_is_reported_as_the_wrong_role(watchdog):
    """A card offering only headset profiles is the wrong-role case, and gets
    the specific explanation rather than the generic "no A2DP" one."""
    watchdog.cards = """Card #42
\tName: bluez_card.AC_63_BE_11_22_33
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\theadset-head-unit-cvsd: Headset Head Unit (sinks: 1, sources: 1, priority: 1, available: yes)
\tActive Profile: headset-head-unit-cvsd
"""

    assert watchdog._activate_a2dp_profile(ADDRESS) is False
    assert "telephony role" in watchdog._detected_profile_error
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

    def test_unreachable_audio_server_is_reported(self, watchdog, monkeypatch, tmp_path):
        """With a live socket present, the server itself is the suspect."""
        monkeypatch.setenv("PULSE_SERVER", f"unix:{tmp_path / 'native'}")
        (tmp_path / "native").write_text("")   # exists, but not a socket

        message = self._diagnose(
            watchdog, "", returncode=1, stderr="Connection failure: Connection refused",
        )

        assert "is not a socket" in message
        assert str(tmp_path / "native") in message

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


class TestAudioServerProbe:
    """A one-off startup probe of the audio server.

    Everything audible on this node -- TTS replies, wake chimes, music --
    goes through the same server, so a dead session is not a Bluetooth
    problem. Discovering it only when a speaker fails to become ready sent
    the owner looking at Bluetooth instead of at their audio session.
    """

    def _probe(self, watchdog, returncode, stdout="", stderr=""):
        watchdog._run = lambda args: type(
            "R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr},
        )()
        return watchdog.audio_server_probe()

    def test_a_reachable_server_reports_its_name_and_sink(self, watchdog):
        ok, message = self._probe(watchdog, 0, stdout=(
            "Server Name: PulseAudio (on PipeWire 1.0.5)\n"
            "Default Sink: alsa_output.platform-bcm2835_audio.analog-stereo\n"
        ))

        assert ok is True
        assert "PipeWire" in message
        assert "alsa_output" in message

    def test_connection_refused_points_at_the_missing_socket(self, watchdog, monkeypatch, tmp_path):
        """The container case: PULSE_SERVER names a path that is not there,
        which Docker produces by creating an empty dir for a missing mount."""
        empty = tmp_path / "pulse"
        empty.mkdir()
        monkeypatch.setenv("PULSE_SERVER", f"unix:{empty / 'native'}")

        ok, message = self._probe(
            watchdog, 1, stderr="pa_context_connect() failed: Connection refused",
        )

        assert ok is False
        assert "does not exist here" in message
        assert "is empty" in message
        assert "detect-pulse-audio.sh" in message
        assert "enable-linger" in message

    def test_missing_pactl_is_distinguished(self, watchdog, monkeypatch):
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.shutil.which", lambda name: None)
        ok, message = watchdog.audio_server_probe()

        assert ok is False
        assert "pulseaudio-utils" in message

    def test_start_probes_and_announces_a_dead_server(self, watchdog, monkeypatch):
        watchdog.config.bluetooth_reconnect_enabled = True
        monkeypatch.setattr(
            watchdog, "audio_server_probe", lambda: (False, "audio server is dead"),
        )
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.threading.Thread", lambda **kw: type(
            "T", (), {"start": lambda self: None, "is_alive": lambda self: False},
        )())

        watchdog.start()

        assert watchdog.audio_server_ok is False
        assert "audio server is dead" in watchdog.notes
        assert watchdog.status()["audio_server_ok"] is False


class TestUnreachableServerDiagnosis:
    """"Connection refused" reads as "the server is down" and sends the owner
    to a host session that is usually running fine. In a container the usual
    cause is that the socket PULSE_SERVER names is not present at all."""

    def _diagnose(self, watchdog, pulse_server, monkeypatch):
        monkeypatch.setenv("PULSE_SERVER", pulse_server)
        result = type("R", (), {
            "returncode": 1, "stdout": "",
            "stderr": "pa_context_connect() failed: Connection refused",
        })()
        return watchdog._diagnose_unreachable_server(result)

    def test_a_missing_socket_is_named_as_the_cause(self, watchdog, monkeypatch, tmp_path):
        missing = tmp_path / "pulse" / "native"
        message = self._diagnose(watchdog, f"unix:{missing}", monkeypatch)

        assert "does not exist here" in message
        assert "force-recreate" in message

    def test_an_empty_mount_directory_explains_the_docker_behaviour(self, watchdog, monkeypatch, tmp_path):
        """Docker silently creates an empty dir when a bind source is missing."""
        empty = tmp_path / "pulse"
        empty.mkdir()
        message = self._diagnose(watchdog, f"unix:{empty / 'native'}", monkeypatch)

        assert "is empty" in message
        assert "bind-mount source is missing" in message

    def test_a_populated_directory_lists_what_is_actually_there(self, watchdog, monkeypatch, tmp_path):
        present = tmp_path / "pulse"
        present.mkdir()
        (present / "pid").write_text("1")
        message = self._diagnose(watchdog, f"unix:{present / 'native'}", monkeypatch)

        assert "contains: pid" in message

    def test_a_path_that_is_not_a_socket_is_distinguished(self, watchdog, monkeypatch, tmp_path):
        notsock = tmp_path / "native"
        notsock.write_text("not a socket")
        message = self._diagnose(watchdog, f"unix:{notsock}", monkeypatch)

        assert "is not a socket" in message

    @pytest.mark.skipif(
        not hasattr(__import__("socket"), "AF_UNIX"),
        reason="AF_UNIX is POSIX-only; the Pi has it, this host does not",
    )
    def test_a_live_socket_being_refused_blames_the_server_not_the_path(self, watchdog, monkeypatch, tmp_path):
        import socket as socketlib

        sock_path = tmp_path / "native"
        server = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
        try:
            server.bind(str(sock_path))
            message = self._diagnose(watchdog, f"unix:{sock_path}", monkeypatch)
        finally:
            server.close()

        assert "Connection refused" in message
        assert "PULSE_COOKIE" in message
        assert "does not exist here" not in message


# An Echo Dot that connected in the wrong direction: it is acting as the audio
# source and treating the Pi as its output, so its card carries only telephony
# profiles and can never produce a playback sink.
AUDIO_GATEWAY_CARD = """Card #42
\tName: bluez_card.AC_63_BE_11_22_33
\tProfiles:
\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)
\t\taudio-gateway: Audio Gateway (A2DP Source & HSP/HFP AG) (sinks: 0, sources: 1, priority: 20, available: yes)
\tActive Profile: audio-gateway
"""

DEVICE_WITH_SINK = """Device AC:63:BE:11:22:33 (public)
\tAlias: Echo Dot-8MR
\tPaired: yes
\tTrusted: yes
\tConnected: yes
\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
"""


class TestWrongRoleRecovery:
    """A speaker connected as the audio gateway.

    Its card offers only telephony profiles, so waiting for a sink never
    succeeds. When BlueZ says the device does advertise an A2DP Audio Sink,
    the roles were negotiated badly and reconnecting from this side settles
    them -- but only once, since repeatedly dropping a speaker someone is
    listening through would be worse than the fault.
    """

    def _setup(self, watchdog, device_info=DEVICE_WITH_SINK):
        watchdog.cards = AUDIO_GATEWAY_CARD
        watchdog._detected_name = "Echo Dot-8MR"
        watchdog._device_info = lambda address: device_info
        return watchdog

    def test_a_gateway_role_triggers_one_reconnect(self, watchdog, monkeypatch):
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.time.sleep", lambda s: None)
        dog = self._setup(watchdog)

        assert dog._activate_a2dp_profile(ADDRESS) is False

        actions = [c[:2] for c in dog.commands if c[0] == "bluetoothctl"]
        assert ["bluetoothctl", "disconnect"] in actions
        assert ["bluetoothctl", "connect"] in actions
        assert any("audio gateway" in note for note in dog.notes)

    def test_the_reconnect_is_not_repeated(self, watchdog, monkeypatch):
        """Never drop the speaker twice for the same device."""
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.time.sleep", lambda s: None)
        dog = self._setup(watchdog)

        dog._activate_a2dp_profile(ADDRESS)
        first = len([c for c in dog.commands if c[:2] == ["bluetoothctl", "disconnect"]])
        dog._activate_a2dp_profile(ADDRESS)
        dog._activate_a2dp_profile(ADDRESS)
        again = len([c for c in dog.commands if c[:2] == ["bluetoothctl", "disconnect"]])

        assert first == 1 and again == 1

    def test_after_the_retry_the_fix_is_spelled_out(self, watchdog, monkeypatch):
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.time.sleep", lambda s: None)
        dog = self._setup(watchdog)
        dog._activate_a2dp_profile(ADDRESS)          # uses up the one retry

        dog._activate_a2dp_profile(ADDRESS)

        message = dog._detected_profile_error
        assert "telephony role" in message
        assert "Alexa, pair Bluetooth" in message
        assert ADDRESS in message

    def test_a_device_with_no_sink_uuid_is_not_reconnected(self, watchdog, monkeypatch):
        """Nothing to renegotiate towards -- dropping it would be pointless."""
        monkeypatch.setattr("nekosuneai.bluetooth_watchdog.time.sleep", lambda s: None)
        dog = self._setup(watchdog, device_info="Device AC:63:BE:11:22:33 (public)\n\tPaired: yes\n")

        dog._activate_a2dp_profile(ADDRESS)

        assert not [c for c in dog.commands if c[:2] == ["bluetoothctl", "disconnect"]]
        assert "telephony role" in dog._detected_profile_error

    def test_a_non_telephony_card_without_a2dp_is_reported_plainly(self, watchdog):
        """Not the wrong-role case, so no reconnect and no Echo advice."""
        watchdog.cards = """Card #42
\tName: bluez_card.AC_63_BE_11_22_33
\tProfiles:
\t\tsome-other-profile: Other (sinks: 1, sources: 0, priority: 5, available: yes)
\tActive Profile: some-other-profile
"""
        assert watchdog._activate_a2dp_profile(ADDRESS) is False

        assert "offers no A2DP sink profile" in watchdog._detected_profile_error
        assert not [c for c in watchdog.commands if c[:2] == ["bluetoothctl", "disconnect"]]
