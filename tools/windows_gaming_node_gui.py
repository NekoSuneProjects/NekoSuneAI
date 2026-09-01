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

BG = "#0b0f14"
PANEL = "#111820"
PANEL_2 = "#151e28"
BORDER = "#24303d"
TEXT = "#f4f7fb"
MUTED = "#93a4b7"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#927cff"
SUCCESS = "#2ed69b"
DANGER = "#ff5d6c"
INPUT_BG = "#0f151c"


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
    candidates: list[str] = []
    names = ["nekosuneai.local", "nekosunepi.local", "raspberrypi.local"]
    for host in names:
        try:
            socket.gethostbyname(host)
        except OSError:
            continue
        for scheme in ("https", "http"):
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
        self.geometry("1080x720")
        self.minsize(920, 620)
        self.configure(bg=BG)

        self.config_data = load_config()
        self.agent_thread: threading.Thread | None = None
        self.agent: WindowsGamingAgent | None = None

        self.status_var = tk.StringVar(value="Ready")
        self.connection_var = tk.StringVar(value="Not paired")
        self.server_var = tk.StringVar(value=self.config_data.get("server_url", ""))
        self.name_var = tk.StringVar(value=self.config_data.get("name", "Windows Gaming Node"))
        self.node_var = tk.StringVar(value=self.config_data.get("node_id", socket.gethostname()))
        self.pairing_id_var = tk.StringVar()
        self.pairing_code_var = tk.StringVar()
        self.game_var = tk.StringVar()
        self.verify_tls_var = tk.BooleanVar(value=bool(self.config_data.get("verify_tls", True)))

        self._configure_style()
        self._build()
        self._load_games()
        self._refresh_pair_state()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=PANEL_2)
        style.configure("Sidebar.TFrame", background="#0d131a")

        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background=PANEL_2, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Body.TLabel", background=PANEL_2, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=PANEL_2, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#0d131a", foreground=MUTED, font=("Segoe UI", 9))

        style.configure(
            "Modern.TEntry",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
            padding=9,
        )
        style.map("Modern.TEntry", bordercolor=[("focus", ACCENT)])

        style.configure(
            "Modern.TCombobox",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=8,
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT)],
        )

        style.configure(
            "Primary.TButton",
            background=ACCENT,
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=(16, 10),
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("pressed", "#6d50e8")])

        style.configure(
            "Secondary.TButton",
            background="#1b2530",
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(14, 9),
            font=("Segoe UI", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#24313f")])

        style.configure(
            "Danger.TButton",
            background="#3a1820",
            foreground="#ff9aa6",
            borderwidth=0,
            padding=(14, 9),
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#51212b")])

        style.configure(
            "Modern.TCheckbutton",
            background=PANEL_2,
            foreground=TEXT,
            font=("Segoe UI", 9),
            indicatorcolor=INPUT_BG,
            indicatorrelief="flat",
        )
        style.map("Modern.TCheckbutton", background=[("active", PANEL_2)], indicatorcolor=[("selected", ACCENT)])

    def _build(self) -> None:
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        content = ttk.Frame(root, style="App.TFrame")
        content.pack(side="left", fill="both", expand=True)

        brand = tk.Frame(sidebar, bg="#0d131a")
        brand.pack(fill="x", padx=22, pady=(24, 18))
        tk.Label(brand, text="NekoSuneAI", bg="#0d131a", fg=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(brand, text="WINDOWS GAMING NODE", bg="#0d131a", fg=ACCENT, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(2, 0))

        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label, glyph in (
            ("setup", "Setup & Pair", "●"),
            ("gaming", "Gaming Node", "▶"),
            ("about", "Status", "◆"),
        ):
            btn = tk.Button(
                sidebar,
                text=f"  {glyph}   {label}",
                anchor="w",
                relief="flat",
                bd=0,
                bg="#0d131a",
                fg=MUTED,
                activebackground="#161f29",
                activeforeground=TEXT,
                font=("Segoe UI", 10, "bold"),
                padx=14,
                pady=12,
                cursor="hand2",
                command=lambda page=key: self._show_page(page),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(18, 12))
        tk.Label(sidebar, text="CONNECTION", bg="#0d131a", fg="#66788a", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=24)
        self.sidebar_state = tk.Label(sidebar, textvariable=self.connection_var, bg="#0d131a", fg=MUTED, font=("Segoe UI", 9))
        self.sidebar_state.pack(anchor="w", padx=24, pady=(6, 0))

        tk.Label(
            sidebar,
            text="Emergency stop\nCtrl + Alt + F12",
            justify="left",
            bg="#0d131a",
            fg="#ff8b97",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="bottom", anchor="w", padx=24, pady=24)

        header = ttk.Frame(content, style="App.TFrame")
        header.pack(fill="x", padx=34, pady=(28, 14))
        ttk.Label(header, text="Windows Gaming Node", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Connect your gaming PC to NekoSuneAI, discover the server, pair the device and run game profiles.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        self.page_host = ttk.Frame(content, style="App.TFrame")
        self.page_host.pack(fill="both", expand=True, padx=34, pady=(0, 24))

        self.pages: dict[str, ttk.Frame] = {}
        self._build_setup_page()
        self._build_gaming_page()
        self._build_status_page()

        statusbar = ttk.Frame(content, style="Sidebar.TFrame")
        statusbar.pack(fill="x", side="bottom")
        ttk.Label(statusbar, textvariable=self.status_var, style="Status.TLabel").pack(side="left", padx=18, pady=8)
        ttk.Label(statusbar, text="NekoSuneAI • Windows", style="Status.TLabel").pack(side="right", padx=18, pady=8)

        self._show_page("setup")

    def _card(self, parent: tk.Widget, title: str, subtitle: str = "") -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame")
        outer.pack(fill="x", pady=(0, 16))
        top = ttk.Frame(outer, style="Card.TFrame")
        top.pack(fill="x", padx=22, pady=(18, 12))
        ttk.Label(top, text=title, style="Heading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(top, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        return outer

    def _field(self, parent: tk.Widget, label: str, variable: tk.Variable, row: int, *, secret: bool = False) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Body.TLabel").grid(row=row, column=0, sticky="w", padx=(22, 18), pady=9)
        entry = ttk.Entry(parent, textvariable=variable, style="Modern.TEntry", show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 22), pady=9)
        return entry

    def _build_setup_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["setup"] = page

        server_card = self._card(page, "Server connection", "Find your NekoSuneAI Docker/Pi instance automatically or enter it manually.")
        server_card.columnconfigure(1, weight=1)
        self._field(server_card, "Server URL", self.server_var, 1)
        ttk.Label(server_card, text="Device name", style="Body.TLabel").grid(row=2, column=0, sticky="w", padx=(22, 18), pady=9)
        ttk.Entry(server_card, textvariable=self.name_var, style="Modern.TEntry").grid(row=2, column=1, sticky="ew", padx=(0, 22), pady=9)
        self._field(server_card, "Node ID", self.node_var, 3)

        controls = ttk.Frame(server_card, style="Card.TFrame")
        controls.grid(row=4, column=0, columnspan=2, sticky="ew", padx=22, pady=(8, 20))
        ttk.Checkbutton(controls, text="Verify HTTPS certificate", variable=self.verify_tls_var, style="Modern.TCheckbutton").pack(side="left")
        ttk.Button(controls, text="Discover server", command=self.discover, style="Secondary.TButton").pack(side="right")
        ttk.Button(controls, text="Save settings", command=self.save, style="Primary.TButton").pack(side="right", padx=(0, 10))

        pair_card = self._card(page, "Pair this PC", "Use the pairing ID and code shown by your NekoSuneAI dashboard.")
        pair_card.columnconfigure(1, weight=1)
        self._field(pair_card, "Pairing ID", self.pairing_id_var, 1)
        self._field(pair_card, "Pairing code", self.pairing_code_var, 2, secret=True)

        pair_actions = ttk.Frame(pair_card, style="Card.TFrame")
        pair_actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 20))
        ttk.Label(pair_actions, textvariable=self.connection_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(pair_actions, text="Pair device", command=self.pair, style="Primary.TButton").pack(side="right")

    def _build_gaming_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["gaming"] = page

        profile_card = self._card(page, "Game & Remote Play", "Choose a reviewed game profile, Xbox Remote Play or PlayStation Remote Play.")
        profile_card.columnconfigure(1, weight=1)
        ttk.Label(profile_card, text="Profile", style="Body.TLabel").grid(row=1, column=0, sticky="w", padx=(22, 18), pady=10)
        self.game_combo = ttk.Combobox(profile_card, textvariable=self.game_var, state="readonly", style="Modern.TCombobox")
        self.game_combo.grid(row=1, column=1, sticky="ew", padx=(0, 22), pady=10)

        actions = ttk.Frame(profile_card, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 20))
        ttk.Button(actions, text="Refresh profiles", command=self._load_games, style="Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Stop node", command=self.stop_node, style="Danger.TButton").pack(side="right")
        ttk.Button(actions, text="Start node", command=self.start_node, style="Primary.TButton").pack(side="right", padx=(0, 10))

        live_card = self._card(page, "Live status", "The local node stays connected to the Pi/Docker brain and only executes approved game capabilities.")
        live_inner = ttk.Frame(live_card, style="Card.TFrame")
        live_inner.pack(fill="x", padx=22, pady=(0, 20))

        self.live_dot = tk.Canvas(live_inner, width=12, height=12, bg=PANEL_2, highlightthickness=0)
        self.live_dot.pack(side="left", padx=(0, 10))
        self.live_dot.create_oval(2, 2, 10, 10, fill="#657280", outline="")
        ttk.Label(live_inner, textvariable=self.status_var, style="Body.TLabel", wraplength=650).pack(side="left")

    def _build_status_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["about"] = page

        card = self._card(page, "Node overview", "Local configuration and safety status.")
        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill="x", padx=22, pady=(0, 20))

        rows = (
            ("Device", self.name_var),
            ("Node ID", self.node_var),
            ("Server", self.server_var),
            ("Connection", self.connection_var),
            ("Selected profile", self.game_var),
        )
        for label, var in rows:
            line = ttk.Frame(body, style="Card.TFrame")
            line.pack(fill="x", pady=7)
            ttk.Label(line, text=label, style="Muted.TLabel", width=18).pack(side="left")
            ttk.Label(line, textvariable=var, style="Body.TLabel").pack(side="left")

        safety = self._card(page, "Safety", "Input remains bounded to approved profiles and the selected foreground game window.")
        ttk.Label(
            safety,
            text="Ctrl + Alt + F12 immediately releases active input and disables AI game control.",
            style="Body.TLabel",
        ).pack(anchor="w", padx=22, pady=(0, 20))

    def _show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for key, button in self.nav_buttons.items():
            active = key == name
            button.configure(bg="#181f2a" if active else "#0d131a", fg=TEXT if active else MUTED)

    def _refresh_pair_state(self) -> None:
        paired = bool(self.config_data.get("device_token"))
        self.connection_var.set("Paired" if paired else "Not paired")
        self.sidebar_state.configure(fg=SUCCESS if paired else MUTED)

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
        self.status_var.set("Settings saved")

    def discover(self) -> None:
        self.status_var.set("Discovering NekoSuneAI on your LAN…")

        def worker() -> None:
            found = discover_candidates()
            self.after(0, lambda: self._discovery_done(found))

        threading.Thread(target=worker, daemon=True).start()

    def _discovery_done(self, found: list[str]) -> None:
        if found:
            self.server_var.set(found[0])
            self.status_var.set(f"Found NekoSuneAI at {found[0]}")
        else:
            self.status_var.set("No automatic match found — enter the Docker/Pi URL manually")

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

        self.status_var.set("Pairing Windows Gaming Node…")

        def worker() -> None:
            try:
                agent = WindowsGamingAgent(self.config_data, self._profile())
                token = agent.pair(pairing_id, pairing_code)
                self.config_data["device_token"] = token
                save_config(self.config_data)
                self.after(0, self._pair_success)
            except Exception as exc:
                self.after(0, lambda: self._pair_failed(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _pair_success(self) -> None:
        self._refresh_pair_state()
        self.pairing_code_var.set("")
        self.status_var.set("Paired successfully")
        messagebox.showinfo(APP_TITLE, "Windows Gaming Node paired successfully.")

    def _pair_failed(self, error: str) -> None:
        self.status_var.set("Pairing failed")
        messagebox.showerror(APP_TITLE, f"Pairing failed:\n{error}")

    def start_node(self) -> None:
        if self.agent_thread and self.agent_thread.is_alive():
            self.status_var.set("Gaming Node is already running")
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

        self.status_var.set(f"Running • {self.game_var.get()}")
        self.live_dot.delete("all")
        self.live_dot.create_oval(2, 2, 10, 10, fill=SUCCESS, outline="")

        def worker() -> None:
            try:
                assert self.agent is not None
                self.agent.run()
                self.after(0, self._node_stopped)
            except Exception as exc:
                self.after(0, lambda: self._node_error(str(exc)))

        self.agent_thread = threading.Thread(target=worker, daemon=True)
        self.agent_thread.start()

    def _node_stopped(self) -> None:
        self.status_var.set("Gaming Node stopped")
        self.live_dot.delete("all")
        self.live_dot.create_oval(2, 2, 10, 10, fill="#657280", outline="")

    def _node_error(self, error: str) -> None:
        self.status_var.set(f"Node error • {error}")
        self.live_dot.delete("all")
        self.live_dot.create_oval(2, 2, 10, 10, fill=DANGER, outline="")

    def stop_node(self) -> None:
        if self.agent is None:
            self.status_var.set("Gaming Node is not running")
            return
        try:
            self.agent._stop.set()
            self.status_var.set("Stopping Gaming Node…")
        except Exception as exc:
            self.status_var.set(f"Could not stop node • {exc}")


if __name__ == "__main__":
    App().mainloop()
