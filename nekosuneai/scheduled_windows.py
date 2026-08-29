from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Config
from .database import get_state, set_state
from .mcp_client import call_first_available, route_tool
from .monitors import Monitor, _summary, _weather_alert_level

STATE_KEY = "scheduled_monitor_windows_v1"
DAY_INDEX = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}


@dataclass
class WindowedMonitor:
    id: str
    tool: str
    arguments: dict[str, Any]
    weekdays: list[int]
    start_minute: int
    end_minute: int
    interval_seconds: int = 300
    active: bool = True
    next_run_epoch: float = 0
    last_hash: str = ""
    last_run_epoch: float = 0


def _load() -> list[WindowedMonitor]:
    try:
        rows = json.loads(get_state(STATE_KEY, "[]"))
        return [WindowedMonitor(**row) for row in rows if isinstance(row, dict)]
    except (ValueError, TypeError):
        return []


def _save(items: list[WindowedMonitor]) -> None:
    set_state(STATE_KEY, json.dumps([asdict(x) for x in items], ensure_ascii=False))


def _parse_clock(value: str) -> int:
    value = value.strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
    if not m: raise ValueError("Invalid time")
    hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if suffix:
        if hour < 1 or hour > 12: raise ValueError("Invalid 12-hour time")
        hour %= 12
        if suffix == "pm": hour += 12
    elif hour > 23:
        raise ValueError("Invalid 24-hour time")
    return hour * 60 + minute


def _days_from_text(lower: str) -> list[int]:
    found = [index for name, index in DAY_INDEX.items() if re.search(rf"\b{name}s?\b", lower)]
    if found: return sorted(set(found))
    if "weekdays" in lower: return [0,1,2,3,4]
    if "weekends" in lower: return [5,6]
    if "every day" in lower or "daily" in lower: return list(range(7))
    return list(range(7))


def parse_windowed_monitor(text: str) -> WindowedMonitor | None:
    lower = text.lower().strip()
    if not any(x in lower for x in ("monitor ", "track ", "schedule ")): return None
    m = re.search(r"\b(?:(?:from|between)\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:to|until|and)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", lower)
    if not m: return None
    routed = route_tool(text)
    if not routed: return None
    interval = 300
    im = re.search(r"\bevery\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)", lower)
    if im:
        count = max(1, int(im.group(1))); unit = im.group(2)
        interval = count * (3600 if unit.startswith(("hour","hr")) else 60 if unit.startswith(("minute","min")) else 1)
    tool, arguments = routed
    return WindowedMonitor(
        id=uuid.uuid4().hex[:8], tool=tool, arguments=arguments,
        weekdays=_days_from_text(lower), start_minute=_parse_clock(m.group(1)),
        end_minute=_parse_clock(m.group(2)), interval_seconds=max(30, interval),
    )


def _inside(item: WindowedMonitor, now: datetime) -> bool:
    if now.weekday() not in item.weekdays: return False
    minute = now.hour * 60 + now.minute
    if item.start_minute == item.end_minute: return True
    if item.start_minute < item.end_minute:
        return item.start_minute <= minute < item.end_minute
    return minute >= item.start_minute or minute < item.end_minute


def _clock(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    suffix = "AM" if h < 12 else "PM"
    shown = h % 12 or 12
    return f"{shown}:{m:02d} {suffix}"


def _day_text(days: list[int]) -> str:
    if days == list(range(7)): return "every day"
    names = [name.title() for name, idx in DAY_INDEX.items() if idx in days]
    return ", ".join(names)


class WindowedMonitorManager:
    def __init__(self, config: Config, notify: Callable[[str, str], None]) -> None:
        self.config = config
        self.notify = notify
        self.timezone = ZoneInfo(getattr(config, "timezone", None) or "Europe/London")
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="windowed-monitor")
        self._thread.start()

    def handle(self, text: str) -> str | None:
        lower = text.lower().strip()
        if re.search(r"\b(?:list|show)\b.*\b(?:timed|windowed|time window)\s+(?:monitors|tracking|schedules)\b", lower):
            items = [x for x in _load() if x.active]
            if not items: return "There are no timed monitor schedules."
            return "Timed monitor schedules:\n" + "\n".join(
                f"- {x.id}: {_day_text(x.weekdays)}, {_clock(x.start_minute)} to {_clock(x.end_minute)}, every {x.interval_seconds}s"
                for x in items
            )
        m = re.search(r"\b(?:remove|delete|stop|cancel)\s+(?:timed\s+)?(?:monitor|schedule)\s+([a-f0-9]{8})\b", lower)
        if m:
            items = _load(); found = False
            for x in items:
                if x.id == m.group(1): x.active = False; found = True
            _save(items)
            return f"Stopped timed monitor {m.group(1)}." if found else f"I couldn't find timed monitor {m.group(1)}."
        item = parse_windowed_monitor(text)
        if not item: return None
        with self._lock:
            items = _load(); items.append(item); _save(items)
        return (
            f"Scheduled monitor {item.id} for {_day_text(item.weekdays)} from {_clock(item.start_minute)} "
            f"to {_clock(item.end_minute)}. It checks every {item.interval_seconds // 60 or 1} minute(s) only inside that window."
        )

    def _loop(self) -> None:
        while not self._stop.wait(10):
            now_epoch = time.time(); local_now = datetime.now(self.timezone)
            with self._lock:
                items = _load()
            changed = False
            for item in items:
                if not item.active or not _inside(item, local_now):
                    continue
                if item.next_run_epoch > now_epoch:
                    continue
                level = "none"
                try:
                    result = call_first_available(self.config, item.tool, item.arguments)
                    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
                    digest = hashlib.sha256(serialized.encode()).hexdigest()
                    if digest != item.last_hash or now_epoch - item.last_run_epoch >= 3600:
                        level = _weather_alert_level(item.tool, result)
                        temp = Monitor(id=item.id, name="Scheduled monitor", tool=item.tool, arguments=item.arguments, interval_seconds=item.interval_seconds)
                        self.notify(_summary(temp, result), level)
                    item.last_hash = digest
                except Exception as exc:
                    self.notify(f"Timed monitor [{item.id}] could not update: {exc}", "warning")
                item.last_run_epoch = now_epoch
                item.next_run_epoch = now_epoch + item.interval_seconds
                changed = True
            if changed:
                with self._lock: _save(items)
