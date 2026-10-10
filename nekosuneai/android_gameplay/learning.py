"""Versioned action learning from observed UI transitions, not model guesses."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .memory import safe_name


FUNCTIONS = {
    "coinmaster/open_village": "Open village",
    "coinmaster/building_upgrade": "Upgrade building",
    "coinmaster/back_to_board": "Return to board",
    "ocr/button": "Dismiss dialog",
    "coinmaster/result_continue": "Dismiss dialog",
    "coinmaster/numbered_icon": "Open numbered icon",
    "coinmaster/treasure_choice": "Choose treasure",
    "coinmaster/merge_item": "Merge items",
    "coinmaster/attack_target": "Attack building",
    "coinmaster/close_popup": "Dismiss dialog",
    "coinmaster/collect_free": "Dismiss dialog",
    "coinmaster/tap_anywhere": "Dismiss dialog",
    "coinmaster/leave_merge": "Dismiss dialog",
    "coinmaster/spin": "Unclassified",
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def scene(observations):
    names = {m["name"] for m in observations}
    for name, label in [("coinmaster/close_popup", "popup"),
                        ("coinmaster/building_upgrade", "village"),
                        ("coinmaster/result_continue", "result"),
                        ("coinmaster/attack_target", "attack"),
                        ("coinmaster/merge_item", "merge"),
                        ("coinmaster/treasure_choice", "treasure"),
                        ("coinmaster/open_village", "board")]:
        if name in names:
            return label
    return "other"


def selector(target):
    result = {k: target[k] for k in ("name", "text", "slot", "cell") if k in target}
    if target["name"] == "coinmaster/numbered_icon" and "normalized_center" in target:
        result["anchor"] = [round(v/50) for v in target["normalized_center"]]
    return result


def resolve(action, observations):
    target_id = action.get("target_id", action.get("from_target_id"))
    if target_id is not None:
        return next((m for m in observations if str(m["id"]) == str(target_id)), None)
    if action.get("action") in {"tap", "long_press"} and "x" in action and "y" in action:
        for target in observations:
            x, y, w, h = target["box"]
            if x <= action["x"] < x+w and y <= action["y"] < y+h:
                return target
    return None


def outcome(action, before, after, visual_change):
    target = resolve(action, before)
    if target is None:
        return "inconclusive", "Action has no recognized semantic target"
    name = target["name"]
    before_scene, after_scene = scene(before), scene(after)
    if name == "coinmaster/open_village" and after_scene == "village":
        return "confirmed", "Village upgrade controls appeared"
    if name == "coinmaster/back_to_board" and after_scene == "board":
        return "confirmed", "Board navigation appeared"
    if name == "coinmaster/attack_target":
        targets_gone = not any(m["name"] == name for m in after)
        reward_dialog = any(m["name"] == "coinmaster/result_continue" or
                            (m["name"] == "ocr/button" and (m.get("text") or "").upper() == "OK") for m in after)
        if targets_gone and (after_scene == "board" or reward_dialog) and visual_change > 3:
            return "confirmed", "Attack markers cleared and a result dialog or board appeared"
    if name == "coinmaster/building_upgrade":
        current = next((m for m in after if m["name"] == name and m.get("slot") == target.get("slot")), None)
        if current:
            old_coins, new_coins = target.get("balance_coins"), current.get("balance_coins")
            old_price, new_price = target.get("price_coins"), current.get("price_coins")
            if (old_coins is not None and new_coins is not None and new_coins < old_coins
                    and old_price is not None and new_price is not None and new_price > old_price):
                return "confirmed", "Coin balance decreased and the upgrade slot changed"
    if name == "coinmaster/treasure_choice":
        previous = [m for m in before if m["name"] == name]
        current = [m for m in after if m["name"] == name]
        tx, ty = target["center"]
        still_present = any(abs(m["center"][0]-tx) < target["box"][2]/2
                            and abs(m["center"][1]-ty) < target["box"][3]/2 for m in current)
        if current and len(current) < len(previous) and not still_present:
            return "confirmed", "Selected treasure disappeared and fewer choices remain"
    if name == "coinmaster/merge_item" and action.get("action") == "swipe":
        destination = next((m for m in before if str(m["id"]) == str(action.get("to_target_id"))), None)
        current = [m for m in after if m["name"] == name]
        if (destination and after_scene == "merge"
                and not any(m.get("cell") == target.get("cell") for m in current)
                and any(m.get("cell") == destination.get("cell") for m in current)
                and len(current) < sum(m["name"] == name for m in before)):
            return "confirmed", "Source cell cleared and destination remains after merge"
    if name == "ocr/button" and (target.get("text") or "").upper() in {"OK", "CLOSE", "CONTINUE"}:
        present = any(selector(m) == selector(target) for m in after)
        if not present and after_scene != "other" and visual_change > 3:
            return "confirmed", "Dialog control disappeared and a recognized game screen is visible"
    if (name == "coinmaster/result_continue" and after_scene in {"board", "attack", "treasure", "village", "merge"}
            and not any(m["name"] == name for m in after) and visual_change > 3):
        return "confirmed", "Completed result dialog dismissed and gameplay resumed"
    if name == "coinmaster/numbered_icon" and before_scene == "board" and after_scene in {"village", "merge"}:
        return "confirmed", "Numbered icon opened a recognized panel"
    if name == "coinmaster/leave_merge":
        if not any(m["name"] == name for m in after) and visual_change > 3:
            return "confirmed", "Merge event closed"
    if name in {"coinmaster/close_popup", "coinmaster/collect_free"}:
        tx, ty = target["center"]
        same_spot = any(m["name"] == name and abs(m["center"][0]-tx) < 40
                        and abs(m["center"][1]-ty) < 40 for m in after)
        if not same_spot and visual_change > 3:
            return "confirmed", "Popup closed and the screen behind it changed"
    if name == "coinmaster/spin":
        was, now = target.get("spinning"), next(
            (m.get("spinning") for m in after if m["name"] == name), None)
        if now is not None and was != now:
            return "confirmed", "Auto-roll " + ("stopped" if was else "started")
    if name == "coinmaster/tap_anywhere" and visual_change > 3:
        return "confirmed", "Reward screen advanced"
    if visual_change < 1.0:
        return "failed", "No visible response after the settle interval"
    return "inconclusive", "Screen changed, but the intended result was not established"


class GameLearning:
    def __init__(self, root, package, game_version, layout_revision, goal, required, confirmations=3):
        if not package or not game_version or game_version == "unknown":
            raise ValueError("A package and detected game version are required for versioned learning")
        if not required or any(name not in FUNCTIONS.values() for name in required):
            raise ValueError("Select at least one supported training function")
        self.root = Path(root)
        self.required = list(dict.fromkeys(required))
        self.confirmations = max(2, int(confirmations))
        identity = {"package": package, "game_version": game_version, "layout_revision": str(layout_revision),
                    "goal": goal, "required": self.required, "confirmations": self.confirmations}
        self.identity = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        directory = safe_name(package)
        self.path = self.root / "training" / directory / f"{self.identity}.json"
        self.skills = self.root / "skills" / directory
        self.monitor = self.path.with_suffix(".monitor.json")
        self.skill_path = None
        self.verified_keys = set()
        self.data = {"schema_version": 1, **identity, "status": "training", "created_at": stamp(),
                     "entries": {}, "attempts": [], "skill_version": None}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            published = sorted(self.skills.glob(f"v*-{self.identity}.json"))
            if published:
                self.skill_path = published[-1]
                self.data = json.loads(self.skill_path.read_text(encoding="utf-8"))
                self.verified_keys = set(self.data["entries"])
                if self.monitor.exists():
                    self.data["entries"] = json.loads(self.monitor.read_text(encoding="utf-8"))["entries"]
        self._save()

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _save(self):
        if self.skill_path is None:
            self._write(self.path, self.data)
        else:
            self._write(self.monitor, {"updated_at": stamp(), "entries": self.data["entries"],
                                       "attempts": self.data["attempts"][-30:]})

    def _key(self, action, observations):
        target = resolve(action, observations)
        if target is None:
            return None, None
        pattern = {"scene": scene(observations), "target": selector(target), "action": action["action"]}
        if action["action"] == "swipe":
            destination = next((m for m in observations if str(m["id"]) == str(action.get("to_target_id"))), None)
            pattern["destination"] = selector(destination) if destination else None
        key = hashlib.sha256(json.dumps(pattern, sort_keys=True).encode()).hexdigest()[:16]
        return key, pattern

    def blocked(self, action, observations):
        key, _ = self._key(action, observations)
        entry = self.data["entries"].get(key, {})
        return entry.get("misses", 0) >= 2

    def context(self, observations):
        verified, avoid = [], []
        for entry in self.data["entries"].values():
            if entry["scene"] != scene(observations):
                continue
            for target in observations:
                if selector(target) != entry["target"] or target.get("enabled") is False:
                    continue
                suggestion = {"target_id": target["id"], "method": entry["action"]}
                if entry["action"] == "swipe":
                    destination = next((m for m in observations if selector(m) == entry.get("destination")), None)
                    if destination is None or destination.get("enabled") is False:
                        continue
                    suggestion = {"from_target_id": target["id"], "to_target_id": destination["id"], "method": "swipe"}
                if entry.get("misses", 0) >= 2:
                    avoid.append({**suggestion, "reason": entry.get("last_reason")})
                elif entry.get("confirmed", 0) >= self.confirmations:
                    verified.append({**suggestion, "confirmed": entry["confirmed"]})
        return {"status": self.data["status"], "version": self.data.get("skill_version"),
                "verified_current_targets": verified[:12], "avoid_repeating": avoid[:12],
                "remaining_functions": self.remaining()}

    def remaining(self):
        covered = {entry["function"] for entry in self.data["entries"].values()
                   if entry["confirmed"] >= self.confirmations and entry["misses"] == 0}
        return [name for name in self.required if name not in covered]

    def record(self, action, before, after, visual_change):
        result, reason = outcome(action, before, after, visual_change)
        key, pattern = self._key(action, before)
        if key is None:
            return result, reason, False
        target = resolve(action, before)
        function = FUNCTIONS.get(target["name"], "Unclassified")
        entry = self.data["entries"].setdefault(key, {**pattern, "function": function,
                                                    "confirmed": 0, "misses": 0})
        if result == "confirmed":
            entry["confirmed"] += 1
            entry["misses"] = 0
        elif result == "failed":
            entry["misses"] += 1
            entry["confirmed"] = 0
        # "inconclusive" means the screen moved but the effect could not be
        # proven. Counting that as a miss let two chained popups veto the only
        # control a screen has, and nothing could ever clear the veto again.
        entry["last_reason"] = reason
        self.data["attempts"].append({"time": stamp(), "pattern": key, "action": action,
                                      "result": result, "reason": reason,
                                      "before_scene": scene(before), "after_scene": scene(after),
                                      "before": [{k: m[k] for k in ("name", "text", "slot", "cell", "state", "balance_coins", "price_coins") if k in m}
                                                 for m in before if m["name"].startswith("coinmaster/") or m["name"] == "ocr/button"][:30],
                                      "after": [{k: m[k] for k in ("name", "text", "slot", "cell", "state", "balance_coins", "price_coins") if k in m}
                                                for m in after if m["name"].startswith("coinmaster/") or m["name"] == "ocr/button"][:30]})
        self.data["attempts"] = self.data["attempts"][-200:]
        if self.skill_path and key in self.verified_keys and entry["misses"] >= 2:
            archive = self.skills / "archive" / self.skill_path.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            self.skill_path.replace(archive)
            self.skill_path = None
            self.verified_keys.clear()
            self.data["status"] = "training"
            # Quarantine the suspect method, while allowing a new method to be learned.
        promoted = False
        if self.skill_path is None and not self.remaining():
            versions = [int(p.name.split("-", 1)[0][1:]) for p in self.skills.rglob("v*-*.json")]
            self.data["skill_version"] = max(versions, default=0) + 1
            self.data["status"] = "verified"
            self.data["verified_at"] = stamp()
            published = {**self.data,
                         "entries": {key: value for key, value in self.data["entries"].items()
                                     if value["confirmed"] >= self.confirmations and value["misses"] == 0},
                         "attempts": [item for item in self.data["attempts"] if item["result"] == "confirmed"]}
            self._write(self.path, published)
            self.skills.mkdir(parents=True, exist_ok=True)
            self.skill_path = self.skills / f"v{self.data['skill_version']:04d}-{self.identity}.json"
            self.path.replace(self.skill_path)
            self.verified_keys = set(published["entries"])
            promoted = True
        self._save()
        return result, reason, promoted
