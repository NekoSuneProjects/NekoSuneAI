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

Once it walks back to within a short distance of where it started this pass,
that's a closed loop — that boundary is done, so it stops circling it. It
doesn't stop mapping there, though: a junction where it had to turn hard to
find a way through gets noted as a possible unexplored branch, and once the
current loop is closed it backtracks (dead-reckoned) to each noted branch in
turn and explores from there too — so a big, multi-room world like Popcorn
Palace keeps getting checked for more area instead of stopping after the
first lap, without re-walking ground it's already covered. It gives up on a
branch it can't dead-reckon its way back to (drift, or the layout changed)
rather than getting stuck, and still respects the overall time limit. The
traced path itself is stored as a filled floor polygon per pass, so a viewer
can shade in the whole room instead of needing every square metre individually
walked.

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
  * A plain "hug the wall" bias can lock onto a small interior obstacle (a
    bar counter, a pillar) and circle it forever instead of ever reaching a
    doorway to the next area. If it hasn't made real net progress over a
    stretch of steps, it forces a large break-out turn rather than politely
    continuing to circle whatever it's stuck on — but this is a heuristic,
    not a guarantee it finds every doorway in a busy room; positioning the
    avatar in the area you actually want mapped and starting a fresh pass
    from there (rather than always starting at the entrance) still works and
    merges in with what's already saved.
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

Starting a new pass for a world that already has a saved map resumes from
that map's last known position/heading (``world_map_resume`` in config,
default on) instead of resetting to (0, 0) wherever the avatar currently
stands -- stand at roughly the same physical spot you stopped at before
moving. Without this, two separate passes would have unrelated coordinate
frames, and merging would see the earlier pass's still-real walls as
"not confirmed this run" and delete them by mistake. Turn it off to
deliberately start a fresh pass at (0, 0) instead (e.g. re-mapping after a
layout change where the old coordinates no longer mean anything).

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
LOOP_CLOSE_RADIUS_M = 1.5     # back within this of this pass's start counts as "closed the loop"
LOOP_CLOSE_MIN_STEPS = 15     # don't allow loop-closure until it's actually gone somewhere first
LOOP_CLOSE_MIN_TRAVELED_M = 3.0   # ...and must have gotten at least this far from start at some point --
                                  # otherwise a tight circle around a bar counter/pillar near the start
                                  # falsely counts as "the whole room's loop is done"
OSCILLATION_WINDOW_STEPS = 24     # if position hasn't moved net OSCILLATION_MIN_NET_DISPLACEMENT_M in
OSCILLATION_MIN_NET_DISPLACEMENT_M = 3.0  # this many steps, it's circling the same spot (an obstacle,
                                           # not the room boundary) -- force a large turn to break out
HUG_BIAS_MAX_CLEAR_STEPS = 12  # only keep curving back toward a wall for this many clear steps after
                               # actually touching one -- past that it's likely lost the wall (open
                               # space), so it should walk straight instead of spiralling forever
FRONTIER_MIN_SPACING_M = 3.0  # don't note/re-visit a frontier this close to one already queued or covered
FRONTIER_JUNCTION_TURNS = 3   # needing at least this many 30 degree turns to get through implies a junction
FRONTIER_ARRIVE_RADIUS_M = 1.5
FRONTIER_MAX_QUEUED = 60      # sanity cap so a very branchy world can't queue forever
NAVIGATE_MAX_STEPS = 80       # give up backtracking to a frontier after this many steps (drift/blocked)
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
        self._active_world: dict[str, str] | None = None
        self._frontiers: list[dict[str, float]] = []
        self._visited_frontiers: list[tuple[float, float]] = []
        self._manual = threading.Event()
        self._manual_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "manual": self._manual.is_set(),
            "steps": self.steps,
            "walls_found": self.walls_found,
            "floor_index": self.floor_index,
            "floors_mapped": len(self._sealed_floors) + 1,
            "frontiers_queued": len(self._frontiers),
            "position": {"x": round(self.x, 2), "y": round(self.y, 2), "heading_deg": round(self.heading_deg, 1)},
            "events": list(self.events),
            "last_saved_path": self._last_saved_path,
            "walls": list(self._new_walls),
            "path": list(self.path[-500:]),
            "landmarks": list(self._new_landmarks),
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
        # Resolve the world ONCE, now, and reuse it at save time -- VRChat's
        # log file only gets read a bounded tail for world detection, and a
        # long/busy mapping session can push the original "Joining wrld_..."
        # line out of that window by the time the run ends, silently making
        # save() unable to tell what world it was even in. Detecting it here
        # (right as this starts, when the join line is guaranteed recent) and
        # trusting that for the whole run avoids that failure mode entirely.
        world = vrchat_logs.current_world(self.agent.config.get("vrchat_log_dir") or None)
        if not world or not world.get("id"):
            raise RuntimeError("Could not detect the current world from VRChat's logs — join a world first")
        self._active_world = world
        self.steps = self.walls_found = self.floor_index = 0
        self.path = []
        self._new_walls = []
        self._new_landmarks = []
        self._sealed_floors = []
        self._saw_velocity = False
        self._stair_streak = 0
        self._stair_direction = 0
        self._frontiers = []
        self._visited_frontiers = []

        # Resume this world's floor-0 coordinate frame from where the last
        # save left off, rather than always resetting to (0, 0) at wherever
        # the avatar currently stands -- that would put this run in an
        # unrelated coordinate frame from any earlier saved run, making merge
        # wrongly treat the earlier run's still-real walls as unconfirmed and
        # delete them. Off via world_map_resume: false in config if you'd
        # rather always start a fresh pass at (0, 0) (e.g. re-mapping after a
        # layout change where the old coordinates no longer mean anything).
        self.x = self.y = self.heading_deg = 0.0
        if bool(self.agent.config.get("world_map_resume", True)):
            existing = self._load_raw(self._map_path(world))
            if existing and existing.get("world_id") == world["id"]:
                floor0 = next((f for f in (existing.get("floors") or []) if f.get("floor_index") == 0), None)
                last_position = (floor0 or {}).get("last_position")
                if last_position:
                    self.x = float(last_position.get("x", 0.0))
                    self.y = float(last_position.get("y", 0.0))
                    self.heading_deg = float(last_position.get("heading_deg", 0.0))
                    self._emit(
                        f"Resuming from the last saved position ({self.x}, {self.y}) — "
                        "stand at roughly the same spot before moving, or turn off "
                        "\"Resume from last position\" to start a fresh pass at (0, 0)."
                    )
        if self.x == 0.0 and self.y == 0.0 and self.heading_deg == 0.0:
            self._emit("Starting a fresh pass at (0, 0).")

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
        # Infer a "kind" from the label's own text using the same patterns
        # auto-tagging uses, so a manually-typed "VIP Room" colors the same
        # on the blueprint as an OCR auto-detected one, without a separate
        # kind picker in the UI.
        kind = next((k for k, pattern in FEATURE_PATTERNS if pattern.search(label)), None)
        landmark: dict[str, Any] = {"label": label, "x": round(self.x, 2), "y": round(self.y, 2), "epoch": time.time()}
        if kind:
            landmark["kind"] = kind
        self._new_landmarks.append(landmark)
        self._emit(f"Tagged landmark '{label}' at ({round(self.x, 2)}, {round(self.y, 2)})")

    # ── manual driving (fallback for when auto wall-following makes a mess) ──

    def set_manual_mode(self, enabled: bool) -> None:
        """Pause/resume the automatic wall-following loop so a person can
        drive the avatar directly instead -- for a layout the heuristic keeps
        getting wrong (open rooms, glass, mirrors, anything that confuses
        velocity-based wall detection). Manual steps still update position and
        record walls/path into the same in-progress map, so switching back to
        auto afterwards continues from wherever manual driving left off."""
        if not self.running:
            raise RuntimeError("Start mapping before enabling manual driving")
        if enabled:
            self._manual.set()
            self._emit("Manual driving enabled — automatic wall-following paused.")
        else:
            self._manual.clear()
            self._emit("Manual driving disabled — automatic wall-following resumed.")

    def is_manual(self) -> bool:
        return self._manual.is_set()

    _MANUAL_OFFSETS = {"forward": 0.0, "back": 180.0, "strafe_left": -90.0, "strafe_right": 90.0}

    def manual_step(self, direction: str) -> None:
        """One manual movement/turn, recorded the same way an automatic step
        would be (position update or a recorded wall on no movement)."""
        if not self.running:
            raise RuntimeError("Start mapping before driving manually")
        if not self._manual.is_set():
            raise RuntimeError("Enable manual driving first")
        config = self.agent.config
        step_seconds = max(0.2, min(float(config.get("world_map_step_seconds", 0.6)), 2.0))
        walk_speed = max(0.1, float(config.get("world_map_walk_speed_mps", 2.0)))
        turn_rate = max(10.0, float(config.get("world_map_turn_deg_per_sec", 90.0)))
        with self._manual_lock:
            if direction == "turn_left":
                self._turn(-30.0, turn_rate)
            elif direction == "turn_right":
                self._turn(30.0, turn_rate)
            elif direction in self._MANUAL_OFFSETS:
                self._manual_move(self._MANUAL_OFFSETS[direction], step_seconds, walk_speed)
            else:
                raise ValueError(f"Unknown manual direction: {direction}")

    def _manual_move(self, offset_deg: float, step_seconds: float, walk_speed_mps: float) -> None:
        move_heading_rad = math.radians(self.heading_deg + offset_deg)
        if offset_deg == 0.0:
            axis, sign = "Vertical", 1.0
        elif offset_deg == 180.0:
            axis, sign = "Vertical", -1.0
        else:
            axis, sign = "Horizontal", (-1.0 if offset_deg < 0 else 1.0)
        self.agent.vrchat.pulse(axis, sign, step_seconds)
        velocity = self._velocity()
        if velocity is None:
            moved = True
        else:
            self._saw_velocity = True
            vx, vy, vz = velocity
            moved = math.hypot(vx, vz) > WALL_SPEED_THRESHOLD
        if moved:
            distance = walk_speed_mps * step_seconds
            self.x += math.cos(move_heading_rad) * distance
            self.y += math.sin(move_heading_rad) * distance
            self.path.append((round(self.x, 2), round(self.y, 2)))
        else:
            self._record_wall(move_heading_rad)
        self.steps += 1

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
            # Where this floor's local coordinate frame was left off, so a
            # later separate run can resume from here instead of resetting to
            # (0, 0) at wherever the avatar happens to be standing -- without
            # this, two separate passes would have unrelated coordinate
            # frames, and merge would see the earlier pass's real walls as
            # "not confirmed this run" and delete them.
            "last_position": {"x": round(self.x, 2), "y": round(self.y, 2), "heading_deg": round(self.heading_deg, 1)},
        }

    def _begin_new_floor(self, direction: int) -> None:
        hint = self._ocr_floor_hint()
        abandoned = f", abandoning {len(self._frontiers)} unexplored branch(es) on it" if self._frontiers else ""
        self._emit(
            f"Detected stairs {'up' if direction > 0 else 'down'} — "
            f"sealing floor {self.floor_index}{abandoned}, continuing on floor {self.floor_index + direction}."
            + (f" (saw '{hint}' on screen)" if hint else "")
        )
        self._sealed_floors.append(self._seal_current_floor())
        self.floor_index += direction
        self.x = self.y = 0.0
        self.path = []
        self._new_walls = []
        self._new_landmarks = []
        self._stair_streak = self._stair_direction = 0
        # Frontier coordinates are relative to the floor they were seen on;
        # they mean nothing on the new floor's reset-to-(0,0) local map.
        self._frontiers = []
        self._visited_frontiers = []

    # ── main loop ────────────────────────────────────────────────────────────

    def _recover_from_wall(self, step_seconds: float, walk_speed: float, turn_rate: float, turn_probe_deg: float = 30.0) -> tuple[bool, int]:
        """Turn in fixed increments looking for an opening after a blocked
        step. Returns (opened, turns_taken) — a larger turns_taken means it
        had to turn hard/far to get through, which is the closest thing to a
        junction signal available from movement feedback alone."""
        for attempt in range(1, 13):
            if self._stop.is_set():
                return False, attempt
            self._turn(turn_probe_deg, turn_rate)
            if self._try_forward(step_seconds, walk_speed):
                return True, attempt
        return False, 12

    def _maybe_add_frontier(self, x: float, y: float, heading_deg: float) -> None:
        if len(self._frontiers) >= FRONTIER_MAX_QUEUED:
            return
        for known in (*self._frontiers, *({"x": vx, "y": vy} for vx, vy in self._visited_frontiers)):
            if math.hypot(known["x"] - x, known["y"] - y) < FRONTIER_MIN_SPACING_M:
                return
        self._frontiers.append({"x": round(x, 2), "y": round(y, 2), "heading_deg": round(heading_deg, 1)})
        self._emit(f"Noted a possible unexplored branch near ({round(x, 2)}, {round(y, 2)}) to check later.")

    def _turn_to_heading(self, target_deg: float, turn_rate: float) -> None:
        delta = ((target_deg - self.heading_deg + 180) % 360) - 180
        self._turn(delta, turn_rate)

    def _explore_until_stuck(self, step_seconds: float, walk_speed: float, turn_rate: float, deadline: float) -> None:
        """Wall-hug from the current position/heading until this pass's loop
        closes, a dead end is hit, time runs out, or it's stopped. Junctions
        found along the way are queued as frontiers, not explored immediately
        — that keeps one pass simple (just hug the wall) and leaves the
        actual "go check the other branch" step to the caller."""
        turn_probe_deg, hug_deg, clear_run = 30.0, 8.0, 0
        start_x, start_y, steps_this_pass = self.x, self.y, 0
        max_dist_from_start = 0.0
        recent_positions: deque[tuple[float, float]] = deque(maxlen=OSCILLATION_WINDOW_STEPS)
        breakouts = 0
        was_manual = False
        while not self._stop.is_set() and time.monotonic() < deadline:
            if self._manual.is_set():
                was_manual = True
                time.sleep(0.2)
                continue
            if was_manual:
                # Manual driving may have moved the avatar somewhere new --
                # restart this pass's loop-closure/oscillation baselines from
                # here rather than judging against wherever automatic
                # exploration happened to start before the manual detour.
                start_x, start_y, steps_this_pass = self.x, self.y, 0
                max_dist_from_start = 0.0
                recent_positions.clear()
                clear_run = 0
                was_manual = False
            pre_x, pre_y, pre_heading = self.x, self.y, self.heading_deg
            moved = self._try_forward(step_seconds, walk_speed)
            steps_this_pass += 1
            if not moved:
                opened, turns_taken = self._recover_from_wall(step_seconds, walk_speed, turn_rate, turn_probe_deg)
                if not opened:
                    self._emit("No opening found after a full turn — this branch is a dead end.")
                    return
                clear_run = 0
                if turns_taken >= FRONTIER_JUNCTION_TURNS:
                    self._maybe_add_frontier(pre_x, pre_y, pre_heading)
            else:
                clear_run += 1
                # Only curve back while still close to the wall it just found --
                # applying this bias unconditionally forever makes it spiral
                # through open space with nothing nearby to actually hug, which
                # produces a smooth curvy/S-shaped path instead of a room-like
                # sketch. Past HUG_BIAS_MAX_CLEAR_STEPS clear steps, it's likely
                # in open space, so just walk straight until it hits something.
                if clear_run <= HUG_BIAS_MAX_CLEAR_STEPS and clear_run % 3 == 0:
                    self._turn(-hug_deg, turn_rate)
            max_dist_from_start = max(max_dist_from_start, math.hypot(self.x - start_x, self.y - start_y))
            recent_positions.append((self.x, self.y))
            if self.steps % 5 == 0:
                self._maybe_auto_tag_landmarks()
            if (
                steps_this_pass >= LOOP_CLOSE_MIN_STEPS
                and max_dist_from_start >= LOOP_CLOSE_MIN_TRAVELED_M
                and math.hypot(self.x - start_x, self.y - start_y) < LOOP_CLOSE_RADIUS_M
            ):
                self._emit("Back near where this pass started — loop closed.")
                return
            # A plain "hug the wall" bias can lock onto a small interior
            # obstacle (a bar counter, a pillar) and circle it forever instead
            # of ever reaching the room's actual boundary/doorway -- if
            # position hasn't gone anywhere net over the last stretch despite
            # taking that many steps, force a break out of the loop with a
            # large, varying turn rather than politely continuing to hug
            # whatever it's stuck on.
            if len(recent_positions) == OSCILLATION_WINDOW_STEPS:
                oldest_x, oldest_y = recent_positions[0]
                if math.hypot(self.x - oldest_x, self.y - oldest_y) < OSCILLATION_MIN_NET_DISPLACEMENT_M:
                    breakouts += 1
                    breakout_deg = 110.0 + (breakouts * 61) % 150
                    self._emit(f"Circling the same spot without making progress — forcing a {breakout_deg:.0f}° turn to break out.")
                    self._turn(breakout_deg, turn_rate)
                    recent_positions.clear()

    def _navigate_to(self, target_x: float, target_y: float, step_seconds: float, walk_speed: float, turn_rate: float, deadline: float) -> bool:
        """Best-effort dead-reckoned walk toward a previously-noted frontier.
        Returns whether it got close enough — drift, a changed layout, or a
        dead end along the way can all make a frontier unreachable, in which
        case it's simply skipped rather than getting the mapper stuck."""
        steps_taken = 0
        while steps_taken < NAVIGATE_MAX_STEPS:
            if self._stop.is_set() or time.monotonic() >= deadline:
                return False
            if self._manual.is_set():
                # Don't burn the navigation step budget while waiting out a
                # manual-driving detour -- it isn't making backtracking progress.
                time.sleep(0.2)
                continue
            dx, dy = target_x - self.x, target_y - self.y
            if math.hypot(dx, dy) < FRONTIER_ARRIVE_RADIUS_M:
                return True
            self._turn_to_heading(math.degrees(math.atan2(dy, dx)), turn_rate)
            if not self._try_forward(step_seconds, walk_speed):
                opened, _ = self._recover_from_wall(step_seconds, walk_speed, turn_rate)
                if not opened:
                    return False
            steps_taken += 1
        return math.hypot(target_x - self.x, target_y - self.y) < FRONTIER_MIN_SPACING_M

    def _run(self) -> None:
        config = self.agent.config
        step_seconds = max(0.2, min(float(config.get("world_map_step_seconds", 0.6)), 2.0))
        walk_speed = max(0.1, float(config.get("world_map_walk_speed_mps", 2.0)))
        turn_rate = max(10.0, float(config.get("world_map_turn_deg_per_sec", 90.0)))
        max_minutes = max(1.0, float(config.get("world_map_max_minutes", 10.0)))
        deadline = time.monotonic() + max_minutes * 60
        self._emit("Mapping started.")
        try:
            self._explore_until_stuck(step_seconds, walk_speed, turn_rate, deadline)
            while self._frontiers and not self._stop.is_set() and time.monotonic() < deadline:
                frontier = self._frontiers.pop(0)
                self._emit(f"Backtracking to check an unexplored area near ({frontier['x']}, {frontier['y']})…")
                if self._navigate_to(frontier["x"], frontier["y"], step_seconds, walk_speed, turn_rate, deadline):
                    self._visited_frontiers.append((self.x, self.y))
                    self._turn_to_heading(frontier["heading_deg"], turn_rate)
                    self._explore_until_stuck(step_seconds, walk_speed, turn_rate, deadline)
                else:
                    self._emit("Could not backtrack there (blocked, drifted, or out of time) — skipping it.")
            if not self._frontiers and not self._stop.is_set() and time.monotonic() < deadline:
                self._emit("No more unexplored branches noted on this floor — mapping this pass is done.")
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
        # Runs in a background thread with no console attached -- an
        # unhandled exception here would otherwise just vanish silently
        # (the thread dies, nothing gets written, and there's no visible
        # trace of why). Always emit *something* the GUI's event log shows.
        try:
            # Use the world resolved at start() rather than re-reading VRChat's
            # log now: a long/busy session can push the original "Joining
            # wrld_..." line out of the log's bounded read-tail by the time
            # mapping ends, which would otherwise make save() silently think
            # it can't tell what world this was and skip saving entirely.
            world = self._active_world or vrchat_logs.current_world(self.agent.config.get("vrchat_log_dir") or None)
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
        except Exception as exc:
            self._emit(f"Failed to save the world map: {exc}")

    def load_saved(self) -> dict[str, Any] | None:
        """The last-saved map for whatever world VRChat's logs say we're
        currently in, for a viewer to render when nothing is actively being
        mapped right now."""
        world = vrchat_logs.current_world(self.agent.config.get("vrchat_log_dir") or None)
        if not world or not world.get("id"):
            return None
        data = self._load_raw(self._map_path(world))
        if data and data.get("world_id") != world["id"]:
            return None
        return data

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
