from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .database import get_state, set_state

STATE_KEY = "assistant_reminders_v1"


@dataclass
class Reminder:
    id: str
    message: str
    due_epoch: float
    created_epoch: float
    repeat_seconds: int = 0
    active: bool = True


def _load() -> list[Reminder]:
    try:
        rows = json.loads(get_state(STATE_KEY, "[]"))
        return [Reminder(**row) for row in rows if isinstance(row, dict)]
    except (TypeError, ValueError):
        return []


def _save(rows: list[Reminder]) -> None:
    set_state(STATE_KEY, json.dumps([asdict(x) for x in rows], ensure_ascii=False))


def _parse_due(text: str, tz: ZoneInfo) -> tuple[float, int, str] | None:
    lower = text.lower().strip()
    now = datetime.now(tz)
    repeat = 0

    m = re.search(r"\bin\s+(\d+)\s*(seconds?|minutes?|hours?|days?)\b", lower)
    if m:
        n = max(1, int(m.group(1))); unit = m.group(2)
        seconds = n * (86400 if unit.startswith("day") else 3600 if unit.startswith("hour") else 60 if unit.startswith("minute") else 1)
        return now.timestamp() + seconds, repeat, m.group(0)

    tm = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if tm:
        hour = int(tm.group(1)) % 12
        if tm.group(3) == "pm": hour += 12
        minute = int(tm.group(2) or 0)
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if "tomorrow" in lower:
            due += timedelta(days=1)
        elif due <= now:
            due += timedelta(days=1)
        return due.timestamp(), repeat, tm.group(0)

    return None


def parse_reminder_request(text: str, tz: ZoneInfo) -> tuple[str, object] | None:
    lower = text.lower().strip()
    if re.search(r"\b(?:list|show)\b.*\breminders\b", lower):
        return "list", None
    if re.search(r"\b(?:clear|delete|remove|cancel)\s+all\s+reminders\b", lower):
        return "clear", None
    m = re.search(r"\b(?:cancel|delete|remove)\s+reminder\s+([a-f0-9]{8})\b", lower)
    if m:
        return "remove", m.group(1)
    if "remind me" not in lower and not lower.startswith("set a reminder") and not lower.startswith("set reminder"):
        return None

    parsed = _parse_due(text, tz)
    if not parsed:
        return "error", "I need a time, for example: remind me in 20 minutes, or remind me at 7 PM to feed the dog."
    due, repeat, matched_time = parsed

    message = re.sub(r"^.*?\bremind me\b", "", text, flags=re.I).strip(" ,.-")
    message = re.sub(r"^.*?\bset (?:a )?reminder\b", "", message, flags=re.I).strip(" ,.-")
    message = re.sub(re.escape(matched_time), "", message, count=1, flags=re.I).strip(" ,.-")
    message = re.sub(r"\b(?:today|tomorrow)\b", "", message, flags=re.I).strip(" ,.-")
    message = re.sub(r"^to\s+", "", message, flags=re.I).strip()
    if not message:
        message = "your reminder"
    return "create", Reminder(uuid.uuid4().hex[:8], message, due, time.time(), repeat)


class ReminderManager:
    def __init__(self, notify: Callable[[str, str], None], timezone: str = "Europe/London") -> None:
        self.notify = notify
        self.tz = ZoneInfo(timezone)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="assistant-reminders")
        self._thread.start()

    def handle(self, text: str) -> str | None:
        parsed = parse_reminder_request(text, self.tz)
        if not parsed:
            return None
        action, value = parsed
        with self._lock:
            rows = _load()
            if action == "error":
                return str(value)
            if action == "clear":
                count = sum(1 for x in rows if x.active)
                for x in rows: x.active = False
                _save(rows)
                return f"Cancelled {count} reminder(s)."
            if action == "remove":
                found = False
                for x in rows:
                    if x.id == value and x.active:
                        x.active = False; found = True
                _save(rows)
                return f"Cancelled reminder {value}." if found else f"I couldn't find reminder {value}."
            if action == "list":
                active = sorted((x for x in rows if x.active), key=lambda x: x.due_epoch)
                if not active: return "You don't have any active reminders."
                return "Your reminders:\n" + "\n".join(
                    f"- {x.id}: {x.message}, {datetime.fromtimestamp(x.due_epoch, self.tz).strftime('%A %H:%M')}"
                    for x in active[:20]
                )
            reminder = value
            assert isinstance(reminder, Reminder)
            rows.append(reminder); _save(rows)
            shown = datetime.fromtimestamp(reminder.due_epoch, self.tz).strftime("%A at %I:%M %p").replace(" 0", " ")
            return f"Okay. I'll remind you to {reminder.message} on {shown}."

    def _loop(self) -> None:
        while not self._stop.wait(1):
            now = time.time(); fired: list[Reminder] = []
            with self._lock:
                rows = _load()
                for item in rows:
                    if item.active and item.due_epoch <= now:
                        fired.append(item)
                        if item.repeat_seconds > 0:
                            item.due_epoch = now + item.repeat_seconds
                        else:
                            item.active = False
                if fired: _save(rows)
            for item in fired:
                self.notify(f"Reminder: {item.message}", "warning")
