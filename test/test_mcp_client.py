import json
import unittest
from unittest.mock import Mock

from nekosuneai.mcp_client import McpClient, McpServerConfig, route_tool


class McpRoutingTests(unittest.TestCase):
    def test_routes_realtime_requests(self):
        self.assertEqual(route_tool("show rain radar near me")[0], "weather_radar")
        self.assertEqual(route_tool("any military aircraft near me?")[0], "military_aircraft_nearby")

    def test_preserves_selected_area_and_radius(self):
        tool, args = route_tool("track aircraft within 30 miles around Newcastle upon Tyne every 5 minutes")
        self.assertEqual(tool, "aircraft_nearby")
        self.assertEqual(args["location"], "Newcastle upon Tyne")
        self.assertEqual(args["radius_nm"], 30.0)

    def test_routes_uk_government_broadcast(self):
        tool, args = route_tool("monitor UK government emergency broadcasts every 5 minutes")
        self.assertEqual(tool, "emergency_alerts")
        self.assertEqual(args, {"region": "GB", "scope": "region"})

    def test_explicit_tool_arguments(self):
        self.assertEqual(route_tool('/mcp weather_now {"location":"London"}'),
                         ("weather_now", {"location": "London"}))

    def test_api_key_headers(self):
        client = McpClient(McpServerConfig(name="test", url="https://example/mcp",
            auth="api_key", bearer_token="nai_x", api_key="key_x"))
        self.assertEqual(client._headers()["Authorization"], "Bearer nai_x")
        self.assertEqual(client._headers()["X-API-Key"], "key_x")

    def test_decodes_empty_notification_response(self):
        response = Mock(content=b"", text="", headers={})
        self.assertEqual(McpClient._decode(response), {})


if __name__ == "__main__":
    unittest.main()
