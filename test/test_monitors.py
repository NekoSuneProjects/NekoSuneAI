import unittest

from nekosuneai.monitors import Monitor, _summary, parse_monitor_request


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

    def test_cleans_government_alert_for_tts(self):
        monitor = Monitor("alert1", "UK alerts", "emergency_alerts", {"region":"GB"}, 300)
        spoken = _summary(monitor, {"structuredContent":{"alerts":[{"headline":"Flood warning", "severity":"Severe", "instruction":"Move to higher ground."}]}})
        self.assertIn("Government emergency broadcast", spoken)
        self.assertIn("Flood warning", spoken)
        self.assertNotIn("structuredContent", spoken)


if __name__ == "__main__":
    unittest.main()
