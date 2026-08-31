"""NekoSuneAI - shopping lists and prioritised to-do lists.

A small, local-first companion feature that mirrors the shape of
``reminders.py``: pure natural-language parsing plus a thin manager that
persists everything through the shared SQLite ``app_state`` store. No cloud
account is required.

Two lists are supported:

* ``shopping`` - a flat list of things to buy.
* ``todo``     - tasks that additionally carry a priority and an optional due
                 date/time.

The parser is intentionally forgiving so spoken phrasings like
"add milk and eggs to my shopping list" or
"add call the dentist to my to-do list by friday, high priority" work.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .database import get_state, set_state

STATE_KEY = "assistant_lists_v1"

# Priority order, lowest to highest. Spoken aliases map onto these labels.
PRIORITIES = ("low", "normal", "high", "urgent")
_PRIORITY_ALIASES = {
    "low": "low", "minor": "low", "whenever": "low",
    "normal": "normal", "medium": "normal", "standard": "normal",
    "high": "high", "important": "high",
    "urgent": "urgent", "critical": "urgent", "asap": "urgent", "top": "urgent",
}

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


@dataclass
class ListItem:
    id: str
    text: str
    created_epoch: float
    done: bool = False
    # Only meaningful for the ``todo`` list; ignored for shopping.
    priority: str = "normal"
    due_epoch: float = 0.0


def _empty_store() -> dict[str, list[ListItem]]:
    return {"shopping": [], "todo": []}


def _load() -> dict[str, list[ListItem]]:
    try:
        raw = json.loads(get_state(STATE_KEY, "{}"))
    except (TypeError, ValueError):
        return _empty_store()
    store = _empty_store()
    if isinstance(raw, dict):
        for name in ("shopping", "todo"):
            rows = raw.get(name)
            if isinstance(rows, list):
                store[name] = [ListItem(**row) for row in rows if isinstance(row, dict)]
    return store


def _save(store: dict[str, list[ListItem]]) -> None:
    set_state(
        STATE_KEY,
        json.dumps(
            {name: [asdict(x) for x in rows] for name, rows in store.items()},
            ensure_ascii=False,
        ),
    )


# ── parsing helpers ────────────────────────────────────────────────────────

def _detect_list(lower: str) -> str | None:
    """Return 'shopping', 'todo', or None if no list is named."""
    if re.search(r"\b(shopping|grocery|groceries|buy)\s+list\b", lower) or "shopping list" in lower:
        return "shopping"
    if re.search(r"\b(to-?do|task)\s+list\b", lower) or "todo list" in lower:
        return "todo"
    return None


def _extract_priority(text: str) -> tuple[str, str]:
    """Pull a priority out of *text*; return (priority_label, cleaned_text)."""
    priority = "normal"
    cleaned = text
    m = re.search(r"\b(?:priority\s+)?(low|minor|whenever|normal|medium|standard|high|important|urgent|critical|asap|top)(?:\s+priority)?\b", text, re.I)
    if m:
        priority = _PRIORITY_ALIASES.get(m.group(1).lower(), "normal")
        cleaned = (text[: m.start()] + text[m.end():]).strip(" ,.-")
    return priority, cleaned


def _extract_due(text: str, tz: ZoneInfo) -> tuple[float, str]:
    """Pull a due date/time out of *text*; return (due_epoch, cleaned_text).

    Recognises 'today', 'tomorrow', weekday names, and an optional clock time
    ('at 5pm', '17:00'). Returns 0.0 when nothing is found.
    """
    now = datetime.now(tz)
    cleaned = text
    due_day: datetime | None = None

    day_match = re.search(r"\b(?:by|due|on|before)\s+(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.I)
    if day_match:
        word = day_match.group(1).lower()
        if word == "today":
            due_day = now
        elif word == "tomorrow":
            due_day = now + timedelta(days=1)
        else:
            target = _WEEKDAYS[word]
            delta = (target - now.weekday()) % 7
            due_day = now + timedelta(days=delta or 7)
        cleaned = (text[: day_match.start()] + text[day_match.end():]).strip(" ,.-")

    hour = minute = None
    time_match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", cleaned, re.I)
    if time_match:
        hour = int(time_match.group(1)) % 12
        if time_match.group(3).lower() == "pm":
            hour += 12
        minute = int(time_match.group(2) or 0)
        cleaned = (cleaned[: time_match.start()] + cleaned[time_match.end():]).strip(" ,.-")
    else:
        clock = re.search(r"\bat\s+(\d{1,2}):(\d{2})\b", cleaned)
        if clock:
            hour, minute = int(clock.group(1)), int(clock.group(2))
            cleaned = (cleaned[: clock.start()] + cleaned[clock.end():]).strip(" ,.-")

    if due_day is None and hour is None:
        return 0.0, text
    base = due_day or now
    if hour is not None:
        base = base.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
        if due_day is None and base <= now:
            base += timedelta(days=1)
    else:
        base = base.replace(hour=18, minute=0, second=0, microsecond=0)
    return base.timestamp(), cleaned


def _split_items(text: str) -> list[str]:
    """Split 'milk, eggs and bread' into ['milk', 'eggs', 'bread']."""
    parts = re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", text)
    return [p.strip(" ,.-") for p in parts if p.strip(" ,.-")]


def parse_list_request(text: str, tz: ZoneInfo) -> tuple[str, Any] | None:
    """Parse *text* into a (action, payload) tuple, or None if unrelated.

    Actions: 'add', 'remove', 'complete', 'show', 'clear', 'error'.
    Payloads carry the target list name plus any parsed items.
    """
    lower = text.lower().strip()
    target = _detect_list(lower)
    # Phrase that names a list, stripped out of item text once matched.
    _list_tail = r"(?:off|from|on)?\s*(?:my|the)?\s*(?:shopping|grocery|groceries|to-?do|task)?\s*list\b"

    # ── clear ─────────────────────────────────────────────────────────────────
    if re.search(r"\b(clear|empty|wipe)\s+(?:my|the)?\s*(shopping|grocery|groceries|to-?do|task)?\s*list\b", lower):
        return "clear", {"list": target or "shopping"}

    # ── remove ────────────────────────────────────────────────────────────────
    remove_m = re.search(r"\bremove\s+(.+?)\s+from\s+(?:my|the)?\s*(?:shopping|grocery|groceries|to-?do|task)?\s*list\b", text, re.I)
    if remove_m:
        return "remove", {"list": target, "items": _split_items(remove_m.group(1))}

    # ── complete / check off ──────────────────────────────────────────────────
    complete_m = re.search(r"\b(?:check off|cross off|tick off|mark|complete|finished?|done with|got)\s+(.+)$", text, re.I)
    if complete_m and re.search(r"\b(check off|cross off|tick off|mark|complete|finished?|done with|got)\b", lower):
        raw = re.sub(_list_tail, "", complete_m.group(1), flags=re.I)
        raw = re.sub(r"\bas\s+(?:done|complete)\b", "", raw, flags=re.I)
        items = _split_items(raw)
        if items:
            return "complete", {"list": target, "items": items}

    # ── add ───────────────────────────────────────────────────────────────────
    add_m = re.search(r"\b(?:add|put|note|record)\s+(.+?)\s+(?:to|on|onto|in)\s+(?:my|the)?\s*(shopping|grocery|groceries|to-?do|task)\s*list\b(.*)$", text, re.I)
    if add_m:
        body = add_m.group(1).strip()
        kind = add_m.group(2).lower()
        trailing = add_m.group(3) or ""
        list_name = "shopping" if kind in {"shopping", "grocery", "groceries"} else "todo"
        if list_name == "shopping":
            items = [ListItem(uuid.uuid4().hex[:8], name, time.time()) for name in _split_items(body)]
        else:
            # Priority/due can appear before or after the list phrase, so scan both.
            combined = f"{body} {trailing}".strip(" ,.-")
            priority, body2 = _extract_priority(combined)
            due, body3 = _extract_due(body2, tz)
            task = body3.strip(" ,.-")
            if not task:
                return "error", "What task should I add to your to-do list?"
            items = [ListItem(uuid.uuid4().hex[:8], task, time.time(), priority=priority, due_epoch=due)]
        if not items:
            return "error", "I didn't catch what to add to the list."
        return "add", {"list": list_name, "items": items}

    # ── show ──────────────────────────────────────────────────────────────────
    if re.search(r"\b(what'?s?|show|read|tell me|check|see|view)\b", lower) and \
            (target or re.search(r"\bon\s+(?:my|the)\s+list\b", lower)):
        if re.search(r"\b(shopping|grocery|groceries|buy)\b", lower):
            return "show", {"list": "shopping"}
        if re.search(r"\b(to-?do|task)\b", lower):
            return "show", {"list": "todo"}
        if target:
            return "show", {"list": target}

    return None


def _priority_rank(item: ListItem) -> int:
    try:
        return PRIORITIES.index(item.priority)
    except ValueError:
        return PRIORITIES.index("normal")


class ListManager:
    """Persist and mutate the shopping/to-do lists behind spoken commands."""

    def __init__(self, timezone: str = "Europe/London") -> None:
        self.tz = ZoneInfo(timezone)
        self._lock = threading.RLock()

    # ---- rendering ---------------------------------------------------------
    def _render(self, list_name: str, rows: list[ListItem]) -> str:
        pending = [x for x in rows if not x.done]
        if not pending:
            noun = "shopping list" if list_name == "shopping" else "to-do list"
            return f"Your {noun} is empty."
        if list_name == "shopping":
            names = ", ".join(x.text for x in pending)
            return f"Your shopping list has {len(pending)} item(s): {names}."
        ordered = sorted(pending, key=lambda x: (-_priority_rank(x), x.due_epoch or float("inf"), x.created_epoch))
        lines = []
        for x in ordered:
            extra = []
            if x.priority != "normal":
                extra.append(f"{x.priority} priority")
            if x.due_epoch:
                extra.append("due " + datetime.fromtimestamp(x.due_epoch, self.tz).strftime("%a %H:%M").replace(" 00:00", ""))
            suffix = f" ({', '.join(extra)})" if extra else ""
            lines.append(f"- {x.id}: {x.text}{suffix}")
        return f"Your to-do list has {len(pending)} task(s):\n" + "\n".join(lines)

    # ---- command entry point ----------------------------------------------
    def handle(self, text: str) -> str | None:
        parsed = parse_list_request(text, self.tz)
        if not parsed:
            return None
        action, payload = parsed
        if action == "error":
            return str(payload)

        with self._lock:
            store = _load()

            if action == "show":
                name = payload["list"]
                return self._render(name, store[name])

            if action == "clear":
                name = payload["list"]
                count = sum(1 for x in store[name] if not x.done)
                store[name] = []
                _save(store)
                noun = "shopping list" if name == "shopping" else "to-do list"
                return f"Cleared {count} item(s) from your {noun}."

            if action == "add":
                name = payload["list"]
                store[name].extend(payload["items"])
                _save(store)
                items = payload["items"]
                if name == "shopping":
                    names = ", ".join(x.text for x in items)
                    return f"Added {names} to your shopping list."
                item = items[0]
                bits = [f'Added "{item.text}" to your to-do list']
                if item.priority != "normal":
                    bits.append(f"{item.priority} priority")
                if item.due_epoch:
                    bits.append("due " + datetime.fromtimestamp(item.due_epoch, self.tz).strftime("%A at %I:%M %p").replace(" 0", " "))
                return ", ".join(bits) + "."

            # remove / complete both target pending items by text match.
            names = payload.get("items") or []
            candidate_lists = [payload["list"]] if payload.get("list") else ["shopping", "todo"]
            hit: list[str] = []
            miss: list[str] = []
            for wanted in names:
                found = False
                for list_name in candidate_lists:
                    for x in store[list_name]:
                        if not x.done and x.text.lower() == wanted.lower():
                            if action == "remove":
                                store[list_name] = [y for y in store[list_name] if y.id != x.id]
                            else:
                                x.done = True
                            found = True
                            break
                    if found:
                        break
                (hit if found else miss).append(wanted)
            if hit:
                _save(store)
            verb = "Removed" if action == "remove" else "Checked off"
            if hit and not miss:
                return f"{verb} {', '.join(hit)}."
            if hit and miss:
                return f"{verb} {', '.join(hit)}. I couldn't find {', '.join(miss)}."
            return f"I couldn't find {', '.join(miss)} on your list." if miss else None
