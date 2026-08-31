"""NekoSuneAI - notification gating: quiet hours, dedup, cooldowns, recall.

A single choke point that every background announcement passes through before
it reaches the user's speakers / phone / toast layer. It implements four
roadmap items from the "Timers, alarms, reminders & lists" section:

* Do-not-disturb / quiet hours - suppress non-critical announcements during a
  configured window (emergencies may override when the user allows it).
* Intelligent interruption priorities - emergency > important > normal.
* Notification summarisation, deduplication and cooldowns - collapse repeats
  and rate-limit chatty monitors.
* Ask about previous announcements - answer "what did you just tell me?".

Everything is local-first and persisted through the shared SQLite ``app_state``
store. A ``now_fn`` is injectable so the behaviour is deterministic in tests.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from .database import get_state, set_state

SETTINGS_KEY = "assistant_notify_settings_v1"
HISTORY_KEY = "assistant_announcements_v1"

# Interruption priorities, lowest to highest.
PRIORITY_NORMAL = 1
PRIORITY_IMPORTANT = 2
PRIORITY_EMERGENCY = 3

_HISTORY_LIMIT = 40


@dataclass
class NotifySettings:
    dnd_enabled: bool = False
    quiet_start: str = "22:00"       # HH:MM local
    quiet_end: str = "07:00"         # HH:MM local
    emergency_override: bool = True  # emergencies pierce quiet hours
    cooldown_seconds: int = 30       # per-message minimum gap
    dedup_window: int = 120          # identical text suppressed within this many seconds
    dont_interrupt: bool = False     # hold non-urgent announcements during active conversation/media


def _load_settings() -> NotifySettings:
    try:
        raw = json.loads(get_state(SETTINGS_KEY, "{}"))
    except (TypeError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    known = {f: raw[f] for f in NotifySettings.__dataclass_fields__ if f in raw}
    return NotifySettings(**known)


def _save_settings(settings: NotifySettings) -> None:
    set_state(SETTINGS_KEY, json.dumps(asdict(settings), ensure_ascii=False))


def _load_history() -> list[dict]:
    try:
        rows = json.loads(get_state(HISTORY_KEY, "[]"))
        return [r for r in rows if isinstance(r, dict)]
    except (TypeError, ValueError):
        return []


def _save_history(rows: list[dict]) -> None:
    set_state(HISTORY_KEY, json.dumps(rows[-_HISTORY_LIMIT:], ensure_ascii=False))


def classify_priority(msg: str, level: str) -> int:
    """Map a monitor (msg, level) onto an interruption priority."""
    if msg.startswith("Government emergency broadcast") or level in {"danger", "emergency"}:
        return PRIORITY_EMERGENCY
    if level == "warning":
        return PRIORITY_IMPORTANT
    return PRIORITY_NORMAL


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return h, mi
    return None


def _in_quiet_window(now: datetime, start: str, end: str) -> bool:
    s = _parse_hhmm(start)
    e = _parse_hhmm(end)
    if not s or not e:
        return False
    cur = now.hour * 60 + now.minute
    smin = s[0] * 60 + s[1]
    emin = e[0] * 60 + e[1]
    if smin == emin:
        return False
    if smin < emin:                      # same-day window, e.g. 13:00-14:00
        return smin <= cur < emin
    return cur >= smin or cur < emin      # overnight window, e.g. 22:00-07:00


def _parse_clock_phrase(text: str) -> str | None:
    """Turn '10pm' / '7 am' / '22:00' into a normalised 'HH:MM' string."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.I)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "pm":
            hour += 12
        return f"{hour:02d}:{int(m.group(2) or 0):02d}"
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return f"{h:02d}:{mi:02d}"
    return None


def parse_notify_command(text: str) -> tuple[str, object] | None:
    """Parse DnD/quiet-hours settings or announcement-recall requests.

    Returns (action, value) where action is one of:
    'dnd_on', 'dnd_off', 'set_quiet', 'recall', 'summary', 'status', or None.
    """
    lower = text.lower().strip()
    mentions_dnd = bool(re.search(r"\b(do not disturb|do-not-disturb|dnd|quiet hours|quiet mode|quiet time)\b", lower))

    # ── settings window: "set quiet hours from 10pm to 7am" ────────────────────
    if mentions_dnd:
        m = re.search(r"\bfrom\s+(.+?)\s+(?:to|until|till)\s+(.+?)(?:\.|$)", lower)
        if m:
            start = _parse_clock_phrase(m.group(1))
            end = _parse_clock_phrase(m.group(2))
            if start and end:
                return "set_quiet", (start, end)
        if re.search(r"\b(off|disable|turn off|cancel|end|stop)\b", lower):
            return "dnd_off", None
        if re.search(r"\b(on|enable|turn on|start|activate|set)\b", lower):
            return "dnd_on", None
        return "status", None

    # ── recall: "what did you just tell me?" ──────────────────────────────────
    if re.search(r"\bwhat did you (?:just )?(?:say|tell me|announce)\b", lower) or \
            re.search(r"\b(repeat|say) (?:that|the last|your last)\b", lower):
        return "recall", None
    if re.search(r"\bwhat (?:have you|did you) (?:told|tell|announced?)\b", lower) or \
            re.search(r"\b(recent|last|latest) (?:announcements?|notifications?|alerts?)\b", lower) or \
            re.search(r"\bwhat announcements\b", lower):
        return "summary", None

    # ── don't-interrupt mode ──────────────────────────────────────────────────
    if re.search(r"\b(don'?t interrupt|do not interrupt|no interruptions?)\b", lower):
        if re.search(r"\b(off|disable|turn off|cancel|stop|allow)\b", lower):
            return "interrupt_off", None
        return "interrupt_on", None
    return None


class NotificationGate:
    """Gate + record background announcements; answer recall/settings queries."""

    def __init__(self, timezone: str = "Europe/London", now_fn: Callable[[], float] = time.time) -> None:
        self.tz = ZoneInfo(timezone)
        self._now = now_fn
        self._lock = threading.RLock()
        # message-key -> last time it was *seen* (delivered or not).
        self._recent: dict[str, float] = {}
        # "don't interrupt" holds non-urgent announcements until this epoch.
        self._busy_until: float = 0.0

    def mark_activity(self, seconds: float = 30.0) -> None:
        """Signal active conversation/media so don't-interrupt mode can hold alerts."""
        with self._lock:
            self._busy_until = max(self._busy_until, self._now() + seconds)

    # ---- gating ------------------------------------------------------------
    def should_deliver(self, msg: str, level: str = "none") -> bool:
        """Decide whether *msg* reaches the user, recording it when delivered."""
        with self._lock:
            settings = _load_settings()
            priority = classify_priority(msg, level)
            now = self._now()
            key = msg.strip().lower()
            last_seen = self._recent.get(key)

            # Emergencies always fire (subject only to override policy for DnD).
            if priority < PRIORITY_EMERGENCY:
                if last_seen is not None and (now - last_seen) < settings.dedup_window:
                    self._recent[key] = now
                    return False
                if last_seen is not None and (now - last_seen) < settings.cooldown_seconds:
                    self._recent[key] = now
                    return False
                local = datetime.fromtimestamp(now, self.tz)
                if settings.dnd_enabled and _in_quiet_window(local, settings.quiet_start, settings.quiet_end):
                    self._recent[key] = now
                    return False
                if settings.dont_interrupt and now < self._busy_until:
                    self._recent[key] = now
                    return False
            else:
                local = datetime.fromtimestamp(now, self.tz)
                if settings.dnd_enabled and not settings.emergency_override and \
                        _in_quiet_window(local, settings.quiet_start, settings.quiet_end):
                    self._recent[key] = now
                    return False

            self._recent[key] = now
            self._record(msg, level, priority, now)
            return True

    def _record(self, msg: str, level: str, priority: int, now: float) -> None:
        rows = _load_history()
        rows.append({"text": msg, "level": level, "priority": priority, "epoch": now})
        _save_history(rows)

    # ---- conversational surface -------------------------------------------
    def handle(self, text: str) -> str | None:
        parsed = parse_notify_command(text)
        if not parsed:
            return None
        action, value = parsed
        with self._lock:
            settings = _load_settings()

            if action == "dnd_on":
                settings.dnd_enabled = True
                _save_settings(settings)
                return f"Do-not-disturb is on. I'll hold non-urgent announcements during quiet hours ({settings.quiet_start}-{settings.quiet_end})."
            if action == "dnd_off":
                settings.dnd_enabled = False
                _save_settings(settings)
                return "Do-not-disturb is off. I'll announce updates normally again."
            if action == "set_quiet":
                start, end = value  # type: ignore[misc]
                settings.quiet_start, settings.quiet_end, settings.dnd_enabled = start, end, True
                _save_settings(settings)
                return f"Quiet hours set from {start} to {end}, and do-not-disturb is now on."
            if action == "interrupt_on":
                settings.dont_interrupt = True
                _save_settings(settings)
                return "Don't-interrupt mode is on. I'll hold non-urgent announcements while you're talking or playing media, and catch you up after."
            if action == "interrupt_off":
                settings.dont_interrupt = False
                _save_settings(settings)
                return "Don't-interrupt mode is off. I'll announce updates as they arrive again."
            if action == "status":
                state = "on" if settings.dnd_enabled else "off"
                interrupt = "on" if settings.dont_interrupt else "off"
                return f"Do-not-disturb is {state}. Quiet hours are {settings.quiet_start} to {settings.quiet_end}; emergency alerts {'do' if settings.emergency_override else 'do not'} override them. Don't-interrupt mode is {interrupt}."

            if action == "recall":
                rows = _load_history()
                if not rows:
                    return "I haven't told you anything recently."
                last = rows[-1]
                when = datetime.fromtimestamp(last["epoch"], self.tz).strftime("%H:%M")
                return f"At {when} I said: {last['text']}"

            if action == "summary":
                rows = _load_history()
                if not rows:
                    return "I haven't made any announcements recently."
                recent = rows[-5:]
                lines = [
                    f"- {datetime.fromtimestamp(r['epoch'], self.tz).strftime('%H:%M')}: {r['text']}"
                    for r in recent
                ]
                return f"Here are my last {len(recent)} announcement(s):\n" + "\n".join(lines)
        return None
