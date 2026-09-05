# NekoSuneAI Windows TODO

Owner checkout: `Windows/`
Product branch and PR target: `build/windows-gaming-node-release`
Scope: Native Windows app, pairing client, capture/input, game profiles, OBS and desktop integrations.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and [AGENTS.md](AGENTS.md) before choosing work.
Every task below belongs to this branch. Shared contract IDs identify a separate
peer deliverable on the branch named in the map, not an instruction to add the
other app here.

Work P0 first, then P1, then the product backlog below. Existing `[x]` and
`[ ]` states moved from Docker's old combined roadmap are preserved historical
status, not a fresh audit or proof that a peer app is implemented or deployed.
Do not bulk-complete inherited tasks without checking this branch.

## P0 - Windows Pairing and Packaging

- [ ] [PAIR-01] Verify approval and one-use code pairing with the deployed Docker server, including refusal, expiry, reconnect and token persistence.
- [ ] Verify the rebuilt standalone EXE exposes bundled profiles and pairing controls on a clean Windows machine; local automated checks are not clean-install verification.
- [ ] Keep Windows GUI/agent changes and EXE packaging on build/windows-gaming-node-release.

## P1 - Windows Integration Work

- [ ] [NODE-01] Coordinate transport/capability changes with Docker's server contract; enforce permissions and connection-loss input release locally.
- [ ] [CONTEXT-01] Implement the PC side of configured audio/intercom and conversation handoff without embedding the server backend.
- [ ] [STREAM-01] Verify local game readiness, OBS/capture telemetry and owner stop/take-over behavior against server supervision.
- [ ] [GAME-01] Implement Windows PC launcher/execution adapters; Linux/Steam Deck adapters are not part of this app branch.
- [ ] [HEALTH-01] Collect supported PC hardware telemetry and enforce configured local stop rules; Docker owns aggregated history and dashboard policy.
- [ ] [VRCX-01] Implement the Windows local-file/read-only import adapter and export contract; Docker owns centralized ingestion, timeline queries and retention.

## P2 - Windows vision / autonomous gaming & Twitch streaming

Keep the Raspberry Pi/Docker instance as NekoSuneAI's persistent brain while a Windows Gaming Agent on the gaming PC handles heavy vision, game execution, real-time input, OBS and Twitch. Games must run on Windows rather than being streamed/executed inside the Pi container.

### Windows Gaming Agent

- [x] Build a dedicated Windows NekoSuneAI Desktop/Game Agent that securely pairs with the Pi/server.
- [ ] Encrypted authenticated WebSocket/node transport between NekoSuneAI and the Windows gaming PC.
- [x] Windows agent heartbeat showing online/offline state, latency, GPU/CPU load and active game.
- [ ] Start with Windows automatically as an optional service/tray application.
- [x] Restrict Neko to configured game/application windows rather than unrestricted desktop control by default.
- [ ] Per-game permissions for vision, keyboard, mouse, controller, audio, mods/APIs and streaming.
- [x] Emergency local hotkey/button to immediately disable all AI game input.
### Game capture & vision

- [ ] Low-latency Windows game-window capture using supported desktop/game capture APIs.
- [x] Capture only the selected game/window/monitor instead of uploading the entire desktop when possible.
- [x] Adjustable capture FPS/resolution so visual analysis does not overload the PC or network.
- [ ] Fast local vision preprocessing/object detection on the Windows GPU where available.
- [x] Send compact observations/state to the Pi instead of sending every raw frame.
- [x] On-demand high-detail screenshots when Neko needs to inspect UI/text/scenes more closely.
- [x] OCR for menus, HUD text, subtitles, inventory, coordinates and game messages where useful.
- [x] Scene-change/death/menu/loading detection to avoid pointless actions during transitions.
- [x] Maintain a short-lived visual working memory of recent frames/events for game reasoning.
### Input & real-time control

- [x] Keyboard/mouse control through an explicit allowlisted input layer.
- [x] Virtual game-controller support for games that work better with controller input.
- [x] High-level action API instead of requiring the LLM to generate individual keypresses every frame.
- [x] Local fast-control loops on Windows for movement, steering and bounded camera turning while the Pi gives higher-level goals.
- [x] Configurable action timeouts so a stuck action automatically releases held keys/buttons.
- [x] Automatic release of all virtual inputs when the connection to Neko is lost.
- [ ] Manual user input can optionally override/pause Neko immediately.
- [x] Record action/result telemetry so Neko can learn which game skills are reliable.
### Game adapters & skills

- [x] Generic vision-only game adapter for offline/single-player games without APIs/mods.
- [x] Structured game-state adapter interface for games/mods/plugins that can safely expose better telemetry than vision alone.
- [ ] Hybrid mode combining game API/mod telemetry + screenshots + controlled input.
- [x] Named reusable game skills instead of relearning controls every session.
- [x] Skill examples: `generic.move`, `generic.look`, `generic.interact`, `generic.open_menu`, `generic.pause`.
- [x] Per-game keybind/control profile discovered/configured before autonomous play.
- [x] Skill failure reporting with reason such as blocked path, UI changed, target lost or unsupported action.
- [ ] Safe game-specific memory for maps, controls, known locations, recurring objectives and user-approved strategies.
### Minecraft autonomous play

- [ ] Minecraft adapter with screen vision plus optional mod/plugin telemetry.
- [ ] Read health, hunger, coordinates, inventory and nearby entities from an approved mod/API when available.
- [x] Minecraft skills such as walking, looking, jumping, interacting, mining, placing blocks, eating and opening inventory.
- [ ] Higher-level skills such as `find tree`, `collect wood`, `find shelter`, `craft item`, and `return home` built on local movement/action primitives.
- [ ] Navigation/pathfinding handled locally where practical rather than sending every movement decision to the Pi.
- [x] Detect death/respawn/menu states and stop unsafe repeated inputs.
- [x] Server-specific automation policy so Neko only uses autonomous play where server/game rules permit it.
### VRChat autonomous avatar play

- [ ] Run VRChat on Windows while Neko's brain remains on the Pi/server.
- [ ] VRChat game-window vision feed to Neko.
- [ ] Combine vision with existing/planned VRChat OSC, navigation and avatar-control integrations where permitted.
- [ ] Autonomous avatar movement using safe high-level skills such as follow, walk, look, wave, sit and navigate known areas.
- [ ] `vrchat.follow_player`, `vrchat.look_at_player`, `vrchat.wave`, `vrchat.sit`, and known-world navigation skills.
- [ ] Nearby conversation/audio pipeline so Neko can hear and respond through TTS where configured.
- [ ] Avatar expression/gesture reactions driven by conversation, stream events and game context.
- [ ] Detect VRChat menus/loading screens and stop movement/input during transitions.
- [ ] Keep world/user privacy controls and avoid automated actions that violate VRChat or world rules.
### Additional games

- [ ] Adapter framework for Roblox where automation is permitted by the experience/platform rules.
- [x] Adapter framework for supported offline/single-player games such as Fallout-style games.
- [ ] Emulator adapter for user-owned games with generic controller + vision support.
- [x] Game-specific adapter packages can be enabled/disabled independently.
- [x] Anti-cheat-aware game profiles: disable automated input for multiplayer/competitive games where bots/macros are prohibited.
- [x] Never attempt to bypass anti-cheat, bot detection or game/platform restrictions.
### OBS / stream control

- [x] OBS WebSocket integration from the Windows node.
- [x] Start/stop stream only with configured permission/confirmation policy.
- [x] Start/stop recording and replay-buffer controls.
- [x] Scene switching for gameplay, chatting, BRB, technical-problem and ending scenes.
- [ ] Monitor stream state, bitrate, dropped frames, encoder load and game-capture availability.
- [ ] Detect broken/missing game capture and optionally switch to BRB while attempting a safe recovery.
- [ ] Monitor configured audio meters so Neko can warn if game/TTS/microphone audio disappears or clips.
- [ ] Automatically restore the gameplay scene after a verified recovery.
- [ ] Stream title/category update integration where Twitch permissions allow it.
- [ ] Create stream markers/bookmarks for notable moments and optional clip requests where supported.
- [ ] Stream-session timeline with game changes, scene switches, technical issues and notable moments.
### Autonomous stream sessions

- [ ] Launch the configured game and wait until it is actually ready before beginning autonomous play.
### Architecture / performance

- [ ] Windows PC performs game rendering, screen capture, fast vision preprocessing, input loops, OBS and audio routing.
- [x] Do not send every video frame or keypress through the Pi; use local Windows control loops and compact observations.
- [ ] Adaptive vision rate: reduce analysis while loading/idle and increase it temporarily when precise visual understanding is needed.
- [ ] Hardware acceleration on Windows where supported without making a dedicated GPU mandatory for basic operation.

## P2 - JARVIS / physical-world integration

Real-world features inspired by JARVIS that are practical with current hardware and software.
The AI should make high-level decisions while dedicated controllers enforce safety for motors,
locks, robotics and other physical systems.

### Computers, servers & network

- [ ] Computer-control agent for approved workflows such as opening OBS/VRChat/apps and preparing a stream session.

## P2 - Neko Peripheral Nodes

Build a reusable hardware capability protocol instead of hardcoding every future device into the core AI.
A node registers its identity, permissions, state and a strict set of capabilities Neko is allowed to call.

- [ ] PC/Desktop Node.

## P2 - Console & gaming control

Build one gaming-control layer so Neko can understand consoles, PCs, TVs and streaming/remote-play devices without every command being platform-specific. Use official/local interfaces where available and fall back gracefully when a console does not expose a supported action.

Ownership: Windows PC adapters only. Steam Deck/Linux endpoints and server-side gaming intents require Docker GAME-01 work.

### Steam / Steam Deck / PC gaming

- [ ] Steam/Steam Deck node integration with online state and current-game status.
- [ ] Launch installed Steam games by App ID/name on an authenticated PC/Deck node.
- [ ] Steam Big Picture/Game Mode launch and navigation shortcuts where locally supported.
- [ ] Sunshine/Moonlight integration to start/stop a configured game-streaming session.
- [ ] PC launcher adapters for approved launchers such as Steam, Epic, GOG and Xbox app where automation is reliable.
- [ ] Detect whether a configured game is installed before attempting to launch it.

## P2 - VRChat Owner Read-Only Monitor & VRCX History

Keep the owner account physically separated from the autonomous bot account. The owner session is read-only: it may observe, import, cache, index and notify, but it must not send invites, accept requests, join worlds, change status, modify friendships, message users or perform any other account action.

Ownership: local read-only VRCX adapter only. Server owner-account monitoring and centralized timeline ingestion remain on main (VRCX-01).

### VRCX historical import / catch-up

- [ ] Import user-selected VRCX local history/database/export data without requiring VRCX to remain running.
- [ ] Parse supported historical friend presence, notifications, world/instance visits, joins/leaves, status changes and other user-owned VRCX records where available.
- [ ] Import VRCX friend/friendship history so the dashboard can show data from before Neko's live monitor was installed.
- [ ] Dry-run import mode showing record counts/types before committing data to Neko's history database.
- [ ] Never modify or write back into the original VRCX database during import.
- [ ] Store import metadata such as source file/database, import time and detected VRCX schema/version.
- [ ] Re-import support for newer VRCX exports without duplicating existing historical records.
- [ ] Report unsupported/unknown VRCX tables/fields instead of silently guessing their meaning.

## P2 - VRChat / heavier ML backlog

- [ ] A* dead-reckoning navigation and persisted world maps.
- [ ] YOLO/ONNX screen object detection (opt-in).
- [ ] RapidOCR nameplate reading.
