"""Manual, wall-following VRChat world mapper.

Builds a rough sketch map of a VRChat world's walls/edges by dead reckoning:
it repeatedly tries to walk forward, and uses the avatar's own OSC velocity
feedback (the standard ``VelocityX``/``VelocityY``/``VelocityZ``/``Grounded``
avatar parameters most avatars already send) to notice when a forward step
didn't actually move it — the same "I pushed forward but didn't move, must be
a wall" signal used elsewhere for wall detection. On a blocked step it turns
until it finds an opening (a simple wall-following/hugging behaviour, not a
full room-by-room exploration), so it traces corridors and room boundaries
the way someone feeling their way along a wall would, rather than wandering
randomly around the whole world.

Once it walks back to within a short distance of where it started this floor,
that's a closed loop — the boundary is done, so it stops on its own instead of
retracing the same lap forever. The traced path itself is stored as a filled
floor polygon, so a viewer can shade in the whole room instead of needing
every square metre individually walked.

Stairs going up or down are detected the same wall-less-detection way, from
sustained vertical (``VelocityY``) motion while still moving horizontally,
corroborated by on-screen OCR text when it mentions a floor/stairs — and
treated as a transition to a new floor: the current floor's walls/path/
landmarks are sealed off, floor-relative position resets to (0, 0), and
mapping continues on the new floor. A world with more floors than that just
keeps stacking them the same way.

This is a best-effort sketch, not a laser-precision map:
  * Position/heading are pure dead reckoning (estimated walk speed and turn
    rate times elapsed time) — drift accumulates over a large world.
  * Wall-following can miss interior rooms that don't touch the boundary it's
    tracing; use "Tag landmark here" to manually mark anything it walks past
    (VIP rooms, back rooms, etc.) — it also auto-tags doors, lifts/elevators,
    teleporters and VIP signage whenever the on-screen OCR text names one, as
    a best-effort hint (this is text-only: a door or lift with no visible
    label/sign won't be auto-tagged, since there's no real object detection
    behind it — just OCR reading whatever's on screen).
  * It needs the avatar's velocity OSC parameters to detect walls (and
    stairs) at all; if the current avatar doesn't send them, it still traces
    a path but can't tell where the walls or floor changes are.

One JSON file per world lives under ``world_map_dir`` (default
``world-maps/``), named from the world's display name so a finished map is
easy to find, sync, and commit to its own branch. Re-running the mapper on
the same world always re-merges, floor by floor: wall segments confirmed
again are kept/refreshed, wall segments from a previous run that no longer
show up this run are dropped (the "red lines that don't exist any more" get
deleted), and any newly found segments are added — so an updated world
version converges to whatever the world actually looks like now without
needing special-casing for "did the world really change or not".
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from . import vrchat_logs

WALL_SPEED_THRESHOLD = 0.15   # m/s; at/below this after a forward push, treat as "hit a wall"
WALL_MATCH_RADIUS_M = 1.0     # merge distance: an old wall within this of a new one is "confirmed"
VIP_LANDMARK_RADIUS_M = 3.0   # don't re-auto-tag a VIP landmark this close to an existing one
STAIR_VY_THRESHOLD = 0.3      # m/s vertical; above this while moving horizontally, count as "on stairs"
STAIR_CONFIRM_STEPS = 3       # consecutive stair-like steps needed before treating it as a real floor change
LOOP_CLOSE_RADIUS_M = 1.5     # back within this of this floor's start counts as "closed the loop"
LOOP_CLOSE_MIN_STEPS = 15     # don't allow loop-closure until it's actually gone somewhere first
FLOOR_HINT_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)?\s*f(?:loor)?\b|upstairs|downstairs|\bvip\b", re.I)

# Auto-tagged from on-screen OCR text alone (signage, button labels, VIP
# plaques) — most VIP/back-room access is exactly this: a lift with call
# buttons, or a door/teleporter pad you'd otherwise have to walk right up to
# and read. Checked in a fixed order so one line of text yields one tag.
FEATURE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("vip", re.compile(r"\bvip\b", re.I)),
    ("elevator", re.compile(r"\b(lift|elevator)\b", re.I)),
    ("teleporter", re.compile(r"\bteleport(?:er|ation)?\b|\bportal\b", re.I)),
    ("door", re.compile(r"\bdoor(?:way)?\b", re.I)),
    ("entrance", re.compile(r"\b(entrance|entry)\b", re.I)),
    ("exit", re.compile(r"\bexit\b", re.I)),
]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return slug or "world"


class WorldMapper:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.events: deque[str] = deque(maxlen=40)
        self.running = False
        self.steps = 0
        self.walls_found = 0
        self.floor_index = 0
        self.x = 0.0
        self.y = 0.0
        self.heading_deg = 0.0
        self.path: list[tuple[float, float]] = []
        self._new_walls: list[dict[str, float]] = []
        self._new_landmarks: list[dict[str, Any]] = []
        self._sealed_floors: list[dict[str, Any]] = []
        self._saw_velocity = False
        self._stair_streak = 0
        self._stair_direction = 0
        self._last_saved_path = ""

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "steps": self.steps,
            "walls_found": self.walls_found,
            "floor_index": self.floor_index,
            "floors_mapped": len(self._sealed_floors) + 1,
            "position": {"x": round(self.x, 2), "y": round(self.y, 2), "heading_deg": round(self.heading_deg, 1)},
            "events": list(self.events),
            "last_saved_path": self._last_saved_path,
        }

    def _emit(self, text: str) -> None:
        self.events.append(f"{time.strftime('%H:%M:%S')}  {text}")

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.running:
            raise RuntimeError("World mapper is already running")
        if self.agent.vrchat is None:
            raise RuntimeError("Select the VRChat profile and enable OSC first")
        if not self.agent.vrchat.armed.is_set():
            raise RuntimeError("Arm VRChat OSC first (VRChat OSC page)")
        self.steps = self.walls_found = self.floor_index = 0
        self.x = self.y = self.heading_deg = 0.0
        self.path = []
        self._new_walls = []
        self._new_landmarks = []
        self._sealed_floors = []
        self._saw_velocity = False
        self._stair_streak = 0
        self._stair_direction = 0
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="world-mapper")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def tag_landmark(self, label: str) -> None:
        if not self.running:
            raise RuntimeError("Start mapping before tagging a landmark")
        label = str(label).strip()[:80] or "Landmark"
        self._new_landmarks.append({"label": label, "x": round(self.x, 2), "y": round(self.y, 2), "epoch": time.time()})
        self._emit(f"Tagged landmark '{label}' at ({round(self.x, 2)}, {round(self.y, 2)})")

    # ── movement primitives ──────────────────────────────────────────────────

    def _velocity(self) -> tuple[float, float, float] | None:
        params = (self.agent.vrchat.status() or {}).get("parameters") or {}
        vx, vy, vz = params.get("VelocityX"), params.get("VelocityY"), params.get("VelocityZ")
        if vx is None or vz is None:
            return None
        try:
            return float(vx), float(vy) if vy is not None else 0.0, float(vz)
        except (TypeError, ValueError):
            return None

    def _try_forward(self, step_seconds: float, walk_speed_mps: float) -> bool:
        self.agent.vrchat.pulse("Vertical", 1.0, step_seconds)
        velocity = self._velocity()
        heading_rad = math.radians(self.heading_deg)
        if velocity is None:
            moved = True  # no wall telemetry available; assume it worked
        else:
            self._saw_velocity = True
            vx, vy, vz = velocity
            moved = math.hypot(vx, vz) > WALL_SPEED_THRESHOLD
            self._track_stairs(vy, moved)
        if moved:
            distance = walk_speed_mps * step_seconds
            self.x += math.cos(heading_rad) * distance
            self.y += math.sin(heading_rad) * distance
            self.path.append((round(self.x, 2), round(self.y, 2)))
        else:
            self._record_wall(heading_rad)
        self.steps += 1
        return moved

    def _record_wall(self, heading_rad: float) -> None:
        hit_x = self.x + math.cos(heading_rad) * 0.5
        hit_y = self.y + math.sin(heading_rad) * 0.5
        perp = heading_rad + math.pi / 2
        self._new_walls.append({
            "x1": round(hit_x + math.cos(perp) * 0.5, 2), "y1": round(hit_y + math.sin(perp) * 0.5, 2),
            "x2": round(hit_x - math.cos(perp) * 0.5, 2), "y2": round(hit_y - math.sin(perp) * 0.5, 2),
        })
        self.walls_found += 1

    def _turn(self, delta_deg: float, turn_deg_per_sec: float) -> None:
        direction = 1.0 if delta_deg > 0 else -1.0
        remaining = abs(delta_deg)
        while remaining > 0.5 and not self._stop.is_set():
            chunk_deg = min(remaining, turn_deg_per_sec * 2.0)
            seconds = max(0.05, min(2.0, chunk_deg / max(turn_deg_per_sec, 1.0)))
            self.agent.vrchat.pulse("LookHorizontal", direction, seconds)
            self.heading_deg = (self.heading_deg + direction * chunk_deg) % 360
            remaining -= chunk_deg

    def _maybe_auto_tag_landmarks(self) -> None:
        """Read on-screen OCR text and auto-tag any door/lift/teleporter/VIP
        signage it recognizes. This is purely text-based (no real object
        detection of what a door or lift actually looks like) — it catches
        exactly the "walk up and read the sign/button" case, which is how a
        lot of VIP/back-room access is actually gated in VRChat worlds, but a
        landmark with no visible label on it won't be auto-tagged this way;
        use "Tag landmark here" for those."""
        try:
            text = str((self.agent.vision.capture() or {}).get("ocr") or "")
        except Exception:
            return
        if not text:
            return
        for kind, pattern in FEATURE_PATTERNS:
            if not pattern.search(text):
                continue
            near = any(
                landmark.get("kind") == kind
                and math.hypot(landmark["x"] - self.x, landmark["y"] - self.y) < VIP_LANDMARK_RADIUS_M
                for landmark in self._new_landmarks if landmark.get("auto")
            )
            if near:
                continue
            self._new_landmarks.append({
                "label": f"{kind.capitalize()} (auto-detected)", "kind": kind,
                "x": round(self.x, 2), "y": round(self.y, 2), "epoch": time.time(), "auto": True,
            })
            self._emit(f"Auto-tagged a possible {kind} (saw matching text on screen).")

    # ── stairs / floor changes ───────────────────────────────────────────────

    def _ocr_floor_hint(self) -> str:
        try:
            text = str((self.agent.vision.capture() or {}).get("ocr") or "")
        except Exception:
            return ""
        match = FLOOR_HINT_RE.search(text)
        return match.group(0) if match else ""

    def _track_stairs(self, vy: float, moved_horizontally: bool) -> None:
        if moved_horizontally and abs(vy) > STAIR_VY_THRESHOLD:
            direction = 1 if vy > 0 else -1
            if direction == self._stair_direction:
                self._stair_streak += 1
            else:
                self._stair_direction, self._stair_streak = direction, 1
            if self._stair_streak == STAIR_CONFIRM_STEPS:
                self._begin_new_floor(direction)
        else:
            self._stair_streak, self._stair_direction = 0, 0

    def _floor_polygon(self) -> list[list[float]]:
        # The wall-hugging path already traces roughly the room/corridor
        # boundary, so it can double as a fillable floor outline without
        # needing separate dense interior coverage.
        if len(self.path) < 3:
            return []
        return [[px, py] for px, py in self.path]

    def _seal_current_floor(self) -> dict[str, Any]:
        return {
            "floor_index": self.floor_index,
            "walls": self._new_walls,
            "landmarks": self._new_landmarks,
            "path": self.path[-1000:],
            "floor_polygon": self._floor_polygon(),
        }

    def _begin_new_floor(self, direction: int) -> None:
        hint = self._ocr_floor_hint()
        self._emit(
            f"Detected stairs {'up' if direction > 0 else 'down'} — "
            f"sealing floor {self.floor_index}, continuing on floor {self.floor_index + direction}."
            + (f" (saw '{hint}' on screen)" if hint else "")
        )
        self._sealed_floors.append(self._seal_current_floor())
        self.floor_index += direction
        self.x = self.y = 0.0
        self.path = []
        self._new_walls = []
        self._new_landmarks = []
        self._stair_streak = self._stair_direction = 0

    # ── main loop ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        config = self.agent.config
        step_seconds = max(0.2, min(float(config.get("world_map_step_seconds", 0.6)), 2.0))
        walk_speed = max(0.1, float(config.get("world_map_walk_speed_mps", 2.0)))
        turn_rate = max(10.0, float(config.get("world_map_turn_deg_per_sec", 90.0)))
        max_minutes = max(1.0, float(config.get("world_map_max_minutes", 10.0)))
        deadline = time.monotonic() + max_minutes * 60
        turn_probe_deg = 30.0
        hug_deg = 8.0
        clear_run = 0
        self._emit("Mapping started.")
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                moved = self._try_forward(step_seconds, walk_speed)
                if not moved:
                    opened = False
                    for _ in range(12):
                        if self._stop.is_set():
                            break
                        self._turn(turn_probe_deg, turn_rate)
                        if self._try_forward(step_seconds, walk_speed):
                            opened = True
                            clear_run = 0
                            break
                    if not opened:
                        self._emit("No opening found after a full turn — stopping (dead end or fully enclosed).")
                        break
                else:
                    clear_run += 1
                    if clear_run % 3 == 0:
                        self._turn(-hug_deg, turn_rate)  # curve back toward the wall it's hugging
                if self.steps % 5 == 0:
                    self._maybe_auto_tag_landmarks()
                if self.steps >= LOOP_CLOSE_MIN_STEPS and math.hypot(self.x, self.y) < LOOP_CLOSE_RADIUS_M:
                    self._emit("Back near this floor's start — loop closed, no need to keep circling.")
                    break
        except PermissionError as exc:
            self._emit(f"Stopped: {exc}")
        except Exception as exc:
            self._emit(f"Stopped on error: {exc}")
        finally:
            if not self._saw_velocity:
                self._emit("Note: this avatar never reported VelocityX/Y/Z, so walls and stairs could not be detected — only the walked path was recorded.")
            self._save()
            self.running = False

    # ── persistence ──────────────────────────────────────────────────────────

    def _map_dir(self) -> Path:
        return Path(self.agent.config.get("world_map_dir") or "world-maps")

    def _map_path(self, world: dict[str, str]) -> Path:
        root = self._map_dir()
        slug = _slugify(world.get("name") or world["id"])
        candidate = root / f"{slug}.json"
        existing = self._load_raw(candidate)
        if existing and existing.get("world_id") and existing["world_id"] != world["id"]:
            slug = f"{slug}-{world['id'][-8:]}"
            candidate = root / f"{slug}.json"
        return candidate

    @staticmethod
    def _load_raw(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return None

    def _fetch_world_version(self, world_id: str) -> int | None:
        friends = getattr(self.agent, "vrchat_friends", None)
        api_client = getattr(friends, "_api_client", None) if friends is not None else None
        if api_client is None:
            return None
        try:
            from vrchatapi.api import worlds_api  # type: ignore
            world = worlds_api.WorldsApi(api_client).get_world(world_id)
            version = getattr(world, "version", None)
            return int(version) if version is not None else None
        except Exception as exc:
            self._emit(f"Could not fetch world version (mapping still saved): {exc}")
            return None

    @staticmethod
    def _merge_walls(old: list[dict[str, float]], new: list[dict[str, float]]) -> list[dict[str, float]]:
        def midpoint(wall: dict[str, float]) -> tuple[float, float]:
            return (wall["x1"] + wall["x2"]) / 2, (wall["y1"] + wall["y2"]) / 2

        used_new: set[int] = set()
        kept: list[dict[str, float]] = []
        for old_wall in old:
            omid = midpoint(old_wall)
            match = next(
                (i for i, nw in enumerate(new) if i not in used_new
                 and math.hypot(omid[0] - midpoint(nw)[0], omid[1] - midpoint(nw)[1]) <= WALL_MATCH_RADIUS_M),
                None,
            )
            if match is not None:
                kept.append(new[match])
                used_new.add(match)
            # else: not confirmed this run — dropped (the stale "red line" is deleted)
        kept.extend(nw for i, nw in enumerate(new) if i not in used_new)
        return kept

    @classmethod
    def _merge_floors(cls, old_floors: list[dict[str, Any]], new_floors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_index: dict[int, dict[str, Any]] = {int(f["floor_index"]): dict(f) for f in old_floors if "floor_index" in f}
        for new_floor in new_floors:
            index = int(new_floor["floor_index"])
            old_floor = by_index.get(index)
            if old_floor is None:
                by_index[index] = new_floor
                continue
            by_index[index] = {
                "floor_index": index,
                "walls": cls._merge_walls(old_floor.get("walls") or [], new_floor.get("walls") or []),
                "landmarks": list(old_floor.get("landmarks") or []) + list(new_floor.get("landmarks") or []),
                "path": new_floor.get("path") or old_floor.get("path") or [],
                "floor_polygon": new_floor.get("floor_polygon") or old_floor.get("floor_polygon") or [],
            }
        return [by_index[index] for index in sorted(by_index)]

    def _save(self) -> None:
        world = vrchat_logs.current_world(self.agent.config.get("vrchat_log_dir") or None)
        if not world or not world.get("id"):
            self._emit("Could not detect the current world from VRChat's logs — nothing saved.")
            return
        version = self._fetch_world_version(world["id"])
        path = self._map_path(world)
        existing = self._load_raw(path)
        if existing and existing.get("world_id") != world["id"]:
            existing = None
        new_floors = self._sealed_floors + [self._seal_current_floor()]
        merged_floors = self._merge_floors((existing or {}).get("floors") or [], new_floors)
        data = {
            "schema_version": 2,
            "world_id": world["id"],
            "world_name": world.get("name") or world["id"],
            "world_version": version if version is not None else (existing or {}).get("world_version"),
            "mapped_epoch": time.time(),
            "floors": merged_floors,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), "utf-8")
        self._last_saved_path = str(path)
        total_walls = sum(len(f.get("walls") or []) for f in merged_floors)
        total_landmarks = sum(len(f.get("landmarks") or []) for f in merged_floors)
        self._emit(f"Saved {path.name}: {len(merged_floors)} floor(s), {total_walls} wall segments, {total_landmarks} landmarks.")

    def sync_from_url(self, base_url: str, world: dict[str, str] | None = None) -> str:
        """Download a finished map JSON published at ``<base_url>/<slug>.json``
        (e.g. a raw.githubusercontent.com URL for a branch holding world-maps/)
        and save it locally, overwriting any local copy for that world."""
        import requests

        if world is None:
            world = vrchat_logs.current_world(self.agent.config.get("vrchat_log_dir") or None)
        if not world or not world.get("id"):
            raise RuntimeError("Could not detect the current world from VRChat's logs")
        slug = _slugify(world.get("name") or world["id"])
        url = base_url.rstrip("/") + f"/{slug}.json"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        path = self._map_dir() / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), "utf-8")
        self._emit(f"Synced {path.name} from {url}")
        return str(path)
