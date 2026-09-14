"""Node-initiated conversation turns (contract NODE-CONVERSE-01).

Covers the endpoint's two jobs: running a turn the node started, and routing a
music request to the node's own speaker rather than the backend host's.
"""
from __future__ import annotations

import time

import pytest

from nekosuneai.node_converse import NodeConverseService
from nekosuneai.peripheral_nodes import PeripheralNodeRegistry

ALL_ALLOWED = {"music.play": "allow", "music.stop": "allow", "audio.speak": "allow"}


class FakeNodes:
    def __init__(self, policies=None):
        self.policies = dict(policies if policies is not None else ALL_ALLOWED)
        self.events = []

    def action_policy(self, node_id, capability):
        return self.policies.get(capability, "confirm")

    def record_event(self, event, node_id, **details):
        self.events.append((event, node_id, details))


class FakeState:
    voice_enabled = True


class FakeApi:
    """Stands in for webgui's Api; records what reached the reply pipeline."""

    def __init__(self):
        self.state = FakeState()
        self.media_enabled = True
        self.seen = []
        self.output_during_turn = []

    def _pipeline(self, text, from_voice):
        self.seen.append(text)
        self.output_during_turn.append((self.state.voice_enabled, self.media_enabled))
        return "The sky is blue."


class FakeMedia:
    def __init__(self, fail=False):
        self.fail = fail

    def handle(self, operation, payload):
        assert operation == "tts"
        if self.fail:
            raise RuntimeError("tts is down")
        return {"audio_base64": "QUJD", "content_type": "audio/wav"}


@pytest.fixture
def service():
    return NodeConverseService(FakeApi(), FakeNodes(), FakeMedia())


def _turn(service, text, **payload):
    """One turn, spaced past the per-node minimum gap."""
    time.sleep(1.05)
    return service.handle("pi-1", {"text": text, **payload})


def test_play_request_becomes_a_node_command_not_a_backend_playback(service):
    result = service.handle("pi-1", {"text": "play lofi hip hop"})

    assert result["commands"] == [
        {"capability": "music.play", "arguments": {"query": "lofi hip hop"}},
    ]
    # The backend's own handle_media_request would have played this on the
    # backend host, which is the wrong room entirely.
    assert service.api.seen == []
    assert result["reply"] == "Playing lofi hip hop."


@pytest.mark.parametrize("phrase", ["stop", "pause"])
def test_stop_and_pause_reach_the_node(service, phrase):
    result = service.handle("pi-1", {"text": phrase})
    assert result["commands"] == [{"capability": "music.stop", "arguments": {}}]


def test_ordinary_question_goes_to_the_reply_pipeline(service):
    result = service.handle("pi-1", {"text": "why is the sky blue?"})

    assert service.api.seen == ["why is the sky blue?"]
    assert result["reply"] == "The sky is blue."
    assert result["commands"] == []
    assert result["audio_base64"] == "QUJD"


def test_backend_host_stays_quiet_during_a_node_turn(service):
    """The owner is talking to the Pi; the VPS must not speak to an empty room."""
    service.handle("pi-1", {"text": "why is the sky blue?"})

    assert service.api.output_during_turn == [(False, False)]
    # ...and the backend's own settings are restored afterwards.
    assert service.api.state.voice_enabled is True
    assert service.api.media_enabled is True


def test_denied_capability_never_leaks_a_command(service):
    service.nodes.policies = {"audio.speak": "allow"}

    result = service.handle("pi-1", {"text": "play jazz"})

    assert result["commands"] == []
    assert "not allowed" in result["reply"]


def test_tts_failure_degrades_to_text_instead_of_failing_the_turn():
    service = NodeConverseService(FakeApi(), FakeNodes(), FakeMedia(fail=True))

    result = service.handle("pi-1", {"text": "why is the sky blue?"})

    assert result["reply"] == "The sky is blue."
    assert "audio_base64" not in result
    assert result["tts_error"] == "tts is down"


def test_turns_are_rate_limited_per_node(service):
    service.handle("pi-1", {"text": "first"})
    with pytest.raises(RuntimeError):
        service.handle("pi-1", {"text": "immediately again"})
    # A different node is unaffected by another node's pace.
    assert service.handle("pi-2", {"text": "unrelated"})["ok"]


@pytest.mark.parametrize("text", ["", "   ", "x" * 801])
def test_text_bounds_are_enforced(service, text):
    with pytest.raises(ValueError):
        service.handle("pi-1", {"text": text})


def test_every_turn_is_audited(service):
    service.handle("pi-1", {"text": "play lofi"})
    _turn(service, "why is the sky blue?")

    assert [event for event, _node, _details in service.nodes.events] == [
        "conversation", "conversation",
    ]
    assert service.nodes.events[0][2]["commands"] == ["music.play"]


class TestCapabilityPolicy:
    """A voice node has to be able to speak on arrival without losing the
    blanket confirm-by-default rule for everything else."""

    CAPABILITIES = {
        "bluetooth.status": {"kind": "read"},
        "audio.speak": {"kind": "write"},
        "audio.listen": {"kind": "write"},
        "music.play": {"kind": "write"},
        "music.stop": {"kind": "write"},
        "console.command": {"kind": "write"},
        "camera.snapshot": {"kind": "write"},
    }

    def _register(self, registry, node_type="pi-proxy", node_id="pi-1"):
        pairing = registry.create_pairing("Pi")
        return registry.register(
            pairing["pairing_id"], pairing["pairing_code"], node_id, "Pi",
            node_type, self.CAPABILITIES,
        )

    def _policies(self, node):
        return {name: spec["policy"] for name, spec in node["capabilities"].items()}

    def test_pi_proxy_audio_is_allowed_on_arrival(self, tmp_path):
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        policies = self._policies(self._register(registry)["node"])

        assert policies["audio.speak"] == "allow"
        assert policies["music.play"] == "allow"
        assert policies["music.stop"] == "allow"
        # Reaching past the speaker still needs the owner.
        assert policies["console.command"] == "confirm"
        assert policies["camera.snapshot"] == "confirm"
        assert policies["audio.listen"] == "confirm"

    def test_allowed_audio_can_be_queued_without_confirmation(self, tmp_path):
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        self._register(registry)

        assert registry.enqueue("pi-1", "music.play", {"query": "lofi"})["capability"] == "music.play"
        with pytest.raises(PermissionError):
            registry.enqueue("pi-1", "console.command", {"platform": "xbox", "action": "on"})

    def test_heartbeat_redeclaration_does_not_reset_the_policies(self, tmp_path):
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        before = self._policies(self._register(registry)["node"])

        registry.update_capabilities("pi-1", self.CAPABILITIES)

        assert self._policies(registry.list_nodes()[0]) == before

    def test_an_owner_tightening_the_policy_still_wins(self, tmp_path):
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        self._register(registry)

        registry.set_policy("pi-1", "music.play", "deny")
        registry.update_capabilities("pi-1", self.CAPABILITIES)

        assert self._policies(registry.list_nodes()[0])["music.play"] == "deny"

    def test_other_node_types_keep_confirm_by_default(self, tmp_path):
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        node = self._register(registry, node_type="windows-gaming", node_id="win-1")["node"]

        assert self._policies(node)["audio.speak"] == "confirm"
        assert self._policies(node)["music.play"] == "confirm"

    def test_a_node_cannot_self_declare_allow_outside_the_allowlist(self, tmp_path):
        """The manifest is attacker-controlled: a node asking for `allow` on
        something outside its type's allowlist must still be downgraded."""
        registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
        pairing = registry.create_pairing("Pi")
        node = registry.register(
            pairing["pairing_id"], pairing["pairing_code"], "pi-1", "Pi", "pi-proxy",
            {"console.command": {"kind": "write", "policy": "allow"}},
        )["node"]

        assert node["capabilities"]["console.command"]["policy"] == "confirm"
