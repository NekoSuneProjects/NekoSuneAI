# Branch Ownership Map

These are separate products in separate branches of NekoSuneAI. `main` is the
Docker/Pi backend, not an integration branch for the native apps.

| Product | Local checkout | Product branch / PR target | Owned implementation |
| --- | --- | --- | --- |
| Docker/Pi backend | `Docker/` | `main` | Server APIs, web dashboard, persistence, orchestration, model/provider integrations (LLM, vision, STT/TTS, yt-dlp resolution), Docker image. Can run anywhere with more cores/GPU (a VPS), not only on a physical Pi. |
| Android companion | `Android/` | `build/android-apk` | `android/`, native UI/services/permissions, phone and wearable adapters, APK build |
| Windows app | `Windows/` | `build/windows-gaming-node-release` | Windows GUI/agent, capture/input, game profiles, OBS/desktop adapters, EXE build |
| Pi Proxy | `PiProxy/` | `build/pi-proxy-release` | Lightweight paired node for a physical Raspberry Pi: local Bluetooth speaker management, local audio capture/playback, wake-word listening, local-network console control (PS5/Xbox — see CONSOLE-LAN-01), relaying media (STT/TTS) and command execution to the Docker backend, its own local read-only status page (deliberately not the full backend dashboard, to stay low CPU/RAM — that's this product's "GUI mode"). No local LLM/vision/STT/TTS model inference — that stays on the Docker backend. Exception: yt-dlp/YouTube resolution runs locally on Pi Proxy, not the backend, on purpose — YouTube's bot/cookie checks trip on datacenter/VPS IPs but not a home Pi's residential IP, so a VPS-hosted Docker backend genuinely cannot do this reliably itself. The backend still decides *what* to play (search/song choice); Pi Proxy resolves the actual stream via yt-dlp and plays it back locally. One Docker/Pi backend can pair with several Pi Proxy installs at once (one per room/device). |

Each checkout has its own `TODO.md`, `AGENTS.md` and `CLAUDE.md`. Read the
TODO on the owning branch. Paths in that TODO are relative to that checkout.
Sibling directory names describe this workspace, not folders to create inside
the repository. In a standalone clone, use the named branch instead.

## Work Routing

1. Verify the repository root, current branch and uncommitted changes before editing.
2. Select the owning product and read its local TODO. Every checkbox inherits
   that file's owner and target branch unless it explicitly links a peer task.
3. Create any feature/fix branch from the owning product branch. Target the
   same product branch in its PR: Android, Windows and Pi Proxy PRs must not target `main`.
4. Split a feature spanning products into backend and native-client changes.
   Use the same contract ID below in each affected TODO, with a distinct
   deliverable and verification state for each branch.
5. Commit and validate each checkout separately when committing is requested.
   Do not merge an entire native-app branch into `main`, merge `main` wholesale
   into a native-app branch, or mirror client modules into Docker to keep copies
   synchronized. Port only explicitly required, scoped protocol changes.
6. Keep an item open until its owning implementation and required checks pass.
   A backend endpoint does not complete its Android/Windows/Pi Proxy UI task,
   and a successful local test does not prove a deployed container, APK, EXE
   or Pi install works.

## Shared Contracts

These IDs link separate deliverables; they do not authorize code on another branch.

| ID | Docker / `main` | Android / `build/android-apk` | Windows / `build/windows-gaming-node-release` | Pi Proxy / `build/pi-proxy-release` |
| --- | --- | --- | --- | --- |
| PAIR-01 | Approval/code APIs, dashboard approval, token lifecycle | Native discovery, request/status, token storage | Native approval/code UI, discovery, token storage | Native pairing-code entry, discovery, token storage (same `/api/nodes/register` flow as Windows) |
| NODE-01 | Capability validation, permissions, queues, heartbeat APIs | Phone/wearable capability adapter | PC/game capability adapter and local enforcement | Bluetooth/audio capability adapter and local enforcement |
| CONTEXT-01 | Conversation, intercom and notification routing | Phone audio/presence/notification delivery | PC audio and context handoff | Room/device audio presence and notification delivery via a Bluetooth speaker |
| STREAM-01 | Session planning, Twitch reasoning, dashboard supervision | Native status and owner supervision controls | Game readiness, capture/input, OBS and local stop | Not applicable (no gaming/capture role) |
| WEAR-01 | Vision/reasoning endpoints and retained context | Glasses SDK, capture/audio/HUD, consent and controls | No wearable implementation currently assigned | No wearable implementation currently assigned |
| GAME-01 | Gaming intents, permissions and high-level goals | Optional remote supervision via STREAM-01 | PC launcher and native game execution; keep Steam Deck/Linux work separate | Not applicable |
| HEALTH-01 | Aggregate telemetry, deterministic policy, incident dashboard | Phone sensor/battery telemetry and alerts | PC sensor collection and local deterministic stop | Pi/Bluetooth hardware telemetry (link status, CPU/RAM) and local deterministic stop |
| VRCX-01 | Validated history ingestion, provenance, merge/query/retention | No import implementation currently assigned | Local file selection, read-only VRCX parsing/export | Not applicable |
| MEDIA-RELAY-01 | `/api/nodes/media/vision`, `/api/nodes/media/stt`, `/api/nodes/media/tts` endpoints (model calls happen here); decides what song/video to play, hands Pi Proxy the query/URL, not a resolved stream | Not applicable | Calls these endpoints for its own game-vision/STT/TTS needs | Calls these same endpoints for local mic capture (STT) and Bluetooth speaker playback (TTS) — never runs an LLM/vision/STT/TTS model itself. Exception: runs yt-dlp locally to resolve a stream from the residential IP (see product table above), then plays it back locally |
| NODE-CONVERSE-01 | New endpoint: node submits a transcript, gets back an assistant reply (text/TTS/commands) — does not exist yet | Not applicable | Not applicable | Needed for wake-word support: capture-and-transcribe already works via MEDIA-RELAY-01, but getting an actual spoken reply back needs this new endpoint first |
| CONSOLE-LAN-01 | `console_control.py` lives here too for a same-box/LAN deployment; route console intents to a paired node when off-LAN | Not applicable | Not applicable | `console_control.py` (PS5/Xbox discovery/status/command) also runs here, called as `console.status`/`console.capabilities`/`console.command` node capabilities — needed because a VPS-hosted backend has no LAN path to a home console |

## Legacy Files

Some branches still contain historical files from before the product split.
Their presence does not change ownership. Native-client copies on `main` are
not the source of truth and must not receive new native-app features. Track
their import/package/test dependencies before a separate, scoped removal.
Documentation reorganization does not claim those legacy files were removed.

`PiProxy/` in particular started as a full clone of `main` (so it could reuse
`bluetooth_watchdog.py` and the audio helpers as-is) and still carries the
rest of the Docker backend's modules (LLM/vision/RAG/dashboard/etc.) unused —
those are legacy on this branch too, tracked for a later scoped removal in
Pi Proxy's own TODO, not evidence that Pi Proxy implements backend features.

New product backlogs belong in that product's branch, not in Docker's TODO.
Changes to this map must be reflected in the other affected product checkouts.
