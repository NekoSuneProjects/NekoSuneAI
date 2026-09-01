import time

from nekosuneai.briefings import BriefingManager
from nekosuneai.home_events import HomeEventTimeline


def test_house_status_reports_devices_batteries_temperature_and_incidents(tmp_path):
    timeline = HomeEventTimeline(tmp_path / "timeline.json")
    manager = BriefingManager(
        timeline,
        lambda: [
            {"id": "thermo", "name": "Hall Sensor", "online": True, "state": {"temperature_c": 21.5}},
            {"id": "lock", "name": "Door Lock", "online": False, "state": {"battery": 12}},
        ],
        lambda: [{"node_id": "pi", "name": "Kitchen Pi", "online": True, "battery_percent": 80}],
        lambda: ["smoke:sensor"],
    )
    result = manager.house_status()
    assert "1 of 2 smart-home devices online" in result
    assert "active emergency sensors require attention" in result
    assert "Door Lock 12%" in result
    assert "Hall Sensor 21.5°C" in result
    assert "offline: Door Lock" in result


def test_local_weather_station_readings(tmp_path):
    manager = BriefingManager(
        HomeEventTimeline(tmp_path / "timeline.json"),
        lambda: [{
            "id": "garden-weather", "name": "Garden Weather", "online": True,
            "state": {"temperature_c": 14.2, "humidity": 81, "pressure_hpa": 1008, "rain_mm": 1.5},
        }],
        lambda: [], lambda: [],
    )
    result = manager.handle("local weather station readings")
    assert "Garden Weather: 14.2°C" in result
    assert "humidity 81%" in result
    assert "rain 1.5 mm" in result


def test_rss_briefing_attributes_sources_links_and_uncertainty(tmp_path):
    feed = b"""<?xml version='1.0'?><rss><channel><title>Official Example</title>
    <item><title>Confirmed service update</title><link>https://example.test/update</link></item>
    </channel></rss>"""
    manager = BriefingManager(
        HomeEventTimeline(tmp_path / "timeline.json"), lambda: [], lambda: [], lambda: [],
        rss_feeds=["https://example.test/feed.xml"], feed_fetcher=lambda _url: feed,
    )
    result = manager.news_briefing()
    assert result.startswith("Headlines from configured sources; details may be incomplete")
    assert "Official Example: Confirmed service update" in result
    assert "https://example.test/update" in result


def test_timeline_briefing_and_natural_commands(tmp_path):
    timeline = HomeEventTimeline(tmp_path / "timeline.json")
    timeline.record("sensor", "front-door.open", "Front door opened.", room="hall", epoch=time.time())
    manager = BriefingManager(timeline, lambda: [], lambda: [], lambda: [])
    assert "Front door opened" in manager.handle("what happened at home in the last 2 hours?")
    assert "latest matching event" in manager.handle("when did the front door last open?").lower()
    assert manager.handle("give me a house status briefing").startswith("House status:")


def test_news_briefing_requires_explicit_configured_feeds(tmp_path):
    manager = BriefingManager(HomeEventTimeline(tmp_path / "timeline.json"), lambda: [], lambda: [], lambda: [], rss_feeds=[])
    assert "No RSS briefing feeds are configured" in manager.handle("news briefing")
