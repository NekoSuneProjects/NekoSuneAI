# NekoSuneAI Windows Gaming Node

[![Windows Gaming Node](https://img.shields.io/badge/build-windows--gaming--node-0078D6)](.github/workflows/windows-gaming-node.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPL_v3-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-see-VERSION-violet)](VERSION)

Standalone Windows executable that runs bounded, reviewed game-skill
automation, OBS control and Twitch chat on a gaming PC, plus templates for
Xbox and PlayStation Remote Play. This build is intentionally minimal: it
contains only the files needed to build and run the Windows Gaming Node,
trimmed from the wider NekoSuneAI project.

This framework is for offline/single-player games and environments where
automation is explicitly permitted. It never attempts to bypass anti-cheat,
bot detection, platform rules or game restrictions — `competitive_or_anticheat`
profiles force autonomous input off.

## What's here

- `tools/windows_gaming_node_entry.py` — PyInstaller entrypoint
- `nekosuneai/windows_gaming_agent.py` — the agent (input safety controller,
  virtual gamepad, OBS/Twitch integration, skill execution)
- `nekosuneai/game_skills.py` — bundled game-skill package loader
- `game-skills/` — reviewed per-game skill packages and guides
- `config/windows-gaming-agent.example.json` — example node config
- `docs/GAME_SKILLS_AND_REMOTE_PLAY.md`, `docs/WINDOWS_GAMING_AND_TWITCH.md` —
  usage docs
- `requirements-windows-gaming-node.txt` — minimal build dependencies
- `.github/workflows/windows-gaming-node.yml` — CI build/release workflow

## Building

```powershell
python -m pip install -r requirements-windows-gaming-node.txt
pyinstaller --noconfirm --clean --onefile --name NekoSuneAI-Windows-Gaming-Node `
  --icon data/logo.ico --collect-all vgamepad --collect-all obsws_python `
  --hidden-import PIL --hidden-import PIL.Image --hidden-import pytesseract `
  tools/windows_gaming_node_entry.py
```

See `docs/GAME_SKILLS_AND_REMOTE_PLAY.md` for running the built executable and
`docs/WINDOWS_GAMING_AND_TWITCH.md` for pairing and configuration details.

## Tests

```
pytest test/test_windows_gaming_agent.py test/test_game_skills.py
```
