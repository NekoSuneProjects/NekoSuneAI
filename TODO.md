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

## 🎮 VRChat / heavier ML backlog
- [ ] A* dead-reckoning navigation and persisted world maps.
- [ ] YOLO/ONNX screen object detection (opt-in).
- [ ] RapidOCR nameplate reading.
- [ ] Voice-per-language profiles.
