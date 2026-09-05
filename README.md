# NekoSuneAI Pi Proxy

Container image: `ghcr.io/nekosuneprojects/nekosuneai:piproxy-1.2.1`.
See [container setup and publishing](docs/CONTAINER.md).

Pi Proxy is a lightweight paired node meant to run on a physical Raspberry
Pi. It handles Bluetooth speaker management and local audio capture/playback
for one room/device, and relays media and commands to the Docker/Pi backend
(which itself can run on a Pi, or on a more powerful VPS with more cores/GPU).
One backend can pair with several Pi Proxy installs at once -- one per
room/device.

Pi Proxy never runs a local LLM/vision/STT/TTS model. `audio.speak` and
`audio.listen` relay through the backend's existing
`/api/nodes/media/tts`/`/api/nodes/media/stt` endpoints. The one exception is
`music.play`: the backend hands this node a search query or a YouTube
URL/video id (not a pre-resolved stream URL), and Pi Proxy resolves it with
`yt-dlp` locally before playing it back, because YouTube's bot/cookie
verification blocks the datacenter/VPS IPs the backend may run from but not a
Pi's residential IP. The backend still decides what to play; Pi Proxy only
does the resolution step that has to happen from a residential IP, plus local
playback.

See [BRANCH_MAP.md](BRANCH_MAP.md), [AGENTS.md](AGENTS.md) and
[TODO.md](TODO.md) for the full product scope and status. This checkout
started as a full clone of the Docker backend's `main` branch so it could
reuse a handful of its modules as-is (Bluetooth, console control, Kinect
vision, alert sounds) — everything else from that clone (LLM/vision/RAG/
dashboard/etc.) has since been removed; see `TODO.md`'s "Legacy cleanup"
section for exactly what was kept and why.

## What's here

- `nekosuneai/pi_proxy_agent.py` -- the `PiProxyAgent`: pairs against the
  backend's `/api/nodes/register`, then loops
  `/api/nodes/heartbeat`/`/api/nodes/poll` and executes queued commands:
  `bluetooth.status`/`bluetooth.reconnect`, `audio.speak`/`audio.listen`,
  `music.play`/`music.stop`, `console.status`/`console.capabilities`/
  `console.command` (PS5/Xbox on the local network), `camera.status`/
  `camera.snapshot` (Xbox 360 Kinect). Also runs an optional wake-word
  listener and plays local alert sounds/offline TTS (see below).
- `nekosuneai/pi_proxy_web.py` -- a minimal, read-only, mobile-friendly local
  status page (pairing, Bluetooth, audio/music, wake word, console, camera,
  backend-reachable state, recent command log).
- `config/pi-proxy-agent.example.json` -- example config; copy it to
  `config/pi-proxy-agent.json` (gitignored) and fill in your server address.

## Wake word

Off by default (`wake_word_enabled: false` in config) — needs a real
microphone and a wake-word model file. When enabled, detection plays a short
acknowledgement chime (Alexa/Echo-style "I heard you"), then captures and
transcribes a short utterance through the backend's STT endpoint. Getting an
actual spoken *reply* back needs a backend endpoint that doesn't exist yet
(see `TODO.md`'s NODE-CONVERSE-01) — today this only detects, captures,
transcribes, and shows the transcript on the status page/command log.

## Kinect camera (lite vision)

Off by default (`kinect_vision_enabled: false`) — needs a real Xbox 360
Kinect and libfreenect installed. Runs a cheap local facial-expression/
posture cue (`local_affect.py`, a small ONNX model — see
`tools/setup_local_affect_model.py` to download it) entirely on-device, and
can relay a captured frame through the backend's `/api/nodes/media/vision`
endpoint for a fuller description (`camera.snapshot`) — Pi Proxy never calls
a vision provider directly itself. Needs `requirements-vision-lite.txt`
installed in addition to the base requirements. See
`docs/RASPBERRY_PI_VOICE_HOME.md` for this exact Pi + Kinect + Alexa
Bluetooth hardware combination.

## Console control (PS5/Xbox, local network)

`console_control.py`'s discovery/status/command logic only works from
something on the same LAN as the console — which Pi Proxy is, even when the
Docker backend itself is hosted on a VPS with no LAN path to your PS5/Xbox at
all. Exposed as `console.status`/`console.capabilities`/`console.command`.

## Alert sounds and offline fallback

Three short generated tones (`sounds/wake.wav`/`warning.wav`/`danger.wav`,
pure math/wave, no dependencies, never overwritten if you supply your own)
play for: wake-word acknowledgement, a restored backend connection (`wake.wav`
again), and a lost backend connection (`warning.wav`). If the backend's own
TTS is unreachable — including three consecutive missed heartbeats — Pi
Proxy falls back to a local `espeak-ng` announcement so it can still say
something instead of going silently mute. This does not make Pi Proxy a
local-TTS node in normal operation.

## Setup

```
pip install -r requirements-pi-proxy.txt
```

Also install these system tools through your OS package manager (not pip) --
Pi Proxy invokes them via subprocess instead of depending on a new Python
audio library:

```
sudo apt install pulseaudio-utils ffmpeg alsa-utils bluez espeak-ng
```

- `paplay` (falls back to `aplay`) plays TTS audio and any other WAV Pi Proxy
  is handed.
- `ffplay` (bundled with `ffmpeg`) plays the stream URL resolved for
  `music.play`, with no video output.
- `arecord` (from `alsa-utils`) captures the bounded local mic recording for
  `audio.listen`.
- `bluetoothctl`/`pactl` (BlueZ + PipeWire-pulse/PulseAudio) are what
  `bluetooth_watchdog.py` already uses for Bluetooth speaker detection and
  reconnect.
- `espeak-ng` is the offline fallback voice used only when the backend's own
  TTS is unreachable (see "Alert sounds and offline fallback" below).

Kinect camera support additionally needs `pip install -r
requirements-vision-lite.txt` and `libfreenect` installed via your OS package
manager — only if you actually have a Kinect.

Copy the example config and fill in your server address and per-node
settings (Bluetooth target device, audio capture length, web status port):

```
cp config/pi-proxy-agent.example.json config/pi-proxy-agent.json
```

## .env support

Same idea as the Docker backend's `.env`: copy `.env.example` to `.env` next
to `compose.pi-proxy.yml` and fill in whatever you'd rather set through the
environment than edit into the JSON config directly (handy for
compose/systemd deployments, secrets managers, etc.). `.env` values override
the JSON config *for that run only* — they're never written back into the
JSON file, so removing a line from `.env` just falls back to whatever the
JSON file already has. `compose.pi-proxy.yml` already loads `.env`
automatically (`env_file: .env`, optional); for a plain systemd/bare-metal
run, export the same variables in the unit file or source `.env` yourself
before starting the agent.

## First-run pairing

Run the agent once with no `device_token` saved yet and it will prompt
interactively, the same as the Windows Gaming Node:

```
python -m nekosuneai.pi_proxy_agent --config config/pi-proxy-agent.json
```

- If `server_url` is blank in the config, it asks for the server address
  first (works against a VPS-hosted backend too, no LAN discovery needed).
- It then asks for a **Pairing ID** and **Pairing code** (create one from the
  Docker backend's dashboard) and saves the returned device token back into
  the config file.

You can also pass pairing details directly on the command line for scripted
first-run setups:

```
python -m nekosuneai.pi_proxy_agent --config config/pi-proxy-agent.json \
  --pairing-id <id> --pairing-code <code>
```

Once paired, subsequent runs skip straight to the heartbeat/poll loop.

## Running unattended (systemd)

There is no installer script here yet (see `TODO.md`'s Packaging section --
that's a tracked, separate task). For now, run it unattended with your own
systemd unit invoking:

```
python -m nekosuneai.pi_proxy_agent --config /path/to/pi-proxy-agent.json
```

with `Restart=on-failure`.

## Local status page

If `web_status_enabled` is true in the config, a read-only status page is
served on `web_status_port` (default `8799`). It shows pairing state,
Bluetooth link status, whether audio/music is currently playing, and a
recent command log -- there is no control path on this page, only status, by
design (the same reasoning as the Windows agent's status page: don't create
a second, less-guarded way to trigger actions).

**Never forward this port to the public internet.** It is unauthenticated
and meant to be reached only from your own LAN (e.g. checking it from your
phone while on the same Wi-Fi).

## Emergency stop

Sending `SIGINT`/`SIGTERM` (e.g. Ctrl+C, or a normal systemd stop) to the
agent process immediately stops any active audio/music playback and disables
further audio commands before the process exits -- there is no desktop
hotkey listener on a Pi node, so the process signal is the local kill switch.
