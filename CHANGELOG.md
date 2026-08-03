# Changelog

All notable changes to **NekoSuneAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

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
