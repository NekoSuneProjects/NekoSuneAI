# Changelog

All notable changes to **NekoSuneAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

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

[1.1.1]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.1
[1.1.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.1.0
[1.0.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.0.0
