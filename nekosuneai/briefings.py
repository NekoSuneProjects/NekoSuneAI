"""Local house/timeline briefings plus source-attributed opt-in RSS headlines."""
from __future__ import annotations

import html
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .home_events import HomeEventTimeline


DeviceProvider = Callable[[], list[dict[str, Any]]]
IncidentProvider = Callable[[], list[str]]
FeedFetcher = Callable[[str], bytes]


def _clean(value: str, limit: int = 500) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return " ".join(text.split())[:limit]


def _safe_link(value: str) -> str:
    link = _clean(value, 500)
    parsed = urlparse(link)
    return link if parsed.scheme in {"http", "https"} and parsed.hostname else ""


class BriefingManager:
    def __init__(
        self,
        timeline: HomeEventTimeline,
        smart_devices: DeviceProvider,
        peripheral_nodes: DeviceProvider,
        active_incidents: IncidentProvider,
        *,
        timezone: str = "Europe/London",
        rss_feeds: list[str] | None = None,
        feed_fetcher: FeedFetcher | None = None,
    ) -> None:
        self.timeline = timeline
        self.smart_devices = smart_devices
        self.peripheral_nodes = peripheral_nodes
        self.active_incidents = active_incidents
        self.timezone = ZoneInfo(timezone)
        configured = rss_feeds if rss_feeds is not None else os.getenv("RSS_BRIEFING_FEEDS", "").split(",")
        self.rss_feeds = [str(url).strip() for url in configured if str(url).strip()][:20]
        self.feed_fetcher = feed_fetcher or self._fetch_feed

    @staticmethod
    def _fetch_feed(url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("RSS feed URL must use HTTP or HTTPS")
        request = urllib.request.Request(url, headers={"User-Agent": "NekoSuneAI/1.0 RSS briefing"})
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read(2_000_001)

    @staticmethod
    def _number(state: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            try:
                if state.get(key) not in (None, ""):
                    return float(state[key])
            except (TypeError, ValueError):
                continue
        return None

    def house_status(self) -> str:
        smart = list(self.smart_devices())
        nodes = list(self.peripheral_nodes())
        online_smart = [row for row in smart if row.get("online")]
        online_nodes = [row for row in nodes if row.get("online")]
        low_batteries: list[str] = []
        temperatures: list[str] = []
        for row in [*smart, *nodes]:
            state = dict(row.get("state") or {})
            battery = row.get("battery_percent")
            if battery is None:
                battery = self._number(state, "battery", "battery_percent", "battery_level")
            try:
                if battery is not None and float(battery) <= 20:
                    low_batteries.append(f"{row.get('name', row.get('id', 'device'))} {float(battery):.0f}%")
            except (TypeError, ValueError):
                pass
            temperature = self._number(state, "temperature_c", "temperature", "temp_c")
            if temperature is not None:
                temperatures.append(f"{row.get('name', row.get('id', 'sensor'))} {temperature:.1f}°C")
        incidents = self.active_incidents()
        parts = [
            f"House status: {len(online_smart)} of {len(smart)} smart-home devices online",
            f"{len(online_nodes)} of {len(nodes)} peripheral nodes online",
        ]
        parts.append("active emergency sensors require attention" if incidents else "no active local emergency sensor incidents")
        if low_batteries:
            parts.append("low batteries: " + ", ".join(low_batteries[:5]))
        if temperatures:
            parts.append("temperatures: " + ", ".join(temperatures[:5]))
        offline = [str(row.get("name") or row.get("id")) for row in [*smart, *nodes] if not row.get("online")]
        if offline:
            parts.append("offline: " + ", ".join(offline[:8]))
        return "; ".join(parts) + "."

    def weather_station_status(self) -> str:
        readings: list[str] = []
        for row in self.smart_devices():
            state = dict(row.get("state") or {})
            values = []
            temperature = self._number(state, "temperature_c", "temperature", "temp_c")
            humidity = self._number(state, "humidity", "humidity_percent")
            pressure = self._number(state, "pressure_hpa", "pressure")
            rain = self._number(state, "rain_mm", "precipitation_mm")
            wind = self._number(state, "wind_kph", "wind_speed_kph")
            if temperature is not None:
                values.append(f"{temperature:.1f}°C")
            if humidity is not None:
                values.append(f"humidity {humidity:.0f}%")
            if pressure is not None:
                values.append(f"pressure {pressure:.0f} hPa")
            if rain is not None:
                values.append(f"rain {rain:.1f} mm")
            if wind is not None:
                values.append(f"wind {wind:.1f} km/h")
            if values:
                readings.append(f"{row.get('name', row.get('id', 'sensor'))}: " + ", ".join(values))
        if not readings:
            return "No local MQTT/Home Assistant weather-station readings are available."
        return "Local weather-station readings: " + "; ".join(readings[:8]) + "."

    def news_briefing(self) -> str:
        if not self.rss_feeds:
            return "No RSS briefing feeds are configured. Add trusted feed URLs to RSS_BRIEFING_FEEDS."
        headlines: list[str] = []
        failures = 0
        for url in self.rss_feeds:
            try:
                payload = self.feed_fetcher(url)
                if len(payload) > 2_000_000:
                    raise ValueError("feed is too large")
                root = ET.fromstring(payload)
                source = _clean(root.findtext("./channel/title") or root.findtext("{*}title") or urlparse(url).hostname or "feed", 100)
                entries = root.findall("./channel/item") or root.findall("{*}entry")
                for entry in entries[:3]:
                    title = _clean(entry.findtext("title") or entry.findtext("{*}title") or "", 220)
                    link = _safe_link(entry.findtext("link") or entry.findtext("{*}link") or "")
                    if not link:
                        link_node = entry.find("{*}link")
                        link = _safe_link(link_node.get("href", "") if link_node is not None else "")
                    if title:
                        headlines.append(f"{source}: {title}{f' ({link})' if link else ''}")
            except Exception:
                failures += 1
        if not headlines:
            return f"I couldn't read any configured RSS headlines ({failures} feed failure(s))."
        caveat = "Headlines from configured sources; details may be incomplete, developing, or disputed."
        failure_note = f" {failures} feed(s) could not be read." if failures else ""
        return caveat + failure_note + " " + " | ".join(headlines[:10])

    def timeline_summary(self, hours: int = 24, room: str = "") -> str:
        hours = max(1, min(int(hours), 24 * self.timeline.retention_days))
        rows = self.timeline.query(since_epoch=time.time() - hours * 3600, room=room, limit=20)
        location = f" in {room}" if room else ""
        if not rows:
            return f"No retained home events were recorded{location} in the last {hours} hour(s)."
        lines = []
        for row in rows[-10:]:
            shown = datetime.fromtimestamp(float(row["epoch"]), self.timezone).strftime("%a %H:%M")
            lines.append(f"{shown}: {row['summary']}")
        return f"Retained home timeline{location}, last {hours} hour(s): " + " | ".join(lines)

    def handle(self, text: str) -> str | None:
        lower = " ".join(text.strip().lower().split())
        if re.search(r"\b(?:local )?weather station (?:status|readings|report)\b", lower):
            return self.weather_station_status()
        if re.search(r"\b(?:house|home) (?:status|state)(?: briefing| report)?\b", lower):
            return self.house_status()
        if re.search(r"\b(?:rss|news|headline) briefing\b|\bbrief me on (?:the )?news\b", lower):
            return self.news_briefing()
        if re.search(r"\bwhat happened (?:at )?home\b|\bhome timeline\b|\brecent home events\b", lower):
            match = re.search(r"(?:last|past)\s+(\d+)\s+hours?", lower)
            hours = int(match.group(1)) if match else 24
            room_match = re.search(r"\bin (?:the )?([a-z0-9 _-]+?)(?:\s+(?:during|over|in)\b|[?.]|$)", lower)
            room = room_match.group(1).strip() if room_match else ""
            if room.startswith(("last ", "past ")):
                room = ""
            return self.timeline_summary(hours, room)
        match = re.search(r"\bwhen did (?:the )?(.+?) last (open|close|change|trigger)[?]?$", lower)
        if match:
            row = self.timeline.latest(f"{match.group(1)} {match.group(2)}")
            if not row:
                return f"I don't have a retained event matching {match.group(1)}."
            shown = datetime.fromtimestamp(float(row["epoch"]), self.timezone).strftime("%A at %I:%M %p").replace(" 0", " ")
            return f"The latest matching event was {shown}: {row['summary']}"
        return None
