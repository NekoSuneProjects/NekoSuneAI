"""Node-initiated conversation turns (contract NODE-CONVERSE-01).

Covers the endpoint's two jobs: running a turn the node started, and routing a
music request to the node's own speaker rather than the backend host's.
"""
from __future__ import annotations

import time

import pytest

from nekosuneai.node_converse import NodeConverseService
from nekosuneai.peripheral_nodes import PeripheralNodeRegistry

ALL_ALLOWED = {
    "music.play": "allow", "music.stop": "allow", "music.pause": "allow",
    "music.resume": "allow", "music.skip": "allow", "music.volume": "allow",
    "audio.speak": "allow",
}


class FakeNodes:
    def __init__(self, policies=None):
        self.policies = dict(policies if policies is not None else ALL_ALLOWED)
        self.events = []
        self.nodes = [{
            "node_id": "pi-1", "node_type": "pi-proxy", "online": True,
            "capabilities": {"music.play": {"kind": "write"}}, "state": {},
        }]

    def list_nodes(self):
        return list(self.nodes)

    def action_policy(self, node_id, capability):
        return self.policies.get(capability, "confirm")

    def record_event(self, event, node_id, **details):
        self.events.append((event, node_id, details))


class FakeState:
    voice_enabled = True


class FakeApi:
    """Stands in for webgui's Api.

    Reproduces the behaviour that caused the bug: the real `_pipeline` pushes
    the assistant's reply through `_push_chat` and *returns a UI status
    string*, so a test whose fake returns the reply directly would not have
    caught "hello" coming back as "Ready.".
    """

    def __init__(self, reply="The sky is blue.", status="Ready."):
        self.state = FakeState()
        self.media_enabled = True
        self.seen = []
        self.output_during_turn = []
        self.chat = []
        self._reply = reply
        self._status = status

    def _push_chat(self, author, message, role):
        self.chat.append((author, message, role))

    def _pipeline(self, text, from_voice):
        self.seen.append(text)
        self.output_during_turn.append((self.state.voice_enabled, self.media_enabled))
        if self._reply is not None:
            self._push_chat("System", f"Searching: {text}", "system")
            self._push_chat("NekoSuneAI", self._reply, "assistant")
        return self._status


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


@pytest.mark.parametrize(
    ("phrase", "capability"),
    [
        ("stop the music", "music.stop"),
        ("pause the music", "music.pause"),
        ("resume the music", "music.resume"),
        ("skip this song", "music.skip"),
    ],
)
def test_transport_controls_reach_the_node(service, phrase, capability):
    result = service.handle("pi-1", {"text": phrase})
    assert result["commands"][0]["capability"] == capability


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


class TestReplyCapture:
    """The assistant's words, not the GUI's status line.

    `_pipeline` is written for the desktop UI: it pushes the real reply through
    `_push_chat` and returns "Ready." / "Hands-free listening." / "Media
    request handled.". Using that return value meant a node asking "hello" was
    told "Ready." instead of being answered.
    """

    def _service(self, **kwargs):
        return NodeConverseService(FakeApi(**kwargs), FakeNodes(), FakeMedia())

    def test_the_llm_reply_is_returned_not_the_status_string(self):
        service = self._service(reply="Hello! How can I help?", status="Ready.")

        result = service.handle("pi-1", {"text": "hello"})

        assert result["reply"] == "Hello! How can I help?"
        assert result["reply"] != "Ready."

    @pytest.mark.parametrize(
        "status",
        ["Ready.", "Hands-free listening.", "Stopped.", "Media request handled."],
    )
    def test_no_ui_status_string_can_become_a_reply(self, status):
        """Every status `_pipeline` can return, not just the one that was seen."""
        service = self._service(reply=None, status=status)

        result = service.handle("pi-1", {"text": "hello"})

        assert result["reply"] == "Sorry, I didn't catch that."

    def test_system_notices_are_not_mistaken_for_the_reply(self):
        """Web-search progress lines go through _push_chat too, as "system"."""
        service = self._service(reply="Paris is the capital.")

        result = service.handle("pi-1", {"text": "what is the capital of france"})

        assert result["reply"] == "Paris is the capital."
        # The pipeline really did emit a system line alongside it.
        assert any(role == "system" for _author, _text, role in service.api.chat)

    def test_an_error_message_still_reaches_the_owner(self):
        """A failure has no assistant push, but its text is worth relaying."""
        service = self._service(reply=None, status="[Companion error] Ollama is unreachable")

        result = service.handle("pi-1", {"text": "hello"})

        assert "Ollama is unreachable" in result["reply"]

    def test_push_chat_is_restored_after_the_turn(self):
        """The capture swaps an attribute on the shared Api object.

        Restored by deletion rather than reassignment, so the object is left
        exactly as found -- no instance attribute shadowing the class method.
        """
        service = self._service()

        service.handle("pi-1", {"text": "hello"})

        assert "_push_chat" not in vars(service.api)
        assert service.api._push_chat.__func__ is FakeApi._push_chat

    def test_push_chat_is_restored_even_when_the_pipeline_raises(self):
        service = self._service()
        service.api._pipeline = lambda text, from_voice: (_ for _ in ()).throw(RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            service.handle("pi-1", {"text": "hello"})

        assert "_push_chat" not in vars(service.api)
        assert service.api._push_chat.__func__ is FakeApi._push_chat

    def test_an_api_that_already_owns_push_chat_keeps_it(self):
        """webserver.py assigns instance attributes onto Api (see _pipeline),
        so an owned _push_chat must be put back, not deleted."""
        service = self._service()
        replacement = lambda author, message, role: service.api.chat.append((author, message, role))
        service.api._push_chat = replacement

        service.handle("pi-1", {"text": "hello"})

        assert service.api._push_chat is replacement

    def test_the_reply_still_reaches_the_dashboard(self):
        """Capturing must not swallow the push the dashboard depends on."""
        service = self._service(reply="Hello there.")

        service.handle("pi-1", {"text": "hello"})

        assert ("NekoSuneAI", "Hello there.", "assistant") in service.api.chat

    def test_the_spoken_reply_is_the_llm_answer(self):
        """What gets synthesised is what the owner actually hears."""
        media = FakeMedia()
        media.spoken = []
        original = media.handle

        def record(operation, payload):
            media.spoken.append(payload["text"])
            return original(operation, payload)

        media.handle = record
        service = NodeConverseService(FakeApi(reply="It is raining."), FakeNodes(), media)

        service.handle("pi-1", {"text": "what is the weather"})

        assert media.spoken == ["It is raining."]
