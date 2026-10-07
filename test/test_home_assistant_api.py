from types import SimpleNamespace

from nekosuneai.home_assistant_api import HomeAssistantApi
from nekosuneai.home_assistant import HomeAssistantMqtt


def _entity(entity_id, state="off", name=None, **attrs):
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": {"friendly_name": name or entity_id.split(".", 1)[1].replace("_", " "), **attrs},
        "last_changed": "2026-10-07T00:00:00+00:00",
        "last_updated": "2026-10-07T00:00:00+00:00",
    }


def test_media_player_voice_commands_cover_xbox_tv_and_cast(monkeypatch):
    api = HomeAssistantApi("http://ha.local:8123", "token", websocket_enabled=False)
    api._entities = {
        "media_player.xbox": _entity("media_player.xbox", "on", "Living Room Xbox", source="Home"),
        "media_player.tv": _entity("media_player.tv", "on", "Living Room TV", source="HDMI 1"),
    }
    calls = []

    def call(entity_id, service, data=None, confirmed=False):
        calls.append((entity_id, service, data or {}, confirmed))
        return "ok"

    monkeypatch.setattr(api, "call_service", call)

    assert api.handle("pause on living room xbox") == "ok"
    assert calls[-1][:3] == ("media_player.xbox", "media_pause", {})

    assert api.handle("set living room tv volume to 35%") == "ok"
    assert calls[-1][:3] == ("media_player.tv", "volume_set", {"volume_level": 0.35})

    assert api.handle("switch living room tv source to HDMI 2") == "ok"
    assert calls[-1][:3] == ("media_player.tv", "select_source", {"source": "hdmi 2"})

    assert api.handle("launch Netflix on living room xbox") == "ok"
    assert calls[-1][:3] == ("media_player.xbox", "select_source", {"source": "netflix"})


def test_cover_climate_vacuum_scene_and_button(monkeypatch):
    api = HomeAssistantApi("http://ha.local:8123", "token", websocket_enabled=False)
    api._entities = {
        "cover.blinds": _entity("cover.blinds", "closed", "Bedroom Blinds"),
        "climate.heating": _entity("climate.heating", "heat", "Heating"),
        "vacuum.robot": _entity("vacuum.robot", "docked", "Robot Vacuum"),
        "scene.movie": _entity("scene.movie", "scening", "Movie Mode"),
        "button.coffee": _entity("button.coffee", "unknown", "Coffee Maker"),
    }
    calls = []

    def call(entity_id, service, data=None, confirmed=False):
        calls.append((entity_id, service, data or {}, confirmed))
        return "ok"

    monkeypatch.setattr(api, "call_service", call)

    assert api.handle("set bedroom blinds position to 40%") == "ok"
    assert calls[-1][:3] == ("cover.blinds", "set_cover_position", {"position": 40})

    assert api.handle("set heating to 21 degrees") == "ok"
    assert calls[-1][:3] == ("climate.heating", "set_temperature", {"temperature": 21.0})

    assert api.handle("start robot vacuum") == "ok"
    assert calls[-1][:2] == ("vacuum.robot", "start")

    assert api.handle("activate movie mode") == "ok"
    assert calls[-1][:2] == ("scene.movie", "turn_on")

    assert api.handle("press coffee maker") == "ok"
    assert calls[-1][:2] == ("button.coffee", "press")


def test_unlock_requires_explicit_confirmation(monkeypatch):
    api = HomeAssistantApi("http://ha.local:8123", "token", websocket_enabled=False)
    api._entities = {"lock.front": _entity("lock.front", "locked", "Front Door")}
    monkeypatch.setattr(api, "_request", lambda *a, **k: None)

    try:
        api.call_service("lock.front", "unlock")
    except PermissionError as exc:
        assert "confirmation" in str(exc)
    else:
        raise AssertionError("unlock should require confirmation")


def test_home_assistant_wrapper_works_without_mqtt(monkeypatch):
    config = SimpleNamespace(
        home_assistant_url="http://ha.local:8123",
        home_assistant_token="token",
        home_assistant_verify_tls=True,
        home_assistant_websocket_enabled=False,
        home_assistant_mqtt_host=None,
        home_assistant_mqtt_port=1883,
        home_assistant_mqtt_username=None,
        home_assistant_mqtt_password=None,
    )
    integration = HomeAssistantMqtt(config, lambda _text: None)
    integration.api._entities = {
        "media_player.xbox": _entity("media_player.xbox", "on", "Xbox"),
    }
    integration.api.connected = True

    assert integration.status()["configured"] is True
    assert integration.status()["connected"] is True
    assert any(x["entity_id"] == "media_player.xbox" for x in integration.list_devices())
