# MCP and NekoAI Bridge

NekoSuneAI can use remote Streamable HTTP MCP servers on low-power computers,
including Raspberry Pi. The local Pi records/plays audio and runs the UI; the
bridge can perform weather, aircraft, radar, emergency, TTS, and STT work.

## Authentication

In Settings → Remote MCP & NekoAI Bridge, enable MCP and provide a JSON server
list. API-key mode sends both the Bridge User bearer token and the configured
API-key header. OAuth mode sends an OAuth access token and automatically uses a
refresh token when the server returns 401 (when client ID and token URL are set).
Keep tokens private and never commit real values.

For an OAuth-only or mixed bridge, save the server URL in Settings and press
**Connect OAuth**. NekoSuneAI dynamically registers its exact dashboard callback,
opens the Bridge consent page with PKCE-S256, and stores the resulting access and
rotating refresh tokens. Enter the desired Bridge User `nai_...` token only on
the Bridge consent page; NekoSuneAI never receives that account token during the
OAuth exchange. The dashboard must be opened through an address the same browser
can return to, such as `http://RASPBERRY_PI_IP:8788`, not `0.0.0.0`.

See `.env.example` for both formats. Multiple server objects may be added to the
list. NekoSuneAI tries enabled servers in order.

## Automatic tools and explicit calls

Natural requests about weather, rain, radar, aircraft, severe weather, and
emergency alerts are routed to compatible bridge tools. An exact tool can be
called with `/mcp tool_name {"argument":"value"}`.

Configure `WARNING_SOUND_PATH` and `DANGER_SOUND_PATH` to local WAV/MP3 files.
Warning-like results play the warning cue; extreme/severe or immediate threats
play the danger cue before speech.

## Persistent monitoring and scheduled updates

Monitoring instructions are stored in SQLite and resume whenever NekoSuneAI is
started. Examples:

- `Track aircraft within 30 miles around Newcastle upon Tyne every 5 minutes and keep me posted.`
- `Monitor the weather forecast for Newcastle upon Tyne every 15 minutes until I tell you to stop.`
- `Keep me updated about weather warnings in Newcastle upon Tyne.`
- `List scheduled monitors.`
- `Stop monitor ab12cd34.`
- `Stop all monitors.`
- `Monitor UK government emergency broadcasts every 5 minutes and read them aloud.`

The first check is immediate. Later notifications are posted when data changes,
with an hourly unchanged heartbeat so the assistant remains visibly active
without repeating the same aircraft/weather payload every few minutes. The
minimum interval is 30 seconds to protect the Pi and public data providers.

Government emergency results are cleaned into a spoken announcement rather
than reading raw JSON. When `EMERGENCY_BROADCAST_TTS=true`, a new official
warning plays the configured warning/danger cue first and then reads the alert,
severity, affected-area information and official instructions through the
selected local or remote TTS engine. NekoSuneAI only announces what the bridge's
configured public government sources return; it does not imitate the UK's
mobile-network Emergency Alerts system or claim an alert is official without a
source result.

## Remote voice

Set `BRIDGE_WS_URL` to the authenticated bridge WebSocket (normally
`wss://host/ws`). Choose `bridge` for TTS and/or STT in Settings. The same Bridge
User bearer token from the first MCP entry authenticates WebSocket voice calls.
Piper/gTTS and Whisper then run remotely, avoiding heavy speech models on the Pi.

OAuth is used by `/mcp`; the bridge WebSocket currently uses its Bridge User
bearer token because that is the protocol exposed by `nekoai-bridge`.

### Fast streaming TTS

`BRIDGE_TTS_ENGINE=edge-stream` uses the bridge's Node-based
`edge-tts-universal` provider. Audio is sent to NekoSuneAI in chunks and, when
`ffplay` is available, playback begins while the remaining sentence is still
being generated. This avoids waiting for Piper to load a model and render a
complete WAV. Set an Edge neural voice such as `en-GB-SoniaNeural` in the
Remote voice field and adjust `BRIDGE_TTS_RATE` (default `+10%`).

Set `BRIDGE_TTS_ENGINE=piper` for fully offline speech. If streaming playback
is unavailable on the client, NekoSuneAI safely buffers the Edge MP3 and plays
it normally when complete. Edge Read Aloud is an online unofficial service, so
Piper remains the privacy/offline fallback.
