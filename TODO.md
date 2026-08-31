# NekoSuneAI — Roadmap / TODO

Tracking the push toward full **Neuro-sama-style** capability, VRChat-first. This
file was rewritten from scratch after a round of cleanup — most of what used to
be here is either done differently now or gone (Image Review, built-in Radio).

## ✅ Done (this push)

- **RVC voice for normal chat** (`nekosuneai/rvc.py`) — optional real-time RVC
  voice-conversion pass over every spoken reply (not just singing), with a Pitch
  control and a couple of standard RVC knobs (index rate, protect) in Settings →
  Voice. Forces non-streaming XTTS synthesis since the whole line has to render
  before it can be converted.
- **Radio removed** (`nekosuneai/media.py`) — the built-in station directory +
  internet-radio.com search are gone. Music search/streaming stays.
- **Image Review removed** — vision is VRChat-first now.
- **Sticky wake-instructions + memory reset** (`nekosuneai/sticky.py`).
- **Thinking music** (`nekosuneai/media_player.py`).
- **OSC chatbox paging** (`games/vrchat.py`).
- **VRChat friends system** (`games/vrchat_friends.py`).
- **VRChat embodiment** (`games/vrchat.py`, `vrchat_logs.py`).
- **Watch & React mode**.
- **Per-language TTS voice**.

## 🏠 Smart assistant / Alexa & Google Home-style ideas

These are integrations/features NekoSuneAI could gain so she can act more like a
full home assistant rather than only a conversational AI. Prefer local/offline
control where practical and make cloud/account integrations optional.

### Audio, speakers & multi-room
- [ ] **Alexa/Echo Bluetooth volume control** — detect the active PipeWire/
      PulseAudio sink and support `volume 50`, `turn it up/down`, `mute`, and
      `unmute` without needing an Amazon account API.
- [ ] **Per-device speaker volume** — remember independent volume levels for
      Alexa/Echo, Bluetooth speakers, HDMI, USB audio and Android nodes.
- [ ] **Multi-room audio groups** — choose one speaker, a room, or all paired
      NekoSuneAI nodes for music/TTS playback.
- [ ] **Whole-home broadcast / intercom** — `announce dinner is ready everywhere`
      or send speech to a specific room, Pi, PC or Android device.
- [ ] **Do-not-disturb / quiet hours** — reduce volume or suppress non-critical
      spoken notifications during configured hours.
- [ ] **Adaptive volume** — optionally raise/lower TTS volume based on ambient
      microphone noise, then restore the previous volume.

### Matter / smart-home devices
- [ ] **Matter controller integration** — discover and control compatible local
      lights, plugs, switches, thermostats, sensors, blinds and other devices.
- [ ] **Matter device dashboard** — rooms, device state, online/offline status,
      controls, rename, room assignment and favorites.
- [ ] **Thread support/documentation** — use an existing Thread Border Router for
      Matter-over-Thread while allowing Wi-Fi/Ethernet Matter devices directly.
- [ ] **Home Assistant entity control** — expand the existing MQTT support so
      natural-language commands can query/control HA lights, switches, sensors,
      climate devices, scenes and automations.
- [ ] **MQTT generic devices** — configurable discovery/control for DIY ESP32,
      Raspberry Pi, Tasmota and similar MQTT hardware.
- [ ] **Philips Hue local integration** — local bridge discovery and light/
      scene/brightness/colour control.
- [ ] **WLED integration** — local control of WLED strips, presets, brightness,
      effects and segments.
- [ ] **Shelly local integration** — discover/control compatible local relays,
      plugs and power-monitoring devices.

### Routines & automation
- [ ] **Named routines/scenes** — `good morning`, `good night`, `movie mode`, etc.
      can run several NekoSuneAI actions together.
- [ ] **Routine builder dashboard** — trigger + conditions + ordered actions,
      with enable/disable controls.
- [ ] **Sensor-triggered routines** — react to motion, door/window, temperature,
      presence, battery and other smart-home state changes.
- [ ] **Sunrise/sunset routines** — local astronomical triggers based on the
      configured home location.
- [ ] **Presence/occupancy awareness** — optionally use phone/node presence and
      smart-home sensors to know whether somebody is home or which room is
      occupied.

### Timers, alarms, reminders & lists
- [ ] **Multiple named timers** — `set a pizza timer for 12 minutes`, list,
      pause/cancel and announce when finished.
- [ ] **Alarms** — one-off and repeating alarms with configurable sound/TTS and
      snooze support.
- [ ] **Reminder engine** — local reminders with spoken/dashboard/Android
      notifications and recurring schedules.
- [ ] **Shopping list** — voice add/remove/check-off items with dashboard and
      Android synchronization.
- [ ] **To-do list** — named lists, priorities, due dates and spoken queries.
- [ ] **Calendar integration** — read upcoming events and optionally create
      reminders/events through supported calendar providers.

### Media & entertainment
- [ ] **Unified media controls** — play/pause/resume/stop/next/previous/seek and
      volume across NekoSuneAI music outputs.
- [ ] **Spotify Connect integration** — discover available Spotify devices and
      transfer/control playback when authenticated by the user.
- [ ] **Chromecast / Google Cast integration** — discover Cast targets and send
      supported local/media playback to TVs and speakers.
- [ ] **DLNA/UPnP media renderer support** — discover compatible TVs/speakers and
      control playback locally.
- [ ] **TV integration** — optional local integrations such as Android TV/ADB,
      LG webOS and Samsung TV for power/input/volume/media controls where the
      device permits it.

### Phone / Android companion
- [ ] **Find my phone** — command an authenticated Android node to ring loudly
      until dismissed, including when the phone is normally quiet where Android
      permissions allow it.
- [ ] **Phone battery monitoring** — warn through NekoSuneAI when a paired phone
      reaches configurable low/critical battery thresholds.
- [ ] **Incoming notification relay** — optionally announce selected Android
      notifications/SMS sender names while respecting privacy filters.
- [ ] **Phone-as-presence sensor** — authenticated local node heartbeat for
      home/away and room/node awareness.
- [ ] **Remote phone controls** — configurable safe actions such as ring,
      flashlight, media control and notification acknowledgement where Android
      permissions permit.

### Information assistant features
- [ ] **Weather station integration** — local sensors plus online forecast,
      rain/storm/lightning alerts and spoken severe-weather warnings.
- [ ] **Commute/travel status** — optional traffic/transit/travel-time queries
      from configured locations.
- [ ] **Package/delivery tracking** — optional carrier integrations with
      arrival/status notifications.
- [ ] **RSS/news briefing** — configurable feeds for a `morning briefing`
      instead of relying on one proprietary news service.
- [ ] **House status briefing** — `Neko, how is the house?` summarises important
      sensors, temperatures, batteries, offline devices and alerts.

### Safety, privacy & reliability
- [ ] **Local emergency alerts** — smoke/CO/water-leak/security sensor events can
      interrupt normal TTS and broadcast a high-priority warning.
- [ ] **Permission levels per user/device** — restrict sensitive smart-home
      commands such as locks, garage doors or security controls.
- [ ] **Confirmation for sensitive actions** — require explicit confirmation for
      unlocking/opening/disarming or similarly consequential commands.
- [ ] **Local-first credentials vault** — keep integration tokens/passwords out
      of chat logs and the repository, with secrets supplied through protected
      configuration.
- [ ] **Integration health dashboard** — show connected/degraded/offline state,
      last successful poll, latency and reconnect controls for every service.
- [ ] **Graceful offline mode** — local timers, routines, Matter/MQTT control,
      cached device names and basic voice commands continue if Internet access
      disappears.

## 🔜 Deferred (heavier ML deps / bigger lift / opt-in)

### VRChat (from the NekoSuneAI reference implementation)
- [ ] **A* dead-reckoning navigation** — estimate position/heading from received
      Velocity, occupancy grid + pathfinding, "go to X", frontier exploration,
      per-world persisted maps. (`nav/navigator.py`, `world.py`, `locomotion.py`)
- [ ] **YOLO/ONNX screen object detection** — `person` detection with
      angle/closeness, feed obstacles into the nav grid. Heavy (onnxruntime +
      model); make opt-in. (`vision/system.py`)
- [ ] **RapidOCR nameplate reading** — read on-screen player nameplates to greet
      people by name.

### Media
- [ ] **YouTube search + download for music** — in-app yt-dlp-backed search/
      download/stream path.

### Broader Neuro-sama parity
- [ ] **Voice-per-language profiles** — beyond language code, pick a distinct
      cloned voice per language.
