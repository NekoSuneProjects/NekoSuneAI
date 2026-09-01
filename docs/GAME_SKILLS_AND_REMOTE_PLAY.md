# Game skills, real-time play and console Remote Play

NekoSuneAI's game library lives in `game-skills/`. Each game has its own folder
containing a data-only `game.json` and a planner `GUIDE.md`. Packages can be
selected independently; they cannot run Python, shell commands, launchers or
arbitrary input.

Bundled starting packages include Minecraft, Terraria, Cyberpunk 2077, No
Man's Sky, Skyrim, Fallout 4, Stardew Valley, Subnautica, Xbox Remote Play and
PlayStation Remote Play. These are safe starting control maps, not claims that
vision can already complete every quest or understand every modded UI. Review
the game's actual keybinds and window title before enabling input.

## Package structure

`game.json` declares the exact process/window, platform, input permissions,
multiplayer policy, bounded named skills, real-time eligibility, capture rate
and OBS/Twitch permissions. `GUIDE.md` explains goals, HUD state and
irreversible choices to the Pi planner; it is prompt context, never code.

To add another game, copy the closest package and change its ID, process,
window expression, guide and keybinds. Keep `allow_input: false` while testing
capture. Every step must contain exactly one of `key`, `mouse_button`,
`mouse_move`, `button`, `axis` or `wait`. Mouse movement, duration and step
counts are bounded.

## Review and start a game

1. Review `game-skills/<game>/game.json` on the Windows gaming PC.
2. Verify its process/window names and every skill against your keybinds.
3. For single-player, set `allow_input` to `true`.
4. For private/permitted multiplayer, also set `automation_permitted` to
   `true` only after checking the game and server rules. Competitive,
   anti-cheat and `prohibited` packages remain disabled.
5. Pair/re-pair after changing input permissions so the node advertises the
   correct capabilities.
6. Start the package:

   ```powershell
   .\.venv-agent\Scripts\python -m nekosuneai.windows_gaming_agent `
     --config config\windows-gaming-agent.json `
     --skills-root game-skills --game minecraft
   ```

7. In **Studio → Nodes & Routines**, set `game.skill` to `allow`. Set
   `game.plan` to `allow` only for short real-time repeated movement while the
   Pi thinks. Both can return to `confirm` or `deny` at any time.

## Real-time action loop

The Pi makes high-level decisions and generates stream dialogue. A movement or
camera skill marked `realtime: true` becomes a short Windows intent, expiring
within eight seconds. Windows repeats only that reviewed skill until the next
intent arrives, so movement does not freeze during every model response.

The loop releases input when its deadline expires, the approved window loses
focus, OCR detects loading/death/menu state, the connection fails, the
dashboard sends stop/takeover, or **Ctrl+Alt+F12** is pressed. Inventory,
dialogue and confirmation skills are not repeated unless explicitly marked.

## Bounded learning

Neko records attempts, successes, failures, average duration, last failure
reason and reliability for each approved skill in
`data/game-learning/<game-id>.json`. Reliable skills are presented first to the
planner. The file contains no screenshots, raw video, key history, chat or
credentials.

Learning never creates keys, expands permissions, edits package code or turns
on multiplayer automation. New strategies and controls remain owner-reviewed.

## Xbox and PlayStation Remote Play

Console gameplay uses an already installed/authenticated Windows Remote Play
client as the selected window, with an optional ViGEm virtual Xbox 360 or
DualShock 4 controller. Install the Windows-agent requirements and ViGEm
driver, then make a game-specific copy with reviewed bindings and policy.

Generic console packages intentionally use `prohibited`, `allow_input: false`
and `allow_controller: false`. They are templates, not permission to automate
whichever multiplayer title is open. Client support for virtual controllers
varies by version.

The integration does not store Microsoft/Sony passwords, modify consoles,
bypass pairing/device protection, wake/shut down consoles, or claim to launch
a title. Unsupported actions remain visibly unsupported. Foreground-window and
emergency-stop checks apply to Remote Play too.
