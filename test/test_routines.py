import time

import pytest

from nekosuneai.routines import RoutineManager


def _routine(name="Movie mode", event="movie.requested", capability="light.set"):
    return {
        "name": name,
        "triggers": [{"type": "event", "event": event}],
        "conditions": [{"path": "room.occupied", "operator": "eq", "value": True}],
        "actions": [{
            "node_id": "living-room",
            "capability": capability,
            "arguments": {"brightness": 20},
            "undo": {"node_id": "living-room", "capability": capability, "arguments": {"brightness": 100}},
        }],
    }


def test_create_preview_run_explain_and_persist(tmp_path):
    calls = []

    def execute(action):
        calls.append(action)
        return {"queued": True, "undo": action.get("undo")} if action.get("undo") else {"queued": True}

    path = tmp_path / "routines.json"
    manager = RoutineManager(execute, path)
    routine = manager.create(_routine())

    blocked = manager.preview(routine["id"], {"room": {"occupied": False}})
    assert blocked["would_run"] is False
    assert "condition failed" in blocked["blockers"][0]

    result = manager.run("movie mode", {"room": {"occupied": True}})
    assert result["status"] == "completed"
    assert calls[0]["capability"] == "light.set"
    assert manager.explain(routine["id"])["last_execution"]["status"] == "completed"
    assert RoutineManager(execute, path).list()[0]["name"] == "Movie mode"


def test_event_conditions_conflicts_and_expiry(tmp_path):
    manager = RoutineManager(lambda action: {"queued": True}, tmp_path / "routines.json")
    manager.create(_routine("Movie lights"))
    manager.create(_routine("Movie lights backup"))
    manager.create({**_routine("Temporary", "temporary.event", "audio.speak"), "expires_epoch": time.time() + 60})

    assert len(manager.conflicts()) == 1
    results = manager.handle_event("movie.requested", {"room": {"occupied": True}})
    assert [x["status"] for x in results] == ["completed", "completed"]
    assert len(manager.list()) == 3

    temporary = next(x for x in manager._routines.values() if x["name"] == "Temporary")
    temporary["expires_epoch"] = time.time() - 1
    assert len(manager.list()) == 2
    expired = manager.preview(temporary["id"], {"room": {"occupied": True}})
    assert expired["would_run"] is False


def test_large_action_confirmation_and_undo(tmp_path):
    calls = []

    def execute(action):
        calls.append(action)
        return {"undo": action.get("undo")} if action.get("undo") else {"ok": True}

    manager = RoutineManager(execute, tmp_path / "routines.json")
    payload = _routine("Whole home")
    payload["conditions"] = []
    payload["actions"] = [
        {
            "node_id": f"room-{i}",
            "capability": "light.set",
            "arguments": {"on": False},
            "undo": {"node_id": f"room-{i}", "capability": "light.set", "arguments": {"on": True}},
        }
        for i in range(5)
    ]
    manager.create(payload)
    assert manager.run("Whole home")["status"] == "confirmation_required"
    assert manager.run("Whole home", confirmed=True)["status"] == "completed"
    assert manager.undo_last()["ok"] is True
    assert len(calls) == 10


def test_validation_and_natural_commands(tmp_path):
    manager = RoutineManager(lambda action: {"ok": True}, tmp_path / "routines.json")
    with pytest.raises(ValueError, match="action"):
        manager.create({"name": "Empty", "actions": []})
    manager.create({"name": "Good night", "actions": [{"node_id": "bedroom", "capability": "light.off"}]})
    assert manager.handle("run good night") == "Ran Good night with 1 action(s)."
    assert "last finished as completed" in manager.handle("why did good night run?")


def test_policy_resolver_blocks_denied_and_requires_confirmation(tmp_path):
    calls = []
    policies = {"light.set": "confirm", "door.unlock": "deny"}
    manager = RoutineManager(
        lambda action: calls.append(action) or {"ok": True},
        tmp_path / "routines.json",
        policy_resolver=lambda action: policies[action["capability"]],
    )
    manager.create({"name": "Lights", "actions": [{"node_id": "room", "capability": "light.set"}]})
    assert manager.run("Lights")["status"] == "confirmation_required"
    assert manager.handle("confirm run lights") == "Ran Lights with 1 action(s)."

    manager.create({"name": "Door", "actions": [{"node_id": "hall", "capability": "door.unlock"}]})
    preview = manager.preview("Door")
    assert preview["would_run"] is False
    assert "denied" in preview["blockers"][0]
