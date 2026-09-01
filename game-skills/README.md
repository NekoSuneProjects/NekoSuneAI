# NekoSuneAI game skill packages

Each subfolder is an independently selectable, data-only game package:

- `game.json` defines the approved window/process, platform, multiplayer policy,
  input permissions and named skills.
- `GUIDE.md` gives the Pi planner compact game-specific goals, hazards and play
  guidance. It is never executed as code.
- runtime reliability learning is stored outside this folder under
  `data/game-learning/`; it records aggregate outcomes only and never raw video.

Input is disabled in the bundled packages until the owner reviews keybinds and
sets `allow_input` to true. Multiplayer packages additionally require
`automation_permitted: true`, which should be used only on private servers or
where the game/server rules explicitly permit bots. Competitive/anti-cheat
profiles always disable input.

Start a reviewed package with:

```powershell
py -m nekosuneai.windows_gaming_agent --config config\windows-gaming-agent.json `
  --skills-root game-skills --game minecraft
```
