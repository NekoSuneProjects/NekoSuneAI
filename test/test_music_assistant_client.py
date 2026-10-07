from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nekosuneai.music_assistant_client import MusicAssistantClient, MusicAssistantError


def response(payload, status=200):
    item = Mock()
    item.status_code = status
    item.ok = status < 400
    item.json.return_value = payload
    return item


def test_search_then_play_uses_music_assistant_queue():
    client = MusicAssistantClient("http://ma.local:8095", "token", "living-room")
    client.session.post = Mock(side_effect=[
        response({"result": {
            "tracks": [{
                "name": "Hardstyle Mix",
                "uri": "library://track/42",
                "artists": [{"name": "DJ Test"}],
            }]
        }}),
        response({"result": None}),
    ])

    result = client.play_query("hardstyle mix")

    assert result["name"] == "Hardstyle Mix"
    assert result["artist"] == "DJ Test"
    first = client.session.post.call_args_list[0].kwargs["json"]
    assert first["command"] == "music/search"
    assert first["args"]["search_query"] == "hardstyle mix"
    second = client.session.post.call_args_list[1].kwargs["json"]
    assert second == {
        "message_id": "2",
        "command": "player_queues/play_media",
        "args": {"queue_id": "living-room", "media": "library://track/42"},
    }


def test_auth_failure_has_useful_error():
    client = MusicAssistantClient("http://ma.local:8095", "bad", "living-room")
    client.session.post = Mock(return_value=response({"error": "forbidden"}, 401))
    with pytest.raises(MusicAssistantError, match="rejected"):
        client.search("test")


def test_not_configured_player_does_not_claim_playback():
    client = MusicAssistantClient("http://ma.local:8095", "token", "")
    with pytest.raises(MusicAssistantError, match="player id"):
        client.play_query("test")
