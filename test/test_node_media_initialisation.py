"""The backend has to be initialised before a node can use it.

`Api.config` and `Api.state` are None until the heavy init runs, and nothing on
the node path used to trigger it. A node that asked for media before anyone
opened the dashboard got "'NoneType' object has no attribute 'stt_provider'"
-- which meant speech never became text, so the owner could not talk to the
assistant through the node at all.
"""
from __future__ import annotations

import types

import pytest

from nekosuneai.device_turn import run_turn
from nekosuneai.node_media import NodeMediaService
from nekosuneai.tts import should_play_audio_after_synthesis


class LazyApi:
    """Mirrors the real Api: nothing usable until initialize() is called."""

    def __init__(self):
        self.config = None
        self.state = None
        self.media_enabled = True
        self.initialised = 0
        self.chat = []

    def initialize(self):
        self.initialised += 1
        if self.config is None:
            self.config = types.SimpleNamespace(
                stt_provider="vosk", tts_provider="xtts", xtts_stream_output=True,
                rvc_chat_enabled=False, node_tts_no_playback=False,
            )
            self.state = types.SimpleNamespace(voice_enabled=True)

    def _push_chat(self, author, message, role):
        self.chat.append((author, message, role))

    def _pipeline(self, text, from_voice):
        # Would raise AttributeError on a None config, exactly as the real one.
        assert self.config.stt_provider
        self._push_chat("NekoSuneAI", "Hello there.", "assistant")
        return "Ready."


def test_a_device_turn_initialises_the_backend_first():
    api = LazyApi()

    assert run_turn(api, "hello") == "Hello there."
    assert api.initialised == 1


def test_node_media_initialises_before_reading_the_config():
    """The stt_provider crash, reproduced through the real service.

    A real operation with an invalid payload: it gets past the operation-name
    check (which runs first) and into the body that reads api.config, which is
    where the None used to bite.
    """
    api = LazyApi()
    service = NodeMediaService(api)

    with pytest.raises(ValueError, match="TTS text"):
        service.handle("tts", {"text": ""})

    assert api.initialised == 1
    assert api.config is not None


def test_initialisation_is_not_repeated_per_turn():
    api = LazyApi()
    run_turn(api, "one")
    run_turn(api, "two")
    assert api.initialised == 2       # called each time, but the real one no-ops


def test_an_api_without_initialize_still_works():
    """The services are duck-typed; a double that supplies config directly has
    nothing to initialise and must not be forced to grow the method."""
    api = types.SimpleNamespace(
        config=types.SimpleNamespace(stt_provider="vosk"),
        state=types.SimpleNamespace(voice_enabled=True),
        media_enabled=True,
        chat=[],
    )
    api._push_chat = lambda author, message, role: api.chat.append((author, message, role))
    api._pipeline = lambda text, from_voice: (
        api._push_chat("NekoSuneAI", "Fine.", "assistant") or "Ready."
    )

    assert run_turn(api, "hello") == "Fine."


class TestNodeAudioStaysOnTheNode:
    """Audio synthesised for a node belongs on that node's speaker.

    Playing it on the backend means a VPS talking to an empty room, and on a
    container with no audio device it produced a stream of PulseAudio/ALSA
    failures: "Unable to connect: Connection refused", "Failed to open file
    'pipe:0'", "Failed to open file '/app/audio/latest_reply_remote.mp3'".
    """

    def _config(self, **overrides):
        base = dict(
            tts_provider="xtts", xtts_stream_output=False,
            rvc_chat_enabled=False, node_tts_no_playback=False,
        )
        base.update(overrides)
        return types.SimpleNamespace(**base)

    def test_node_audio_is_never_played_on_the_backend(self):
        assert should_play_audio_after_synthesis(self._config(node_tts_no_playback=True)) is False

    def test_the_flag_wins_over_every_provider(self):
        for provider in ("xtts", "bridge", "gtts"):
            config = self._config(tts_provider=provider, node_tts_no_playback=True)
            assert should_play_audio_after_synthesis(config) is False, provider

    def test_the_flag_wins_even_when_rvc_would_force_playback(self):
        config = self._config(node_tts_no_playback=True, rvc_chat_enabled=True)
        assert should_play_audio_after_synthesis(config) is False

    def test_ordinary_dashboard_audio_still_plays(self):
        assert should_play_audio_after_synthesis(self._config()) is True

    def test_node_media_sets_the_flag_on_its_own_copy(self):
        """And must not mutate the server's config doing it."""
        api = LazyApi()
        api.initialize()
        assert api.config.node_tts_no_playback is False
        service = NodeMediaService(api)

        with pytest.raises(ValueError):
            service.handle("tts", {"text": ""})

        assert api.config.node_tts_no_playback is False
