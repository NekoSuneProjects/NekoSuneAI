import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nekosuneai.integration_health import append_runtime_item, build_health_snapshot


def config(**overrides):
    values = dict(tts_provider="gtts", voice_enabled=False, home_assistant_mqtt_host=None, mcp_enabled=False, mcp_servers_json="[]", bluetooth_reconnect_enabled=False)
    values.update(overrides)
    return SimpleNamespace(**values)


class IntegrationHealthTests(unittest.TestCase):
    def test_disabled_integrations_are_not_problems(self):
        with patch.dict(os.environ, {}, clear=True):
            result = build_health_snapshot(config())
        self.assertEqual(result["overall"], "healthy")
        self.assertTrue(all(row["status"] in {"healthy", "disabled"} for row in result["items"]))

    def test_enabled_but_unconfigured_mcp_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            result = build_health_snapshot(config(mcp_enabled=True))
        mcp = next(row for row in result["items"] if row["name"] == "MCP tools")
        self.assertEqual(mcp["status"], "unavailable")
        self.assertEqual(result["overall"], "unavailable")

    def test_runtime_item_updates_summary(self):
        with patch.dict(os.environ, {}, clear=True):
            result = build_health_snapshot(config())
        append_runtime_item(result, "Android companion", "degraded", "No recent heartbeat")
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["problem_count"], 1)

    def test_dashboard_contains_health_panel_and_refresh(self):
        dashboard = (Path(__file__).parents[1] / "nekosuneai" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="d-health-summary"', dashboard)
        self.assertIn("async function loadIntegrationHealth()", dashboard)
        self.assertIn("get_integration_health()", dashboard)


if __name__ == "__main__":
    unittest.main()
