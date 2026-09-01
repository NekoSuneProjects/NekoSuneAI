import json
import time

from nekosuneai.home_events import HomeEventTimeline


def test_timeline_persists_queries_and_redacts_secret_fields(tmp_path):
    path = tmp_path / "timeline.json"
    timeline = HomeEventTimeline(path, retention_days=7)
    row = timeline.record(
        "sensor", "door.open", "Front door opened", room="hall", source="door-1",
        details={"value": "OPEN", "access_token": "do-not-store", "nested": {"api_key": "also-secret"}},
    )
    assert row["details"] == {"value": "OPEN", "nested": {}}
    restored = HomeEventTimeline(path, retention_days=7)
    assert restored.query(category="sensor", room="hall")[0]["summary"] == "Front door opened"
    assert restored.latest("door", "hall")["event"] == "door.open"
    assert "do-not-store" not in path.read_text("utf-8")


def test_timeline_prunes_expired_rows(tmp_path):
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps({"events": [{"epoch": time.time() - 3 * 86400, "event": "old"}]}), "utf-8")
    timeline = HomeEventTimeline(path, retention_days=1)
    assert timeline.query() == []
