"""Routing music to a Pi Proxy node instead of playing it on the backend host.

The backend may be a VPS: YouTube's bot check blocks its datacenter IP, and
its speaker is in a datacenter rather than the owner's living room. When a Pi
Proxy is online, music requests become node commands instead.
"""
from __future__ import annotations

import pytest

from nekosuneai.node_music import NodeMusicRouter

PI = {
    "node_id": "pi-living-room", "node_type": "pi-proxy", "online": True,
    "name": "Living Room Pi",
    "capabilities": {"music.play": {"kind": "write"}, "music.skip": {"kind": "write"}},
    "state": {},
}


def router(nodes=None, node_id=""):
    return NodeMusicRouter(lambda: list(nodes if nodes is not None else [PI]), node_id=node_id)


class Enqueued(list):
    def __call__(self, node_id, capability, arguments, **kwargs):
        self.append((node_id, capability, arguments, kwargs))
        return {"id": len(self)}


@pytest.mark.parametrize(
    ("text", "capability", "arguments"),
    [
        ("play lofi hip hop", "music.play", {"query": "lofi hip hop"}),
        ("stop the music", "music.stop", {}),
        ("pause the music", "music.pause", {}),
        ("resume the music", "music.resume", {}),
        ("skip this song", "music.skip", {}),
        ("previous track", "music.skip", {"previous": True}),
        ("set volume to 40", "music.volume", {"percent": 40}),
    ],
)
def test_music_phrasings_map_to_node_commands(text, capability, arguments):
    reply, commands = router().plan(text)

    assert commands == [{"capability": capability, "arguments": arguments}]
    assert reply


def test_play_is_routed_to_the_node_not_the_backend_player():
    enqueue = Enqueued()

    reply = router().handle("play lofi hip hop", enqueue)

    assert reply == "Playing lofi hip hop."
    node_id, capability, arguments, kwargs = enqueue[0]
    assert (node_id, capability) == ("pi-living-room", "music.play")
    assert arguments == {"query": "lofi hip hop"}
    # Owner-initiated, so it does not sit waiting for a second confirmation.
    assert kwargs["confirmed"] is True


def test_no_node_online_falls_back_to_the_backend_player():
    """A deployment without a Pi Proxy must keep working exactly as before."""
    offline = dict(PI, online=False)

    assert router([offline]).handle("play lofi", Enqueued()) is None
    assert router([]).handle("play lofi", Enqueued()) is None


def test_a_node_without_music_support_is_not_chosen():
    other = dict(PI, node_type="windows-gaming", capabilities={"game.skill": {"kind": "write"}})
    assert router([other]).target_node() is None


def test_explicit_node_id_wins_over_auto_selection():
    kitchen = dict(PI, node_id="pi-kitchen", name="Kitchen Pi")

    chosen = router([PI, kitchen], node_id="pi-kitchen").target_node()

    assert chosen["node_id"] == "pi-kitchen"


def test_several_online_pis_pick_deterministically():
    kitchen = dict(PI, node_id="pi-kitchen")
    assert router([PI, kitchen]).target_node()["node_id"] == "pi-kitchen"
    assert router([kitchen, PI]).target_node()["node_id"] == "pi-kitchen"


@pytest.mark.parametrize("text", ["what is the weather", "play a game", "tell me a joke", ""])
def test_non_music_requests_are_left_alone(text):
    assert router().plan(text) is None
    assert router().handle(text, Enqueued()) is None


def test_louder_and_quieter_step_the_volume():
    shared = router()

    assert shared.plan("turn the music up")[1][0]["arguments"]["percent"] == 85
    assert shared.plan("turn the music up")[1][0]["arguments"]["percent"] == 95
    assert shared.plan("turn the music down")[1][0]["arguments"]["percent"] == 85


def test_volume_is_clamped_to_a_sane_range():
    assert router().plan("set volume to 500")[1][0]["arguments"]["percent"] == 100


def test_status_is_answered_from_heartbeat_state_without_queuing():
    playing = dict(PI, state={"music": {"title": "Lofi Girl", "queued": 3, "paused": False}})
    enqueue = Enqueued()

    reply = router([playing]).handle("what's playing", enqueue)

    assert reply == "Playing Lofi Girl, 3 more queued."
    assert enqueue == []


def test_status_reports_a_paused_track():
    paused = dict(PI, state={"music": {"title": "Lofi Girl", "paused": True}})
    assert router([paused]).handle("what's playing", Enqueued()) == "Lofi Girl is paused."


def test_status_with_nothing_playing():
    assert "Nothing is playing" in router().handle("what's playing", Enqueued())


def test_a_blocked_capability_explains_itself_instead_of_failing_silently():
    def refuse(*args, **kwargs):
        raise PermissionError("music.play is denied for this node")

    reply = router().handle("play lofi", refuse)

    assert "Living Room Pi" in reply and "dashboard" in reply


def test_an_older_node_missing_a_control_falls_back_to_the_backend():
    """A Pi Proxy that only advertises play/stop must not have `skip` silently
    swallowed -- the backend's own player should get the request instead."""

    def unsupported(*args, **kwargs):
        raise ValueError("node does not advertise music.skip")

    assert router().handle("skip this song", unsupported) is None
