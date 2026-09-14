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
- `nekosuneai/pi_proxy_web.py` -- a minimal, mobile-friendly local dashboard
  (pairing, Bluetooth, audio/music, wake word, console, camera,
  backend-reachable state, recent command log) plus owner controls: talk to
  Neko, push-to-talk, music, Bluetooth reconnect and a microphone picker.
- `nekosuneai/alsa_devices.py` -- resolves which ALSA capture device
  `arecord` should open, so command capture uses the same microphone the
  wake word was heard on rather than whatever holds the ALSA default.
- `nekosuneai/music.py` -- local music: yt-dlp resolution, a playback queue,
  and transport controls (pause/resume/skip/previous/volume). See
  [Music](#music) below.
- `config/pi-proxy-agent.example.json` -- example config; copy it to
  `config/pi-proxy-agent.json` (gitignored) and fill in your server address.

## Wake word

Off by default (`wake_word_enabled: false` in config) — needs a real
microphone and a wake-word model file. When enabled, detection plays a short
acknowledgement chime (Alexa/Echo-style "I heard you"), captures and
transcribes a short utterance through the backend's STT endpoint, then sends
that transcript to the backend's `/api/nodes/converse` and acts on the answer:
it speaks the reply (falling back to local espeak-ng if the backend returns no
audio) and runs any commands that came back — so "play some music" starts
music on this node's own speaker. See [docs/NODE_CONVERSE.md](docs/NODE_CONVERSE.md).

The dashboard's **Listen** button takes exactly the same path, so you can test
the whole loop without saying the wake word.

### Choosing the microphone

Command capture uses `arecord`. Which device it opens is resolved in this
order: an explicit `mic_alsa_device` in the config, the `hw:X,Y` embedded in
the wake-word listener's own resolved device name, a name match against
`arecord -l`, a Kinect preference, then a single unambiguous capture card. If
none of those settle it, the ALSA default is used.

Run `arecord -l` to see what the Pi has. If the wrong one is being picked —
common on a Pi with onboard audio, a USB mic and a Bluetooth speaker all
competing for the default — set it explicitly, using `plughw` (not `hw`) so
ALSA downmixes and resamples for you:

```json
"mic_alsa_device": "plughw:2,0"
```

An Xbox 360 Kinect's microphone array is a 4-channel device and *must* go
through `plughw`; asking it directly for the mono 16 kHz the backend's STT
endpoint requires just fails to open. The dashboard's microphone picker lists
the same devices and switches between them for the current run.

## Music

Music plays **here**, not on the Docker backend. Two reasons, both about where
the machine is:

- YouTube's bot/cookie verification blocks datacenter IPs. A VPS-hosted backend
  gets "confirm you're not a robot" and age-verification walls where this Pi's
  residential IP resolves the same video fine.
- The speaker is in your house. The backend's own player would put the audio
  out of a sound card in a datacenter.

So when this node is paired and online, the backend routes music requests here
as `music.*` commands and this node does the resolving and the playing. Ask the
backend (dashboard chat, or out loud to this node) for any of:

    play lofi hip hop        pause the music        skip this song
    stop the music           resume the music       previous track
    set volume to 40         turn the music up      what's playing

The dashboard has the same controls as buttons. A backend with no Pi Proxy
online falls back to its own player exactly as before.

Playback uses tools already in the image -- `yt-dlp` to resolve, `ffplay` to
play, `SIGSTOP`/`SIGCONT` to pause the stream reader, `pactl` for volume -- so
there is no extra dependency to install. The queue lives on this node so the
gap between tracks is a local resolve rather than a round trip to the backend;
the backend can hand over a whole playlist in one command.

See [docs/NODE_MUSIC.md](docs/NODE_MUSIC.md) for the capability list, how the
node is chosen when you have more than one Pi (`MUSIC_NODE_ID`), and the
protocol details.

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

If `web_status_enabled` is true in the config, a dashboard is served on
`web_status_port` (default `8799`). It shows pairing state, Bluetooth link
status, wake-word state and last transcript, the conversation so far, whether
audio/music is playing, the resolved microphone, console/camera status and a
recent command log. It also surfaces the failures that used to be invisible:
alert-sound generation errors, microphone capture errors and a wake-word
thread that died.

The controls (talk/listen, music, Bluetooth reconnect, microphone picker,
stop/re-enable audio) each map to a capability this node already implements
and the backend already policy-gates, so the page offers a local way to reach
them rather than new abilities. Two knobs bound it:

- `web_control_enabled: false` returns the page to being strictly read-only.
- `web_control_pin: "1234"` requires that PIN on every control request, for a
  LAN you don't fully trust. Unset by default.

**Never forward this port to the public internet**, with or without a PIN. It
is meant to be reached only from your own LAN (e.g. from your phone on the
same Wi-Fi).

## Emergency stop

Sending `SIGINT`/`SIGTERM` (e.g. Ctrl+C, or a normal systemd stop) to the
agent process immediately stops any active audio/music playback and disables
further audio commands before the process exits -- there is no desktop
hotkey listener on a Pi node, so the process signal is the local kill switch.
