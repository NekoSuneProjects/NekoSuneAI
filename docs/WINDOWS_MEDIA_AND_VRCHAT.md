# Windows Media and VRChat

Owner: `build/windows-gaming-node-release`. Backend peer: Docker `main`.
Windows captures and plays audio. The Pi/Docker backend performs STT, TTS and
image understanding through its configured providers. No local speech model is installed.

## Setup

1. Deploy the matching Docker node-media endpoints, configure its STT/TTS and
   vision providers, and pair the Windows node through Setup. Use HTTPS outside
   a trusted LAN; audio and images are sent to the configured backend/providers.
2. Select a game profile and start the node. In Audio & Vision, refresh devices,
   select a microphone or playback loopback input and a Windows playback output.
3. Use Record once and Speak through Pi to test each direction. Apply media
   settings to enable continuous listening or periodic gameplay analysis.
4. For a one-off frame, choose Analyse in 3 seconds and focus the game window.
   Capture remains restricted by the selected profile and foreground checks.
   Tesseract is optional for local OCR; Pi image understanding needs a vision model.
5. Allow `audio.speak` in the server node permissions for automatic game narration.
   Newly advertised write capabilities require confirmation by default. Existing
   owner policies survive heartbeat capability refresh, without re-pairing.

Listening pauses during TTS and uses bounded recordings, not simultaneous
full-duplex streaming. Transcripts are observations, not automatically trusted
owner commands. Stop audio disables continuous listening and narration and cancels
recording and pending playback; re-enable narration through Apply media settings.
Stop the node
to disable all media. Select devices again after Windows audio devices change.

## VRChat

Select the VRChat profile, enable local OSC, save and restart the node. Enable
OSC in VRChat's action menu. Default ports are 9000 to VRChat and 9001 from
VRChat, on loopback only. Another OSC receiver using 9001 must be stopped or
configured for a different port. Explicitly Arm OSC before sending controls.

The app supports bounded movement/look/jump actions, chatbox messages, avatar
parameter writes and local avatar telemetry. Stop/disarm releases input axes
and buttons; connection loss disarms control. After an emergency input stop,
restart the node before arming again. Remote actions also require server policy.

OSC does not provide an instance player-name roster. Visible nameplates can be
read through the configured vision provider or optional OCR, with uncertain
readings treated as uncertain. VRCX history import is a separate backlog task.
Use controls only where automation is permitted and with participant consent.

References: https://docs.vrchat.com/docs/osc-as-input-controller and
https://docs.vrchat.com/docs/osc-avatar-parameters

## Continuous listening (no microphone required to be heard)

Continuous listening now records until the speaker goes quiet (silence-to-finish,
default 10s) instead of a fixed clip, up to a max-recording cap (default 30s) as
a safety net, so it isn't cut off mid-sentence in normal use. If someone talks
non-stop long enough to hit the cap, NekoSuneAI gives a short spoken nudge to
pause occasionally, at most once a minute. Chatbox/on-screen text is read
through the existing OCR pipeline regardless of microphone use — it refreshes
continuously in the background rather than only once per heartbeat, so
short-lived chat bubbles are far less likely to be missed.

## VRChat Friends (bot account)

A separate opt-in bot account can auto-accept friend requests and narrate
friend online/offline activity, configured on the VRChat page: bot username/
password/TOTP secret, and an optional owner VRChat username used only to call
the owner out by name in those narrations. This is against VRChat's ToS for
automated accounts — use a throwaway bot account, never the owner's own login.
Enabling or disabling it requires restarting the node.

## World Map (manual, wall-following)

The World Map page builds a rough sketch map of the current VRChat world by
repeatedly walking forward and turning when the avatar's own OSC velocity
feedback shows it didn't move (a wall), tracing corridors/edges the way someone
feeling their way along a wall would rather than wandering the whole world.
It's manual only (Start/Stop buttons) — nothing maps automatically. It reads
the current world from VRChat's own latest log file, so it's always the world
you're actually in.

Maps are saved one JSON file per world under `world-maps/`, named after the
world (its `world_id` is stored inside for exact matching, so two worlds
sharing a display name don't collide). Re-running the mapper on the same world
merges: wall segments confirmed again are kept, ones that don't show up this
run are dropped, and new ones are added — so it converges to the world's
current layout without needing to know in advance whether the world actually
changed. If the bot account above is logged in, the world's numeric version
from VRChat's API is stored and refreshed too. "Tag landmark here" marks the
mapper's current estimated position with a label you choose (VIP rooms, back
rooms, anything wall-following might walk past) — it also auto-tags doors,
lifts/elevators, teleporters and VIP signage whenever the on-screen OCR text
names one (this is text-only, reading whatever sign/button label is on
screen — there's no real object detection of what a door or lift actually
looks like, so an unlabeled one won't be caught this way), as a best-effort
hint, not a substitute for tagging things yourself.

This is dead reckoning (estimated walk speed and turn rate over time), not a
laser scan — position drifts over a large world, and wall-following can miss
interior rooms that never touch the boundary it traces. `world-maps/` is a
plain folder specifically so a finished map can be committed to its own branch
and pulled down elsewhere; "Sync map for current world" downloads one from a
raw file host (e.g. a raw.githubusercontent.com URL) instead of remapping it.

Once it walks back to near where it started the current pass, that loop is
considered closed and it stops circling it — the traced path is also stored
as a fillable floor outline (`floor_polygon`), so a viewer can shade the whole
room in instead of needing every square metre individually walked. It doesn't
stop mapping there, though: a junction it had to turn hard through to find a
way past gets noted as a possible unexplored branch, and once the current
loop closes it dead-reckons its way back to each noted branch and explores
from there too — so a big, multi-room world (a Popcorn Palace-sized one, say)
keeps getting checked for more area across a run instead of stopping after
the first lap, without deliberately re-walking ground it's already covered.
It gives up on a branch it can't find its way back to (drift, or a changed
layout) rather than getting stuck. `world_map_dir` defaults to a `world-maps`
folder next to wherever the app is actually running from (the EXE's own
folder, not whatever the launcher's current directory happened to be), and
the World Map page shows a live top-down sketch (walls, path, landmarks,
current position) below the log, drawn from the in-progress run or, when idle,
from the last saved map for the world you're in.

Stairs up/down are detected from sustained vertical OSC velocity while still
moving horizontally (corroborated by OCR text mentioning a floor/stairs when
visible) and treated as a new floor: the current floor's walls/path/landmarks
are sealed off under its own `floor_index`, position resets to (0, 0) for the
new floor, and mapping continues — a world with more floors just keeps
stacking them the same way. The saved JSON is a `floors` list (schema v2),
each with its own `walls`/`landmarks`/`path`/`floor_polygon`, merged
independently per floor on re-runs.

## Mobile web view (view-only, from your phone)

With one monitor, the desktop app can't sit visibly on top of a fullscreen
game the way it could with a second screen. Enable "Mobile web view" on the
Status page (a port, default 8799) and it serves the same OCR text, a
refreshing JPEG of the captured game view, VRChat/world-mapper status and
recent friends-bot activity to any browser on the same Wi-Fi — the Status
page shows the exact address to type into your phone once the node is
running. It's read-only by design: there is no command/input path on this
page, only the observation data the agent already collects for itself, so it
can't become a second, less-guarded way to control the game. It isn't
authenticated, so only enable it on a network you trust and never forward the
port to the public internet.

## Verification Boundary

Local automated checks and packaging are separate from a live Pi deployment,
actual microphone/loopback playback and an in-game VRChat test. Those hardware
checks remain open in this branch's TODO.
