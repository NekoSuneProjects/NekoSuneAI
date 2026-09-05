# Windows Gaming Agent, OBS and Twitch (server-side view)

The Raspberry Pi/Docker host remains NekoSuneAI's persistent brain. Games,
selected-window capture, bounded input skills, OBS and Twitch IRC run on the
Windows gaming PC, in the separate Windows checkout (`build/windows-gaming-node-release`
branch). This Docker/server checkout does not contain the agent implementation,
the game-skills packages, or any direct game/VRChat control code — it only
reaches a paired Windows node through the generic node-capability relay
described below.

This framework is intended for offline/single-player games and environments
where automation is explicitly permitted. It never attempts to bypass
anti-cheat, bot detection, platform rules or game restrictions. Set
`competitive_or_anticheat: true` for multiplayer/competitive profiles; this
forces autonomous input off even if another field requests it. (This policy is
enforced by the Windows-side agent; the server only forwards owner-controlled
capability policies.)

## Where things live

- **Windows checkout**: the full gaming agent, one `game.json`/`GUIDE.md`
  package per supported game, real-time intents, bounded learning, console
  Remote Play, VRChat OSC/API control, OBS and Twitch IRC connectivity, and the
  local install/pairing CLI (`nekosuneai.windows_gaming_agent`).
- **This Docker/server checkout**: pairing and node registry APIs, the
  dashboard's Nodes & Routines and Game pages, capability policy storage
  (`allow`/`confirm`/`deny`), and `nekosuneai/games/windows_remote.py` — a
  generic relay driver that queues named capabilities (`game.status`,
  `game.skill`, `game.plan`, `game.input.stop`, `vrchat.*`, etc.) to whichever
  node is paired and reads back whatever state/telemetry (including
  `state["vrchat"]`) that node reports over heartbeat. The server never talks
  to a game or to VRChat directly — it only knows named capabilities and
  heartbeat state.

For installing and configuring the actual agent, packages and VRChat
integration, see the Windows checkout's own docs.

## Fail-closed game control (enforced on the Windows agent, reported to the server)

- Only a foreground window matching `window_title_pattern` can be captured or
  receive input.
- The agent exposes named skills from the selected JSON profile, not arbitrary
  keys, mouse coordinates, shell commands, application launch or desktop APIs.
- Input defaults off. Every step is capped at two seconds, every skill at 20
  steps/ten seconds, and all held keys are released on completion, failure,
  window change, disconnect or process exit.
- Press **Ctrl+Alt+F12** locally to release and disable every AI-held input.
  The dashboard's **Stop all input** button provides a second owner control.
- OCR is optional. Screenshots are restricted to the approved foreground
  window, resized, rate-limited, and only sent on demand when the compressed
  payload fits the node heartbeat limit. The 20-observation working memory
  keeps compact metadata and OCR, never screenshot bytes.
- CPU/RAM, supported NVIDIA GPU load, active window, configured game/process,
  compact scene hash/OCR/transition state and last command result are reported
  through the normal authenticated heartbeat.

To use the high-level goal loop, first verify the local profile and game on
the Windows machine, then set only the node's `game.skill` capability to
`allow` in **Studio → Nodes & Routines**. Select **Paired Windows game** on the
Game page and start a goal. Pairing alone never enables autonomous input. The
Pi sends only exact named skills advertised by the node's heartbeat; the
Windows agent validates the foreground window and releases input locally.
Setting the policy back to `confirm` or pressing the emergency hotkey stops
further autonomous actions. For uninterrupted movement while the Pi thinks,
also set `game.plan` to `allow`; each local intent still expires within eight
seconds.

## OBS

Enable OBS WebSocket in OBS 28+ and set its local password in the private
Windows agent config. Available capabilities include status, scene switching,
stream start/stop, recording and replay-buffer save, relayed the same way as
game capabilities. State-changing node capabilities default to `confirm`; live
stream start/stop additionally refuses locally when the command does not
contain confirmation.

Ask `prepare stream minecraft` for a read-only preflight or use the Windows
node card in the dashboard. The preflight checks node connectivity, selected
profile, running game, approved-window capture, OBS connection, existing stream
state and emergency-stop availability. It does not claim audio or Twitch are
healthy when those signals are unavailable.

## Twitch chat

The Windows agent connects directly to Twitch IRC over TLS and sends only a
bounded queue of compact public chat messages to the Pi. Neko prioritises
mentions, questions and highlighted messages without speaking every line.
Duplicate/flooded text and per-user bursts are rate-limited.

Public chat is processed with a separate prompt and no assistant tools, owner
memory, device control, OBS control or game control. Viewer commands are limited
to harmless chat-only `!hello`/`!neko` replies. `twitch.chat.send` defaults to
the node's confirmation policy; automatic replies begin only after the owner
explicitly changes that capability to `allow`.

## Sunshine / Moonlight capture option

For the preferred low-overhead split, run Sunshine on Windows and Moonlight on
the Raspberry Pi/encoding machine over Ethernet at 720p30, H.264, HDR off. OBS
may capture the Moonlight window and encode to Twitch. This view-only path is
separate from the paired Windows input agent and does not grant the Pi raw
keyboard/mouse control.
