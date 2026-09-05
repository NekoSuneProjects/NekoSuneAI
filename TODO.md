# NekoSuneAI Android TODO

Owner checkout: `Android/`
Product branch and PR target: `build/android-apk`
Scope: Native Android companion, Android permissions/services, phone sensors and wearable client.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and [AGENTS.md](AGENTS.md) before choosing work.
Every task below belongs to this branch. Shared contract IDs identify a separate
peer deliverable on the branch named in the map, not an instruction to add the
other app here.

Work P0 first, then P1, then the product backlog below. Existing `[x]` and
`[ ]` states moved from Docker's old combined roadmap are preserved historical
status, not a fresh audit or proof that a peer app is implemented or deployed.
Do not bulk-complete inherited tasks without checking this branch.

## P0 - Android Pairing and Compatibility

- [ ] [PAIR-01] Verify discovery, owner approval, token storage and reconnect against the updated Docker backend on an actual Android device.
- [ ] Keep APK packaging, Android manifests, permissions and native services on build/android-apk.

## P1 - Android Integration Work

- [ ] [NODE-01] Publish supported phone capabilities and telemetry through the shared node contract with native permission checks.
- [ ] [CONTEXT-01] Implement the phone side of intercom, conversation handoff and filtered notification delivery; Docker owns routing and stored context.
- [ ] [STREAM-01] Add/verify native game, objective and stream status plus owner pause/take-over/stop controls against the backend contract.
- [ ] [HEALTH-01] Report supported phone battery/thermal readings and display configured urgent alerts; report unavailable sensor values as unknown.
- [ ] [WEAR-01] Implement the glasses/phone side of the wearable contract; use Docker endpoints for server reasoning and retained context.

## P2 - Smart assistant / Alexa & Google Home-style ideas

Prefer local/offline control where practical and make cloud/account integrations optional.

### Phone / Android companion

- [x] Find my phone with authenticated loud ring.
- [x] Phone battery monitoring.
- [ ] Selected incoming notification/SMS relay with privacy filters.
- [x] Phone-as-presence sensor.
- [ ] Safe remote phone controls such as ring, flashlight and media control.

## P2 - Smart glasses / wearable NekoSuneAI node

The glasses should act as a lightweight sensor/display/audio endpoint while the heavier NekoSuneAI
brain runs on the phone, Pi, PC or server. Hardware support depends on whether a manufacturer exposes
camera, microphone, speaker, IMU, display, buttons or an SDK/API.

Ownership: native SDK, consent, capture, transport and presentation. Vision/reasoning and retained context require Docker's WEAR-01 and CONTEXT-01 deliverables; implement only the client portion here.

### Wearable connection architecture

- [ ] Smart-glasses node protocol through the Android/phone companion or direct local network connection.
- [ ] Encrypted authenticated glasses ↔ phone ↔ NekoSuneAI transport.
- [ ] Bluetooth-audio fallback for glasses that expose only microphone/speaker functionality.
- [ ] Capability discovery so Neko knows whether connected glasses provide camera, display, IMU, GPS, buttons, gestures or audio.
- [ ] Graceful feature fallback when glasses do not expose a camera/display SDK.
- [ ] Battery monitoring and low-battery warnings for the glasses.
- [ ] Continue the same conversation/context between glasses, phone, Pi and PC.
### Vision through glasses

- [ ] `Neko, what am I looking at?` camera query when the user intentionally invokes vision.
- [ ] Read visible text, labels, QR codes, signs, error messages and device model numbers.
- [ ] Look at a configured 3D printer and ask whether the current print appears healthy.
- [ ] Look at the user's own enrolled device and combine camera context with live telemetry/logs.
- [ ] Contextual `this/that` device control using vision plus room/device mapping.
- [ ] Object-memory sightings from wearable camera, with configurable retention and explicit privacy controls.
- [ ] `Remember where this is` / `remember this location` for the user's own objects/equipment.
- [ ] Avoid automatic face identification of strangers; household profile recognition remains strictly opt-in.
### HUD / augmented information

- [ ] Minimal JARVIS-style HUD showing time, weather, Neko state, notifications and urgent home alerts.
- [ ] Optional small Neko VRM/avatar/listening indicator where the glasses display API allows rendering.
- [ ] Live captions of Neko's replies for noisy environments.
- [ ] Live translation/subtitles where supported.
- [ ] Navigation prompts/arrows using phone GPS or compatible glasses location APIs.
- [ ] Overlay the state/name of the user's mapped smart devices where spatial/AR capabilities allow it.
- [ ] Show printer progress, server health, phone battery, house warnings and selected notifications in a compact HUD.
- [ ] Privacy-first notification filtering so sensitive notification content is hidden unless explicitly permitted.
### Wearable controls

- [ ] Glasses button/tap/gesture mapped to wake, mute, stop speaking, push-to-talk or acknowledge notification.
- [ ] IMU/head-gesture shortcuts where the hardware SDK safely supports them.
- [ ] Voice command to capture a snapshot only when explicitly requested or when a user-created routine allows it.
- [ ] Quiet/private reply mode using the glasses speaker instead of broadcasting through room speakers.
- [ ] Wearable emergency shortcut that can trigger an approved local action/alert without navigating menus.

## P2 - Neko Peripheral Nodes

Build a reusable hardware capability protocol instead of hardcoding every future device into the core AI.
A node registers its identity, permissions, state and a strict set of capabilities Neko is allowed to call.

- [ ] Android Phone Node.
- [ ] Smart Glasses Node.

## P2 - Neko Operations Center

Create one operations view that combines physical hardware, VPSs, websites, applications, Discord/community systems, GitHub, game servers and Neko nodes.

### Away/asleep summary

- [ ] Optional Android notification when a new CRITICAL/EMERGENCY operational incident occurs.
