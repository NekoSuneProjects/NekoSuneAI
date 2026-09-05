# NekoSuneAI Windows Gaming Node

Branch ownership: **Windows** on `build/windows-gaming-node-release`. See the
[branch map](BRANCH_MAP.md) and this product's [TODO](TODO.md) before making
changes. Native app branches remain separate from the Docker backend on main.

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

## Pairing

Set the Server URL and select a game profile in the Windows app. **Open
dashboard** opens the server's **Nodes & Routines** page. Sign in there.

- **Request pairing**: approve the PC under **Windows & Android pairing
  requests**. Local-network approval is enabled by default.
- **Pair with code**: select **Create pairing code** on the dashboard, enter
  both the Pairing ID and One-use code in Windows, then select **Pair with code**.
  Codes expire after five minutes and can only be used once. This also works
  through your HTTPS server URL when remote approval requests are disabled.

After pairing, select **Start node** on the Gaming page to connect the PC.

## Building

```powershell
python -m pip install -r requirements-windows-gaming-node.txt
pyinstaller --noconfirm --clean NekoSuneAI-Windows-Gaming-Node.spec
```

See `docs/GAME_SKILLS_AND_REMOTE_PLAY.md` for running the built executable and
`docs/WINDOWS_GAMING_AND_TWITCH.md` for pairing and configuration details.

## Tests

```
pytest test/test_windows_gaming_agent.py test/test_game_skills.py
```
