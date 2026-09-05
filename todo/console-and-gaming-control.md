## P2 - Console & gaming control

Build one gaming-control layer so Neko can understand consoles, PCs, TVs and streaming/remote-play devices without every command being platform-specific. Use official/local interfaces where available and fall back gracefully when a console does not expose a supported action.

**Local-network reachability note (PI-PROXY split):** `nekosuneai/console_control.py`'s discovery/status/command logic (PS5/Xbox) only works from something on the *same local network* as the console — a Docker backend hosted on a VPS has no LAN path to a PS5/Xbox at home at all. `PiProxy/` (branch `build/pi-proxy-release`) now also carries this module and calls it directly as new paired-node capabilities (`console.status`, `console.capabilities`, `console.command`), since Pi Proxy runs on the home network. This backend should route console intents to a paired Pi Proxy node's capabilities (same pattern as routing game intents to the Windows Gaming Node in GAME-01) rather than assuming it can reach the console itself when deployed off-LAN; keep `console_control.py` here too for a same-box/LAN deployment where the backend *is* on the local network, but don't assume that's always true going forward.

### PlayStation 5 / PlayStation

- [ ] PS5 discovery/online-state monitoring on the local network where feasible.
- [ ] Turn on / wake from Rest Mode through supported paired-device or Remote Play-style mechanisms where available.
- [ ] Put PS5 into Rest Mode through a supported authenticated integration.
- [ ] Power/status commands such as `is the PS5 on?`, `wake the PS5`, and `put the PS5 to sleep`.
- [x] PS Remote Play / compatible local bridge integration for supported controls without bypassing Sony account/device protections.
- [ ] Launch game/app shortcuts only where an authenticated supported interface exposes them; otherwise report that direct launch is unavailable.
- [ ] Read currently active title/activity where exposed by supported integrations.
- [ ] Remote/media navigation controls where the platform/integration allows them.
- [ ] Console health/session dashboard showing online/rest/offline, active title and last-seen state.
### Xbox

- [ ] Xbox console discovery and online/offline status.
- [ ] Network wake / supported remote power-on.
- [ ] Sleep/shutdown/restart controls where Xbox remote APIs/local integrations permit them.
- [ ] Launch installed games/apps where supported by authenticated Xbox integrations.
- [ ] Basic dashboard/media remote commands such as home, back, play/pause and navigation where supported.
- [ ] Active game/app detection where exposed.
- [ ] Xbox Remote Play integration/launcher shortcuts.
- [ ] Controller battery/status reporting where an available local or authenticated interface exposes it.
### Nintendo Switch

- [ ] Detect Switch/dock presence on the LAN/TV setup where practical.
- [ ] HDMI-CEC-based TV/dock wake/input switching for a stock Switch setup where supported.
- [ ] Optional safe Bluetooth/HID controller bridge for simple approved navigation only when the user's hardware supports it.
- [x] Do not require console modification/custom firmware for the core integration.
- [x] Clearly mark unsupported stock-console actions such as arbitrary remote game launching rather than pretending they succeeded.
### TV / HDMI / gaming-mode automation

- [ ] HDMI-CEC integration to power compatible TVs/AVRs, switch input and query basic state.
- [ ] Smart-TV integration can switch directly to the console's HDMI input when supported.
- [ ] `Neko, start PS5 mode` routine: wake console, power TV, select HDMI, set lights/audio and suppress non-critical alerts.
- [ ] `Neko, start Xbox mode` / `Switch mode` / `PC gaming mode` equivalents.
- [ ] End-gaming routine that restores room lights/audio and optionally returns compatible devices to standby.
- [ ] Avoid automatically powering off a console if another household user/session is active where that state can be detected.
### Unified game commands & dashboard

- [ ] Generic gaming intents: `turn on`, `sleep`, `shutdown`, `launch`, `what am I playing?`, `switch input`, `start remote play`.
- [ ] Console aliases such as `PlayStation`, `PS5`, `Xbox`, `Switch`, `Deck`, `gaming PC`.
- [ ] Gaming dashboard showing each console/device, state, current title, TV input and remote-play availability.
- [ ] Per-platform capability discovery so the UI only shows actions that actually work for the configured hardware/integration.
- [ ] Confirmation before shutdown/restart or other actions that could interrupt an active game/session.
- [ ] Gaming activity history stored locally and optionally disabled.
- [ ] Optional play-time reminders/session timers controlled by the user, without silently enforcing limits.
- [ ] Neko Peripheral Node capabilities such as `console.status`, `console.wake`, `console.sleep`, `console.launch`, `gaming.current_title`, and `tv.set_input`.

