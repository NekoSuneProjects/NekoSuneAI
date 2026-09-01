from __future__ import annotations

import ipaddress
import json
import socket
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import messagebox, ttk

import requests
import urllib3

from nekosuneai.game_skills import GameSkillLibrary
from nekosuneai.windows_gaming_agent import GameProfile, WindowsGamingAgent

APP_TITLE = "NekoSuneAI Windows Gaming Node"
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "windows-gaming-agent.json"
SKILLS_ROOT = BASE_DIR / "game-skills"
DEFAULT_SERVER_PORT = 8788
MDNS_SERVICE = "_nekosuneai._tcp.local."

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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        "game_learning_file": str(BASE_DIR / "data/game-learning/{game_id}.json"),
        "obs_host": "127.0.0.1",
        "obs_port": 4455,
        "obs_password": "",
        "twitch_login": "",
        "twitch_oauth_token": "",
        "twitch_channel": "",
    }


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), "utf-8")


def _local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")):
                addresses.add(ip)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.25)
        probe.connect(("1.1.1.1", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if not ip.startswith(("127.", "169.254.")):
            addresses.add(ip)
    except OSError:
        pass
    return sorted(addresses)


def _looks_like_nekosuneai(url: str) -> bool:
    base = url.rstrip("/")
    try:
        response = requests.get(base + "/api/pairing/status", timeout=1.3, verify=False, allow_redirects=False)
        if response.status_code in {200, 400, 401, 403, 405, 422}:
            return True
    except requests.RequestException:
        pass
    try:
        response = requests.get(base + "/", timeout=1.3, verify=False, allow_redirects=True)
        text = response.text[:12000].casefold()
        return response.status_code < 500 and ("nekosuneai" in text or "/login" in response.url.casefold())
    except requests.RequestException:
        return False


def _decode_property(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore").strip()
    return str(value).strip()


def _discover_mdns(timeout: float = 3.0) -> list[str]:
    """Match Android discovery: read the advertised HTTPS public_url first.

    If the server has no public domain configured, use the mDNS service IPv4 and
    advertised port (normally http://LAN-IP:8788).
    """
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except Exception:
        return []

    found: list[str] = []
    lock = threading.Lock()

    class Listener(ServiceListener):
        def add_service(self, zc, service_type, name):
            self._resolve(zc, service_type, name)

        def update_service(self, zc, service_type, name):
            self._resolve(zc, service_type, name)

        def remove_service(self, zc, service_type, name):
            return

        def _resolve(self, zc, service_type, name):
            try:
                info = zc.get_service_info(service_type, name, timeout=1200)
                if not info:
                    return
                props = info.properties or {}
                public_url = _decode_property(props.get(b"public_url") or props.get("public_url")).rstrip("/")
                local_url = _decode_property(props.get(b"local_url") or props.get("local_url")).rstrip("/")
                addresses = info.parsed_addresses()
                candidates: list[str] = []
                if public_url.startswith("https://"):
                    candidates.append(public_url)
                if local_url.startswith(("http://", "https://")):
                    candidates.append(local_url)
                for address in addresses:
                    try:
                        ip = ipaddress.ip_address(address.split("%", 1)[0])
                    except ValueError:
                        continue
                    if ip.version == 4 and (ip.is_private or ip.is_link_local):
                        candidates.append(f"http://{address}:{info.port}")
                with lock:
                    for candidate in candidates:
                        if candidate not in found:
                            found.append(candidate)
            except Exception:
                return

    zc = Zeroconf()
    browser = ServiceBrowser(zc, MDNS_SERVICE, Listener())
    try:
        time.sleep(timeout)
    finally:
        try:
            browser.cancel()
        except Exception:
            pass
        zc.close()
    return found


def _scan_lan_8788() -> list[str]:
    own_ips = set(_local_ipv4_addresses())
    networks: set[ipaddress.IPv4Network] = set()
    for ip in own_ips:
        try:
            networks.add(ipaddress.ip_network(f"{ip}/24", strict=False))
        except ValueError:
            pass

    hosts = [str(addr) for network in networks for addr in network.hosts() if str(addr) not in own_ips]

    def probe(host: str) -> str | None:
        try:
            with socket.create_connection((host, DEFAULT_SERVER_PORT), timeout=0.18):
                pass
        except OSError:
            return None
        candidate = f"http://{host}:{DEFAULT_SERVER_PORT}"
        return candidate if _looks_like_nekosuneai(candidate) else None

    results: list[str] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = [pool.submit(probe, host) for host in hosts]
        for future in as_completed(futures):
            try:
                value = future.result()
                if value and value not in results:
                    results.append(value)
            except Exception:
                pass
    return results


def discover_candidates() -> list[str]:
    results: list[str] = []

    def add(candidate: str) -> None:
        clean = candidate.strip().rstrip("/")
        if clean and clean not in results:
            results.append(clean)

    # Same order as Android: mDNS metadata first, with public HTTPS preferred.
    for candidate in _discover_mdns():
        add(candidate)

    # If mDNS is unavailable, try common .local names.
    for host in ("nekosuneai.local", "nekosunepi.local", "raspberrypi.local"):
        try:
            socket.gethostbyname(host)
        except OSError:
            continue
        candidate = f"http://{host}:{DEFAULT_SERVER_PORT}"
        if _looks_like_nekosuneai(candidate):
            add(candidate)

    # Final fallback mirrors Android's local-network behavior with IPv4:8788.
    for candidate in _scan_lan_8788():
        add(candidate)

    # Keep HTTPS first whenever the Docker advertises a domain.
    results.sort(key=lambda value: (0 if value.startswith("https://") else 1, value))
    return results


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
        for name, bg in (("App.TFrame", BG), ("Card.TFrame", PANEL_2), ("Sidebar.TFrame", "#0d131a")):
            style.configure(name, background=bg)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background=PANEL_2, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Body.TLabel", background=PANEL_2, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=PANEL_2, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#0d131a", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Modern.TEntry", fieldbackground=INPUT_BG, foreground=TEXT, bordercolor=BORDER, insertcolor=TEXT, padding=9)
        style.configure("Modern.TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG, foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER, padding=8)
        style.map("Modern.TCombobox", fieldbackground=[("readonly", INPUT_BG)], foreground=[("readonly", TEXT)])
        style.configure("Primary.TButton", background=ACCENT, foreground="white", borderwidth=0, padding=(16, 10), font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", ACCENT_HOVER)])
        style.configure("Secondary.TButton", background="#1b2530", foreground=TEXT, bordercolor=BORDER, padding=(14, 9))
        style.configure("Danger.TButton", background="#3a1820", foreground="#ff9aa6", borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.configure("Modern.TCheckbutton", background=PANEL_2, foreground=TEXT, indicatorcolor=INPUT_BG)
        style.map("Modern.TCheckbutton", indicatorcolor=[("selected", ACCENT)])

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
        for key, label, glyph in (("setup", "Setup & Pair", "●"), ("gaming", "Gaming Node", "▶"), ("about", "Status", "◆")):
            button = tk.Button(sidebar, text=f"  {glyph}   {label}", anchor="w", relief="flat", bd=0, bg="#0d131a", fg=MUTED, activebackground="#161f29", activeforeground=TEXT, font=("Segoe UI", 10, "bold"), padx=14, pady=12, cursor="hand2", command=lambda page=key: self._show_page(page))
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = button

        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(18, 12))
        tk.Label(sidebar, text="CONNECTION", bg="#0d131a", fg="#66788a", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=24)
        self.sidebar_state = tk.Label(sidebar, textvariable=self.connection_var, bg="#0d131a", fg=MUTED, font=("Segoe UI", 9))
        self.sidebar_state.pack(anchor="w", padx=24, pady=(6, 0))
        tk.Label(sidebar, text="Emergency stop\nCtrl + Alt + F12", justify="left", bg="#0d131a", fg="#ff8b97", font=("Segoe UI", 9, "bold")).pack(side="bottom", anchor="w", padx=24, pady=24)

        header = ttk.Frame(content, style="App.TFrame")
        header.pack(fill="x", padx=34, pady=(28, 14))
        ttk.Label(header, text="Windows Gaming Node", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Android-style discovery prefers your HTTPS domain and falls back to LAN IPv4:8788.", style="Subtitle.TLabel").pack(anchor="w", pady=(5, 0))

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
        # IMPORTANT: outer uses pack only. The returned body may use grid OR pack.
        # This prevents Tk's "cannot use geometry manager grid ... already managed by pack" crash.
        outer = ttk.Frame(parent, style="Card.TFrame")
        outer.pack(fill="x", pady=(0, 16))
        top = ttk.Frame(outer, style="Card.TFrame")
        top.pack(fill="x", padx=22, pady=(18, 12))
        ttk.Label(top, text=title, style="Heading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(top, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        body = ttk.Frame(outer, style="Card.TFrame")
        body.pack(fill="x", expand=True, pady=(0, 6))
        return body

    def _field(self, parent: tk.Widget, label: str, variable: tk.Variable, row: int, *, secret: bool = False) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Body.TLabel").grid(row=row, column=0, sticky="w", padx=(22, 18), pady=9)
        entry = ttk.Entry(parent, textvariable=variable, style="Modern.TEntry", show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 22), pady=9)
        return entry

    def _build_setup_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["setup"] = page
        server = self._card(page, "Server connection", "Discovery matches Android: HTTPS public domain first, local IPv4:8788 fallback.")
        server.columnconfigure(1, weight=1)
        self._field(server, "Server URL", self.server_var, 0)
        self._field(server, "Device name", self.name_var, 1)
        self._field(server, "Node ID", self.node_var, 2)
        controls = ttk.Frame(server, style="Card.TFrame")
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(8, 14))
        ttk.Checkbutton(controls, text="Verify HTTPS certificate", variable=self.verify_tls_var, style="Modern.TCheckbutton").pack(side="left")
        ttk.Button(controls, text="Discover server", command=self.discover, style="Secondary.TButton").pack(side="right")
        ttk.Button(controls, text="Save settings", command=self.save, style="Primary.TButton").pack(side="right", padx=(0, 10))

        pair = self._card(page, "Pair this PC", "Use the Windows node pairing ID/code from the authenticated NekoSuneAI dashboard.")
        pair.columnconfigure(1, weight=1)
        self._field(pair, "Pairing ID", self.pairing_id_var, 0)
        self._field(pair, "Pairing code", self.pairing_code_var, 1, secret=True)
        actions = ttk.Frame(pair, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 14))
        ttk.Label(actions, textvariable=self.connection_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(actions, text="Pair device", command=self.pair, style="Primary.TButton").pack(side="right")

    def _build_gaming_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["gaming"] = page
        profile = self._card(page, "Game & Remote Play", "Choose a reviewed game profile, Xbox Remote Play or PlayStation Remote Play.")
        profile.columnconfigure(1, weight=1)
        ttk.Label(profile, text="Profile", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(22, 18), pady=10)
        self.game_combo = ttk.Combobox(profile, textvariable=self.game_var, state="readonly", style="Modern.TCombobox")
        self.game_combo.grid(row=0, column=1, sticky="ew", padx=(0, 22), pady=10)
        actions = ttk.Frame(profile, style="Card.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 14))
        ttk.Button(actions, text="Refresh profiles", command=self._load_games, style="Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Stop node", command=self.stop_node, style="Danger.TButton").pack(side="right")
        ttk.Button(actions, text="Start node", command=self.start_node, style="Primary.TButton").pack(side="right", padx=(0, 10))

        live = self._card(page, "Live status", "The node only executes approved gaming capabilities.")
        self.live_dot = tk.Canvas(live, width=12, height=12, bg=PANEL_2, highlightthickness=0)
        self.live_dot.pack(side="left", padx=(22, 10), pady=(4, 14))
        self.live_dot.create_oval(2, 2, 10, 10, fill="#657280", outline="")
        ttk.Label(live, textvariable=self.status_var, style="Body.TLabel", wraplength=650).pack(side="left", pady=(4, 14))

    def _build_status_page(self) -> None:
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["about"] = page
        card = self._card(page, "Node overview", "Local configuration and connection state.")
        for label, var in (("Device", self.name_var), ("Node ID", self.node_var), ("Server", self.server_var), ("Connection", self.connection_var), ("Selected profile", self.game_var)):
            line = ttk.Frame(card, style="Card.TFrame")
            line.pack(fill="x", padx=22, pady=7)
            ttk.Label(line, text=label, style="Muted.TLabel", width=18).pack(side="left")
            ttk.Label(line, textvariable=var, style="Body.TLabel").pack(side="left")
        safety = self._card(page, "Safety", "Input remains bounded to approved profiles and the foreground game window.")
        ttk.Label(safety, text="Ctrl + Alt + F12 immediately releases active input and disables AI game control.", style="Body.TLabel").pack(anchor="w", padx=22, pady=(4, 14))

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
            "server_url": self.server_var.get().strip().rstrip("/"),
            "verify_tls": self.verify_tls_var.get(),
            "node_id": self.node_var.get().strip() or socket.gethostname(),
            "name": self.name_var.get().strip() or "Windows Gaming Node",
        })
        return cfg

    def save(self) -> bool:
        cfg = self.current_config()
        if not cfg["server_url"]:
            messagebox.showerror(APP_TITLE, "Enter or discover your NekoSuneAI server URL first.")
            return False
        self.config_data = cfg
        save_config(cfg)
        self.status_var.set("Settings saved")
        return True

    def discover(self) -> None:
        self.status_var.set("Discovering NekoSuneAI • HTTPS domain first • LAN IPv4 fallback…")
        threading.Thread(target=lambda: self.after(0, lambda: self._discovery_done(discover_candidates())), daemon=True).start()

    def _discovery_done(self, found: list[str]) -> None:
        if found:
            selected = found[0]
            self.server_var.set(selected)
            self.verify_tls_var.set(selected.startswith("https://"))
            self.status_var.set(f"Found NekoSuneAI • {selected}")
            return
        local = ", ".join(_local_ipv4_addresses()) or "unknown"
        self.status_var.set(f"No NekoSuneAI service found • Windows IP: {local}")

    def _profile(self) -> GameProfile:
        game = self.game_var.get().strip()
        if not game:
            raise RuntimeError("Select a game profile first.")
        return GameProfile.from_mapping(GameSkillLibrary(SKILLS_ROOT).load(game).profile_mapping())

    def pair(self) -> None:
        if not self.save():
            return
        pairing_id = self.pairing_id_var.get().strip()
        pairing_code = self.pairing_code_var.get().strip()
        if not pairing_id or not pairing_code:
            messagebox.showerror(APP_TITLE, "Enter the pairing ID and pairing code shown by NekoSuneAI.")
            return
        self.status_var.set(f"Pairing through {self.config_data['server_url']}…")

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
        if not self.save():
            return
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
