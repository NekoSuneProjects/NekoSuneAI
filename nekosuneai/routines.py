"""Local-first routines with deterministic conditions, audit and undo."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ActionExecutor = Callable[[dict[str, Any]], dict[str, Any] | None]
NaturalActionResolver = Callable[[str, str, Any, str | None], dict[str, Any]]


class RoutineManager:
    """Persist and execute ordered, capability-scoped routines.

    The manager does not execute shell commands.  Actions are plain objects
    handed to a caller-provided allowlisted executor (the web server uses the
    peripheral-node registry).  This keeps automation decisions deterministic
    and physical-device safety outside the language model.
    """

    def __init__(
        self,
        executor: ActionExecutor,
        storage_path: str | Path | None = None,
        policy_resolver: Callable[[dict[str, Any]], str] | None = None,
        natural_action_resolver: NaturalActionResolver | None = None,
        timezone: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        self.executor = executor
        self.policy_resolver = policy_resolver
        self.natural_action_resolver = natural_action_resolver
        self.timezone = ZoneInfo(timezone or os.getenv("ROUTINES_TIMEZONE", "Europe/London"))
        self.latitude = float(latitude if latitude is not None else os.getenv("HOME_LATITUDE", "51.5074"))
        self.longitude = float(longitude if longitude is not None else os.getenv("HOME_LONGITUDE", "-0.1278"))
        self.storage_path = Path(storage_path or os.getenv("ROUTINES_FILE", "data/routines.json"))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._routines: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.storage_path.read_text("utf-8"))
            if isinstance(raw, dict):
                self._routines = {str(x["id"]): x for x in raw.get("routines", []) if isinstance(x, dict) and x.get("id")}
                self._history = list(raw.get("history") or [])[-500:]
        except Exception:
            self._routines, self._history = {}, []

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"routines": list(self._routines.values()), "history": self._history[-500:]}, indent=2),
            "utf-8",
        )
        tmp.replace(self.storage_path)

    @staticmethod
    def _validate(payload: dict[str, Any], routine_id: str | None = None) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()[:100]
        if not name:
            raise ValueError("routine name is required")
        triggers = payload.get("triggers") or [{"type": "manual"}]
        conditions = payload.get("conditions") or []
        actions = payload.get("actions") or []
        if not isinstance(triggers, list) or not all(isinstance(x, dict) for x in triggers):
            raise ValueError("triggers must be a list of objects")
        if not isinstance(conditions, list) or not all(isinstance(x, dict) for x in conditions):
            raise ValueError("conditions must be a list of objects")
        if not isinstance(actions, list) or not actions or not all(isinstance(x, dict) for x in actions):
            raise ValueError("at least one action is required")
        if len(actions) > 50:
            raise ValueError("a routine may contain at most 50 actions")
        for trigger in triggers:
            trigger_type = str(trigger.get("type", ""))
            if trigger_type not in {"manual", "event", "sensor", "schedule", "sunrise", "sunset", "presence"}:
                raise ValueError("unsupported trigger type")
            if trigger_type == "schedule" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(trigger.get("time", ""))):
                raise ValueError("schedule time must be HH:MM")
            if trigger_type in {"sunrise", "sunset"}:
                offset = int(trigger.get("offset_minutes", 0) or 0)
                if abs(offset) > 1440:
                    raise ValueError("sunrise/sunset offset must be within 24 hours")
            if trigger_type == "presence" and not str(trigger.get("room", "")).strip():
                raise ValueError("presence trigger room is required")
        for condition in conditions:
            if str(condition.get("operator", "eq")) not in {"eq", "ne", "gt", "gte", "lt", "lte", "in"}:
                raise ValueError("unsupported condition operator")
            if not str(condition.get("path", "")).strip():
                raise ValueError("condition path is required")
        for action in actions:
            smart_home = action.get("kind") == "smart_home"
            if smart_home and (not str(action.get("device_id", "")).strip() or not str(action.get("action", "")).strip()):
                raise ValueError("each smart-home action needs device_id and action")
            if not smart_home and (not str(action.get("node_id", "")).strip() or not str(action.get("capability", "")).strip()):
                raise ValueError("each action needs node_id and capability")
        now = time.time()
        expires = float(payload.get("expires_epoch") or 0)
        return {
            "id": routine_id or uuid.uuid4().hex[:10],
            "name": name,
            "enabled": bool(payload.get("enabled", True)),
            "triggers": triggers,
            "conditions": conditions,
            "actions": actions,
            "expires_epoch": expires if expires > now else 0.0,
            "created_epoch": float(payload.get("created_epoch") or now),
            "updated_epoch": now,
            "last_trigger_slots": dict(payload.get("last_trigger_slots") or {}),
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="assistant-routines")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(20):
            try:
                self.run_due_once()
            except Exception:
                # A malformed persisted entry or transient device failure must
                # not permanently stop future schedule polling.
                continue

    @staticmethod
    def _day_allowed(trigger: dict[str, Any], current: datetime) -> bool:
        days = trigger.get("days") or []
        if not days:
            return True
        wanted = {str(day).strip().lower()[:3] for day in days}
        return current.strftime("%a").lower()[:3] in wanted

    def _solar_datetime(self, day: date, event: str) -> datetime | None:
        """Return local sunrise/sunset using NOAA's compact solar calculation."""
        zenith = 90.833
        n = day.timetuple().tm_yday
        lng_hour = self.longitude / 15.0
        approximate = n + (((6 if event == "sunrise" else 18) - lng_hour) / 24.0)
        mean_anomaly = (0.9856 * approximate) - 3.289
        longitude = mean_anomaly + 1.916 * math.sin(math.radians(mean_anomaly))
        longitude += 0.020 * math.sin(math.radians(2 * mean_anomaly)) + 282.634
        longitude %= 360
        right_ascension = math.degrees(math.atan(0.91764 * math.tan(math.radians(longitude)))) % 360
        right_ascension += (math.floor(longitude / 90) * 90) - (math.floor(right_ascension / 90) * 90)
        right_ascension /= 15
        sin_dec = 0.39782 * math.sin(math.radians(longitude))
        cos_dec = math.cos(math.asin(sin_dec))
        denominator = cos_dec * math.cos(math.radians(self.latitude))
        if denominator == 0:
            return None
        cos_hour = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(self.latitude))) / denominator
        if cos_hour < -1 or cos_hour > 1:
            return None
        hour = 360 - math.degrees(math.acos(cos_hour)) if event == "sunrise" else math.degrees(math.acos(cos_hour))
        hour /= 15
        local_mean = hour + right_ascension - (0.06571 * approximate) - 6.622
        utc_hours = (local_mean - lng_hour) % 24
        midnight_utc = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("UTC"))
        return (midnight_utc + timedelta(hours=utc_hours)).astimezone(self.timezone)

    def run_due_once(self, now: float | datetime | None = None) -> list[dict[str, Any]]:
        current = now if isinstance(now, datetime) else datetime.fromtimestamp(time.time() if now is None else now, self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        else:
            current = current.astimezone(self.timezone)
        due: list[tuple[str, str, dict[str, Any]]] = []
        with self._lock:
            for routine in self.list():
                if not routine.get("enabled", True):
                    continue
                for index, trigger in enumerate(routine.get("triggers", [])):
                    trigger_type = str(trigger.get("type", ""))
                    if trigger_type not in {"schedule", "sunrise", "sunset"} or not self._day_allowed(trigger, current):
                        continue
                    if trigger_type == "schedule":
                        target = current.replace(
                            hour=int(str(trigger["time"]).split(":")[0]),
                            minute=int(str(trigger["time"]).split(":")[1]), second=0, microsecond=0,
                        )
                    else:
                        solar = self._solar_datetime(current.date(), trigger_type)
                        if solar is None:
                            continue
                        target = solar + timedelta(minutes=int(trigger.get("offset_minutes", 0) or 0))
                    # The polling window tolerates delayed wake-up without replaying old days.
                    if not (target <= current < target + timedelta(minutes=2)):
                        continue
                    slot = f"{current.date().isoformat()}:{index}:{target.strftime('%H:%M')}"
                    if routine.get("last_trigger_slots", {}).get(str(index)) == slot:
                        continue
                    due.append((routine["id"], slot, {"schedule": {"type": trigger_type, "target": target.isoformat()}}))
                    self._routines[routine["id"]].setdefault("last_trigger_slots", {})[str(index)] = slot
            if due:
                self._save()
        return [self.run(routine_id, context, reason=f"schedule:{slot}") for routine_id, slot, context in due]

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        routine = self._validate(payload)
        with self._lock:
            if any(x["name"].casefold() == routine["name"].casefold() for x in self._routines.values()):
                raise ValueError("a routine with that name already exists")
            self._routines[routine["id"]] = routine
            self._save()
            return dict(routine)

    def update(self, routine_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            old = self._routines.get(str(routine_id))
            if not old:
                raise ValueError("routine was not found")
            merged = {**old, **payload, "created_epoch": old["created_epoch"]}
            routine = self._validate(merged, str(routine_id))
            self._routines[str(routine_id)] = routine
            self._save()
            return dict(routine)

    def delete(self, routine_id: str) -> bool:
        with self._lock:
            existed = self._routines.pop(str(routine_id), None) is not None
            if existed:
                self._save()
            return existed

    def list(self, include_expired: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                dict(item)
                for item in self._routines.values()
                if include_expired or not item.get("expires_epoch") or float(item["expires_epoch"]) > now
            ]

    def _find(self, selector: str) -> dict[str, Any]:
        wanted = str(selector).strip().casefold()
        exact = [x for x in self._routines.values() if x["id"].casefold() == wanted or x["name"].casefold() == wanted]
        if len(exact) == 1:
            return exact[0]
        partial = [x for x in self._routines.values() if wanted and wanted in x["name"].casefold()]
        if len(partial) == 1:
            return partial[0]
        if not exact and not partial:
            raise ValueError("routine was not found")
        raise ValueError("routine name is ambiguous; use its ID")

    @staticmethod
    def _read_path(context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for part in str(path).split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @classmethod
    def _condition_result(cls, condition: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
        actual = cls._read_path(context, str(condition.get("path", "")))
        expected = condition.get("value")
        operator = str(condition.get("operator", "eq"))
        try:
            if operator == "eq":
                passed = actual == expected
            elif operator == "ne":
                passed = actual != expected
            elif operator == "gt":
                passed = actual > expected
            elif operator == "gte":
                passed = actual >= expected
            elif operator == "lt":
                passed = actual < expected
            elif operator == "lte":
                passed = actual <= expected
            else:
                passed = actual in expected
        except TypeError:
            passed = False
        reason = f"{condition.get('path')} {operator} {expected!r} (actual {actual!r})"
        return passed, reason

    def preview(self, selector: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = dict(context or {})
        with self._lock:
            routine = self._find(selector)
            now = time.time()
            blockers: list[str] = []
            if not routine.get("enabled", True):
                blockers.append("routine is disabled")
            if routine.get("expires_epoch") and float(routine["expires_epoch"]) <= now:
                blockers.append("temporary routine has expired")
            condition_details = []
            for condition in routine.get("conditions", []):
                passed, reason = self._condition_result(condition, context)
                condition_details.append({"passed": passed, "reason": reason})
                if not passed:
                    blockers.append("condition failed: " + reason)
            actions = list(routine.get("actions") or [])
            policies: list[str] = []
            if self.policy_resolver is not None:
                for action in actions:
                    try:
                        policy = str(self.policy_resolver(action))
                    except Exception:
                        policy = "deny"
                    policies.append(policy)
                    if policy == "deny":
                        target = (
                            f"{action.get('device_id')}.{action.get('action')}"
                            if action.get("kind") == "smart_home"
                            else f"{action.get('node_id')}.{action.get('capability')}"
                        )
                        blockers.append(
                            f"{target} is unavailable or denied"
                        )
            requires_confirmation = (
                len(actions) >= 5
                or any(bool(x.get("requires_confirmation")) for x in actions)
                or "confirm" in policies
            )
            return {
                "routine_id": routine["id"],
                "name": routine["name"],
                "would_run": not blockers,
                "blockers": blockers,
                "conditions": condition_details,
                "actions": actions,
                "requires_confirmation": requires_confirmation,
            }

    def run(
        self,
        selector: str,
        context: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        reason: str = "manual",
    ) -> dict[str, Any]:
        with self._lock:
            preview = self.preview(selector, context)
            if not preview["would_run"]:
                result = {**preview, "status": "blocked", "reason": "; ".join(preview["blockers"])}
                self._record(result, reason)
                return result
            if preview["requires_confirmation"] and not confirmed:
                result = {**preview, "status": "confirmation_required", "reason": "large or sensitive routine"}
                self._record(result, reason)
                return result
            completed: list[dict[str, Any]] = []
            try:
                for action in preview["actions"]:
                    output = self.executor({**action, "confirmed": confirmed}) or {}
                    completed.append({"action": action, "output": output})
            except Exception as exc:
                result = {
                    **preview,
                    "status": "failed",
                    "reason": str(exc),
                    "completed_actions": completed,
                }
                self._record(result, reason)
                return result
            result = {
                **preview,
                "status": "completed",
                "reason": reason,
                "completed_actions": completed,
            }
            self._record(result, reason)
            return result

    def _record(self, result: dict[str, Any], trigger_reason: str) -> None:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "epoch": time.time(),
            "routine_id": result.get("routine_id"),
            "name": result.get("name"),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "trigger": trigger_reason,
            "completed_actions": result.get("completed_actions", []),
        }
        self._history.append(entry)
        del self._history[:-500]
        self._save()

    def handle_event(self, event: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        matches: list[str] = []
        event_context = dict(context or {})
        with self._lock:
            for routine in self.list():
                for trigger in routine.get("triggers", []):
                    if trigger.get("type") in {"event", "sensor"} and str(trigger.get("event", "")) == str(event):
                        matches.append(routine["id"])
                        break
                    if trigger.get("type") == "presence" and str(event) == "presence.changed":
                        presence = event_context.get("presence") if isinstance(event_context.get("presence"), dict) else {}
                        room_matches = str(presence.get("room", "")).casefold() == str(trigger.get("room", "")).casefold()
                        occupied_matches = bool(presence.get("occupied")) == bool(trigger.get("occupied", True))
                        if room_matches and occupied_matches:
                            matches.append(routine["id"])
                            break
        return [self.run(routine_id, event_context, reason=f"event:{event}") for routine_id in matches]

    def conflicts(self) -> list[dict[str, Any]]:
        """Find enabled routines that react to the same event and target the same capability."""
        routines = [x for x in self.list() if x.get("enabled", True)]
        conflicts: list[dict[str, Any]] = []
        for index, left in enumerate(routines):
            left_events = {str(t.get("event")) for t in left.get("triggers", []) if t.get("event")}
            left_targets = {self._action_target(a) for a in left.get("actions", [])}
            for right in routines[index + 1:]:
                shared_events = left_events & {str(t.get("event")) for t in right.get("triggers", []) if t.get("event")}
                shared_targets = left_targets & {self._action_target(a) for a in right.get("actions", [])}
                if shared_events and shared_targets:
                    conflicts.append({
                        "routines": [left["id"], right["id"]],
                        "events": sorted(shared_events),
                        "targets": sorted([list(x) for x in shared_targets]),
                    })
        return conflicts

    @staticmethod
    def _action_target(action: dict[str, Any]) -> tuple[Any, Any]:
        if action.get("kind") == "smart_home":
            return action.get("device_id"), action.get("action")
        return action.get("node_id"), action.get("capability")

    def explain(self, selector: str) -> dict[str, Any]:
        with self._lock:
            routine = self._find(selector)
            latest = next((x for x in reversed(self._history) if x.get("routine_id") == routine["id"]), None)
            return {"routine": dict(routine), "last_execution": latest}

    def undo_last(self) -> dict[str, Any]:
        """Run explicit undo actions returned by the executor, newest first."""
        with self._lock:
            latest = next((x for x in reversed(self._history) if x.get("status") == "completed"), None)
            if not latest:
                raise ValueError("there is no completed routine to undo")
            undos = []
            for completed in reversed(latest.get("completed_actions") or []):
                undo = (completed.get("output") or {}).get("undo")
                if isinstance(undo, dict):
                    undos.append(self.executor({**undo, "confirmed": True}) or {})
            if not undos:
                raise ValueError("the previous routine did not provide known prior states")
            entry = {"id": uuid.uuid4().hex[:12], "epoch": time.time(), "status": "undone", "undo_of": latest["id"]}
            self._history.append(entry)
            self._save()
            return {"ok": True, "undo_of": latest["id"], "actions": undos}

    def handle(self, text: str) -> str | None:
        lower = text.strip().lower()
        if re.match(r"^(?:neko[, ]+)?(?:create|make|add) (?:a )?routine\b", lower):
            routine = self.create_from_text(text)
            trigger = routine["triggers"][0]
            if trigger["type"] == "schedule":
                timing = f"{'on selected days' if trigger.get('days') else 'daily'} at {trigger['time']}"
            elif trigger["type"] in {"sunrise", "sunset"}:
                timing = trigger["type"]
            else:
                timing = f"when {trigger['room']} becomes {'occupied' if trigger.get('occupied', True) else 'vacant'}"
            return f"Created {routine['name']}: {timing}, with {len(routine['actions'])} action(s)."
        match = re.match(r"^(?:neko[, ]+)?(?:(confirm)\s+)?(?:run|start|activate) (?:the )?(.+?)(?: routine| scene)?$", lower)
        if match:
            result = self.run(match.group(2), confirmed=bool(match.group(1)))
            if result["status"] == "completed":
                return f"Ran {result['name']} with {len(result['actions'])} action(s)."
            if result["status"] == "confirmation_required":
                return f"{result['name']} needs confirmation because it affects {len(result['actions'])} devices/actions. Preview it in the routines API first."
            return f"I did not run {result['name']}: {result['reason']}."
        match = re.match(r"^(?:neko[, ]+)?(?:why did|explain why) (?:the )?(.+?)(?: routine| scene)?(?: run)?[?]?$", lower)
        if match:
            info = self.explain(match.group(1))
            latest = info.get("last_execution")
            if not latest:
                return f"{info['routine']['name']} has no recorded execution yet."
            return f"{info['routine']['name']} last finished as {latest['status']} because {latest.get('reason') or latest.get('trigger')}."
        if re.fullmatch(r"(?:neko[, ]+)?undo (?:the )?(?:last|previous) routine[.!]?", lower):
            self.undo_last()
            return "Undid the previous routine using its recorded prior state."
        return None

    def create_from_text(self, text: str) -> dict[str, Any]:
        """Create one safe smart-home routine from a constrained natural phrase."""
        if self.natural_action_resolver is None:
            raise ValueError("natural-language routine actions are not configured")
        cleaned = " ".join(text.strip().split())
        match = re.match(
            r"^(?:neko[, ]+)?(?:create|make|add) (?:a )?routine(?: (?:called|named) (?P<name>.+?))?(?:\s*(?::|that|to)\s*)?(?P<rule>(?:every day|every weekday|at |when ).+)$",
            cleaned,
            re.I,
        )
        if not match:
            raise ValueError(
                "describe a routine like: create a routine called porch lights: at sunset turn on the porch light"
            )
        rule = match.group("rule").strip()
        trigger: dict[str, Any]
        remainder: str
        scheduled = re.match(r"^(every day|every weekday) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(.+)$", rule, re.I)
        solar = re.match(r"^at (sunrise|sunset)(?:\s+([+-]?\d+)\s+minutes?)?\s+(.+)$", rule, re.I)
        presence = re.match(
            r"^when (?:the )?(.+?) (?:is|becomes|gets) (occupied|empty|vacant|unoccupied)\s*,?\s*(.+)$",
            rule,
            re.I,
        )
        if scheduled:
            hour, minute = int(scheduled.group(2)), int(scheduled.group(3) or 0)
            marker = (scheduled.group(4) or "").lower()
            if marker:
                if not 1 <= hour <= 12:
                    raise ValueError("scheduled hour must be 1-12 when using AM/PM")
                hour = hour % 12 + (12 if marker == "pm" else 0)
            if hour > 23 or minute > 59:
                raise ValueError("scheduled time is invalid")
            trigger = {"type": "schedule", "time": f"{hour:02d}:{minute:02d}"}
            if "weekday" in scheduled.group(1).lower():
                trigger["days"] = ["mon", "tue", "wed", "thu", "fri"]
            remainder = scheduled.group(5)
        elif solar:
            trigger = {"type": solar.group(1).lower(), "offset_minutes": int(solar.group(2) or 0)}
            remainder = solar.group(3)
        elif presence:
            occupied = presence.group(2).lower() == "occupied"
            trigger = {"type": "presence", "room": presence.group(1).strip(), "occupied": occupied}
            remainder = presence.group(3)
        else:
            raise ValueError("supported triggers are daily/weekday times, sunrise/sunset, or room occupancy")
        action_match = re.match(r"^(?:then )?(?:turn|switch)\s+(on|off)\s+(?:the )?(.+)$", remainder, re.I)
        if not action_match:
            action_match = re.match(r"^(?:then )?(?:turn|switch)\s+(?:the )?(.+?)\s+(on|off)$", remainder, re.I)
            if not action_match:
                raise ValueError("the routine action must say turn on/off followed by a discovered device")
            description, action = action_match.group(1), action_match.group(2).lower()
        else:
            action, description = action_match.group(1).lower(), action_match.group(2)
        room = str(trigger.get("room") or "").strip() or None
        resolved = self.natural_action_resolver(description.strip(), action, None, room)
        name = (match.group("name") or "").strip(" :-")
        if not name:
            name = f"{trigger['type'].replace('_', ' ').title()} {action} {description}"[:100]
        return self.create({"name": name, "triggers": [trigger], "actions": [resolved]})
