"""Running a turn on behalf of a device, and getting back what was said.

The backend is the brain; the device is where the conversation happens. Every
remote surface -- Pi Proxy, the Android app -- needs the assistant's actual
words to say on its own speaker, and needs the backend host to stay quiet
while it does.
"""
from __future__ import annotations

import pytest

from nekosuneai.device_turn import UI_STATUS_STRINGS, run_turn


class FakeState:
    voice_enabled = True


class FakeApi:
    """Mirrors the real contract: push the reply, return a UI status string.

    A double that returned the reply from `_pipeline` is exactly why this bug
    reached two shipped endpoints without a test noticing.
    """

    def __init__(self, reply="The sky is blue.", status="Ready."):
        self.state = FakeState()
        self.media_enabled = True
        self.chat = []
        self.seen = []
        self.output_during_turn = []
        self._reply = reply
        self._status = status

    def _push_chat(self, author, message, role):
        self.chat.append((author, message, role))

    def _pipeline(self, text, from_voice):
        self.seen.append((text, from_voice))
        self.output_during_turn.append((self.state.voice_enabled, self.media_enabled))
        self._push_chat("You", text, "user")
        if self._reply is not None:
            self._push_chat("System", f"Searching: {text}", "system")
            self._push_chat("NekoSuneAI", self._reply, "assistant")
        return self._status


def test_the_assistant_reply_is_returned_not_the_status():
    api = FakeApi(reply="Hello! How can I help?", status="Ready.")

    assert run_turn(api, "hello") == "Hello! How can I help?"


@pytest.mark.parametrize("status", sorted(UI_STATUS_STRINGS))
def test_no_ui_status_string_can_become_a_reply(status):
    """Every status `_pipeline` can return, not only the one that was reported."""
    assert run_turn(FakeApi(reply=None, status=status), "hello") == ""


def test_system_notices_are_not_mistaken_for_the_reply():
    api = FakeApi(reply="Paris.")

    assert run_turn(api, "capital of france") == "Paris."
    assert any(role == "system" for _a, _t, role in api.chat)


def test_an_error_message_is_relayed():
    api = FakeApi(reply=None, status="[Companion error] Ollama is unreachable")

    assert "Ollama is unreachable" in run_turn(api, "hello")


def test_the_backend_host_stays_quiet_during_the_turn():
    """The owner is at the device; the backend must not talk to an empty room."""
    api = FakeApi()

    run_turn(api, "hello")

    assert api.output_during_turn == [(False, False)]
    assert api.state.voice_enabled is True      # restored
    assert api.media_enabled is True


def test_the_reply_still_reaches_the_backend_dashboard():
    api = FakeApi(reply="Hello there.")

    run_turn(api, "hello")

    assert ("NekoSuneAI", "Hello there.", "assistant") in api.chat


def test_the_speaker_is_attributed_to_the_device():
    """A question asked in the living room should not read as typed here."""
    api = FakeApi()

    run_turn(api, "hello", speaker="Living Room Pi")

    assert ("Living Room Pi", "hello", "user") in api.chat


def test_without_a_speaker_the_author_is_left_alone():
    api = FakeApi()

    run_turn(api, "hello")

    assert ("You", "hello", "user") in api.chat


def test_from_voice_is_passed_through():
    api = FakeApi()

    run_turn(api, "hello", from_voice=True)

    assert api.seen == [("hello", True)]


class TestRestoration:
    def test_push_chat_is_left_exactly_as_found(self):
        api = FakeApi()

        run_turn(api, "hello")

        assert "_push_chat" not in vars(api)
        assert api._push_chat.__func__ is FakeApi._push_chat

    def test_restored_even_when_the_pipeline_raises(self):
        api = FakeApi()
        api._pipeline = lambda text, from_voice: (_ for _ in ()).throw(RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            run_turn(api, "hello")

        assert "_push_chat" not in vars(api)
        assert api.state.voice_enabled is True
        assert api.media_enabled is True

    def test_an_api_that_already_owns_push_chat_keeps_it(self):
        """webserver.py assigns instance attributes onto Api (see api._pipeline),
        so an owned _push_chat must be restored, not deleted."""
        api = FakeApi()
        replacement = lambda author, message, role: api.chat.append((author, message, role))
        api._push_chat = replacement

        run_turn(api, "hello")

        assert api._push_chat is replacement


def test_no_remote_surface_uses_the_pipeline_return_value_directly():
    """Guard against this bug reappearing in a future endpoint.

    `_pipeline`'s return value is a UI status string. Both /api/nodes/converse
    and /api/android/chat shipped using it as the reply, answering the device
    with "Ready." while discarding what the assistant actually said. Any new
    remote surface must go through run_turn instead.

    webgui.py is exempt: it is the desktop GUI the status strings exist for.
    """
    import ast
    import pathlib

    offenders = []
    for path in sorted(pathlib.Path("nekosuneai").glob("*.py")):
        if path.name in {"webgui.py", "device_turn.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # A call to *._pipeline(...) whose result is bound or returned is
            # the shape of the bug; _pipeline being *assigned* is a different
            # thing (webserver installs its own) and is fine.
            if not isinstance(node, (ast.Assign, ast.Return)):
                continue
            value = node.value
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "_pipeline"):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "these use _pipeline's return value (a UI status string) as a reply; "
        f"use device_turn.run_turn instead: {offenders}"
    )
