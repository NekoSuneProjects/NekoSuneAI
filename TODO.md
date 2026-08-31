# NekoSuneAI — Roadmap / TODO

Tracking the push toward full **Neuro-sama-style** capability, VRChat-first.

## 🏠 Smart assistant / Alexa & Google Home-style ideas

Prefer local/offline control where practical and make cloud/account integrations optional.

### Audio, speakers & multi-room
- [ ] Alexa/Echo Bluetooth volume control — volume/up/down/mute/unmute through PipeWire/PulseAudio.
- [ ] Per-device speaker volume and remembered levels.
- [ ] Multi-room audio groups for one room, selected rooms, or whole home.
- [ ] Whole-home broadcast/intercom between Pi, PC, speakers and Android nodes.
- [ ] Do-not-disturb / quiet hours.
- [ ] Adaptive TTS volume based on ambient noise.
- [ ] Follow-me audio — move music/TTS to the room the user moves into.
- [ ] Follow-me conversation — continue the same NekoSuneAI conversation on another room node/phone.
- [ ] Whisper/night mode — whisper to Neko and have her answer quietly.
- [ ] Intelligent interruption priorities — emergency > important > normal > optional.
- [ ] Don't-interrupt mode — delay non-critical announcements while conversation/media is detected.

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
- [ ] Named routines/scenes such as good morning, good night and movie mode.
- [ ] Routine builder dashboard: trigger + conditions + ordered actions.
- [ ] Sensor-triggered routines.
- [ ] Sunrise/sunset routines.
- [ ] Presence/occupancy awareness.
- [ ] Natural-language routine creation — describe a routine instead of programming every field.
- [ ] Temporary routines — `for the next three days, wake me at 8`.
- [ ] Conditional/location reminders — `remind me about washing when I next go downstairs`.
- [ ] Teach-by-demonstration — record a safe sequence of actions such as a streaming setup and save it as an editable routine.
- [ ] Automation conflict detection when two routines fight over the same device.
- [ ] Explain automations — answer `why did the hallway light turn on?` with the triggering rule/sensor.
- [ ] Natural routine debugging — answer why a routine did not execute.
- [ ] Undo previous safe device action where the prior state is known.
- [ ] Preview/confirmation for large actions such as turning off many devices at once.

### Conversational assistant improvements
- [ ] Real conversational follow-ups without repeating device names/wake word every sentence.
- [ ] User-defined natural commands such as teaching `make it cozy`.
- [ ] Explain failures instead of returning generic device errors.
- [ ] Proactive suggestions, e.g. lights left on in an unoccupied room.
- [ ] Correction handling — `no, I meant the kitchen light` updates the previous command.
- [ ] Immediate `Neko stop` interruption for TTS/music/actions.
- [ ] Multiple-person profiles with separate preferences, permissions, calendars and memories.
- [ ] Guest mode with limited safe smart-home access.
- [ ] Optional local voice identification for household profiles.
- [ ] Cross-device conversation/context memory between Pi, PC and Android nodes.

### Timers, alarms, reminders & lists
- [ ] Multiple named timers with list/pause/cancel.
- [ ] One-off/repeating alarms, custom sound/TTS and snooze.
- [ ] Local reminder engine with spoken/dashboard/Android notifications.
- [ ] Shopping lists.
- [ ] To-do lists with priorities/due dates.
- [ ] Calendar integration.
- [ ] Ask about previous announcements — `what did you just tell me?`.
- [ ] Notification summarisation, deduplication and cooldowns.

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
- [ ] Find my phone with authenticated loud ring.
- [ ] Phone battery monitoring.
- [ ] Selected incoming notification/SMS relay with privacy filters.
- [ ] Phone-as-presence sensor.
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
- [ ] Integration health dashboard.
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

- [ ] Generic authenticated node registration/pairing system.
- [ ] Capability manifest such as `printer.status`, `printer.pause`, `camera.snapshot`, `display.notify`, `sensor.temperature`, `device.battery`, `audio.speak`.
- [ ] Per-capability permission/confirmation policy.
- [ ] Read-only vs state-changing capability classification.
- [ ] Node heartbeat, latency, battery and online/offline status.
- [ ] Local WebSocket/MQTT/HTTP transport adapters with encryption/authentication.
- [ ] Remote transport option through the existing bridge without exposing unauthenticated LAN controls.
- [ ] Dashboard for connected nodes, capabilities, permissions and last activity.
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

## 🎮 VRChat / heavier ML backlog
- [ ] A* dead-reckoning navigation and persisted world maps.
- [ ] YOLO/ONNX screen object detection (opt-in).
- [ ] RapidOCR nameplate reading.
- [ ] Voice-per-language profiles.