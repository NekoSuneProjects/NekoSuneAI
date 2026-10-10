# GAME-LAN-01: NekoSuneAI LAN gameplay bridge

Status: proposal; no runtime implementation is claimed.
Owners: Docker backend (`main`), PiProxy (`build/pi-proxy-release`), Android gameplay agent (separate `NekoSuneProjects/nekosuneai-android-ai-gameplay` repository), Windows gaming agent (`build/windows-gaming-node-release`).

## Goal

Let the backend operate approved games on devices reachable from the owner's LAN without exposing ADB, local HTTP services, arbitrary commands, or console discovery to the public Internet. Backend owns reasoning, inference, high-level actions, session supervision and video transcoding. PiProxy provides a paired, outbound-only local-network rendezvous/relay. The actual game-device agent performs capture and scoped input locally.

## Existing components (do not duplicate)

- `main`: `PeripheralNodeRegistry` with pairing, capability policy, polling, heartbeat, audit; `/api/nodes/media/{vision,stt,tts}`; `games/windows_remote.py`; `console_control.py`; existing game-session controls.
- PiProxy: `pi_proxy_agent.py` polling and heartbeats; `console.{status,capabilities,command}` for PS5/Xbox; no local LLM/vision/STT/TTS inference.
- Android gameplay repository: `agent/device.py` ADB screenshot/tap/swipe/key/launch operations; `agent/runtime.py` safe action validation, OCR/YOLO and local game loop; distinct game memory and configuration.
- Windows branch: owns Windows game capture/inputs and skill profiles, not Docker or PiProxy.

## Route selection

Preferred: each Android/Windows game agent pairs directly with Main using outbound HTTPS, even if it is on the LAN. PiProxy discovers local targets (explicit owner-approved IP/port/device ID) and advertises their presence; it can relay frames/commands when direct outbound connectivity is unavailable. It must never become a general-purpose TCP tunnel or arbitrary network proxy.

When an ADB endpoint is available only from PiProxy's subnet, run a separate restricted Android gameplay worker there, explicitly provisioned by the owner, and connect it to the local ADB endpoint. The PiProxy core itself does not execute ADB shell strings supplied by the AI. Before assuming Pi can run the gameplay worker, validate ARM64 dependencies and resource headroom.

## Contract

All sessions are identified by UUID `session_id`; all actions use unique `command_id` and `step_id` for deduplication. Every message includes `node_id`, protocol version, expiry, and target identity. Use the existing `X-Neko-Device-Token` for node-authenticated HTTP; require TLS or a private overlay. Register the actual execution agent as its own paired node; never reuse PiProxy's token.

Suggested typed capabilities (all writes require deliberate owner authorization):
- `game.devices`: list locally approved game devices and reachability, read-only.
- `game.session.start` / `game.session.stop`: start/stop one approved game session.
- `game.observe`: return bounded observation descriptors and media handles, read-only.
- `game.action`: perform one **validated** typed game action, with coordinate bounds, target window/package ID, time budget and local approval; never pass shell commands.
- `game.input.stop`: immediate stop/release, locally enforced even when backend offline.
- `game.stream.start` / `game.stream.stop`: authorize/terminate a game-media stream with consent.

Device descriptors: `device_id`, `agent_node_id`, `kind` (android/windows/console), `display_name`, `available_games`, `online`, `control_supported`, `stream_supported`, `last_seen_epoch`. Never return LAN scanning details or credentials to the LLM.

`game.action` payload: `{session_id,command_id,step_id,device_id,game_id,action:{type, ...},deadline_epoch}`; supported Android types `tap`, `long_press`, `swipe`, `back`, `key`, `wait`, `stop`; optionally `text` with separate user confirmation. Reject game/package changes, real-money purchases, premium-currency spending, raw shell, and unrestricted URLs by default.

Action result: `{session_id,command_id,status,reason,observation_id,executed_epoch}`. Do not ACK commands until local execution result is durably recorded; apply idempotency to avoid replayed taps. A stop message takes precedence over queued actions.

## Media flow

Prefer WebRTC for near-realtime preview; a separate authenticated WSS/binary frame or short-lived signed upload channel is acceptable for initial screenshots. Do **not** send full-rate base64 frames through node heartbeats or the existing 400-KB image-analysis JSON endpoint. Main decodes/transcodes with FFmpeg under explicit CPU/memory/fps/resolution/bitrate limits. Default an AI observation feed to sampled downscaled frames and OCR/YOLO descriptors; separate owner preview stream from AI vision sampling. Preserve image ownership and consent; expire raw frames promptly. PiProxy should forward bytes without decoding/re-encoding when possible.

## End-to-end flow

1. Owner pairs PiProxy and the device-specific game agent with Main and approves each agent's capabilities.
2. PiProxy discovers allowlisted LAN endpoints or announces a reachable approved agent; Main correlates that information with its paired agent ID.
3. Owner chooses game/device, sets time/action limits and permissions and starts session.
4. Game agent captures screenshot/observations; Main computes a bounded next action.
5. Main queues typed action to the actual execution agent (direct) or relays via PiProxy's authenticated targeted route; executor revalidates package, focus, bounds and spending restrictions.
6. Executor sends result and next observation; repeat within rate/time limits.
7. Any local emergency-stop, disconnected session, lost focus, revoke, or timeout stops input, invalidates outstanding actions and tears down media transport.

## Delivery plan (separate PR per owner)

### Main / Docker
- [ ] Versioned game session API, binding of session to selected paired execution node, permission policy and audit.
- [ ] Typed action + observation schema, persistent idempotent result queue, quotas and emergency stop.
- [ ] Media ingestion/transcode worker separated from heartbeat and node-media endpoints.
- [ ] Dashboard game selection, owner preview, stream permissions, manual stop and error diagnostics.
- [ ] Simulation tests: authorization, replay, stop, timeout, revoked node, oversized media, multi-device routing.

### PiProxy branch
- [ ] Opt-in LAN game-agent discovery constrained by explicit device allowlist; no general port scanner.
- [ ] Authenticated targeted relay or metadata-based direct-route discovery; no arbitrary TCP forwarding.
- [ ] Connection health and relay metrics; bounded buffers; offline fail-closed; local stop forwarding.
- [ ] ARM64 networking and CPU-load validation on real Pi.

### Android gameplay repository
- [ ] Agent pairing/token storage, device descriptors and heartbeat.
- [ ] Safe typed command runner reusing existing ADB validation, not accepting arbitrary ADB arguments.
- [ ] Observation capture and frame streaming with configurable bitrate/fps; keep existing local mode.
- [ ] Pause/stop controls, game package identity checks, action idempotency and disconnect stop.
- [ ] Test with BlueStacks, ReDroid and Android ADB target on the owner's LAN.

### Windows branch
- [ ] Adopt shared session/device schema without moving existing Windows game skills.
- [ ] Map scoped `game.skill`, capture, OBS and local stop into new session coordinator.

## Non-goals

- No unbounded shell/SSH/ADB command pass-through.
- No opening PiProxy's LAN services to public Internet.
- No automatic spending or gameplay on devices the owner has not approved.
- No promise of Xbox/PS5 video capture/control merely because console status/commands are available; supported actions depend on tested platform APIs and approved Remote Play integrations.
- No merging the entire PiProxy/Windows native branch into `main`.

## Acceptance

A paired Android worker on the LAN can expose an approved game, Main can obtain a bounded observation and issue one typed approved action, the worker executes it and acknowledges exactly once, Main can relay/transcode a consented frame/preview, and all operation stops promptly on local emergency stop, session expiry, or loss of authorisation. Validate on physical hardware before marking complete.
