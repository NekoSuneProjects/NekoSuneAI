from nekosuneai.home_events import HomeEventTimeline
from nekosuneai.home_safety import HomeSafetyManager


def test_smoke_alarm_broadcasts_once_then_reports_clear(tmp_path):
    notices = []
    timeline = HomeEventTimeline(tmp_path / "timeline.json")
    safety = HomeSafetyManager(lambda message, level: notices.append((message, level)), timeline)
    device = {
        "id": "kitchen-smoke", "name": "Kitchen Smoke", "room": "kitchen",
        "device_class": "smoke", "state": {"value": "ON"},
    }
    result = safety.ingest(device)
    assert result["status"] == "active"
    assert notices[0][1] == "danger"
    assert "Smoke detected in kitchen" in notices[0][0]
    assert safety.ingest(device) is None
    assert len(notices) == 1

    device["state"]["value"] = "OFF"
    assert safety.ingest(device)["status"] == "clear"
    assert notices[-1][1] == "warning"
    assert safety.active_incidents() == []
    assert [row["event"] for row in timeline.query(category="safety")] == ["smoke.active", "smoke.clear"]


def test_non_hazard_sensor_is_ignored(tmp_path):
    notices = []
    safety = HomeSafetyManager(lambda *args: notices.append(args), HomeEventTimeline(tmp_path / "timeline.json"))
    assert safety.ingest({"id": "motion", "device_class": "motion", "state": {"value": "ON"}}) is None
    assert notices == []
