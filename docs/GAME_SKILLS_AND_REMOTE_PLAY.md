# Game skills and Remote Play

The game-skills packages (`game.json`/`GUIDE.md` per game), the full Windows
gaming agent implementation, real-time intents, bounded learning and console
(Xbox/PlayStation) Remote Play support live only in the Windows checkout
(`build/windows-gaming-node-release` branch). The local duplicates that used to
live in this Docker/server checkout (`nekosuneai/windows_gaming_agent.py`,
`nekosuneai/game_skills.py`, `game-skills/`, `config/windows-gaming-agent.example.json`,
`config/game-profiles/`) have been removed — they were legacy copies, not the
source of truth, and assumed the server itself ran on the same machine as the
game.

This server/Docker checkout only ever reaches a game through the paired node's
generic capability relay (`nekosuneai/games/windows_remote.py`), by queuing a
named capability such as `game.status`, `game.skill`, `game.plan` or
`game.input.stop` and reading back whatever state the node reports over
heartbeat. See [`WINDOWS_GAMING_AND_TWITCH.md`](WINDOWS_GAMING_AND_TWITCH.md)
for the server-side pairing, policy and dashboard flow, and the Windows
checkout's own docs for package structure, review/start steps, the real-time
action loop, bounded learning and Remote Play details.
