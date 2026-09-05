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

## Verification Boundary

Local automated checks and packaging are separate from a live Pi deployment,
actual microphone/loopback playback and an in-game VRChat test. Those hardware
checks remain open in this branch's TODO.
