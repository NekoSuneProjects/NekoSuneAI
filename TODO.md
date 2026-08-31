# NekoSuneAI — Roadmap / TODO

Tracking the push toward full **Neuro-sama-style** capability, VRChat-first.

## 🏠 Smart assistant / Alexa & Google Home-style ideas

Prefer local/offline control where practical and make cloud/account integrations optional.

### Audio, speakers & multi-room
- [x] Alexa/Echo Bluetooth volume control — volume/up/down/mute/unmute through PipeWire/PulseAudio.
- [x] Per-device speaker volume and remembered levels.
- [x] Multi-room audio groups for one room, selected rooms, or whole home.
- [ ] Whole-home broadcast/intercom between Pi, PC, speakers and Android nodes.
- [x] Do-not-disturb / quiet hours.
- [ ] Adaptive TTS volume based on ambient noise.
- [ ] Follow-me audio — move music/TTS to the room the user moves into.
- [ ] Follow-me conversation — continue the same NekoSuneAI conversation on another room node/phone.
- [x] Whisper/night mode — whisper to Neko and have her answer quietly.
- [x] Intelligent interruption priorities — emergency > important > normal > optional.
- [x] Don't-interrupt mode — delay non-critical announcements while conversation/media is detected.

### Matter / smart-home devices
- [ ] Matter controller and local device discovery/control.
- [ ] Matter device dashboard with rooms, state, rename and favorites.
- [ ] Thread Border Router support/documentation for Matter-over-Thread.
- [ ] Expanded Home Assistant entity control.
- [ ] Generic MQTT device discovery/control.
- [ ] Philips Hue local bridge integration.
- [ ] WLED integration.
- [ ] Shelly local integration.
- [ ] Universal device aliases — `lamp`, `my light`, and `bedside light` can resolve to the same device.
- [ ] Room-aware commands — `turn the light off` automatically targets the room the user is speaking from.
- [ ] Self-healing integrations — detect offline devices/services and safely attempt reconnection.
- [ ] Device battery prediction and low-battery warnings.
- [ ] Energy monitoring, estimated electricity cost and unusual-consumption detection.
- [ ] Electricity-price-aware routines for compatible appliances/tariffs.

### Routines & automation
- [x] Named routines/scenes such as good morning, good night and movie mode.
- [x] Routine builder dashboard: trigger + conditions + ordered actions.
- [x] Sensor-triggered routines.
- [ ] Sunrise/sunset routines.
- [ ] Presence/occupancy awareness.
- [ ] Natural-language routine creation — describe a routine instead of programming every field.
- [ ] Temporary routines — `for the next three days, wake me at 8`.
- [ ] Conditional/location reminders — `remind me about washing when I next go downstairs`.
- [ ] Teach-by-demonstration — record a safe sequence of actions such as a streaming setup and save it as an editable routine.
- [x] Automation conflict detection when two routines fight over the same device.
- [x] Explain automations — answer `why did the hallway light turn on?` with the triggering rule/sensor.
- [x] Natural routine debugging — answer why a routine did not execute.
- [x] Undo previous safe device action where the prior state is known.
- [x] Preview/confirmation for large actions such as turning off many devices at once.

### Conversational assistant improvements
- [ ] Real conversational follow-ups without repeating device names/wake word every sentence.
- [ ] User-defined natural commands such as teaching `make it cozy`.
- [ ] Explain failures instead of returning generic device errors.
- [ ] Proactive suggestions, e.g. lights left on in an unoccupied room.
- [ ] Correction handling — `no, I meant the kitchen light` updates the previous command.
- [x] Immediate `Neko stop` interruption for TTS/music/actions.
- [ ] Multiple-person profiles with separate preferences, permissions, calendars and memories.
- [ ] Guest mode with limited safe smart-home access.
- [ ] Optional local voice identification for household profiles.
- [ ] Cross-device conversation/context memory between Pi, PC and Android nodes.

### Timers, alarms, reminders & lists
- [x] Multiple named timers with list/pause/resume/cancel and ambiguity-safe ID fallback.
- [ ] One-off/repeating alarms, custom sound/TTS and snooze.
  - [x] One-off/daily/weekday alarms with named TTS, snooze and dismiss controls.
  - [ ] Per-alarm custom sound files.
- [x] Local reminder engine with spoken/dashboard/Android notifications.
- [x] Shopping lists.
- [x] To-do lists with priorities/due dates.
- [ ] Calendar integration.
- [x] Ask about previous announcements — `what did you just tell me?`.
- [x] Notification summarisation, deduplication and cooldowns.

### 📹 CCTV / door / local security vision
- [ ] **Generic CCTV camera integration** — add cameras by RTSP/ONVIF URL so NekoSuneAI is not tied to one camera brand.
- [ ] **ONVIF discovery** — automatically find compatible IP cameras/NVRs on the LAN.
- [ ] **Door/front-garden camera zones** — define door, driveway, garden, gate and ignored areas per camera.
- [ ] **Person-at-door detection** — trigger when a person enters the configured doorway/porch zone instead of every motion event.
- [ ] **Person/animal/vehicle/package classification** — distinguish people, pets, cars/vans/bikes and delivered packages locally where possible.
- [ ] **Known-person recognition (strictly opt-in)** — household members can explicitly enroll themselves; Neko can say a known household member is at the door. Unknown visitors remain `unknown person` rather than being identified from outside data.
- [ ] **Unknown-person alerts** — `There's an unknown person near the front door` with configurable sensitivity and cooldown.
- [ ] **Doorbell event integration** — accept ONVIF/MQTT/Home Assistant/webhook events from compatible smart doorbells.
- [ ] **Door arrival announcement** — broadcast `someone is at the front door` to selected NekoSuneAI speakers/Android nodes.
- [ ] **Snapshot notifications** — optionally send an event snapshot to the dashboard/paired phone instead of continuously streaming footage.
- [ ] **Live camera query** — `Neko, what's at the front door?`, `is the dog in the garden?`, `is there a car on the drive?`.
- [ ] **Camera event timeline** — local event history with time, camera, zone and detection type.
- [ ] **Recent-event questions** — `when was someone last at the door?` or `was there a delivery today?`.
- [ ] **Loitering detection** — optional warning when an unknown person remains inside a configured external zone beyond a threshold.
- [ ] **Package arrival/removed state** — detect a package appearing in a defined porch zone and optionally notify when it disappears.
- [ ] **Vehicle arrival/departure events** — driveway zone notifications without attempting to identify arbitrary people.
- [ ] **Pet-at-door detection** — notify when the household pet is waiting at a configured door where the model can distinguish it reliably.
- [ ] **Privacy masks** — permanently exclude neighbours' property, windows, pavement sections or other areas from AI analysis.
- [ ] **Camera privacy schedules** — disable selected indoor-camera analysis at chosen times or while household members are home.
- [ ] **Local-first CCTV processing** — run detection on the Pi/another local node when hardware permits; cloud vision must be explicit opt-in.
- [ ] **No automatic stranger identification** — do not search the internet/social networks to identify unknown visitors.
- [ ] **Retention controls** — configurable event/snapshot retention and one-command deletion of locally stored camera history.
- [ ] **Camera health monitoring** — warn when an important camera/NVR goes offline, freezes or stops producing frames.
- [ ] **NVR integration** — optional support for systems such as Frigate/Home Assistant and generic RTSP/ONVIF NVRs.
- [ ] **Event-driven processing** — use camera motion/object events to avoid continuously running expensive vision inference on the Pi.

### Media & entertainment
- [ ] Unified play/pause/resume/stop/next/previous/seek/volume controls.
- [ ] Spotify Connect integration.
- [ ] Chromecast / Google Cast integration.
- [ ] DLNA/UPnP media renderer support.
- [ ] Android TV/ADB, LG webOS and Samsung TV integrations where supported.

### Phone / Android companion
- [x] Find my phone with authenticated loud ring.
- [x] Phone battery monitoring.
- [ ] Selected incoming notification/SMS relay with privacy filters.
- [x] Phone-as-presence sensor.
- [ ] Safe remote phone controls such as ring, flashlight and media control.

### Information / briefings
- [ ] Weather station + forecast/rain/storm/lightning alerts.
- [ ] Commute/travel status.
- [ ] Package/delivery tracking.
- [ ] RSS/news briefing.
- [ ] House-status briefing covering sensors, temperature, batteries, offline devices and alerts.
- [ ] Personal morning/evening briefing combining calendar, weather, house status, phone battery, reminders, deliveries and important notifications.
- [ ] Home timeline — query locally retained sensor events such as when a door last opened.

### Safety, privacy & reliability
- [ ] Local smoke/CO/water-leak/security emergency broadcasts.
- [ ] Permission levels per user/device.
- [ ] Confirmation for sensitive actions such as unlocking/opening/disarming.
- [ ] Local-first credentials vault.
- [x] Integration health dashboard with healthy/degraded/disabled/unavailable states.
- [ ] Graceful offline mode for local voice/home functions.
- [ ] Custom wake words and multiple wake-word profiles.
- [ ] Wake-word context based on the room/node that heard the request.
- [ ] No forced ecosystem — Matter, MQTT, Home Assistant, Android, PCs and custom hardware can coexist.

## 🤖 JARVIS / physical-world integration

Real-world features inspired by JARVIS that are practical with current hardware and software.
The AI should make high-level decisions while dedicated controllers enforce safety for motors,
locks, robotics and other physical systems.

### Room awareness & physical context
- [ ] Always-aware room assistant using distributed microphones/sensors and room nodes.
- [ ] Speaker/microphone-array direction finding so Neko can estimate which room/direction a request came from.
- [ ] 3D room mapping with optional depth camera/LiDAR support.
- [ ] Home digital twin mapping rooms, devices, sensors, doors and physical relationships.
- [ ] Object memory — remember where opted-in cameras last saw items such as keys, phone or controller.
- [ ] Natural object queries — `where did I leave my keys?` or `which camera last saw my phone?`.
- [ ] Gesture commands — configured hand gestures for stop, lights, music and other safe actions.
- [ ] Contextual pointing commands — combine room/location/vision so `turn that off` can target a visible device.
- [ ] Environmental awareness from temperature, humidity, CO2, air-quality, light and noise sensors.
- [ ] Automatic environmental adjustment for compatible lights, heating, fans, blinds and music.

### Computers, servers & network
- [ ] Computer-control agent for approved workflows such as opening OBS/VRChat/apps and preparing a stream session.
- [ ] PC/server diagnostics — CPU, RAM, GPU, temperatures, storage, processes, Docker and network status.
- [ ] Predictive hardware warnings using temperature trends, SMART data, battery/UPS state and repeated errors.
- [ ] LAN awareness for the user's own devices — online/offline state, latency and local service reachability.
- [ ] Natural troubleshooting — `why is my PC slow?`, `why is the TV offline?`, `why did this container stop?`.
- [ ] Safe self-maintenance policies — restart failed Neko services/containers, reconnect Bluetooth or switch to configured fallbacks.
- [ ] Service dependency map so Neko can explain what depends on a failed service.
- [ ] Local AI fallback mode when Internet/cloud services are unavailable.

### Physical interfaces & displays
- [ ] JARVIS-style command-center dashboard showing Neko avatar, home, CCTV, weather, calendar, servers, phone, music and alerts.
- [ ] Wall-mounted Pi/tablet Neko terminals for rooms around the house.
- [ ] Projector dashboard mode for walls/desks as a practical hologram-like interface.
- [ ] Optional AR interface that can overlay device status/context onto a room using a compatible phone/headset.
- [ ] Spatial audio replies so Neko's voice can come from the most relevant room/speaker.
- [ ] LED/status-light integration showing listening, thinking, speaking, warning and offline states.
- [ ] Physical buttons/knobs via ESP32 for mute, stop, push-to-talk, room scenes and emergency disable.

### Sensors, electronics & maker integrations
- [ ] ESP32 sensor-node framework for cheap distributed motion, temperature, buttons, LEDs and custom sensors.
- [ ] Voice-controlled electronics bench — read approved serial/MQTT measurements and log results hands-free.
- [ ] GPIO bridge for safe Raspberry Pi input/output projects through explicit allowlisted actions.
- [ ] USB/serial device integration framework for custom meters/controllers.
- [ ] BLE sensor discovery for supported local environmental/beacon devices.
- [ ] Automatic sensor calibration reminders and stale-data detection.

### Robotics
- [ ] Generic robot integration API so Neko can issue high-level tasks to a separate safety controller.
- [ ] Mobile robot status/navigation requests for supported robots with collision avoidance handled outside the LLM.
- [ ] Robot charging-state awareness and `return to charger` high-level command.
- [ ] Robot-arm integration for predefined, safety-limited lightweight tasks.
- [ ] Hard motion boundaries, emergency-stop support and allowlisted robot actions.
- [ ] Drone telemetry integration for the user's own compatible drone — battery/GPS/status only by default.
- [ ] Optional safe high-level drone mission requests only when a dedicated flight controller enforces geofencing and safety.

### Proactive JARVIS-style intelligence
- [ ] `Neko, status report` combining house, PC/server, network, weather, phone, calendar, cameras and warnings.
- [ ] Daily JARVIS briefing with weather, calendar, house state, devices, overnight events and server health.
- [ ] Anomaly detection that learns normal device/sensor patterns and highlights unusual conditions.
- [ ] Event reconstruction — `what happened while I was asleep/out?` summarises opted-in local events.
- [ ] Predictive maintenance suggestions before devices/storage/batteries fail where evidence is strong enough.
- [ ] Context-aware proactive reminders based on devices, location, time and routines.
- [ ] Explainable proactive actions — Neko records why she suggested or executed an automation.

### Power, resilience & emergencies
- [ ] UPS integration — detect mains failure, battery runtime and charging state.
- [ ] Power-cut mode — reduce nonessential workloads and prepare configured systems for safe shutdown.
- [ ] Automatic graceful shutdown before UPS battery depletion.
- [ ] Recovery mode after power returns — staged service startup and health checks.
- [ ] Emergency command-center view showing which smoke/CO/leak/security sensor triggered and where.
- [ ] Priority emergency broadcast to selected speakers/displays/phones.
- [ ] Hardware emergency-disable switch that can stop Neko-controlled physical automations independently of the AI.

## 🖨️ 3D printer / workshop integration

### Printer connectivity & control
- [ ] OctoPrint integration for printer status, jobs, temperature, camera and safe control actions.
- [ ] Klipper/Moonraker integration for Klipper-based printers.
- [ ] PrusaLink/Prusa Connect support where APIs permit it.
- [ ] Bambu-style LAN/API integration where supported, keeping cloud login optional when possible.
- [ ] Generic printer adapter interface so additional printer brands can be added without changing core assistant logic.
- [ ] Multi-printer dashboard showing idle/printing/paused/error/offline state, progress and estimated finish time.
- [ ] Natural commands such as `how is my print?`, `pause the printer`, `what temperature is the nozzle?`, and `which printer is free?`.
- [ ] Require explicit confirmation before starting a print, homing axes, heating or other actions that can move/hot-end hardware.
- [ ] Never allow the LLM to bypass printer firmware limits, thermal protection, endstops or emergency-stop behaviour.

### Print monitoring & vision
- [ ] Printer-camera monitoring via the printer/NVR/RTSP camera.
- [ ] Optional local failed-print/spaghetti detection and warning.
- [ ] Configurable auto-pause on high-confidence print failure, with user opt-in and clear reason logging.
- [ ] Layer-shift, detached-print and obvious filament-tangle alerts where computer vision can identify them reliably.
- [ ] `Neko, does my print look okay?` live snapshot analysis.
- [ ] Print-event snapshots on start, warning, pause, failure and completion.
- [ ] Timelapse trigger/integration where the printer stack already supports it.

### Filament, maintenance & planning
- [ ] Filament/spool inventory with material, colour, remaining weight and printer assignment.
- [ ] Estimate filament remaining/used from slicer or printer job metadata.
- [ ] Warn before a job if the selected spool is unlikely to contain enough filament.
- [ ] Track nozzle/runtime hours and configurable maintenance intervals.
- [ ] Maintenance reminders for lubrication, nozzle inspection, bed cleaning and other user-defined tasks.
- [ ] Print history containing job duration, material use, failures and completion status.
- [ ] Power/energy monitoring for compatible smart plugs/printers.
- [ ] Enclosure temperature/humidity monitoring when sensors exist.
- [ ] Compare printer build volume/material compatibility before suggesting which printer to use.
- [ ] Optional slicer metadata import from G-code/3MF without automatically executing untrusted files.

## 🕶️ Smart glasses / wearable NekoSuneAI node

The glasses should act as a lightweight sensor/display/audio endpoint while the heavier NekoSuneAI
brain runs on the phone, Pi, PC or server. Hardware support depends on whether a manufacturer exposes
camera, microphone, speaker, IMU, display, buttons or an SDK/API.

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

## 🔌 Neko Peripheral Nodes

Build a reusable hardware capability protocol instead of hardcoding every future device into the core AI.
A node registers its identity, permissions, state and a strict set of capabilities Neko is allowed to call.

- [x] Generic authenticated node registration/pairing system.
- [x] Capability manifest such as `printer.status`, `printer.pause`, `camera.snapshot`, `display.notify`, `sensor.temperature`, `device.battery`, `audio.speak`.
- [x] Per-capability permission/confirmation policy.
- [x] Read-only vs state-changing capability classification.
- [x] Node heartbeat, latency, battery and online/offline status.
- [ ] Local WebSocket/MQTT/HTTP transport adapters with encryption/authentication.
- [ ] Remote transport option through the existing bridge without exposing unauthenticated LAN controls.
- [x] Dashboard for connected nodes, capabilities, permissions and last activity.
- [ ] Android Phone Node.
- [ ] Smart Glasses Node.
- [ ] 3D Printer Node.
- [ ] CCTV/NVR Node.
- [ ] ESP32 Sensor Node.
- [ ] PC/Desktop Node.
- [ ] Raspberry Pi/Server Node.
- [ ] Weather Station Node.
- [ ] Robot/Robot Arm Node with safety-controller boundary.
- [ ] Future vehicle-telemetry node restricted to supported read-only/safe capabilities by default.

## 🎮 Console & gaming control

Build one gaming-control layer so Neko can understand consoles, PCs, TVs and streaming/remote-play devices without every command being platform-specific. Use official/local interfaces where available and fall back gracefully when a console does not expose a supported action.

### PlayStation 5 / PlayStation
- [ ] PS5 discovery/online-state monitoring on the local network where feasible.
- [ ] Turn on / wake from Rest Mode through supported paired-device or Remote Play-style mechanisms where available.
- [ ] Put PS5 into Rest Mode through a supported authenticated integration.
- [ ] Power/status commands such as `is the PS5 on?`, `wake the PS5`, and `put the PS5 to sleep`.
- [ ] PS Remote Play / compatible local bridge integration for supported controls without bypassing Sony account/device protections.
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
- [ ] Do not require console modification/custom firmware for the core integration.
- [ ] Clearly mark unsupported stock-console actions such as arbitrary remote game launching rather than pretending they succeeded.

### Steam / Steam Deck / PC gaming
- [ ] Steam/Steam Deck node integration with online state and current-game status.
- [ ] Launch installed Steam games by App ID/name on an authenticated PC/Deck node.
- [ ] Steam Big Picture/Game Mode launch and navigation shortcuts where locally supported.
- [ ] Sunshine/Moonlight integration to start/stop a configured game-streaming session.
- [ ] PC launcher adapters for approved launchers such as Steam, Epic, GOG and Xbox app where automation is reliable.
- [ ] Detect whether a configured game is installed before attempting to launch it.

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

## 👁️ Windows vision / autonomous gaming & Twitch streaming

Keep the Raspberry Pi/Docker instance as NekoSuneAI's persistent brain while a Windows Gaming Agent on the gaming PC handles heavy vision, game execution, real-time input, OBS and Twitch. Games must run on Windows rather than being streamed/executed inside the Pi container.

### Windows Gaming Agent
- [ ] Build a dedicated Windows NekoSuneAI Desktop/Game Agent that securely pairs with the Pi/server.
- [ ] Encrypted authenticated WebSocket/node transport between NekoSuneAI and the Windows gaming PC.
- [ ] Windows agent heartbeat showing online/offline state, latency, GPU/CPU load and active game.
- [ ] Start with Windows automatically as an optional service/tray application.
- [ ] Restrict Neko to configured game/application windows rather than unrestricted desktop control by default.
- [ ] Per-game permissions for vision, keyboard, mouse, controller, audio, mods/APIs and streaming.
- [ ] Emergency local hotkey/button to immediately disable all AI game input.
- [ ] Remote supervision from the Neko dashboard/Android app with pause/take-over/stop controls.
- [ ] Add `Windows Gaming Node` / `Game Vision Node` to Neko Peripheral Nodes.

### Game capture & vision
- [ ] Low-latency Windows game-window capture using supported desktop/game capture APIs.
- [ ] Capture only the selected game/window/monitor instead of uploading the entire desktop when possible.
- [ ] Adjustable capture FPS/resolution so visual analysis does not overload the PC or network.
- [ ] Fast local vision preprocessing/object detection on the Windows GPU where available.
- [ ] Send compact observations/state to the Pi instead of sending every raw frame.
- [ ] On-demand high-detail screenshots when Neko needs to inspect UI/text/scenes more closely.
- [ ] OCR for menus, HUD text, subtitles, inventory, coordinates and game messages where useful.
- [ ] Scene-change/death/menu/loading detection to avoid pointless actions during transitions.
- [ ] Maintain a short-lived visual working memory of recent frames/events for game reasoning.

### Input & real-time control
- [ ] Keyboard/mouse control through an explicit allowlisted input layer.
- [ ] Virtual game-controller support for games that work better with controller input.
- [ ] High-level action API instead of requiring the LLM to generate individual keypresses every frame.
- [ ] Local fast-control loops on Windows for movement, steering, aiming/camera turning and obstacle avoidance while the Pi gives higher-level goals.
- [ ] Configurable action timeouts so a stuck action automatically releases held keys/buttons.
- [ ] Automatic release of all virtual inputs when the connection to Neko is lost.
- [ ] Manual user input can optionally override/pause Neko immediately.
- [ ] Record action/result telemetry so Neko can learn which game skills are reliable.

### Game adapters & skills
- [ ] Generic vision-only game adapter for offline/single-player games without APIs/mods.
- [ ] Structured game-state adapter interface for games/mods/plugins that can safely expose better telemetry than vision alone.
- [ ] Hybrid mode combining game API/mod telemetry + screenshots + controlled input.
- [ ] Named reusable game skills instead of relearning controls every session.
- [ ] Skill examples: `generic.move`, `generic.look`, `generic.interact`, `generic.open_menu`, `generic.pause`.
- [ ] Per-game keybind/control profile discovered/configured before autonomous play.
- [ ] Game objective/goal system: long-term goal on the Pi, short-term actions executed locally on Windows.
- [ ] Skill failure reporting with reason such as blocked path, UI changed, target lost or unsupported action.
- [ ] Safe game-specific memory for maps, controls, known locations, recurring objectives and user-approved strategies.

### Minecraft autonomous play
- [ ] Minecraft adapter with screen vision plus optional mod/plugin telemetry.
- [ ] Read health, hunger, coordinates, inventory and nearby entities from an approved mod/API when available.
- [ ] Minecraft skills such as walking, looking, jumping, interacting, mining, placing blocks, eating and opening inventory.
- [ ] Higher-level skills such as `find tree`, `collect wood`, `find shelter`, `craft item`, and `return home` built on local movement/action primitives.
- [ ] Navigation/pathfinding handled locally where practical rather than sending every movement decision to the Pi.
- [ ] Detect death/respawn/menu states and stop unsafe repeated inputs.
- [ ] Server-specific automation policy so Neko only uses autonomous play where server/game rules permit it.

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
- [ ] Adapter framework for supported offline/single-player games such as Fallout-style games.
- [ ] Emulator adapter for user-owned games with generic controller + vision support.
- [ ] Game-specific adapter packages can be enabled/disabled independently.
- [ ] Anti-cheat-aware game profiles: disable automated input for multiplayer/competitive games where bots/macros are prohibited.
- [ ] Never attempt to bypass anti-cheat, bot detection or game/platform restrictions.

### OBS / stream control
- [ ] OBS WebSocket integration from the Windows node.
- [ ] Start/stop stream only with configured permission/confirmation policy.
- [ ] Start/stop recording and replay-buffer controls.
- [ ] Scene switching for gameplay, chatting, BRB, technical-problem and ending scenes.
- [ ] Monitor stream state, bitrate, dropped frames, encoder load and game-capture availability.
- [ ] Detect broken/missing game capture and optionally switch to BRB while attempting a safe recovery.
- [ ] Monitor configured audio meters so Neko can warn if game/TTS/microphone audio disappears or clips.
- [ ] Automatically restore the gameplay scene after a verified recovery.
- [ ] Stream title/category update integration where Twitch permissions allow it.
- [ ] Create stream markers/bookmarks for notable moments and optional clip requests where supported.
- [ ] Stream-session timeline with game changes, scene switches, technical issues and notable moments.

### Twitch chat & autonomous VTuber behaviour
- [ ] Twitch chat connection integrated into the same Neko conversation/personality system.
- [ ] Read incoming chat without speaking every message aloud.
- [ ] Chat prioritisation so questions/mentions/important messages can be answered without constantly interrupting gameplay.
- [ ] Spam/repetition/raid/message-flood handling and configurable cooldowns.
- [ ] Twitch moderation integration using user-defined rules and permissions.
- [ ] Respond in Twitch chat and optionally speak selected replies through TTS.
- [ ] Recognise follows/subscriptions/raids/channel-point events where Twitch APIs expose them.
- [ ] Trigger avatar expressions/animations, sounds or overlays for configured stream events.
- [ ] Maintain stream-specific conversational context while preserving the normal Neko personality.
- [ ] Separate private owner instructions from public Twitch-chat instructions so viewers cannot control the PC/Neko without permission.
- [ ] Viewer interaction commands are allowlisted and rate-limited.

### Autonomous stream sessions
- [ ] High-level command such as `Neko, stream Minecraft` can prepare an autonomous stream session.
- [ ] Pre-stream checklist: Windows node online, game installed, OBS available, capture source healthy, audio healthy and Twitch connection ready.
- [ ] Launch the configured game and wait until it is actually ready before beginning autonomous play.
- [ ] Optional confirmation immediately before going live.
- [ ] Neko can play, talk to Twitch chat and react to stream events while the user supervises remotely.
- [ ] Scheduled/owner-triggered breaks with BRB scene and safe game pause where supported.
- [ ] Recover from game crash by stopping input, switching to BRB and notifying the owner before attempting configured recovery.
- [ ] End-stream routine: stop game actions, say goodbye, switch ending scene, stop stream, save session summary and optionally close approved apps.
- [ ] Android/dashboard view showing current game, objective, stream state, viewers/chat activity, errors and Neko's current action.
- [ ] One-tap owner `take over`, `pause Neko`, `stop stream`, and `stop all input` controls.

### Architecture / performance
- [ ] Pi/server performs personality, conversation, long-term memory, planning and high-level game goals.
- [ ] Windows PC performs game rendering, screen capture, fast vision preprocessing, input loops, OBS and audio routing.
- [ ] Do not send every video frame or keypress through the Pi; use local Windows control loops and compact observations.
- [ ] Adaptive vision rate: reduce analysis while loading/idle and increase it temporarily when precise visual understanding is needed.
- [ ] Hardware acceleration on Windows where supported without making a dedicated GPU mandatory for basic operation.
- [ ] Backpressure/queue limits so Twitch chat or vision frames cannot overwhelm Neko's reasoning pipeline.
- [ ] Session logs that record goals, observations, skills/actions and results for debugging without retaining raw video unless explicitly enabled.
- [ ] Capability examples: `game.status`, `game.capture`, `game.skill`, `game.input.stop`, `obs.scene`, `obs.stream.status`, `twitch.chat.read`, and `twitch.chat.send`.

## 🔥 Hardware safety & hazard detection

Treat hazard detection as a deterministic safety layer around NekoSuneAI rather than relying on the language model to decide whether a dangerous condition is real.

### Hardware temperature & cooling monitoring
- [ ] Monitor CPU, GPU, SSD/NVMe, motherboard/chipset and other available hardware temperature sensors.
- [ ] Monitor fan RPM/pump RPM and detect stalled, disconnected or abnormally slow cooling devices.
- [ ] Track temperature trends and rate-of-rise, not just fixed maximum thresholds.
- [ ] Device-specific warning/critical thresholds instead of one global temperature limit.
- [ ] Detect sustained overheating versus short harmless temperature spikes.
- [ ] Warn when a component repeatedly thermal-throttles.
- [ ] Monitor server/rack/PC-case ambient temperature with external sensors where available.
- [ ] Detect unusually large temperature differences between internal components and room/enclosure sensors.

### Fire / smoke / thermal-risk sensors
- [ ] Integrate dedicated smoke and heat alarms through supported relay, MQTT, Home Assistant or approved local interfaces.
- [ ] Optional CO detector integration for room/home emergency awareness.
- [ ] ESP32 temperature/smoke-compatible sensor nodes for server racks, printer areas and other configured equipment zones.
- [ ] Optional thermal-camera/IR sensor integration for configured equipment, used as supporting evidence rather than the only fire detector.
- [ ] Detect rapid enclosure temperature rise and escalate independently of normal CPU/GPU temperature limits.
- [ ] Camera-based visible smoke/flame anomaly detection may provide an additional warning but must never replace certified smoke/heat alarms.
- [ ] Record which physical sensor triggered, its location and raw reading/state in the incident timeline.

### Power / electrical anomaly monitoring
- [ ] Monitor UPS voltage, load, battery health, runtime and fault state.
- [ ] Smart-plug/power-meter monitoring for configured equipment where reliable local telemetry exists.
- [ ] Detect abnormal sustained current/power draw compared with the device's learned/configured normal range.
- [ ] Detect equipment consuming power while it should be off or idle where state can be verified.
- [ ] Alert on repeated brownouts, unexpected mains loss or unstable UPS input.
- [ ] Optional current-clamp sensor nodes for circuits/equipment where appropriately installed.
- [ ] Never treat software power telemetry as a replacement for breakers, fuses, RCDs/GFCIs or electrical safety devices.

### Battery & charging safety
- [ ] Monitor available laptop/phone/UPS/portable-device battery temperature, charge rate and health telemetry.
- [ ] Detect abnormal battery temperature rise while charging where the device exposes trustworthy telemetry.
- [ ] Warn when a battery reports swelling/fault/health warnings through supported hardware APIs.
- [ ] Stop optional heavy workloads when a host battery reaches a configured critical thermal or power state.
- [ ] Treat unavailable battery-temperature telemetry as unknown rather than assuming the battery is safe.

### 3D-printer hazard watchdog
- [ ] Monitor commanded versus actual hotend/bed temperature.
- [ ] Detect continued heating when the heater should be off or temperature rises unexpectedly.
- [ ] Surface printer firmware thermal-runaway/heater-fault states immediately.
- [ ] Monitor printer enclosure temperature and external smoke/heat sensors where installed.
- [ ] Correlate printer power draw, temperature and camera events for better warnings.
- [ ] Optional high-confidence emergency pause/stop policy while keeping firmware thermal protection as the primary safety system.
- [ ] Never disable or bypass printer firmware thermal-runaway protection, heater limits or hardware safety systems.

### Water / environment hazards
- [ ] Water-leak sensor support near servers, printers, washing machines, sinks or other configured locations.
- [ ] Humidity/condensation warnings for electronics/storage areas when sensors are installed.
- [ ] Air-quality/VOC sensor support as an additional environmental warning source where useful.
- [ ] Sensor-offline/stale-data warning so missing safety telemetry cannot silently look normal.

### Alert levels & escalation
- [ ] Standard severity model: `INFO`, `WARNING`, `CRITICAL`, `EMERGENCY`.
- [ ] Example `WARNING`: unusually high temperature sustained beyond a configured duration.
- [ ] Example `CRITICAL`: extreme temperature combined with fan/pump failure or repeated thermal shutdown.
- [ ] Example `EMERGENCY`: dedicated smoke/heat alarm triggered or multiple independent sensors indicate a severe thermal event.
- [ ] Escalation cooldowns that avoid notification spam without suppressing worsening conditions.
- [ ] Voice, dashboard and Android emergency notifications with affected device/location and sensor evidence.
- [ ] Emergency alerts override normal do-not-disturb settings when the user enables that policy.

### Deterministic automatic safety actions
- [ ] Safety rules execute outside the LLM so confirmed critical sensor events do not wait for AI reasoning.
- [ ] Configurable first response: reduce AI/game/encoding workloads, stop benchmarks and pause nonessential Docker workloads.
- [ ] Gracefully stop autonomous gaming/streaming if Windows hardware reaches a configured critical state.
- [ ] Graceful OS shutdown for configured PCs/servers when trustworthy sensor rules indicate continuing dangerous overheating.
- [ ] Controlled shutdown of a 3D-print job through the printer's supported safety API where configured.
- [ ] Optional smart-plug power isolation only for explicitly allowlisted equipment and only under carefully configured rules; never from camera inference alone.
- [ ] Preserve dedicated alarm, firmware, UPS, breaker and hardware protection behaviour instead of attempting to replace it.
- [ ] Manual emergency-stop / disable control remains available independently of Neko's AI process.

### Safety dashboard & incident history
- [ ] Hardware safety dashboard showing temperatures, fans, power, smoke/heat alarms, UPS, batteries, leaks and sensor health.
- [ ] Per-device normal/warning/critical limits with editable defaults.
- [ ] Trend graphs for temperature, fan speed and power around an incident.
- [ ] Incident timeline containing warnings, sensor readings, automatic actions and recovery state.
- [ ] `Neko, why did you shut the PC down?` can explain the deterministic rule and sensor evidence that triggered it.
- [ ] Post-incident health check before automatically returning workloads/services to normal.
- [ ] Require user acknowledgement before automatically restarting hardware after a serious smoke/heat/electrical event.
- [ ] Peripheral Node capabilities such as `hardware.temperature`, `hardware.fan`, `power.current`, `safety.smoke`, `safety.heat`, `safety.leak`, `safety.alert`, and `safety.shutdown`.

## 🖥️ VPS / infrastructure & service monitoring

Run a lightweight authenticated Neko Server Node on VPSs, dedicated servers, Raspberry Pis and supported hosts so Neko can monitor infrastructure without running heavy AI workloads on every machine.

### VPS / server node
- [ ] Lightweight Linux server agent with encrypted authenticated connection back to NekoSuneAI.
- [ ] CPU usage, load average, RAM, swap, disk usage, inode usage and uptime monitoring.
- [ ] Disk I/O, filesystem latency and rapidly-growing-disk detection.
- [ ] Network bandwidth, packet loss, latency and connection-state monitoring.
- [ ] Process and systemd-service health monitoring with restart-loop detection.
- [ ] Docker/Compose container state, health checks, CPU/RAM usage and restart-count monitoring.
- [ ] Detect Linux OOM kills, kernel errors, filesystem errors and unexpected reboots.
- [ ] GPU temperature, utilisation, VRAM and driver-health monitoring when a VPS/dedicated host exposes a GPU.
- [ ] SMART/NVMe health and temperature monitoring on dedicated hardware when host access exposes it.
- [ ] Read physical temperature/fan/power sensors only when the host/hypervisor exposes trustworthy telemetry.
- [ ] Explicitly show `unavailable` for physical CPU temperature, fan RPM, SMART or other sensors hidden by normal VPS hypervisors rather than inventing readings.
- [ ] Server tags/groups such as production, development, game servers, streaming, storage and home.
- [ ] Commands such as `Neko, how are all my servers?`, `which VPS is using the most RAM?`, and `why did this server restart?`.

### Websites, APIs & service health
- [ ] HTTP/HTTPS uptime checks with configurable expected status code and response-time limits.
- [ ] API endpoint health checks with optional authenticated health endpoints.
- [ ] WebSocket connectivity checks.
- [ ] TCP service checks for configured ports/services without general Internet scanning.
- [ ] DNS resolution checks and authoritative DNS health monitoring for configured domains.
- [ ] TLS/SSL certificate expiry and invalid-certificate warnings.
- [ ] Domain-expiry reminders where reliable registration data/API access exists.
- [ ] Database health checks for configured PostgreSQL/MySQL/MariaDB services using least-privilege monitoring credentials.
- [ ] Redis availability, memory usage and persistence-health checks.
- [ ] Reverse-proxy health for Nginx, Nginx Proxy Manager, Caddy or Traefik where integrations/log access exist.
- [ ] Detect HTTP 4xx/5xx rate changes and response-time regressions from configured services.
- [ ] Optional application-specific health endpoints for Neko projects.

### Logs, failures & diagnostics
- [ ] Structured ingestion of selected systemd/journald, Docker and application logs with per-source allowlists.
- [ ] Error-rate and repeated-exception detection without uploading every log line to the LLM.
- [ ] Group duplicate errors into one incident instead of notification spam.
- [ ] Detect restart loops, crash loops and dependency failures.
- [ ] Keep sensitive tokens/passwords/headers redacted before logs reach AI context or notifications.
- [ ] Natural diagnostics such as `why is the website down?` using current service state, dependency health and recent errors.
- [ ] Incident evidence bundle containing relevant health checks and redacted log excerpts.

### Infrastructure dependency map
- [ ] Map relationships such as domain → DNS → reverse proxy → web app → API → database/Redis.
- [ ] Correlate downstream failures so one database outage does not create ten unrelated alerts.
- [ ] Identify likely root cause and affected dependent services.
- [ ] `Neko, what broke when VPS-2 went offline?` dependency-impact query.
- [ ] Maintenance mode to suppress expected child alerts while a host/service is intentionally offline.

### Backups, storage & maintenance
- [ ] Monitor configured backup jobs and alert when a scheduled backup does not occur.
- [ ] Verify backup age, size and completion state without assuming a backup is valid merely because a file exists.
- [ ] Optional restore-test workflow for user-approved disposable test environments.
- [ ] NAS/storage capacity and disk-health monitoring through supported local APIs/agents.
- [ ] Warn before disks become critically full using predicted growth rate.
- [ ] Package/security-update availability summary without silently applying major upgrades.
- [ ] Configurable maintenance windows for approved automatic safe actions.

### Safe infrastructure actions
- [ ] Allowlisted actions such as restart a known container/service, collect diagnostics or enter maintenance mode.
- [ ] Require confirmation for host reboot/shutdown, destructive database actions, firewall changes or other high-impact operations unless a deterministic emergency policy explicitly covers them.
- [ ] Never give the AI arbitrary root-shell execution by default.
- [ ] Per-node/action permissions and audit log showing who/what requested each infrastructure change.
- [ ] Health check after automated restart/recovery and escalate if the service remains unhealthy.
- [ ] Capabilities such as `server.status`, `server.metrics`, `service.status`, `service.restart`, `docker.status`, `website.check`, `backup.status` and `network.latency`.

## 💬 Discord / community operations

Use a properly authorised Discord bot in servers where the owner/admin has explicitly installed it. Monitoring should be configurable by server/channel and should not turn private community conversations into unrestricted AI training data.

### Discord server monitoring
- [ ] Monitor configured Discord guild/bot connection health and gateway reconnects.
- [ ] Track selected important channels for mentions, reports, support requests and configured keywords/events.
- [ ] Detect unanswered support/ticket threads after a configurable amount of time.
- [ ] Summarise selected channels while respecting channel/role permissions.
- [ ] Track joins/leaves, moderation-log events and bot status where permissions permit.
- [ ] Detect unusual message floods, repeated spam and raid-like join/message patterns.
- [ ] Watch configured project bots and notify when a required bot goes offline or repeatedly disconnects.
- [ ] Optional channel activity statistics without profiling individual members unnecessarily.
- [ ] Commands such as `Neko, what happened in Discord while I was away?` and `are there support tickets waiting?`.

### Community briefing & triage
- [ ] Daily/owner-requested community briefing summarising unanswered questions, reports, important mentions, project discussion and bot incidents.
- [ ] Prioritise owner/admin mentions and support/moderation queues separately from normal chatter.
- [ ] Deduplicate repeated reports about the same outage/problem.
- [ ] Correlate Discord reports with monitored infrastructure incidents, e.g. several `site is down` messages plus failing API checks.
- [ ] Create a concise incident summary for moderators/admins without exposing unrelated private conversation.
- [ ] Allow configurable channels to be completely excluded from AI summaries/history.

### Moderation assistance
- [ ] Flag likely spam, scam links, repeated flooding and raid patterns for moderator review.
- [ ] Deterministic anti-flood rules can perform preconfigured actions when explicitly enabled.
- [ ] Ambiguous harassment/context decisions stay human-reviewed rather than auto-banning from an LLM judgment alone.
- [ ] Moderator evidence view containing the relevant messages/events and rule that triggered the flag.
- [ ] Configurable escalation: log only, alert moderators, slowmode suggestion, timeout suggestion or approved deterministic action.
- [ ] Keep moderation actions permission-gated and fully auditable.

### Discord + project integrations
- [ ] Post configured service status/incidents to a selected status/admin channel.
- [ ] Post GitHub Actions/build failures and release notifications to selected development channels.
- [ ] Link Discord support reports to the matching service/project when confidence is high.
- [ ] Optional game-server status messages/player counts for configured community servers.
- [ ] Community event/reminder integration with calendar and Neko announcement systems.
- [ ] Never allow ordinary Discord users to invoke owner-only PC/server/smart-home actions.

## 📡 Neko Operations Center

Create one operations view that combines physical hardware, VPSs, websites, applications, Discord/community systems, GitHub, game servers and Neko nodes.

### Unified operations dashboard
- [ ] Global health states using `OK`, `INFO`, `WARNING`, `CRITICAL`, and `EMERGENCY`.
- [ ] Views for Home, Hardware Safety, VPS/Servers, Websites/APIs, Docker, Discord, GitHub, Game Servers, Streaming and Neko Peripheral Nodes.
- [ ] Overall `Neko, status report` that prioritises active problems instead of listing every healthy service.
- [ ] Incident timeline combining alerts from multiple integrations.
- [ ] Acknowledge, mute and maintenance-state controls with expiration times.
- [ ] Group repeated symptoms into one incident where possible.
- [ ] Root-cause/dependency correlation across infrastructure and community reports.
- [ ] Historical uptime/latency/resource graphs with configurable data retention.

### External/project monitoring
- [ ] GitHub repository monitoring for failed Actions workflows, releases, important issues/PRs and configured branch health.
- [ ] Docker/container fleet overview across Pi, home servers and VPS nodes.
- [ ] Minecraft/other game-server status, player count, tick/TPS/performance where supported.
- [ ] VPN/Tailscale/WireGuard node reachability for configured user-owned infrastructure.
- [ ] Internet/WAN connectivity and latency monitoring from selected nodes.
- [ ] Email delivery/service health checks for configured systems without reading unrelated mailbox content.
- [ ] Cloudflare/DNS/tunnel health where supported APIs/account permissions are configured.

### Correlation & proactive intelligence
- [ ] Correlate user/community complaints with live service telemetry before suggesting a likely cause.
- [ ] Detect patterns such as memory leaks, gradually increasing disk usage or repeating nightly failures.
- [ ] Predict likely disk-full conditions and certificate expirations before they become outages.
- [ ] Distinguish one-off transient failures from persistent incidents using configurable retry windows.
- [ ] Explain why an alert was raised and what evidence supports the conclusion.
- [ ] Suggested remediation can be generated separately from automatic execution.

### Away/asleep summary
- [ ] `What happened while I was asleep/out?` combines home safety events, VPS incidents, website outages, Discord activity, GitHub failures, streaming events and other enabled sources.
- [ ] Summaries prioritise emergencies/critical issues, then unresolved warnings, then noteworthy information.
- [ ] Avoid repeating incidents already acknowledged by the owner.
- [ ] Include what automatically recovered, what remains broken and what needs owner attention.
- [ ] Optional Android notification when a new CRITICAL/EMERGENCY operational incident occurs.

## 👤 VRChat Owner Read-Only Monitor & VRCX History

Keep the owner account physically separated from the autonomous bot account. The owner session is read-only: it may observe, import, cache, index and notify, but it must not send invites, accept requests, join worlds, change status, modify friendships, message users or perform any other account action.

### Owner account read-only realtime monitor
- [ ] Separate owner-account credentials/session from the Neko bot account.
- [ ] Read-only adapter that exposes only approved read capabilities and contains no generic write/action endpoint.
- [ ] Consume VRChat realtime/WebSocket/event data that the current supported interface actually exposes.
- [ ] Monitor owner online/offline/session state.
- [ ] Monitor friend online/offline changes.
- [ ] Monitor friend location/world/instance changes only where VRChat exposes that information to the authenticated owner account.
- [ ] Monitor owner world/instance changes where available.
- [ ] Monitor notifications, invites, request events and friend-request events where exposed.
- [ ] Monitor user/friend status changes and other safe social presence events where exposed.
- [ ] Monitor group-related notifications/events where exposed to the owner account.
- [ ] Gracefully mark unsupported or unavailable event types instead of fabricating data.
- [ ] Automatic reconnect with backoff and event-gap detection after realtime connection loss.
- [ ] Capability examples: `vrchat.owner.status.read`, `vrchat.owner.friends.read`, `vrchat.owner.location.read`, `vrchat.owner.notifications.read`, and `vrchat.owner.events.read`.

### Friend history / unfriend tracking
- [ ] Periodic owner friend-list snapshots with timestamp and stable VRChat user IDs.
- [ ] Compare snapshots to detect additions and removals from the friend list.
- [ ] Record the first time a friendship is observed missing after previously existing.
- [ ] Dashboard `friend removed` / `friendship no longer present` event with previous last-seen friendship time.
- [ ] Do not automatically claim `they unfriended you` when the available data only proves the friendship disappeared.
- [ ] Distinguish known explanations where evidence exists, such as account unavailable/deleted, API response incomplete or user action recorded locally.
- [ ] Retry/confirm friend-list removals across multiple successful snapshots before treating temporary API failures as durable changes.
- [ ] Friend-history page showing first seen, last seen, friendship active/removed state and historical presence events.
- [ ] Query support such as `who was removed from my friends recently?`, `who is new on my friends list?`, and `when did this friendship disappear?`.

### VRCX historical import / catch-up
- [ ] Import user-selected VRCX local history/database/export data without requiring VRCX to remain running.
- [ ] Parse supported historical friend presence, notifications, world/instance visits, joins/leaves, status changes and other user-owned VRCX records where available.
- [ ] Import VRCX friend/friendship history so the dashboard can show data from before Neko's live monitor was installed.
- [ ] Dry-run import mode showing record counts/types before committing data to Neko's history database.
- [ ] Never modify or write back into the original VRCX database during import.
- [ ] Store import metadata such as source file/database, import time and detected VRCX schema/version.
- [ ] Re-import support for newer VRCX exports without duplicating existing historical records.
- [ ] Report unsupported/unknown VRCX tables/fields instead of silently guessing their meaning.

### Timeline, merging & deduplication
- [ ] Unified VRChat owner timeline combining live VRChat events, friend-list snapshots and VRCX imports.
- [ ] Every event stores a source such as `VRChat live`, `VRChat snapshot`, or `VRCX import`.
- [ ] Deduplicate equivalent VRCX/live events using stable IDs where available and timestamp/type/user matching where not.
- [ ] Preserve provenance when two sources confirm the same event rather than losing source information.
- [ ] Store confidence/state for inferred events such as friendship removal versus directly received realtime events.
- [ ] Search/filter timeline by user, world, instance, event type, source and date range.
- [ ] Dashboard catch-up view for `today`, `while I was away`, `last 24 hours`, `this week` and custom periods.
- [ ] Natural queries such as `who came online while I was away?`, `what invites did I miss?`, `when did I last see this friend?`, and `what changed in VRChat today?`.
- [ ] Include important VRChat owner events in the wider Neko Operations Center away/asleep summary when enabled.

### Privacy, retention & account safety
- [ ] Owner monitor defaults to read-only at the code/capability layer, not merely by prompt instruction.
- [ ] No owner-account capability for invite/send/accept/join/message/status/friend-modification actions.
- [ ] Bot account is the only VRChat account that may receive configured interactive/autonomous capabilities.
- [ ] Separate credential storage and session identifiers so the bot cannot accidentally reuse the owner account session.
- [ ] Configurable local retention for owner timeline/presence history.
- [ ] Per-event-category retention controls for locations, notifications and friend presence.
- [ ] One-command export/delete of locally stored owner VRChat monitoring history.
- [ ] Sensitive instance/location history can be disabled independently.
- [ ] Dashboard clearly labels imported history versus live observations and inferred friend-list changes.

## 🎮 VRChat / heavier ML backlog
- [ ] A* dead-reckoning navigation and persisted world maps.
- [ ] YOLO/ONNX screen object detection (opt-in).
- [ ] RapidOCR nameplate reading.
- [ ] Voice-per-language profiles.
