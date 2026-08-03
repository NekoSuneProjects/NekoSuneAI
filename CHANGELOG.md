# Changelog

All notable changes to **NekoSuneAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/NekoSuneProjects/NekoSuneAI/releases/tag/v1.0.0
