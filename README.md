<div align="center">
  <img src="data/logo.png" alt="NekoSuneAI" width="180">
</div>

# NekoSuneAI

### *Your brutally honest AI companion that actually talks back.*

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-violet)](VERSION)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-0078D6?logo=windows&logoColor=white)](https://microsoft.com)

NekoSuneAI is a voice-powered desktop companion built with Python. It listens through your mic, thinks with local or cloud LLMs, and speaks back with a cloned voice — all wrapped in a slick dark-themed UI.

Think Alexa, but with *attitude* and zero cloud lock-in. 🔥

---

## ✨ Features at a Glance

| | Feature | Details |
|---|---------|---------|
| 🧠 | **LLM Chat** | Ollama, OpenAI, OpenRouter, LM Studio, or the Claude/Codex CLI — your pick |
| 🎙️ | **Voice Input** | Local `faster-whisper` STT — no audio leaves your machine |
| 🔊 | **Voice Output** | XTTS-v2 streamed synthesis with cloned voices (or Google TTS lite) |
| 🧬 | **Memory / Learning** | RAG long-term memory — remembers facts across sessions and gets better |
| 🎮 | **VRChat Integration** | Plays/hangs out in VRChat via the official OSC API — walk, look, chat, emote, greet people by name |
| 🖼️ | **Image Review** | Show NekoSuneAI an image — it looks, reads any text, and reacts in-character (great for art, memes, or a pic of itself) |
| 👁️ | **Watch & React** | NekoSuneAI periodically glances at your screen (game/video) and reacts live in-character |
| 🌐 | **Per-language Voice** | Auto-detects each reply's language and speaks it in that language (Japanese line → Japanese voice, etc.) |
| 🎤 | **Singing** | Sings songs in its own voice over an auto-found YouTube instrumental |
| 🌐 | **Web Search** | Manual or auto-triggered lookups via SearXNG / DuckDuckGo |
| 🎵 | **Music & Radio** | SoundCloud search, internet radio, in-app playback |
| 👤 | **Profiles** | Multiple companion personalities — create, clone, switch, import/export, delete |
| ⚡ | **Auto-Tune** | Detects your hardware, adjusts models and GPU usage |
| 🔄 | **Self-Update** | Checks GitHub for new versions on startup |
| 🗄️ | **SQLite Storage** | Everything in one clean database — no scattered JSON |

---

## 🚀 Quick Start

### ⚡ One-Line Install (fresh machine)

**Windows** — open PowerShell and paste:

```powershell
powershell -c "irm https://raw.githubusercontent.com/NekoSuneProjects/NekoSuneAI/main/install.ps1 | iex"
```

**Linux** — open a terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/NekoSuneProjects/NekoSuneAI/main/install.sh | bash
```

> Both installers handle **everything** — Python, LLM provider choice (Ollama, OpenAI, OpenRouter, LM Studio, or any custom endpoint), model downloads, NVIDIA GPU setup, and a desktop shortcut/launcher — the works. Just answer a few questions and sit back.

### 🔧 Already have the repo?

```bash
python setup.py          # or python3 on Linux
```

First run does the full setup, then launches the desktop GUI (or terminal mode on a
headless machine). Subsequent runs skip straight to launch.

### 📋 All commands

```bash
python setup.py              # Setup (if needed) + launch (GUI, or terminal if headless)
python setup.py --launch     # 🖥️ Launch desktop GUI
python setup.py --terminal   # ⌨️ Terminal mode
python setup.py --setup      # 🔧 Re-run setup only
python setup.py --update     # 🔄 Check for updates

python app.py --gui          # 🖥️ Same desktop GUI, started directly
python app.py                # ⌨️ Terminal mode, started directly
```

---

## 🖥️ The Desktop GUI

NekoSuneAI runs as a native desktop window powered by **pywebview + Tailwind CSS** — a proper web-rendered UI that looks and feels modern, not some grey widget nightmare.

| Page | What It Does |
|------|-------------|
| 📊 **Dashboard** | Session controls, toggle voice/mic/hands-free/media (all persist across restarts), live status |
| 💬 **Chat** | Full conversation view with text + voice input |
| 🎮 **Game** | Configure the VRChat OSC connection, set a goal, watch it play |
| 🎤 **Sing** | Type a song, attach/auto-find a backing track, replay saved songs |
| 👤 **Profiles** | Create, clone, switch, delete, or import/export personalities |
| ⚙️ **Settings** | Audio devices, web search, LLM/TTS/STT config |

> 💡 **Pro tip:** Voice replies, hands-free mode, and mic mute can all be toggled *before* starting a session. Configure everything first, then hit Start.

---

## 🧬 Beyond Chat

NekoSuneAI can do far more than chat — it remembers, plays VRChat, watches your screen, and sings. Everything below is **local-first** and tuned to run on a modest 6–8GB GPU (with cloud/CLI fallbacks where it matters).

### 🧬 Memory / Learning (RAG)

NekoSuneAI **remembers across sessions** using retrieval-augmented memory — not fine-tuning. Tell it a fact today, ask for it next week, and it recalls it.

- Local **sentence-transformers** embeddings on CPU by default (keeps VRAM free for the LLM); Ollama or OpenAI embedding backends optional
- Stored in the same SQLite DB; thumbs-up/down reinforces or de-weights memories, and stale/low-score ones are pruned automatically
- Configure with `RAG_ENABLED`, `RAG_EMBEDDING_PROVIDER`, `RAG_EMBEDDING_MODEL`, `RAG_TOP_K`

### 🎮 VRChat Integration

NekoSuneAI can join you in **VRChat** via the official **OSC API** (EAC-safe — no risky web API, no GPU-hungry vision needed) and narrate its thoughts aloud as it goes.

- Walk/strafe/run/turn/look, jump, use the chatbox (with typing indicator), and trigger avatar emotes
- **Receives** avatar params (Velocity/Grounded) to notice walls + ledges
- Reads VRChat's own logs for the current world and **who's in the instance** — greets people by name
- Configure the OSC host/ports and log directory in the **Game** panel or via `.env` (`VRCHAT_OSC_HOST`, `VRCHAT_OSC_PORT`, `VRCHAT_OSC_READ_PORT`, `VRCHAT_LOG_DIR`)

### 🖼️ Image Review — NekoSuneAI looks and reacts

Show NekoSuneAI an image and it actually **sees** it: open the **Chat** tab, click 🖼️, pick an image, and (optionally) ask a question. NekoSuneAI describes what's there, **reads any text** in it, and gives an in-character opinion in chat + voice — react to art, memes, screenshots, or a picture of itself. Uses a local **Ollama vision model** (set a Vision model in Settings, e.g. `llava` / `qwen2.5vl` / `moondream`) or an **OpenAI-compatible multimodal** chat model.

### 👁️ Watch & React

NekoSuneAI can periodically glance at your screen (whatever game/video/app is open) and react live, in one short in-character line, using the same vision model as Image Review. Tune the glance interval and whether it speaks aloud from the panel.

### 🎤 Singing

NekoSuneAI sings songs in its **own cloned voice**, on the beat, over a real instrumental.

- Type `Artist - Title` → it fetches **timed lyrics** (LRCLIB) and performs them
- Backing track is optional: attach a **file**, paste a **YouTube URL**, or leave it blank to **auto-find an instrumental** on YouTube
- **Vocals + backing are merged into one audio file**, saved in `audio/songs/` for instant replay
- Works with **XTTS** (timed, on-beat) or **gTTS**. Needs `pip install yt-dlp imageio-ffmpeg` for the YouTube/merge features

---

## ⌨️ Terminal Commands

For the keyboard warriors out there:

<details>
<summary>📖 Click to expand full command list</summary>

### 🗣️ Voice & Input

| Command | What It Does |
|---------|-------------|
| `/mode voice` | Hands-free mic input |
| `/mode text` | Switch back to typing |
| `/listen` or `/ask` | Capture one spoken turn |
| `/voice` | Toggle spoken replies on/off |
| `/recalibrate` | Re-tune mic noise gate |
| `/mics` | List available microphones |
| `/mic <index>` | Choose a specific mic |
| `/mic default` | Reset to system default |
| `/speakers` | List XTTS voices |
| `/speaker <name>` | Switch XTTS voice |
| `/tts` | Show current TTS provider |
| `/tts xtts` / `/tts gtts` | Switch TTS engine |

### 🌐 Web Search

| Command | What It Does |
|---------|-------------|
| `/web` | Show web search status |
| `/web on` / `/web off` | Enable/disable web search |
| `/web auto on` / `/web auto off` | Toggle auto-search for current events |
| `/web clear` | Clear queued web context |
| `/web <query>` | Search and feed results to next reply |

### 🎵 Media

| Command | What It Does |
|---------|-------------|
| `/play <query>` | Play a radio station or search music |
| `/radio <station>` | Tune into a known station |
| `/music <query>` | Search your default music platform |
| `/pause` / `/resume` / `/stop` | Playback controls |

### 👤 Profiles & History

| Command | What It Does |
|---------|-------------|
| `/profile` | Show current profile |
| `/profiles` | List all profiles |
| `/profile use <id>` | Switch profiles |
| `/name <new name>` | Rename the companion |
| `/me <name>` | Set your name |
| `/remember <fact>` | Store a memory note |
| `/reset` | Clear conversation history |
| `/performance` | Show hardware and tuning info |
| `/exit` | Quit |

</details>

> 🗣️ **Natural language works too!** Say *"play Capital FM"* or *"search the web for..."* — NekoSuneAI handles it without a slash command.

---

## 🎭 Profiles — Make It Yours

Each companion profile is deeply customisable. Go wild:

| Section | What You Can Tweak |
|---------|-------------------|
| 🏷️ **Identity** | Name, pronouns, role, relationship style |
| 💬 **Conversation** | Reply length, pacing, verbosity, formatting |
| 🎚️ **Personality Sliders** | Warmth, sass, directness, patience, playfulness, formality |
| 🚧 **Boundaries** | Roast intensity, avoided topics, safety overrides |
| 🧠 **Memory** | Likes, dislikes, personal facts, inside jokes, projects |
| 🔊 **Voice** | Speech style, delivery notes, persona keywords |
| 📜 **Custom Rules** | Hard must-follow rules and soft preferences |

Want a sarcastic best friend? A patient tutor? A no-nonsense project manager? Just create a new profile and dial the sliders. 🎛️

### 📤 Import / Export

Move a profile between machines (e.g. your **PC → Raspberry Pi**) from the **Profiles** page:

- **Export** — click **Export** on any profile to download a `*.nova-profile.json` file (saved to the device you're browsing from).
- **Import** — click **Import**, pick a `*.nova-profile.json` file, and it's added as a **new** profile (importing never overwrites an existing one).
- **Delete** — remove any non-active profile with **Delete** (you always keep at least one).

> 💡 The export file carries the whole profile — identity, sliders, memory notes, voice, and all feature data — so the imported copy behaves exactly like the original.

---

## 🗄️ Data Storage

All runtime data lives in a single **SQLite database** at `data/nekosuneai.db`:

- 💬 Chat history
- 👤 Profiles and all their feature data
- ⚙️ App state (active profile, settings)

Rendered songs live on disk in `audio/songs/` for instant replay.

> 📦 On first run, existing JSON files (`profiles.json`, `history.jsonl`) are **automatically migrated** into the database. No manual steps needed.

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and tweak what you need:

<details>
<summary>📖 Click to expand full configuration reference</summary>

### 🧠 Core

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_TUNE_PERFORMANCE` | `true` | Auto-detect hardware and tune settings |
| `AUTO_TUNE_GOAL` | `balanced` | Tuning goal: `speed`, `balanced`, or `quality` |
| `AUTO_UPDATE_CHECK` | `true` | Check GitHub for updates on startup |
| `AUTO_UPDATE_INSTALL` | `true` | Auto-install updates for non-git installs |

### 🤖 LLM

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Chat backend: `ollama`, `openai`, or `claude-code` / `codex` / `cli` (shell out to an already-logged-in Claude Code / Codex CLI — no API key) |
| `LLM_MODEL` / `OLLAMA_MODEL` | `dolphin3` | Which model to use |
| `LLM_API_URL` | *(auto)* | Chat endpoint URL — set automatically by the installer for your chosen provider |
| `LLM_API_KEY` | *(none)* | API key for cloud providers (OpenAI, OpenRouter, etc.) |
| `OLLAMA_SKIP_LOCAL_SETUP` | `false` | Set `true` when using an existing Ollama server endpoint instead of local install/start |
| `LLM_NUM_PREDICT` | `1200` | Reply token budget |
| `OLLAMA_NUM_CTX` | `0` | Context window sent to Ollama (`0` = Ollama default). Cap it (e.g. `4096`) so long-context models load on small GPUs |
| `LLM_TEMPERATURE` | `0.95` | Response creativity |

### 🌐 Web Search

| Setting | Default | Description |
|---------|---------|-------------|
| `WEB_BROWSING_ENABLED` | `true` | Enable web search features |
| `WEB_AUTO_SEARCH` | `false` | Auto-search for current-event questions |
| `WEB_SEARCH_PROVIDER` | `searxng` | Backend: `searxng` or `duckduckgo` |
| `WEB_SEARCH_URL` | *(built-in)* | SearXNG endpoint URL |
| `WEB_MAX_RESULTS` | `5` | Results per lookup |
| `WEB_SAFESEARCH` | `moderate` | Safe search: `off`, `moderate`, `strict` |

### 🎵 Media

| Setting | Default | Description |
|---------|---------|-------------|
| `MEDIA_REGION` | `GB` | Radio region (`GB`, `US`, `AU`, `CA`, etc.) |
| `MUSIC_PROVIDER_DEFAULT` | `soundcloud` | Default music platform |

### 🔊 Voice & TTS

| Setting | Default | Description |
|---------|---------|-------------|
| `VOICE_ENABLED` | `false` | Start with voice replies on |
| `TTS_PROVIDER` | `xtts` | Voice engine: `xtts` or `gtts` |
| `XTTS_SPEED` | `1.0` | Speaking pace multiplier |
| `XTTS_USE_GPU` | `true` | Use GPU for voice synthesis |
| `XTTS_STREAM_OUTPUT` | `true` | Stream audio while generating |
| `XTTS_SPEAKER` | `Ana Florence` | XTTS voice name |

### 🎙️ Speech-to-Text

| Setting | Default | Description |
|---------|---------|-------------|
| `STT_PROVIDER` | `faster-whisper` | STT engine |
| `STT_MODEL` | `small.en` | Whisper model size |
| `STT_USE_GPU` | `true` | Use GPU for transcription |
| `INPUT_MODE` | `voice` | Default input: `voice` or `text` |

### 🔈 Audio Devices

| Setting | Default | Description |
|---------|---------|-------------|
| `MIC_DEVICE_INDEX` | *(auto)* | Pin a specific microphone |
| `SPEAKER_DEVICE_INDEX` | *(auto)* | Pin a specific speaker |

### 🧬 RAG Memory

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_ENABLED` | `true` | Remember facts across sessions |
| `RAG_EMBEDDING_PROVIDER` | `local` | `local` (CPU MiniLM), `ollama`, or `openai` |
| `RAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model id |
| `RAG_TOP_K` | `4` | How many memories to recall per reply |

### 🎮 Game Playing

| Setting | Default | Description |
|---------|---------|-------------|
| `GAME_ENABLED` | `false` | Enable the game agent |
| `GAME_TICK_SECONDS` | `4` | Seconds between observe/act ticks |
| `VISION_MODEL` | *(none)* | Optional multimodal model for Image Review / Watch & React (not required for VRChat OSC play) |
| `VRCHAT_OSC_HOST` | `127.0.0.1` | VRChat OSC host |
| `VRCHAT_OSC_PORT` | `9000` | VRChat OSC send port |
| `VRCHAT_OSC_READ_PORT` | `9001` | VRChat OSC receive port (avatar params) |
| `VRCHAT_LOG_DIR` | *(auto)* | Folder containing VRChat's output logs (auto-detected if blank) |

### 🎤 Singing

| Setting | Default | Description |
|---------|---------|-------------|
| `SINGING_ENABLED` | `true` | Enable singing |
| `SINGING_BACKEND` | `local` | `local` (XTTS/gTTS), `rvc`, or `cloud` |
| `SINGING_FETCH_INSTRUMENTAL` | `true` | Auto-find a YouTube instrumental when no backing is given |

</details>

---

## 📁 Project Layout

```
NekoSuneAI/
├── app.py                    # 🚪 Entry point
├── setup.py                  # 🔧 Setup, launch, and update — all in one
├── install.ps1               # ⚡ One-line PowerShell installer (Windows)
├── install.sh                # 🐧 One-line bash installer (Linux)
├── requirements.txt          # 📦 Python dependencies (base)
├── requirements-voice.txt    # 🎙️ Optional: mic/STT/TTS/embeddings
├── requirements-gui.txt      # 🖥️ Optional: native pywebview desktop window
├── VERSION                   # 🏷️ Current version
├── .env.example              # ⚙️ Configuration template
│
├── data/
│   ├── logo.png              # 🎨 NekoSuneAI logo
│   ├── logo.ico              # 🎨 Window icon
│   ├── nekosuneai.db         # 🗄️ SQLite database (runtime)
│   └── profile.example.json  # 📝 Example profile
│
└── nekosuneai/
    ├── launcher.py           # 🚪 CLI vs GUI routing + auto-update
    ├── webgui.py             # 🖥️ Backend API for the desktop GUI
    ├── cli.py                # ⌨️ Terminal chat loop + commands
    ├── chat.py               # 🧠 System prompt + LLM requests
    ├── engine.py             # 🧩 Shared reply seam + emotion detection
    ├── memory.py             # 🧬 RAG long-term memory store
    ├── singing.py            # 🎤 Singing engine (XTTS/gTTS + backing merge)
    ├── games/                # 🎮 Game agent + VRChat OSC driver
    ├── vision.py             # 🖼️ Image understanding (look at / read an image, Watch & React)
    ├── config.py             # ⚙️ Environment parsing + runtime config
    ├── database.py           # 🗄️ SQLite schema + CRUD operations
    ├── storage.py            # 💾 Profile/history API (SQLite-backed)
    ├── audio_input.py        # 🎙️ Mic capture + faster-whisper STT
    ├── tts.py                # 🔊 XTTS-v2 / gTTS synthesis + playback
    ├── media.py              # 🎵 Radio + music platform integration
    ├── media_player.py       # ▶️ In-app audio playback (ffplay)
    ├── performance.py        # ⚡ Hardware detection + auto-tuning
    ├── updater.py            # 🔄 GitHub version check + self-update
    ├── web_search.py         # 🌐 SearXNG / DuckDuckGo search
    ├── defaults.py           # 📋 Default profile template
    ├── models.py             # 📦 Shared dataclasses
    ├── paths.py              # 📍 Path constants
    └── static/
        └── index.html        # 🎨 Tailwind CSS frontend (dashboard, GUI-only)
```

---

## 📚 Documentation

<details>
<summary>🧠 How the Chat Pipeline Works</summary>

When you send a message (text or voice), NekoSuneAI runs through this pipeline:

1. **Media check** — is it a play/radio/music request? Handle it directly.
2. **Web search** — if enabled, check for explicit `/web` queries, inferred lookups (*"what's the weather?"*), or auto-search triggers.
3. **Memory recall** — if RAG is enabled, retrieve relevant long-term memories and inject them as context.
4. **LLM request** — build a system prompt from the active profile, attach conversation history, web context, and recalled memories, send to the LLM.
5. **Voice output** — if voice is enabled, synthesise the reply with XTTS-v2 or gTTS and play it back.
6. **Remember** — store the exchange back into RAG memory for future recall.
7. **Hands-free loop** — if hands-free mode is on, immediately start listening for the next turn.

A shared generation seam (`engine.py`) means the VRChat game agent reuses this exact pipeline. The whole thing runs in a background thread so the UI stays responsive.

</details>

<details>
<summary>🎙️ Voice & Audio Architecture</summary>

### Speech-to-Text (STT)
- Engine: `faster-whisper` (local) or Google Web Speech API
- Mic capture via `SpeechRecognition` library
- Automatic noise calibration on first listen
- Configurable silence detection, energy threshold, and VAD

### Text-to-Speech (TTS)
- **XTTS-v2** (default): local neural TTS with voice cloning, GPU-accelerated, streamed output
- **gTTS** (fallback): Google's cloud TTS — lightweight but needs internet
- Audio saved to `audio/latest_reply.wav` (XTTS) or `.mp3` (gTTS)
- Playback via `sounddevice` with configurable output device

### Audio Devices
- Mic and speaker can be pinned via `.env` or the Settings page
- `/mics` and `/speakers` commands list available devices with indices
- Recalibration re-tunes the noise gate without restarting

</details>

<details>
<summary>🗄️ Database Schema</summary>

NekoSuneAI uses SQLite (`data/nekosuneai.db`) with three tables:

**`profiles`** — one row per companion profile
```sql
profile_id   TEXT PRIMARY KEY   -- e.g. "default", "snarky-bot"
profile_name TEXT               -- display name
data         TEXT               -- full profile JSON blob
created_at   TEXT               -- ISO timestamp
updated_at   TEXT               -- ISO timestamp
```

**`history`** — one row per chat message
```sql
id        INTEGER PRIMARY KEY AUTOINCREMENT
timestamp TEXT                -- ISO timestamp
role      TEXT                -- "user", "assistant", or "system"
content   TEXT                -- message text
```

**`app_state`** — key/value settings store
```sql
key   TEXT PRIMARY KEY        -- e.g. "active_profile_id"
value TEXT                    -- the value
```

Feature data lives inside the profile JSON blob under `profile_details`, so it's saved/loaded with the profile automatically.

</details>

<details>
<summary>⚡ Performance Auto-Tuning</summary>

When `AUTO_TUNE_PERFORMANCE=true`, NekoSuneAI detects your hardware at startup and picks a performance profile:

| What It Checks | What It Adjusts |
|----------------|----------------|
| CPU core count | Request timeouts |
| Available RAM | Token budget |
| CUDA GPU presence | TTS/STT GPU acceleration |
| VRAM amount | Whisper model size, XTTS streaming settings |

**Tuning goals:**
- `speed` — smaller models, aggressive timeouts, prioritise response time
- `balanced` — sensible defaults for most hardware
- `quality` — larger models, longer timeouts, prioritise output quality

> ⚠️ Auto-tune **never** changes `XTTS_SPEED`, so your companion's voice pace stays consistent across machines.

</details>

<details>
<summary>🔄 Auto-Update System</summary>

NekoSuneAI can check for and install updates from GitHub:

1. On startup, compares local `VERSION` to the remote `VERSION` on your configured branch
2. If a newer version exists and `AUTO_UPDATE_INSTALL=true`, downloads and applies the update
3. Restarts itself with the new code

**Safety guards:**
- Git checkouts with local edits are **never** auto-updated
- Update results are cached for `AUTO_UPDATE_CACHE_SECONDS` (default: 6 hours) to avoid hammering GitHub
- Manual updates always available via `python setup.py --update`

</details>

<details>
<summary>🎵 Media & Radio</summary>

NekoSuneAI intercepts natural media requests:

- *"play Capital FM"* → finds and streams the radio station
- *"play synthwave on SoundCloud"* → searches and plays a track
- *"pause"* / *"resume"* / *"stop"* → controls the current stream

**Supported radio regions:** UK, US, Australia, Canada, Germany, Japan (with fallback to internet-radio.com search)

**Music platforms:** SoundCloud (default), with Spotify and Deezer as search options

In-app playback uses `ffplay` for radio streams and resolved audio URLs.

</details>

---

## 💡 Good to Know

- 📥 **First run downloads models** — XTTS-v2 and faster-whisper grab model files on first use. `python setup.py` preloads them so you're not waiting forever.
- 🔇 **Mic mute is app-level** — it stops NekoSuneAI from listening. It doesn't touch your Windows system mic.
- 🔒 **Git-safe updates** — if NekoSuneAI detects a git checkout with local edits, self-update is skipped to protect your work.
- 💾 **Audio is always saved** — voice replies land in `audio/latest_reply.wav` even if playback fails. Useful for debugging.
- 🌍 **Works offline** — with Ollama and XTTS, the entire pipeline runs locally. Web search is optional.

---

## 🤝 Contributing

The codebase is modular by design — pick an area and dive in:

| Area | File(s) | Difficulty |
|------|---------|-----------|
| 🎙️ Voice / mic issues | `nekosuneai/audio_input.py` | Medium |
| 🧠 Personality / responses | `nekosuneai/chat.py` | Easy |
| 🔊 TTS / playback | `nekosuneai/tts.py` | Medium |
| ⌨️ Commands / app flow | `nekosuneai/cli.py` | Easy |
| 🎨 GUI frontend | `nekosuneai/static/index.html` | Easy |
| 🖥️ GUI backend | `nekosuneai/webgui.py` | Medium |
| 🗄️ Data / profiles | `nekosuneai/storage.py` + `nekosuneai/database.py` | Medium |
| 🌐 Web search | `nekosuneai/web_search.py` | Medium |
| 🎵 Media / radio | `nekosuneai/media.py` | Medium |
| 🧬 RAG memory | `nekosuneai/memory.py` | Medium |
| 🖼️ Vision (image review / watch & react) | `nekosuneai/vision.py` | Medium |
| 🎮 Game agent / VRChat driver | `nekosuneai/games/` | Hard |
| 🎤 Singing | `nekosuneai/singing.py` | Medium |

PRs welcome! If you're not sure where to start, open an issue and we'll point you in the right direction. 🫡

---

## 🐧 Linux & Raspberry Pi Support

> NekoSuneAI runs on **Windows**, **amd64 Linux**, and **ARM64 / Raspberry Pi 5**.

### Run modes & install profiles

`install.sh` / `install.ps1` ask **how you want to run NekoSuneAI** and install the
right dependency set for it:

| Run mode | Installs | Good for |
|---|---|---|
| **CLI** | `requirements.txt` + `requirements-voice.txt` | Terminal chat loop, works great headless (Pi / server). |
| **GUI** | the above **+ `requirements-gui.txt`** | The native desktop window (needs a display). |

Prefer to pick the raw dependency set yourself? Use `NOVA_INSTALL_PROFILE`
(`minimal` / `voice` / `gui` / `full`) with `setup.py --setup`, or install manually:

```bash
pip install -r requirements.txt                            # minimal (text-only CLI)
pip install -r requirements.txt -r requirements-voice.txt  # add voice/ML
pip install -r requirements.txt -r requirements-gui.txt    # add the desktop GUI
```

> The desktop GUI's CEF backend is Windows-only; on Linux/ARM `requirements-gui.txt`
> uses your system WebView instead (`gir1.2-webkit2-4.1` on Debian/Ubuntu).

### 🍓 Raspberry Pi 5 / headless quick-start

A Pi (or any server) usually has no monitor, mic, or speakers — so run in
**CLI/terminal mode**:

```bash
git clone https://github.com/NekoSuneProjects/NekoSuneAI && cd NekoSuneAI
python3 setup.py --setup        # choose the "CLI" run mode when asked
sudo apt install ffmpeg         # optional, for audio playback later
python3 app.py                  # terminal chat, works headless over SSH
```

- On a box with no audio hardware, keep `VOICE_ENABLED=false` (the default) and set
  `INPUT_MODE=text` in `.env` so terminal mode never reaches for a microphone.
- Voice can be added later — `pip install -r requirements-voice.txt` — once you attach
  a mic/speakers. XTTS runs on CPU there, so expect it to be slow.

### ✅ Done

- [x] **Minimal install runs without torch/coqui/PortAudio** — voice/ML imports are lazy
- [x] **ARM64 / Raspberry Pi 5** — `pip install` no longer pulls Windows-only `cefpython3`
- [x] **`install.sh`** — arch/distro-aware system deps, install-profile prompt, headless detection
- [x] **`nekosuneai/tts.py`** — Linux audio playback via ffplay, ALSA/PulseAudio/PipeWire/JACK support

### 🗺️ Roadmap

- [ ] systemd service / auto-start on boot
- [ ] Test on more distros (Fedora, Arch, NixOS)
- [ ] macOS support

---

## 📄 License

NekoSuneAI is open-source software licensed under the [GNU General Public
License v3.0](LICENSE). You may use, study, fork, and modify it. If you
distribute a modified version, you must provide the corresponding source under
the same license and preserve the required legal notices.

The license does not permit anyone to claim authorship of code they did not
write or present an unofficial fork as an official NekoSuneAI release. See
[NOTICE](NOTICE) for upstream attribution and [TRADEMARKS.md](TRADEMARKS.md)
for the branding policy.

Open-source licenses cannot restrict fields of use. NekoSuneProjects does not
endorse unlawful, harmful, or abusive uses of this software; all users remain
responsible for complying with applicable law.

---

<div align="center">

Built with spite, sarcasm, and way too much caffeine ☕ by [NekoSuneProjects](https://github.com/NekoSuneProjects)

**If NekoSuneAI roasts you, that's a feature, not a bug.** 😏

</div>
