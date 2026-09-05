from unittest.mock import Mock

import pytest
import requests

from nekosuneai.vrchat_osc import VrchatOsc
from nekosuneai.windows_gaming_agent import WindowsGamingAgent
from nekosuneai.world_mapper import WorldMapper


def make_agent():
    agent = WindowsGamingAgent.__new__(WindowsGamingAgent)
    agent.realtime = Mock()
    agent.vrchat = VrchatOsc(client=Mock())
    agent.vrchat.arm()
    agent.world_mapper = WorldMapper(agent)
    agent.world_mapper.running = True
    return agent


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), http_error(503), http_error(429)])
def test_manual_mapper_survives_temporary_backend_failure(error):
    agent = make_agent()
    agent._handle_connection_failure(error)
    agent._handle_connection_failure(error)
    assert agent.vrchat.armed.is_set()
    assert not agent.world_mapper._stop.is_set()
    agent.world_mapper._try_forward(.02, 2)
    assert agent.world_mapper.steps == 1
    assert "continues locally" in agent.world_mapper.events[-1]
    assert len(agent.world_mapper.events) == 1
    agent.realtime.cancel.assert_called_with()


@pytest.mark.parametrize("error", [http_error(401), http_error(403), http_error(400), ValueError(), requests.exceptions.SSLError()])
def test_authentication_and_unexpected_failures_stop_mapper(error):
    agent = make_agent()
    agent._handle_connection_failure(error)
    assert not agent.vrchat.armed.is_set()
    assert agent.world_mapper._stop.is_set()
    assert "Backend" in agent.vrchat.status()["disarm_reason"]
    with pytest.raises(PermissionError, match="Backend"):
        agent.world_mapper._try_forward(.02, 2)


def test_remote_session_still_disarms_on_connection_loss():
    agent = make_agent()
    agent.world_mapper.running = False
    agent._handle_connection_failure(requests.Timeout())
    assert not agent.vrchat.armed.is_set()


def test_explicit_stop_cannot_be_undone_by_reconnect_handler():
    agent = make_agent()
    agent._execute({"capability": "game.input.stop"})
    agent._handle_connection_failure(requests.Timeout())
    assert agent.world_mapper._stop.is_set()
    assert not agent.vrchat.armed.is_set()
    agent.realtime.cancel.assert_any_call(disable=True)


@pytest.mark.parametrize("capability", ["vrchat.input", "vrchat.avatar.set", "game.skill", "game.plan"])
def test_manual_mapper_excludes_remote_movement(capability):
    agent = make_agent()
    with pytest.raises(PermissionError, match="owns movement"):
        agent._execute({"capability": capability})
    agent.vrchat.client.send_message.assert_not_called()
