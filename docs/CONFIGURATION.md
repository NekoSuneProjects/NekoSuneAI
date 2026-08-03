# ⚙️ Configuration Reference

Most day-to-day settings (LLM provider/model/API key, voice, speech-to-text,
web search, memory, media, singing, RVC, VRChat friends, VRChat OSC) live in
the app's **Settings panel** now and are stored in SQLite — live-editable,
no restart needed, no `.env` required. This page only covers what's still
`.env`-only: startup/performance tuning, CLI-provider paths, and low-level
audio/model knobs with no Settings-UI equivalent yet. Copy `.env.example` to
`.env` and adjust as needed — the app boots fine with none of this set.

---

## 🧠 Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_TUNE_PERFORMANCE` | `true` | Auto-detect hardware and optimise settings on startup |
| `AUTO_TUNE_GOAL` | `balanced` | Tuning strategy: `speed`, `balanced`, or `quality` |
| `AUTO_UPDATE_CHECK` | `true` | Check GitHub for version updates on startup |
| `AUTO_UPDATE_INSTALL` | `false` | Automatically install updates on launch — see the security warning in `.env.example` before enabling |
| `AUTO_UPDATE_CACHE_SECONDS` | `21600` | Cache update check results for this many seconds |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | `1` | Suppress Hugging Face Windows symlink warnings |
| `NEKOSUNEAI_GITHUB_REPO` | `NekoSuneProjects/NekoSuneAI` | GitHub repo for update checks (owner/repo slug; a full URL is also accepted) |
| `NEKOSUNEAI_GITHUB_BRANCH` | `main` | GitHub branch for update checks |

---

## 🤖 LLM Tuning

Provider, model, API URL/key and temperature are in **Settings → AI Provider
& Models**. These have no Settings-UI equivalent:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_KEEP_ALIVE` | `30m` | How long Ollama keeps the model loaded |
| `OLLAMA_NUM_PREDICT` | `1200` | Maximum reply tokens |
| `OLLAMA_SKIP_LOCAL_SETUP` | `false` | Skip local Ollama install/start/model pull when using an existing Ollama server (set its URL in Settings) |

### CLI providers

Used when Settings → Provider is `claude-code` / `codex` / `cli`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CLI_MODEL` | *(none)* | Model id passed to the CLI (e.g. `sonnet`, `opus`) — blank uses the CLI's default |
| `CLAUDE_CLI_PATH` | *(auto)* | Override the `claude` executable path if not on PATH |
| `CODEX_CLI_PATH` | *(auto)* | Override the `codex` executable path if not on PATH |
| `LLM_CLI_COMMAND` | *(none)* | Full custom command for Provider=`cli`; use `{prompt}` to inject the prompt as an argument |

---

## 🔊 XTTS / 🎙️ Speech-to-Text tuning

Engine choice, model, speaker, speaker-clone, speed, and language are all in
**Settings → Voice** / **Settings → Speech-to-Text**. These lower-level
model/streaming/recognition knobs have no Settings-UI equivalent:

| Variable | Default | Description |
|----------|---------|-------------|
| `XTTS_MODEL_NAME` | `tts_models/multilingual/multi-dataset/xtts_v2` | XTTS model |
| `XTTS_USE_GPU` | `true` | Use GPU for voice synthesis |
| `XTTS_STREAM_OUTPUT` | `true` | Stream audio while generating |
| `XTTS_STREAM_CHUNK_SIZE` | `20` | Streaming chunk size |
| `XTTS_STREAM_BUFFER_SECONDS` | `1.8` | Stream buffer duration |
| `XTTS_CHUNK_MAX_CHARS` | `240` | Max characters per TTS chunk |
| `XTTS_MAX_TEXT_CHARS` | `5000` | Max total spoken text per reply |
| `STT_USE_GPU` | `true` | Use GPU for transcription |
| `STT_COMPUTE_TYPE` | *(auto)* | Compute type (auto-detected based on hardware) |
| `STT_BEAM_SIZE` | `5` | Beam search width |
| `STT_BEST_OF` | `5` | Best-of-N sampling |
| `STT_VAD_FILTER` | `false` | Voice Activity Detection filter |
| `STT_TIMEOUT_SECONDS` | `15` | Max wait time for speech |
| `STT_PHRASE_TIME_LIMIT_SECONDS` | `30` | Max single phrase duration |
| `STT_PAUSE_THRESHOLD_SECONDS` | `1.8` | Silence duration to end a phrase |
| `STT_NON_SPEAKING_DURATION_SECONDS` | `1.2` | Non-speaking duration threshold |
| `STT_AMBIENT_DURATION_SECONDS` | `0.6` | Ambient noise calibration duration |
| `STT_ENERGY_THRESHOLD` | `300` | Mic energy threshold for speech detection |
| `STT_DYNAMIC_ENERGY_THRESHOLD` | `true` | Dynamically adjust energy threshold |

---

## 🔈 Audio Devices

| Variable | Default | Description |
|----------|---------|-------------|
| `MIC_DEVICE_INDEX` | *(auto)* | Pin a specific microphone by index (see `/mics`) |
| `SPEAKER_DEVICE_INDEX` | *(auto)* | Pin a specific speaker by index |
| `MIC_SAMPLE_RATE` | *(auto)* | Override mic sample rate |
| `MIC_CHUNK_SIZE` | `1024` | Audio capture chunk size |

---

## Interaction & Game

Input mode and voice on/off are toggled from the chat UI (remembered between
sessions). Whether the game agent runs at all has no Settings-UI equivalent
— the OSC host/ports, vision model and think-interval are in **Settings →
Game**:

| Variable | Default | Description |
|----------|---------|-------------|
| `HISTORY_TURNS` | `10` | How many past exchanges the LLM sees for context |
| `REQUEST_TIMEOUT` | `300` | LLM request timeout (seconds) |
| `GAME_ENABLED` | `false` | Enable the VRChat OSC game agent |

---

## 🎤 Singing / RVC

Enabled/backend/RVC model path/cloud API are all in **Settings → Singing**
and **Settings → Voice** (chat RVC). This one has no Settings-UI equivalent:

| Variable | Default | Description |
|----------|---------|-------------|
| `SINGING_FETCH_INSTRUMENTAL` | `true` | Auto-find a YouTube instrumental/karaoke track when no backing is given |

RVC (chat or singing) is lazy-imported and **not** in `requirements-voice.txt`
— it pins `numpy<=1.23.5`, which conflicts with this project's `numpy>=1.24`.
Install it in its own virtualenv, or accept the numpy downgrade at your own
risk: `pip install "rvc-python>=0.1" --no-deps`.

---

## 💡 Tips

- Set `AUTO_TUNE_PERFORMANCE=false` if you want full manual control over performance settings.
- Use `AUTO_TUNE_GOAL=speed` on weaker hardware for snappier responses with smaller models.
- `HISTORY_TURNS=10` means the LLM sees the last 10 exchanges for context. Increase for better memory, decrease for faster responses.
