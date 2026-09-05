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

## Package reference

`allow_input` starts `false` in every package below; the owner must review
keybinds and enable it locally per game. Any profile with
`competitive_or_anticheat: true`, or with `multiplayer_policy: "prohibited"`,
always forces input off regardless of this setting.

| Game | Mode | AI/VTuber automation allowed? |
| --- | --- | --- |
| Minecraft | Private server | Yes, on a private/self-hosted server only |
| Fallout 4 | Single-player | Yes, single-player |
| Skyrim | Single-player | Yes, single-player |
| Cyberpunk 2077 | Single-player | Yes, single-player |
| Subnautica | Single-player | Yes, single-player |
| No Man's Sky | Permitted multiplayer | Vision/observation only by default — owner must review and enable |
| Stardew Valley | Private server | Vision/observation only by default — owner must review and enable |
| Terraria | Private server | Vision/observation only by default — owner must review and enable |
| PlayStation Remote Play | Prohibited-input-disabled | No — input disabled (remote-play/console sessions) |
| Xbox Remote Play | Prohibited-input-disabled | No — input disabled (remote-play/console sessions) |
| Valheim | Private server | Yes, on a private/self-hosted server only |
| Satisfactory | Private server | Yes, on a private/self-hosted server only |
| 7 Days to Die | Private server | Yes, on a private/self-hosted server only |
| Raft | Private server | Yes, on a private/self-hosted server only |
| Don't Starve Together | Private server | Yes, on a private/self-hosted server only |
| Portal 2 | Single-player | Yes, single-player |
| The Long Dark | Single-player | Yes, single-player |
| Human: Fall Flat | Private server | Yes, on a private/self-hosted server only |

Start a reviewed package with:

```powershell
py -m nekosuneai.windows_gaming_agent --config config\windows-gaming-agent.json `
  --skills-root game-skills --game minecraft
```

### First-run pairing

If the config file has no `device_token` yet and you didn't pass
`--pairing-id`/`--pairing-code` on the command line, the agent now prompts on
the console instead of failing: it asks for the server address (if
`server_url` isn't already set), then the pairing ID and pairing code shown on
the Docker/Pi dashboard's pairing page, and saves the resulting `server_url`
and `device_token` back into the config file.

This is exactly what to use when the Docker/Pi server is hosted on a remote
VPS rather than the local network — there's no LAN discovery to fall back on,
so just point it at the server's HTTPS address plus the pairing code from the
dashboard. Prompts are skipped (so scheduled/unattended runs never block on
stdin) when `--install-startup` is passed, a `device_token` is already saved,
or `--pairing-id`/`--pairing-code` are both given on the command line.
