from __future__ import annotations

import json
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import requests

from nekosuneai.game_skills import GameSkillLibrary
from nekosuneai.windows_gaming_agent import GameProfile, WindowsGamingAgent

APP_TITLE = "NekoSuneAI Windows Gaming Node"
CONFIG_PATH = Path("windows-gaming-agent.json")
SKILLS_ROOT = Path("game-skills")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {
        "server_url": "",
        "verify_tls": True,
        "node_id": socket.gethostname() or "windows-gaming-pc",
        "name": "Windows Gaming Node",
        "device_token": "",
        "game_learning_file": "data/game-learning/{game_id}.json",
        "obs_host": "127.0.0.1",
        "obs_port": 4455,
        "obs_password": "",
        "twitch_login": "",
        "twitch_oauth_token": "",
        "twitch_channel": "",
    }


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), "utf-8")


def discover_candidates() -> list[str]:
    # Lightweight LAN discovery matching the Android-style setup experience.
    # We avoid assuming a single server hostname; likely local hostnames are
    # probed and the user can always enter a URL manually.
    candidates: list[str] = []
    names = ["nekosuneai.local", "nekosunepi.local", "raspberrypi.local"]
    for host in names:
        try:
            socket.gethostbyname(host)
        except OSError:
            continue
        for scheme in ("http", "https"):
            url = f"{scheme}://{host}"
            try:
                response = requests.get(url, timeout=1.5, verify=False)
                if response.status_code < 500:
                    candidates.append(url)
                    break
            except requests.RequestException:
                continue
    return candidates


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x620")
        self.minsize(700, 560)
        self.config_data = load_config()
        self.agent_thread: threading.Thread | None = None
        self.agent: WindowsGamingAgent | None = None
        self.status_var = tk.StringVar(value="Not connected")
        self.server_var = tk.StringVar(value=self.config_data.get("server_url", ""))
        self.name_var = tk.StringVar(value=self.config_data.get("name", "Windows Gaming Node"))
        self.node_var = tk.StringVar(value=self.config_data.get("node_id", socket.gethostname()))
        self.pairing_id_var = tk.StringVar()
        self.pairing_code_var = tk.StringVar()
        self.game_var = tk.StringVar()
        self.verify_tls_var = tk.BooleanVar(value=bool(self.config_data.get("verify_tls", True)))
        self._build()
        self._load_games()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 8}
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(18, 8))
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(header, text="Discover, pair and run the Windows gaming node without command-line setup.").pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=18, pady=10)
        setup = ttk.Frame(notebook)
        run = ttk.Frame(notebook)
        notebook.add(setup, text="Setup & Pair")
        notebook.add(run, text="Gaming Node")

        ttk.Label(setup, text="NekoSuneAI server URL").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(setup, textvariable=self.server_var, width=52).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(setup, text="Discover", command=self.discover).grid(row=0, column=2, **pad)

        ttk.Label(setup, text="Device name").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(setup, textvariable=self.name_var).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(setup, text="Node ID").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(setup, textvariable=self.node_var).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Checkbutton(setup, text="Verify HTTPS certificate", variable=self.verify_tls_var).grid(row=3, column=1, sticky="w", **pad)

        ttk.Separator(setup).grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=12)
        ttk.Label(setup, text="Pairing ID").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(setup, textvariable=self.pairing_id_var).grid(row=5, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(setup, text="Pairing code").grid(row=6, column=0, sticky="w", **pad)
        ttk.Entry(setup, textvariable=self.pairing_code_var).grid(row=6, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(setup, text="Save Settings", command=self.save).grid(row=7, column=1, sticky="w", **pad)
        ttk.Button(setup, text="Pair Device", command=self.pair).grid(row=7, column=2, sticky="e", **pad)
        setup.columnconfigure(1, weight=1)

        ttk.Label(run, text="Game / Remote Play profile").grid(row=0, column=0, sticky="w", **pad)
        self.game_combo = ttk.Combobox(run, textvariable=self.game_var, state="readonly")
        self.game_combo.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(run, text="Refresh Profiles", command=self._load_games).grid(row=1, column=1, sticky="w", **pad)
        ttk.Button(run, text="Start Node", command=self.start_node).grid(row=2, column=1, sticky="w", **pad)
        ttk.Button(run, text="Stop Node", command=self.stop_node).grid(row=2, column=2, sticky="e", **pad)
        ttk.Separator(run).grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=12)
        ttk.Label(run, text="Status").grid(row=4, column=0, sticky="nw", **pad)
        ttk.Label(run, textvariable=self.status_var, wraplength=480).grid(row=4, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(run, text="Emergency stop: Ctrl+Alt+F12", font=("Segoe UI", 10, "bold")).grid(row=5, column=1, columnspan=2, sticky="w", **pad)
        run.columnconfigure(1, weight=1)

    def _load_games(self) -> None:
        try:
            rows = GameSkillLibrary(SKILLS_ROOT).discover()
            values = [row["game_id"] for row in rows]
        except Exception:
            values = []
        self.game_combo["values"] = values
        if values and self.game_var.get() not in values:
            self.game_var.set(values[0])

    def current_config(self) -> dict:
        cfg = dict(self.config_data)
        cfg.update({
            "server_url": self.server_var.get().strip(),
            "verify_tls": self.verify_tls_var.get(),
            "node_id": self.node_var.get().strip() or socket.gethostname(),
            "name": self.name_var.get().strip() or "Windows Gaming Node",
        })
        return cfg

    def save(self) -> None:
        cfg = self.current_config()
        if not cfg["server_url"]:
            messagebox.showerror(APP_TITLE, "Enter or discover your NekoSuneAI server URL first.")
            return
        self.config_data = cfg
        save_config(cfg)
        self.status_var.set(f"Settings saved to {CONFIG_PATH.name}")

    def discover(self) -> None:
        self.status_var.set("Discovering NekoSuneAI on your LAN...")
        def worker() -> None:
            found = discover_candidates()
            self.after(0, lambda: self._discovery_done(found))
        threading.Thread(target=worker, daemon=True).start()

    def _discovery_done(self, found: list[str]) -> None:
        if found:
            self.server_var.set(found[0])
            self.status_var.set("Found: " + ", ".join(found))
        else:
            self.status_var.set("No automatic match found. Enter the Docker/Pi URL manually.")

    def _profile(self) -> GameProfile:
        game = self.game_var.get().strip()
        if not game:
            raise RuntimeError("Select a game profile first.")
        return GameProfile.from_mapping(GameSkillLibrary(SKILLS_ROOT).load(game).profile_mapping())

    def pair(self) -> None:
        self.save()
        if not self.config_data.get("server_url"):
            return
        pairing_id = self.pairing_id_var.get().strip()
        pairing_code = self.pairing_code_var.get().strip()
        if not pairing_id or not pairing_code:
            messagebox.showerror(APP_TITLE, "Enter the pairing ID and pairing code shown by NekoSuneAI.")
            return
        try:
            agent = WindowsGamingAgent(self.config_data, self._profile())
            token = agent.pair(pairing_id, pairing_code)
            self.config_data["device_token"] = token
            save_config(self.config_data)
            self.status_var.set("Paired successfully. Device token saved locally.")
            messagebox.showinfo(APP_TITLE, "Windows Gaming Node paired successfully.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Pairing failed:\n{exc}")

    def start_node(self) -> None:
        if self.agent_thread and self.agent_thread.is_alive():
            self.status_var.set("Gaming Node is already running.")
            return
        self.save()
        if not self.config_data.get("device_token"):
            messagebox.showerror(APP_TITLE, "Pair this Windows device first.")
            return
        try:
            self.agent = WindowsGamingAgent(self.config_data, self._profile())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Cannot start node:\n{exc}")
            return
        self.status_var.set(f"Running profile: {self.game_var.get()}")
        def worker() -> None:
            try:
                assert self.agent is not None
                self.agent.run()
                self.after(0, lambda: self.status_var.set("Gaming Node stopped."))
            except Exception as exc:
                self.after(0, lambda: self.status_var.set(f"Node stopped with error: {exc}"))
        self.agent_thread = threading.Thread(target=worker, daemon=True)
        self.agent_thread.start()

    def stop_node(self) -> None:
        if self.agent is None:
            self.status_var.set("Gaming Node is not running.")
            return
        try:
            self.agent._stop.set()
            self.status_var.set("Stopping Gaming Node...")
        except Exception as exc:
            self.status_var.set(f"Could not stop node: {exc}")


if __name__ == "__main__":
    App().mainloop()
