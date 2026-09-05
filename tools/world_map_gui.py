"""World Map page for the Windows app: manual VRChat wall-following mapper."""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# Same resolution windows_gaming_node_gui.py uses for its own BASE_DIR: the
# frozen EXE's own folder, or this checkout's root when run from source. Used
# only as the *default* world_map_dir so a fresh install maps to "wherever
# the app is running from" instead of whatever the process's current working
# directory happens to be (which a shortcut/launcher doesn't always set to
# the EXE's folder) — once saved, the value in config wins regardless.
_BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


class WorldMapControls:
    def _init_world_map_controls(self):
        defaults = {
            "world_map_dir": str(_BASE_DIR / "world-maps"),
            "world_map_step_seconds": 0.6,
            "world_map_walk_speed_mps": 2.0,
            "world_map_turn_deg_per_sec": 90.0,
            "world_map_max_minutes": 10,
            "world_map_sync_base_url": "",
        }
        self.world_map_settings = {}
        for key, value in defaults.items():
            cls = tk.IntVar if isinstance(value, int) and not isinstance(value, bool) else \
                (tk.DoubleVar if isinstance(value, float) else tk.StringVar)
            self.world_map_settings[key] = cls(value=self.config_data.get(key, value))
        self.world_map_current_var = tk.StringVar(value="Current world: unknown (pair, select the VRChat profile and start the node)")
        self.world_map_status_var = tk.StringVar(value="Not mapping")
        self.landmark_label_var = tk.StringVar(value="VIP Room")

    def _world_map_values(self):
        values = {key: variable.get() for key, variable in self.world_map_settings.items()}
        for key, low, high in (("world_map_step_seconds", 0.2, 2.0), ("world_map_walk_speed_mps", 0.1, 10.0),
                                ("world_map_turn_deg_per_sec", 10.0, 360.0), ("world_map_max_minutes", 1, 120)):
            if not low <= float(values[key]) <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        return values

    def _build_world_map_page(self):
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["worldmap"] = page

        card = self._card(
            page, "World Map (VRChat, manual)",
            "Walks the current world like someone feeling their way along a wall: tries forward, "
            "turns when blocked, and traces the path/edges it finds into a JSON file named after the "
            "world under the folder below. Re-running it on the same world keeps confirmed walls, "
            "drops ones that no longer show up (an updated world version), and adds new ones. Start "
            "this only while the VRChat profile is selected, the node is running, and OSC is armed.",
        )
        card.columnconfigure(1, weight=1)
        ttk.Label(card, textvariable=self.world_map_current_var, style="Body.TLabel", wraplength=500).grid(row=0, column=0, columnspan=2, sticky="w", padx=22, pady=(8, 4))

        settings = ttk.Frame(card, style="Card.TFrame")
        settings.grid(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=4)
        self._field(settings, "Map folder", self.world_map_settings["world_map_dir"], 0)
        self._field(settings, "Step seconds", self.world_map_settings["world_map_step_seconds"], 1)
        self._field(settings, "Walk speed (m/s)", self.world_map_settings["world_map_walk_speed_mps"], 2)
        self._field(settings, "Turn rate (deg/s)", self.world_map_settings["world_map_turn_deg_per_sec"], 3)
        self._field(settings, "Max minutes per run", self.world_map_settings["world_map_max_minutes"], 4)
        settings.columnconfigure(1, weight=1)

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
        ttk.Button(actions, text="Save settings", command=self._save_world_map_settings, style="Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Start mapping", command=self._start_world_mapping, style="Primary.TButton").pack(side="left", padx=6)
        ttk.Button(actions, text="Stop mapping", command=self._stop_world_mapping, style="Danger.TButton").pack(side="right")

        landmark = ttk.Frame(card, style="Card.TFrame")
        landmark.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=4)
        landmark.columnconfigure(0, weight=1)
        ttk.Entry(landmark, textvariable=self.landmark_label_var, style="Modern.TEntry").grid(row=0, column=0, sticky="ew")
        ttk.Button(landmark, text="Tag landmark here", command=self._tag_world_landmark, style="Secondary.TButton").grid(row=0, column=1, padx=(8, 0))

        ttk.Label(card, textvariable=self.world_map_status_var, style="Muted.TLabel", wraplength=500).grid(row=4, column=0, columnspan=2, sticky="w", padx=22, pady=8)
        self.world_map_canvas = tk.Canvas(card, width=480, height=360, bg="#0f151c", highlightthickness=0)
        self.world_map_canvas.grid(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 8))
        self.world_map_log = self._text_output(card)
        self.world_map_log.grid(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 8))

        sync = self._card(
            page, "Sync a finished map",
            "Download an already-mapped world's JSON from a raw file host (e.g. a raw.githubusercontent.com "
            "URL for a branch holding world-maps/) instead of remapping it yourself. Overwrites the local "
            "copy for the current world.",
        )
        sync.columnconfigure(1, weight=1)
        self._field(sync, "Map source base URL", self.world_map_settings["world_map_sync_base_url"], 0)
        ttk.Button(sync, text="Sync map for current world", command=self._sync_world_map, style="Primary.TButton").grid(row=1, column=1, sticky="e", padx=22, pady=8)

    def _save_world_map_settings(self):
        try:
            values = self._world_map_values()
        except ValueError as exc:
            messagebox.showerror("World map settings", str(exc))
            return
        self.config_data.update(values)
        if self.agent is not None:
            self.agent.config.update(values)
        self.save()

    def _start_world_mapping(self):
        if self.agent is None:
            messagebox.showerror("World map", "Start the Gaming Node first.")
            return
        self._save_world_map_settings()
        try:
            self.agent.world_mapper.start()
        except RuntimeError as exc:
            messagebox.showerror("World map", str(exc))

    def _stop_world_mapping(self):
        if self.agent is not None:
            self.agent.world_mapper.stop()

    def _tag_world_landmark(self):
        if self.agent is None:
            return
        try:
            self.agent.world_mapper.tag_landmark(self.landmark_label_var.get())
        except RuntimeError as exc:
            messagebox.showerror("World map", str(exc))

    def _sync_world_map(self):
        if self.agent is None:
            messagebox.showerror("World map", "Start the Gaming Node first (it reads the current world from VRChat's logs).")
            return
        base_url = self.world_map_settings["world_map_sync_base_url"].get().strip()
        if not base_url:
            messagebox.showerror("World map", "Enter a map source base URL first.")
            return
        try:
            path = self.agent.world_mapper.sync_from_url(base_url)
        except Exception as exc:
            messagebox.showerror("World map", str(exc))
            return
        self.status_var.set(f"Synced world map to {path}")

    def _redraw_world_map_canvas(self):
        canvas = self.world_map_canvas
        canvas.delete("all")
        width, height = 480, 360
        walls, path, landmarks, position = [], [], [], None
        if self.agent is not None:
            state = self.agent.world_mapper.status()
            if state["running"]:
                walls, path, landmarks, position = state["walls"], state["path"], state["landmarks"], state["position"]
            else:
                data = self.agent.world_mapper.load_saved()
                if data and data.get("floors"):
                    floor = next((f for f in data["floors"] if f.get("floor_index") == 0), data["floors"][0])
                    walls, path, landmarks = floor.get("walls") or [], floor.get("path") or [], floor.get("landmarks") or []
        points = [(w["x1"], w["y1"]) for w in walls] + [(w["x2"], w["y2"]) for w in walls]
        points += [(p[0], p[1]) for p in path] + [(l["x"], l["y"]) for l in landmarks]
        if position:
            points.append((position["x"], position["y"]))
        if not points:
            canvas.create_text(width // 2, height // 2, text="No map data yet for the current world.", fill="#93a4b7", font=("Segoe UI", 10))
            return
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        margin = 24
        scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)

        def to_canvas(x, y):
            return margin + (x - min_x) * scale, height - (margin + (y - min_y) * scale)

        if len(path) >= 2:
            coords = [c for p in path for c in to_canvas(p[0], p[1])]
            canvas.create_line(*coords, fill="#7c5cff", width=2)
        for wall in walls:
            x1, y1 = to_canvas(wall["x1"], wall["y1"])
            x2, y2 = to_canvas(wall["x2"], wall["y2"])
            canvas.create_line(x1, y1, x2, y2, fill="#ff5d6c", width=3)
        for landmark in landmarks:
            lx, ly = to_canvas(landmark["x"], landmark["y"])
            color = "#2ed69b" if landmark.get("auto") else "#f4c542"
            canvas.create_oval(lx - 4, ly - 4, lx + 4, ly + 4, fill=color, outline="")
            canvas.create_text(lx + 8, ly, text=str(landmark.get("label", ""))[:30], fill="#f4f7fb", font=("Segoe UI", 8), anchor="w")
        if position:
            px, py = to_canvas(position["x"], position["y"])
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5, outline="#67e8f9", width=2)

    def _refresh_world_map_status(self):
        if self.agent is not None:
            log_dir = self.agent.config.get("vrchat_log_dir") or None
            try:
                from nekosuneai import vrchat_logs
                world = vrchat_logs.current_world(log_dir)
            except Exception:
                world = None
            if world and (world.get("name") or world.get("id")):
                self.world_map_current_var.set(f"Current world: {world.get('name') or world['id']} ({world.get('id', '')})")
            else:
                self.world_map_current_var.set("Current world: not detected yet (join a world in VRChat).")
            state = self.agent.world_mapper.status()
            position = state["position"]
            self.world_map_status_var.set(
                ("Mapping…" if state["running"] else "Not mapping") +
                f" — floor {state['floor_index']} ({state['floors_mapped']} floor(s) so far), "
                f"steps: {state['steps']}, walls found: {state['walls_found']}, "
                f"unexplored branches queued: {state['frontiers_queued']}, "
                f"position: ({position['x']}, {position['y']}), heading: {position['heading_deg']}°"
                + (f"\nLast saved: {state['last_saved_path']}" if state["last_saved_path"] else "")
            )
            self._set_readonly_text(self.world_map_log, "\n".join(state["events"]) or "No events yet.")
        self._redraw_world_map_canvas()
        self.after(1000, self._refresh_world_map_status)
