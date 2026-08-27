# Changelog

## 1.2.1 wake-word image fix

- Preload the official `hey_jarvis` model in Docker images and automatically
  fetch missing official wake-word models at runtime.
- Expose the Raspberry Pi user's PipeWire/PulseAudio session to Docker, install
  ALSA/Pulse discovery tools, and report Kinect/Alexa device errors in Settings.
- Default wake-word inference to ONNX to avoid Raspberry Pi TFLite native-wrapper
  crashes, with an advanced dashboard setting for either backend.
- Repair the dashboard Start Session control so animated stage layers cannot
  intercept clicks, keep its full button styling, and surface backend errors.
- Pin NumPy to the 1.x ABI used by Raspberry Pi wake-word native modules and
  verify that ABI during the Docker build.

All notable changes to **NekoSuneAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [1.2.1] - Unreleased

### Added
- Remote MCP platforms with API-key and OAuth authentication, NekoAI Bridge
  TTS/STT, aircraft/weather/government-alert tools, persistent scheduled
  monitors, spoken emergency broadcasts, and warning/danger cues.
- Low-latency Edge streaming TTS with Piper as the offline fallback.
- A redesigned VTuber control-studio dashboard.
- Docker-first multi-architecture releases for amd64 and Raspberry Pi arm64.

### Changed
- GitHub Actions now builds Docker images automatically on a self-hosted Linux
  x64 runner. Windows packaging is an optional manual Wine build on that same
  runner; no GitHub-hosted Windows runner is required.

## [1.2.6] - Unreleased

### Added
- **Search gateway web search provider** — Settings → Web Search → Provider
  now has a `gateway` option for a self-hosted multi-backend search proxy
  (`POST {url}/v1/search` with `{"query", "provider"}` + a Bearer API key,
  e.g. one that fronts SearXNG/Brave/Tavily/etc. behind one endpoint). New
  `Gateway backend` (which provider id the gateway should use, e.g.
  `searxng-search`) and `Gateway API key` fields alongside it. Verified
  against real request/response captures for the error case (upstream 429)
  and the empty-results case; the exact field names inside a *non-empty*
  `results` array are unconfirmed (live testing only returned empty result
  sets) — it accepts common variants (title/name, url/link,
  snippet/content/description) but flag it if real results come back oddly.

## [1.2.5] - Unreleased

### Changed
- Settings → Speech-to-Text's Whisper model field is now a dropdown of the
  standard faster-whisper sizes (`tiny.en`, `base.en`, `small.en`,
  `medium.en`, `large-v3`, `distil-large-v3`) instead of a free-text field.
  Picking one downloads and caches it automatically on next use, same as
  before — faster-whisper already fetches an uncached model by name, this
  just removes the need to know/type the exact model id.

## [1.2.4] - Unreleased

### Fixed
- Dashboard showed "Busy" (and disabled Start Session) whenever the backend's
  `busy` flag was true, even with no session started — but `busy` can be true
  from an unrelated background feature (Watch & React, the VRChat game agent)
  mid-tick, which has nothing to do with the chat session. `session_started`
  is now checked first, so an unstarted session always shows "Standby" and
  Start Session is never blocked by unrelated background activity.
- The VRChat friends system (`games/vrchat_friends.py`) needed a separate
  manual `pip install vrchatapi pyotp websocket-client` step — it's
  lightweight with no known conflicts, so it now ships in `requirements.txt`
  like the OSC integration does, with no extra step needed.

## [1.2.3] - Unreleased

### Added
- **End Session button** — the Dashboard's session button was a dead end
  once clicked: it turned into a disabled green "Running" pill with no way
  to stop a session short of restarting the app (there was no backend
  `end_session()` at all). It's now a live "End Session" button (`Api.
  end_session()` in `webgui.py`) that also force-stops anything in-flight
  (LLM/TTS/playback) before ending.
- VRChat's vision read now explicitly prioritizes chat-bubble/speech-bubble
  text above someone's head (quoted verbatim), flags when that text just
  changed since the last look vs. a lingering stale bubble, and distinguishes
  a "typing..." indicator from finished text so the companion waits instead
  of replying to someone who hasn't finished typing yet. When a bubble just
  changed, the next observe/act tick fires ~1.5s later instead of waiting the
  full tick interval, so short-lived bubbles are far less likely to be missed.

### Fixed
- VRChat's `turn`/`look` OSC actions held the look-axis at full deflection
  for up to 6 seconds (whatever duration the LLM picked) with no target/
  feedback loop at all — a multi-second hold could easily swing the camera
  wildly past a person's head into the sky or floor. Durations are now
  clamped tight (turn: 0.05–0.5s, look: 0.05–0.35s) and the game agent is
  told to use several small corrective nudges to track a person, one tick at
  a time, instead of one large blind sweep.

## [1.2.2] - Unreleased

### Changed
- Trimmed `.env.example`/`docs/CONFIGURATION.md`/README down to only what's
  genuinely still `.env`-only. Everything that moved to the SQLite-backed
  Settings panel over time (LLM provider/model/API key/temperature, voice,
  STT, web search, RAG memory, media, singing, RVC, VRChat friends, VRChat
  OSC) is no longer documented as an `.env` variable — those entries were
  stale/redundant since Settings always overrides them at runtime anyway.
  No behavior change; the app already read the same code defaults either way.

## [1.2.1] - Unreleased

### Fixed
- Loading the XTTS voice model for the first time crashed with "You must agree
  to the terms of service to use this model." — coqui-tts asks an interactive
  `[y/n]` CPML license prompt on first download, which has no stdin to answer
  into from either the desktop GUI (no console at all) or the headless setup
  preload step (`bootstrap.py`, run non-interactively via subprocess). Now
  sets the documented `COQUI_TOS_AGREED=1` bypass before any XTTS model load.

## [1.2.0] - Unreleased

### Added
- **Packaged installers**: tagging a release (`git tag v1.2.0 && git push --tags`) now
  builds a Windows installer (`NekoSuneAI-Setup-<version>.exe`, Inno Setup,
  `packaging/windows/nekosuneai.iss`) and Linux `.deb`/`.rpm`/`.apk` packages
  (`packaging/linux/build-packages.sh`, via `fpm`), both bundling the full voice/TTS
  stack — no more manual `git pull` + `install.ps1`/`install.sh` required to get a
  release. Attached to a GitHub Release with changelog-derived notes, an optional
  VirusTotal scan of the Windows installer, and a Discord announcement
  (`.github/workflows/release.yml`).
- **Hosted apt/yum/apk repositories**: the built Linux packages are also published to
  [NekoSuneProjects/packages](https://nekosuneprojects.github.io/packages/), a shared,
  GPG/abuild-signed repo covering every NekoSuneProjects app (not just this one) — once
  set up, `apt install`/`dnf install`/`apk add nekosuneai` will work by name instead of
  needing a downloaded package file. See that repo's `docs/PACKAGES.md` for the add-repo
  commands.

## [1.1.9] - Unreleased

### Fixed
- `install.ps1` contained em-dashes, arrows, and box-drawing characters (in
  comments AND in actual banner/menu string literals). PowerShell 5.1's
  `Invoke-RestMethod` doesn't reliably auto-detect UTF-8 from HTTP responses,
  so fetching the script via the documented `irm ... | iex` one-liner could
  silently mangle those multi-byte sequences, corrupting the token stream and
  producing cascading parse errors ("Missing '(' after 'If'", etc.) that had
  nothing to do with the actual line they pointed at. Scrubbed the whole file
  to plain ASCII, which eliminates this bug class regardless of terminal/
  encoding configuration on the machine running the installer.

### Added
- `install.ps1`/`install.sh` now auto-detect the installed NVIDIA driver's
  supported CUDA version (via `nvidia-smi`) and auto-select the newest
  compatible PyTorch build, instead of always asking. Falls back to the
  previous manual picker if no driver is detected. The manual picker's CUDA
  list is refreshed (added 13.2/13.0/12.9, dropped the now-ancient 12.4) to
  match what's actually published at download.pytorch.org today.
- Prep work for the upcoming packaged installers (Windows `.exe`, Linux
  `.deb`/`.rpm`/`.apk`): `nekosuneai/paths.py` and `nekosuneai/launcher.py`
  now handle running from a PyInstaller-frozen build correctly (`ROOT_DIR`
  resolving to the exe's own directory instead of PyInstaller's internal
  extraction dir, and the self-restart-after-update path no longer assuming
  a separate `app.py` exists next to the exe). No behavior change for normal
  source-checkout runs.

## [1.1.8] - Unreleased

### Added
- Settings → **Web Search** card (provider, SearXNG URL, max results, timeout,
  region, safesearch) and **Memory (RAG)** card (enabled, recall count,
  minimum relevance score) — previously `.env`-only and needed a restart to
  take effect; now live-editable and SQLite-backed like the rest of Settings.

### Fixed
- `THINKING_SOUND_PATH` only accepted a single audio file; pointing it at a
  folder (e.g. `data/music`) silently did nothing since ffplay can't play a
  directory, and an exception on the background timer thread had nowhere to
  surface. It now accepts a folder and picks a random track from it each
  time, and playback failures are logged instead of vanishing silently.

## [1.1.7] - Unreleased

### Fixed
- `install.ps1` had `#Requires -Version 5.1` as its first line, which only
  works when the file is executed directly as a `.ps1` — it errors with
  "not recognized as the name of a cmdlet" under the documented
  `powershell -c "irm ... | iex"` one-liner, since `iex` parses the
  downloaded text as a script block rather than a top-level script file.
  Replaced with an equivalent runtime `$PSVersionTable.PSVersion` check that
  works under both invocation styles.

## [1.1.6] - Unreleased

### Fixed
- The OpenAI-compatible chat path never sent `stream: false` and had no way
  to read a streamed response — a gateway that streams chat-completion
  chunks (Server-Sent Events, `data: {...}` frames) regardless sent back a
  body our client couldn't parse at all, surfacing as "unexpected response
  format" with no usable reply. Requests now explicitly ask for
  `stream: false`, and if a gateway streams anyway, the reply is
  reconstructed from the SSE chunks instead of failing.

## [1.1.5] - Unreleased

### Fixed
- `requirements-voice.txt` pinned `torch>=2.2,<3` with no upper bound inside
  the 2.x series. `pip install --upgrade` (the new fast-update path from
  1.1.3) happily jumped to torch 2.9, but coqui-tts's audio I/O requires the
  separate `torchcodec` package from torch 2.9 onward, which isn't declared
  anywhere — breaking voice model preload with an ImportError. Capped
  `torch`/`torchaudio` to `<2.9` instead of adding torchcodec as a new
  (ABI-fragile, unpinned) dependency; re-run the installer's Update path or
  `pip install -r requirements-voice.txt` in the venv to get pip to
  downgrade back down to a working torch version.

## [1.1.4] - Unreleased

### Fixed
- The new "already installed?" detection in `install.ps1`/`install.sh`
  (1.1.3) only checked for the `.setup-complete` marker, which is written
  at the very END of a successful setup run. A first attempt that crashed
  partway through (e.g. a pip conflict) leaves `setup.py`/the venv in place
  without that marker, so the installer never offered the fast Update path
  and always redid the full wizard. Now detected by `setup.py` being
  present instead, with "Just launch" falling back to the full wizard if
  the venv isn't there yet.

## [1.1.3] - Unreleased

### Fixed
- `install_requirements()` installed all three requirement files (base,
  voice, GUI) in one combined `pip install -r a -r b -r c` call. pip resolves
  that as a single atomic transaction — one conflicting package anywhere in
  the set aborted the WHOLE install, leaving nothing installed (not even the
  base requirements). Each requirement file is now installed with its own
  pip call: base must succeed, but a failure in the optional voice/GUI
  profiles now just disables that feature (with a warning) instead of
  breaking setup entirely.
- `python-osc` (needed for the VRChat OSC driver) was never actually
  installed by the installer — only mentioned in a `.env.example` comment.
  It's now in `requirements.txt`.
- Chat error messages for "unexpected response format" (Ollama and
  OpenAI-compatible) now include a snippet of the actual raw response body,
  instead of a generic message with no way to tell what the endpoint
  actually returned.

### Added
- `install.ps1` / `install.sh` now detect an existing install and offer a
  fast **Update** path (git pull / re-download the code, refresh pip
  packages against the profile from your last setup, no questions asked)
  instead of forcing the whole interactive wizard every time you just want
  to pick up the latest version.
- `setup.py --setup --upgrade` upgrades already-installed packages to the
  newest version allowed by `requirements*.txt` instead of only installing
  what's missing; `python setup.py --update` (and the fast installer update
  path above) now use this automatically.

## [1.1.2] - Unreleased

### Fixed
- The desktop GUI's chat pipeline had no error handling around the LLM call
  or the media/music call — any failure (bad endpoint response, missing
  `ffplay`, etc.) vanished into the browser devtools console with nothing
  shown in the UI. Both paths now push a visible `[Companion error]` /
  `[Media error]` message into the chat log instead.

### Changed
- **Retheme**: swapped the desktop GUI from violet/purple to a dark green
  palette (backgrounds, borders, buttons, focus rings, chat bubbles), with
  glassy card backgrounds, subtle glow shadows, and a pulsing "VR" badge on
  the Game / Watch & React nav items plus a glowing banner on the Game page.
- Finished the NovaAI → NekoSuneAI rename: leftover `run-nova.bat`/
  `run-nova.sh`/`.nova-run-mode` launcher artifacts, the `.nova-profile.json`
  export format, and internal env vars (`NOVA_GITHUB_REPO`/`BRANCH`,
  `NOVA_INSTALL_PROFILE`, `NOVA_SKIP_AUTO_UPDATE`) are now
  `NEKOSUNEAI_*`-named — old env var names still work as a fallback.

## [1.1.1] - Unreleased

### Fixed
- `requirements-voice.txt` no longer installs `rvc-python` directly — it pins
  `numpy<=1.23.5`, which conflicts with this project's `numpy>=1.24` and broke
  `pip install -r requirements-voice.txt` (and therefore full-profile setup)
  outright. RVC (chat or singing) now needs a separately-managed install; see
  `.env.example` for the manual command and caveats.

## [1.1.0] - Unreleased

Leans further into VRChat as the core platform integration, and cleans up
chat-app features that didn't fit that focus.

### Added
- **RVC voice conversion for normal chat replies** (`nekosuneai/rvc.py`), not
  just singing — optional, with Pitch/index-rate/protect controls in
  Settings → Voice (`RVC_CHAT_ENABLED`).
- **Sticky wake-instructions** (`nekosuneai/sticky.py`) — say the companion's
  name plus a standing rule to make it stick until you say "stop"; "reset"/
  "clear" cancels that and wipes long-term RAG memory. Replaces `/remember`.
- **Thinking music** — an optional short cue during noticeably long waits
  (slow local LLM turns, game-agent ticks) that never interrupts music
  already playing.
- **VRChat friends system** (`nekosuneai/games/vrchat_friends.py`) — opt-in,
  credential-gated: auto-accepts friend requests, live online/offline
  awareness via the unofficial web API, and a paged thank-you chatbox
  message. Off by default; uses an account's own credentials, not the
  supported OSC API.
- **OSC chatbox paging** — long `/chatbox/input` text is split across
  multiple numbered messages instead of being truncated at ~140 chars.

### Changed
- VRChat's per-tick screen caption now goes through the same vision
  dispatcher (Ollama-then-OpenAI-vision) that Watch & React uses.

### Removed
- **Radio** — the built-in station directory and internet-radio.com search
  are gone. Music search/streaming (SoundCloud, Spotify/Deezer) stays.
- **Image Review** — the manual "upload a picture and react" 🖼️ chat feature
  is gone; vision is VRChat/screen-focused now (Watch & React, VRChat's own
  screen awareness).
- **`/remember <fact>`** — long-term memory was already automatic; see
  sticky wake-instructions above for the session-mode use case it covered.

## [1.0.0] - Unreleased

First release under the NekoSuneAI name — a focused rebrand of the project
(formerly NovaAI) around a single platform integration: VRChat.

### Changed
- Renamed the project and Python package from NovaAI/`novaai` to
  NekoSuneAI/`nekosuneai`.
- Narrowed the app to a core AI companion (chat, memory, web search, voice,
  singing, music playback) plus VRChat OSC integration as the only
  platform/game integration.
- Only two run modes remain: the native desktop GUI (`python app.py --gui`)
  and CLI/terminal mode (`python app.py`).

### Removed
- The VTuber/3D-avatar system (VRM rendering, MMD dance, avatar overlay,
  lip-sync-to-avatar).
- Twitch chat integration.
- Non-VRChat game-playing (Minecraft/Mineflayer bridge, osu!, Factorio, the
  universal vision+input driver) and the text-based chatgames (battleship,
  connect4, minesweeper, nim, reversi, rps, tictactoe).
- Reminders, alarms, calendar, shopping list, and to-do list.
- Streaming alerts / donation overlay (Streamlabs, StreamElements).
- The Neuro Game SDK server.
- The headless browser web UI (`--web`) and Docker support, which existed to
  serve it.

[1.2.6]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.6
[1.2.5]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.5
[1.2.4]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.4
[1.2.3]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.3
[1.2.2]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.2
[1.2.1]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.1
[1.2.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.2.0
[1.1.9]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.9
[1.1.8]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.8
[1.1.7]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.7
[1.1.6]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.6
[1.1.5]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.5
[1.1.4]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.4
[1.1.3]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.3
[1.1.2]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.2
[1.1.1]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.1
[1.1.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.0
[1.0.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.0.0
