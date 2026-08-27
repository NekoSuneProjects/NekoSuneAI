import unittest

from nekosuneai.monitors import Monitor, _summary, _weather_alert_level, parse_monitor_request


class MonitorParsingTests(unittest.TestCase):
    def test_creates_aircraft_schedule(self):
        action, monitor = parse_monitor_request(
            "Track aircraft within 30 miles around Newcastle upon Tyne every 5 minutes and keep me posted"
        )
        self.assertEqual(action, "create")
        self.assertIsInstance(monitor, Monitor)
        self.assertEqual(monitor.tool, "aircraft_nearby")
        self.assertEqual(monitor.arguments["location"], "Newcastle upon Tyne")
        self.assertEqual(monitor.interval_seconds, 300)

    def test_creates_weather_schedule(self):
        action, monitor = parse_monitor_request(
            "Monitor weather forecast for Newcastle upon Tyne every 15 minutes until I tell you to stop"
        )
        self.assertEqual(action, "create")
        self.assertEqual(monitor.tool, "weather_now")
        self.assertEqual(monitor.arguments["location"], "Newcastle upon Tyne")
        self.assertEqual(monitor.interval_seconds, 900)

    def test_stops_all(self):
        self.assertEqual(parse_monitor_request("stop all scheduled tasks"), ("stop_all", None))

    def test_clear_monitor_phrases(self):
        self.assertEqual(parse_monitor_request("Stop all monitors"), ("stop_all", None))
        self.assertEqual(parse_monitor_request("Clear all scheduled monitors"), ("stop_all", None))

    def test_summarizes_bridge_aircraft_without_reading_raw_json(self):
        monitor = Monitor("plane1", "aircraft — North Shields", "aircraft_nearby", {}, 300)
        payload = {"content": [{"type": "text", "text":
            '{"provider":"adsb.lol","reference":{"name":"North Shields","displayName":"North Shields, North Tyneside, England, United Kingdom","latitude":55.01646,"longitude":-1.44925},"count":1,"aircraft":[{"callsign":"SHT12U","distanceNm":8.3,"movement":{"phase":"ground","note":"Aircraft reports itself on the ground."}}]}'}]}
        spoken = _summary(monitor, payload)
        self.assertIn("North Shields", spoken)
        self.assertIn("1 detected", spoken)
        self.assertIn("SHT12U", spoken)
        self.assertIn("reports itself on the ground", spoken)
        self.assertNotIn('"aircraft"', spoken)
        self.assertNotIn("55.01646", spoken)
        self.assertNotIn("adsb.lol", spoken)

    def test_labels_military_only_results(self):
        monitor = Monitor("mil1", "military aircraft — saved area", "military_aircraft_nearby", {}, 300)
        spoken = _summary(monitor, {"reference": {"name": "saved area"}, "count": 0, "aircraft": []})
        self.assertIn("military aircraft update", spoken)
        self.assertIn("none were detected", spoken)

    def test_warns_when_rain_is_due_within_fifteen_minutes(self):
        monitor = Monitor("rain1", "weather — saved area", "weather_now", {}, 300)
        payload = {
            "location": {"name": "North Shields", "latitude": 55.01, "longitude": -1.44},
            "current": {"temperatureC": 12, "windSpeedKmh": 18},
            "rain": {"currentlyWet": False, "rainEtaMinutes": 15},
            "lightning": {"risk": "low"},
        }
        spoken = _summary(monitor, payload)
        self.assertEqual(_weather_alert_level("weather_now", payload), "warning")
        self.assertIn("Warning: rain is expected in about 15 minutes", spoken)
        self.assertNotIn("latitude", spoken)

    def test_does_not_warn_for_rain_later_than_fifteen_minutes(self):
        payload = {"rain": {"currentlyWet": False, "rainEtaMinutes": 45}, "lightning": {"risk": "low"}}
        self.assertEqual(_weather_alert_level("weather_now", payload), "none")

    def test_cleans_government_alert_for_tts(self):
        monitor = Monitor("alert1", "UK alerts", "emergency_alerts", {"region":"GB"}, 300)
        spoken = _summary(monitor, {"structuredContent":{"alerts":[{"headline":"Flood warning", "severity":"Severe", "instruction":"Move to higher ground."}]}})
        self.assertIn("Government emergency broadcast", spoken)
        self.assertIn("Flood warning", spoken)
        self.assertNotIn("structuredContent", spoken)


if __name__ == "__main__":
    unittest.main()
