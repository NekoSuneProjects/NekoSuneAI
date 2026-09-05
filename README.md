<div align="center">
  <img src="data/logo.png" alt="NekoSuneAI" width="180">
</div>

# NekoSuneAI

Branch ownership: **Docker** on `main`. See the
[branch map](BRANCH_MAP.md) and this product's [TODO](TODO.md) before making
changes. Native app branches remain separate from the Docker backend on main.

### *A local-first AI companion that talks, remembers, learns, watches, listens, plays music, and can follow you onto Android.*

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.2.1-violet)](VERSION)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20ARM64%20%7C%20Android-0078D6)](https://github.com/NekoSuneProjects/NekoSuneAI)

NekoSuneAI is a voice-powered AI companion built with Python. It can run on a desktop, a headless Linux server, or a Raspberry Pi, connect to an Android companion app, use local or cloud LLMs, speak with TTS, remember conversations, learn owner preferences, play music, monitor things, interact with VRChat, use camera/Kinect context, and present itself through a VRM avatar.

The project is **local-first**: Ollama, local STT, local embeddings, lightweight local affect detection, SQLite storage, and Pi-hosted services can all be used without cloud lock-in. Cloud/CLI providers remain optional fallbacks where useful.

---

## ✨ Features at a Glance

| | Feature | Details |
|---|---|---|
| 🧠 | **LLM Chat** | Ollama, OpenAI-compatible APIs, OpenRouter, LM Studio, Claude/Codex CLI and custom endpoints |
| 🎙️ | **Voice Input** | Local `faster-whisper`, Vosk, Google or bridge STT |
| 🔊 | **Voice Output** | XTTS-v2 streamed synthesis with cloned voices or lightweight gTTS fallback |
| 🧬 | **RAG Memory** | Long-term memory across sessions with local MiniLM, Ollama or OpenAI-compatible embeddings |
| 👤 | **Owner Learning** | Starts blank and gradually learns explicit likes, dislikes, hobbies, favourites and comfort activities |
| 💗 | **Companion Mood** | Persistent simulated valence/arousal/trust/caution state drives avatar presentation and response style |
| 🎧 | **Voice-Tone Cues** | Lightweight acoustic cues such as quiet/subdued or energetic/animated, treated as uncertain context only |
| 👁️ | **Camera / Vision** | Android camera, screen vision and Kinect/external-camera support |
| 🪶 | **Low-power Pi Affect Fallback** | Optional FER+ ONNX + OpenCV fallback for visible facial-expression cues without a full VLM |
| 🤝 | **Gentle Check-ins** | Multiple consistent cues can trigger a cooldown-limited, non-diagnostic check-in |
| 🎵 | **YouTube Music** | `yt-dlp` + `ffplay`, playlists, pause/resume/skip/previous/volume controls |
| ⏰ | **Reminders / Timers / Alarms** | Persistent reminders, timers and alarms on the Pi |
| 📡 | **Scheduled Monitoring** | Run aircraft/weather/etc. monitors only inside selected time windows |
| 📱 | **Android Companion** | Remote chat/voice, telemetry, notification forwarding, Find My Phone, camera vision and shared VRM |
| 🌐 | **Mobile PWA** | Token-protected Pi mobile dashboard plus optional self-hosted ntfy alerts |
| 🧍 | **VRM Avatar** | Shared Pi/Android avatar, blinking, expressions, body gestures, visemes and speaking animation |
| 🎮 | **VRChat Integration** | Official OSC movement/chat/emotes plus optional world/screen vision |
| 👁️ | **Watch & React** | Periodically glances at your screen and reacts in-character |
| 🎤 | **Singing** | XTTS/gTTS vocals over timed lyrics and optional YouTube instrumental |
| 🌐 | **Web Search** | Manual or auto-triggered SearXNG / DuckDuckGo research |
| 👤 | **Profiles** | Create, clone, switch, import/export and delete companion profiles |
| ⚡ | **Auto-Tune** | Hardware detection and model/performance tuning |
| 🗄️ | **SQLite Storage** | Chat history, profiles, settings, long-term feature state and memories |

---

## 🚀 Quick Start

### One-line install

**Windows — PowerShell**

```powershell
powershell -c "irm https://raw.githubusercontent.com/NekoSuneProjects/NekoSuneAI/main/install.ps1 | iex"
```

**Linux / Raspberry Pi**

```bash
curl -fsSL https://raw.githubusercontent.com/NekoSuneProjects/NekoSuneAI/main/install.sh | bash
```

The installers can set up Python, dependencies, local/cloud provider choices, hardware-specific options and launchers.

### Existing checkout

```bash
python setup.py
```

Useful commands:

```bash
python setup.py --launch       # desktop GUI
python setup.py --terminal     # terminal mode
python setup.py --setup        # re-run setup
python setup.py --update       # check/apply updates

python app.py --gui            # desktop GUI directly
python app.py                  # terminal mode directly
python app.py --web --web-host 0.0.0.0 --web-port 8788
```

---

## 🍓 Raspberry Pi Smart-Speaker / Companion Mode

NekoSuneAI can run headless on a Raspberry Pi 5 and expose its authenticated web/mobile/Android companion service.

```bash
git clone https://github.com/NekoSuneProjects/NekoSuneAI
cd NekoSuneAI
python3 setup.py --setup
sudo apt install ffmpeg
python3 app.py --web --web-host 0.0.0.0 --web-port 8788
```

Set a permanent dashboard token in `.env`:

```env
WEB_DASHBOARD_TOKEN=replace-with-a-long-random-secret
```

Do **not** expose the raw dashboard port directly to the public Internet. Prefer **Tailscale/VPN**, authenticated HTTPS, or a protected reverse proxy/tunnel.

### Pi music controls

The Pi smart-speaker path uses `yt-dlp` to resolve YouTube audio and `ffplay` for playback. Songs are streamed rather than permanently downloaded.

```text
Neko, play Alan Walker Faded
Neko, pause the music
Neko, resume the music
Neko, next song
Neko, previous song
Neko, stop the music
Neko, music volume 60
Neko, turn the music up
Neko, what's playing?
```

Saved playlists are supported as well:

```text
Neko, create a playlist called Frenchcore
Neko, add Dr Peacock Trip to Valhalla to my Frenchcore playlist
Neko, play my Frenchcore playlist
```

### Reminders, timers and alarms

```text
Neko, remind me in 20 minutes to check the oven
Neko, remind me at 7 PM to feed the dog
Neko, set a timer for 10 minutes
Neko, set an alarm for 7 AM
Neko, wake me at 7 AM
```

### Scheduled monitors

```text
Neko, monitor aircraft 1 PM to 4 PM every Friday
Neko, track military aircraft from 13:00 to 16:00 every Friday
Neko, monitor weather from 8 AM to 10 PM every day
```

Outside the configured window, the scheduled monitor makes no API/MCP calls.

See [`docs/PI_MUSIC_AND_SCHEDULES.md`](docs/PI_MUSIC_AND_SCHEDULES.md).

---

## 📱 Android Companion

The native Android project lives under [`android/`](android/) and connects to a Pi-hosted NekoSuneAI instance.

Current features include:

- persistent low-power Pi connection using a foreground `connectedDevice` service
- telemetry heartbeat: battery, charging, thermal state, RAM and storage
- optional Android notification forwarding without requiring raw SMS permissions
- Find My Phone with full ringtone volume and remote STOP
- typed remote chat
- push-to-talk using Android speech recognition
- local Android TTS replies
- shared Pi-configured VRM avatar
- VRM emotion/gesture/viseme animation
- explicit foreground-only CameraX vision sharing
- Pi mood and vision context returned with chat responses

Natural phone commands include:

```text
Neko, find my phone
Neko, stop ringing my phone
Neko, what is my phone battery?
Neko, is my phone charging?
Neko, show my latest phone notifications
```

### Android build requirements

The current CameraX stack uses `1.6.1`, which requires Android API 36 / modern Android build tooling.

```text
Android Gradle Plugin: 8.9.1
compileSdk:            36
targetSdk:             35
minSdk:                26
Java:                  17
Gradle:                8.11.1
CameraX:               1.6.1
```

Build locally:

```bash
gradle -p android --no-daemon assembleDebug
```

The dedicated `build/android-apk` branch contains the APK workflow and explicitly installs Android SDK 36 / Build Tools 36.0.0 before building.

See [`docs/ANDROID_COMPANION.md`](docs/ANDROID_COMPANION.md) and [`docs/ANDROID_MOBILE.md`](docs/ANDROID_MOBILE.md).

---

## 🧬 Memory + Learned Owner Profile

NekoSuneAI has two complementary memory systems.

### RAG long-term memory

The existing RAG store remembers conversation-relevant facts and recalls them semantically later. Local sentence-transformer embeddings run on CPU by default, with Ollama/OpenAI-compatible embedding backends also supported. If embeddings are unavailable, recall degrades gracefully to recent-memory retrieval instead of hard-failing.

### Structured owner learning

The companion can also build a smaller structured owner profile from **explicit first-person statements**. It starts blank and learns categories such as:

- favourites
- likes
- dislikes
- hobbies
- comfort activities/music/topics

Repeated mentions increase confidence. Camera or voice-tone guesses do **not** silently create personal facts.

Examples:

```text
I love Frenchcore.
My favourite game is Star Citizen.
Making music cheers me up.
Going for a walk helps me relax.
This playlist always makes me feel better.
```

The profile can be inspected through the token-protected endpoint:

```text
GET /api/owner/profile
```

This lets NekoSuneAI use things that have genuinely helped before when the owner asks for support, rather than always giving generic suggestions.

---

## 💗 Multimodal Companion Context

NekoSuneAI can combine several **tentative signals** with the owner's actual words:

1. what the owner said;
2. optional recent camera/Kinect context;
3. optional visible facial-expression cue;
4. optional recent voice-tone cue;
5. learned owner preferences/comfort items;
6. long-term conversational memory.

The owner's words always take priority over camera/audio guesses.

### Persistent companion mood

`nekosuneai/mood_state.py` stores a bounded simulated affect state using valence, arousal, trust and caution. This can influence avatar expression, posture and voice presentation, then gradually returns toward a calm baseline.

This is a **software personality simulation**, not a claim that NekoSuneAI is sentient or has biological emotional needs. It must not guilt, threaten, pressure, or tell the owner they are responsible for the assistant's wellbeing.

### Voice-tone cues

The lightweight `nekosuneai/voice_tone.py` analyzer uses NumPy and short PCM16 WAV audio to estimate broad acoustic cues from energy, pitch, pitch variation and a rough speaking-rate/activity proxy.

Typical labels are deliberately cautious:

```text
quiet or subdued
slow or subdued
energetic or activated
expressive or animated
neutral/uncertain
```

These are not diagnoses and are never treated as proof of an internal emotional state.

Endpoints:

```text
POST /api/voice/tone
POST /api/android/voice-tone
```

See [`docs/VOICE_TONE_HOOK.md`](docs/VOICE_TONE_HOOK.md).

### Gentle support check-ins

While explicit camera sharing is active, several reasonably consistent negative-looking cues can trigger a single gentle check-in with a cooldown, for example:

```text
Hey Neko, you seem a little down or tense right now. Are you okay?
```

One bad camera frame should not cause repeated questioning. The user's own answer always overrides the camera/audio cue. If the owner asks for current ideas or resources, the normal web-search path can be used to research useful information.

---

## 👁️ Camera, Kinect and Lightweight Pi Vision

### Full vision path

When an Ollama/OpenAI-compatible vision model is configured, Android camera or external-camera frames can be understood as normal conversational scene context.

Endpoints:

```text
POST /api/android/vision
POST /api/vision/frame
```

Raw frames are not intentionally persisted by this feature; only short-lived textual context is retained for the current conversation window.

### Lightweight Raspberry Pi facial-affect fallback

When a full VLM is unavailable, NekoSuneAI can optionally use a tiny FER+ ONNX model through OpenCV. It only analyses a detected 64×64 grayscale face crop and therefore uses far less RAM/CPU than a general vision-language model.

Install:

```bash
pip install -r requirements-vision-lite.txt
python tools/setup_local_affect_model.py
```

Default model path:

```text
/app/data/models/emotion-ferplus-8.onnx
```

Override it with:

```env
LOCAL_AFFECT_MODEL=/app/data/models/your-ferplus-model.onnx
```

An INT8 FER+ ONNX model can be substituted for a smaller footprint.

### Kinect / external camera

Kinect v1/360 can use `libfreenect`; Kinect v2 can use `libfreenect2`. NekoSuneAI keeps these hardware drivers outside the base image and accepts refreshed JPEG/PNG frames through a small bridge:

```bash
python tools/kinect_vision_bridge.py \
  --server https://your-neko-host \
  --token "$WEB_DASHBOARD_TOKEN" \
  --frame /tmp/kinect.jpg \
  --interval 5
```

---

## 🧍 Shared VRM Avatar

Set a VRM model URL:

```env
VRM_AVATAR_URL=https://your-host/avatar.vrm
```

The same avatar can be used by the Pi dashboard and Android companion.

Current renderer capabilities:

- blinking
- idle breathing/head motion
- expressions: neutral, happy, sad, angry, excited, relaxed, scared
- body gestures/postures: wave, excited arms, guarded, slouch, emphatic, relaxed
- vowel visemes: `aa`, `ih`, `ou`, `ee`, `oh`
- speaking state events

Current lip sync is generated from the exact spoken text as a synchronized viseme estimate. The renderer/event protocol is designed so true TTS phoneme/viseme timestamps can replace the estimator later without rewriting the avatar UI.

Token-protected config endpoint:

```text
GET /api/avatar/config
```

---

## 🖥️ Desktop GUI

The desktop GUI uses **pywebview + Tailwind CSS**.

| Page | What It Does |
|---|---|
| 📊 **Dashboard** | Session controls, voice/mic/hands-free/media state and live companion status |
| 💬 **Chat** | Conversation view with text + voice input |
| 🎮 **Game** | VRChat OSC connection and agent controls |
| 🎤 **Sing** | Singing workflow and saved songs |
| 👤 **Profiles** | Create, clone, switch, delete and import/export personalities |
| ⚙️ **Settings** | LLM, TTS, STT, memory, web search, audio and feature configuration |

---

## 🎮 VRChat Integration

NekoSuneAI can use the official VRChat OSC API to move, look, jump, type into chatbox and trigger avatar parameters/emotes.

- walk/strafe/run/turn/look/jump
- chatbox with typing indicator and automatic paging
- receives avatar parameters such as velocity/grounded
- reads VRChat logs for world and instance/player context
- optional configured vision model for screen/world awareness
- configurable OSC host/ports and log path

A separate **opt-in unofficial friends API** integration also exists. Because automated use of VRChat's unofficial web API can conflict with VRChat terms/rules and create account risk, leave it disabled unless you understand that tradeoff.

---

## 👁️ Watch & React

NekoSuneAI can periodically inspect the current screen through the configured vision model and react in-character. The feature is optional and can be tuned or disabled independently.

---

## 🎤 Singing

NekoSuneAI can synthesize vocals in its configured voice over a backing track.

- timed lyrics through LRCLIB
- optional local backing file
- optional pasted YouTube URL
- optional auto-found YouTube instrumental
- XTTS or gTTS vocals
- merged songs saved under `audio/songs/`

---

## 🌐 Web Search

Web lookup can be explicit or automatically triggered for current information.

```text
/web
/web on
/web off
/web auto on
/web auto off
/web clear
/web <query>
```

Backends include SearXNG / DuckDuckGo depending on configuration.

---

## ⌨️ Useful Terminal Commands

<details>
<summary>Click to expand</summary>

### Voice / input

| Command | Action |
|---|---|
| `/mode voice` | Hands-free voice input |
| `/mode text` | Text input |
| `/listen` / `/ask` | Capture one spoken turn |
| `/voice` | Toggle spoken replies |
| `/recalibrate` | Re-calibrate mic noise gate |
| `/mics` | List microphones |
| `/mic <index>` | Select microphone |
| `/speakers` | List output devices/voices |
| `/tts` | Show TTS provider |

### Media

| Command | Action |
|---|---|
| `/play <query>` | Search/play media |
| `/music <query>` | Search preferred music source |
| `/pause` / `/resume` / `/stop` | Playback controls |

### Profiles / history

| Command | Action |
|---|---|
| `/profile` | Current profile |
| `/profiles` | List profiles |
| `/profile use <id>` | Switch profile |
| `/name <name>` | Rename companion |
| `/me <name>` | Set owner display name |
| `/reset` | Clear conversation state |
| `/performance` | Hardware/tuning information |
| `/exit` | Quit |

</details>

Natural language works for many of these actions too.

---

## 🎭 Profiles

Profiles can configure:

| Section | Examples |
|---|---|
| Identity | name, pronouns, role, relationship style |
| Conversation | response length, pacing, formatting |
| Personality | warmth, sass, directness, patience, playfulness, formality |
| Boundaries | avoided topics, roast intensity, custom constraints |
| Memory | likes, dislikes, facts, projects, inside jokes |
| Voice | delivery style and speaker settings |
| Rules | persistent hard/soft instructions |

Profiles can be exported/imported as `*.nekosuneai-profile.json` files and moved between PC/Pi installations.

---

## 🗄️ Data Storage

Primary runtime storage is SQLite at:

```text
data/nekosuneai.db
```

It stores chat history, profiles, app state, RAG memory and other persistent feature state. Some companion systems also use named app-state keys for playlists, reminders, schedules, owner learning and simulated mood.

Rendered songs remain under:

```text
audio/songs/
```

Legacy profile/history JSON files are migrated automatically on first run when applicable.

---

## ⚙️ Configuration Highlights

Most normal settings live in the GUI Settings/Game panels. `.env` is still used for startup, low-level tuning and headless/server features.

Useful companion/Pi settings include:

```env
WEB_DASHBOARD_TOKEN=replace-with-a-long-random-secret
VRM_AVATAR_URL=https://your-host/avatar.vrm
YOUTUBE_MUSIC_VOLUME=75

# Optional lightweight local face-expression fallback
LOCAL_AFFECT_MODEL=/app/data/models/emotion-ferplus-8.onnx

# Gentle camera-based check-ins
SUPPORT_CHECKINS_ENABLED=true
SUPPORT_CHECKIN_COOLDOWN_SECONDS=900
SUPPORT_AFFECT_MIN_CONFIDENCE=0.45

# Optional self-hosted ntfy push
MOBILE_NOTIFY_ENABLED=false
MOBILE_NOTIFY_URL=http://127.0.0.1:2586
MOBILE_NOTIFY_TOPIC=
MOBILE_NOTIFY_MIN_LEVEL=warning
# MOBILE_NOTIFY_TOKEN=
```

Core performance examples:

```env
AUTO_TUNE_PERFORMANCE=true
AUTO_TUNE_GOAL=balanced
AUTO_UPDATE_CHECK=true
AUTO_UPDATE_INSTALL=false
LLM_KEEP_ALIVE=30m
OLLAMA_NUM_PREDICT=1200
```

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) and `.env.example` for the complete configuration surface.

Peripheral nodes and local routines use capability-scoped commands rather than
arbitrary remote execution. See
[`docs/PERIPHERAL_NODES_AND_ROUTINES.md`](docs/PERIPHERAL_NODES_AND_ROUTINES.md)
for pairing, permissions, heartbeat, routine and API examples. The Studio's
**Nodes & Routines** button opens the authenticated visual manager.

Home Assistant and generic MQTT devices also appear in that manager with
rooms, aliases, battery and energy telemetry. See
[`docs/SMART_HOME_MQTT.md`](docs/SMART_HOME_MQTT.md) for local discovery and
command examples. Local presence sensors can drive room-aware routines and
one-shot reminders; routine triggers also support daily/weekday schedules and
locally calculated sunrise/sunset times.

Local smoke/CO/leak/security sensor transitions, retained home-event queries,
house status summaries and opt-in source-attributed RSS briefings are documented
in [`docs/SAFETY_AND_BRIEFINGS.md`](docs/SAFETY_AND_BRIEFINGS.md).

The paired Windows Gaming Agent provides selected-window vision, bounded local
game skills, OBS WebSocket supervision and isolated/rate-limited Twitch chat.
See [`docs/WINDOWS_GAMING_AND_TWITCH.md`](docs/WINDOWS_GAMING_AND_TWITCH.md).
Versioned skill packages, real-time local intents, reliability learning and
Xbox/PlayStation Remote Play templates are documented in
[`docs/GAME_SKILLS_AND_REMOTE_PLAY.md`](docs/GAME_SKILLS_AND_REMOTE_PLAY.md).

---

## 📁 Project Layout

```text
NekoSuneAI/
├── app.py
├── setup.py
├── install.ps1
├── install.sh
├── requirements.txt
├── requirements-voice.txt
├── requirements-gui.txt
├── requirements-vision-lite.txt
├── docker-compose.yml
├── docker-compose.mobile.yml
├── android/                         # native Android companion
├── tools/
│   ├── kinect_vision_bridge.py
│   └── setup_local_affect_model.py
├── docs/
│   ├── ANDROID_COMPANION.md
│   ├── ANDROID_MOBILE.md
│   ├── PERIPHERAL_NODES_AND_ROUTINES.md
│   ├── SMART_HOME_MQTT.md
│   ├── PI_MUSIC_AND_SCHEDULES.md
│   └── VOICE_TONE_HOOK.md
└── nekosuneai/
    ├── webserver.py                 # Pi/mobile/Android HTTP integration
    ├── webgui.py                    # desktop/web API
    ├── chat.py
    ├── engine.py
    ├── memory.py                    # RAG memory
    ├── owner_learning.py            # structured owner preferences
    ├── mood_state.py                # simulated companion affect state
    ├── voice_tone.py                # lightweight acoustic cues
    ├── local_affect.py              # FER+ local fallback
    ├── support_checkins.py
    ├── android_devices.py           # phone hub/commands/telemetry
    ├── mobile_notify.py             # ntfy-compatible alerts
    ├── youtube_music.py
    ├── reminders.py
    ├── routines.py                    # local routines, conflicts and undo
    ├── peripheral_nodes.py            # authenticated capability protocol
    ├── smart_home.py                   # HA/MQTT discovery, aliases and telemetry
    ├── scheduled_windows.py
    ├── avatar_motion.py
    ├── vision.py
    ├── audio_input.py
    ├── tts.py
    ├── singing.py
    ├── media.py
    ├── web_search.py
    ├── games/
    └── static/
        ├── index.html
        ├── mobile.html
        ├── mobile-sw.js
        ├── manifest.webmanifest
        └── vrm.html
```

---

## 🔐 Privacy and Security

NekoSuneAI includes camera, microphone, notification and personal-memory features, so deployment choices matter.

- Camera sharing from Android is explicit foreground-only.
- Notification access must be manually granted by the Android owner.
- Raw SMS, contacts, call logs and GPS are not silently enabled by the companion.
- Camera/voice affect cues are treated as uncertain observations, not diagnoses.
- Camera/audio guesses do not silently become owner-profile facts.
- Use `WEB_DASHBOARD_TOKEN` for every remote client.
- Prefer Tailscale/VPN or authenticated HTTPS for remote access.
- Do not publish the raw Pi dashboard port.
- Keep ntfy topics/tokens private if using push alerts.

---

## 🐧 Linux / ARM64 Notes

NekoSuneAI supports Windows, amd64 Linux and ARM64 / Raspberry Pi 5.

Manual install profiles:

```bash
pip install -r requirements.txt
pip install -r requirements.txt -r requirements-voice.txt
pip install -r requirements.txt -r requirements-gui.txt
```

The GUI uses the system WebView on Linux/ARM rather than Windows-only CEF. Headless systems can stay entirely CLI/web based.

Voice can be disabled on machines without audio hardware:

```env
VOICE_ENABLED=false
INPUT_MODE=text
```

---

## 🤝 Contributing

Useful areas include:

| Area | Files |
|---|---|
| Voice / microphone | `nekosuneai/audio_input.py`, `nekosuneai/voice_tone.py` |
| LLM/personality | `nekosuneai/chat.py`, `nekosuneai/engine.py` |
| TTS / avatar speech | `nekosuneai/tts.py`, `nekosuneai/avatar_motion.py` |
| Android companion | `android/`, `nekosuneai/android_devices.py` |
| Pi web integration | `nekosuneai/webserver.py` |
| Owner learning / memory | `nekosuneai/owner_learning.py`, `nekosuneai/memory.py` |
| Mood / support | `nekosuneai/mood_state.py`, `nekosuneai/support_checkins.py` |
| Vision | `nekosuneai/vision.py`, `nekosuneai/local_affect.py` |
| Music / reminders | `nekosuneai/youtube_music.py`, `nekosuneai/reminders.py` |
| VRM frontend | `nekosuneai/static/vrm.html`, Android avatar asset |
| VRChat | `nekosuneai/games/` |
| Singing | `nekosuneai/singing.py` |

Pull requests and issue reports are welcome.

---

## 💖 Support NekoSuneProjects

If NekoSuneAI is useful to you, contributions, bug reports, pull requests and project support are appreciated.

GitHub Sponsors: https://github.com/sponsors/NekoSuneProjects

Selected donation addresses retained from the project:

| Cryptocurrency | Donation Address |
|---|---|
| Ethereum / EVM | `0xAD41cD581FD06dB2589fd745BB179cA454a242ac` |
| Bitcoin | `38qeqyTxgakcsb8swbo4g8EnovUSX4DDNp` |
| Dogecoin | `DGVT15yeHJnSFsAy6zWx3m6grXsK7FV9kk` |
| Hive / HBD | `chisdealhd` |
| Steem / SBD | `chisdealhd` |
| Blurt | `chisdealhd` |
| ZBD / Bitcoin Lightning | `nekosunevr` |

Always verify the cryptocurrency and network before sending funds.

---

## 📄 License

NekoSuneAI is open-source software licensed under the [GNU General Public License v3.0](LICENSE). You may use, study, fork and modify it. If you distribute a modified version, you must provide the corresponding source under the same license and preserve required notices.

See [NOTICE](NOTICE) for upstream attribution and [TRADEMARKS.md](TRADEMARKS.md) for branding policy.

---

<div align="center">

Built with way too much caffeine ☕ by [NekoSuneProjects](https://github.com/NekoSuneProjects)

**NekoSuneAI — desktop companion, Pi smart speaker, Android companion, VRM avatar and local-first assistant in one project.**

</div>
