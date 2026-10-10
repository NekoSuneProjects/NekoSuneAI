# Pi Proxy Sendspin Release

This branch owns the Sendspin sidecar image:

```text
ghcr.io/nekosuneprojects/nekosuneai:piproxy-sendspin-1.2.1
```

It is intentionally separate from the normal Pi Proxy and Kinect Pi Proxy images.

Audio path:

```text
Music Assistant
  -> Sendspin
  -> default ALSA output in the container
  -> host PulseAudio/PipeWire
  -> Bluetooth
  -> Alexa / Echo speaker
```

## Run

On the Raspberry Pi, start with a working PulseAudio/PipeWire-Pulse session.
Identify its actual runtime socket and cookie (do not assume username `pi`
or UID 1000):

```bash
pactl info
pactl get-default-sink
pactl list short sinks
bash scripts/detect-pulse-audio.sh
```

The discovery script populates `PULSE_RUNTIME_DIR` and
`PULSE_COOKIE_FILE` in `.env`. If your host has no cookie at that
path, resolve its actual authentication setup before starting Docker;
a missing bind-mount source may be created as a directory.

```bash
docker compose -f compose.pi-proxy-sendspin.yml pull
docker compose -f compose.pi-proxy-sendspin.yml up -d --force-recreate
docker compose -f compose.pi-proxy-sendspin.yml logs -f
```

Optional `.env` values:

```env
SENDSPIN_NAME=NekoSuneAI Living Room Pi
SENDSPIN_PORT=8937
PULSE_RUNTIME_DIR=/run/user/1000/pulse
PULSE_COOKIE_FILE=/home/pi/.config/pulse/cookie
```

The container stores its persistent identity under `./sendspin-data`.
Do not delete that directory unless you want Music Assistant to see a new player.

## Fix for "Audio device 'pulse' not found"

The old launch command passed `--audio-device pulse`. That ALSA plugin
name may not be in Sendspin's PortAudio device list, making the daemon
exit and restart indefinitely. The default output is already routed to
PulseAudio in `/etc/asound.conf`, so do not force the `pulse` name.

The corrected image/Compose launch omits `--audio-device` and leaves
volume control to Sendspin's software mixer rather than attempting
hardware volume adjustment through an ALSA/PulseAudio shim.

To inspect discovered outputs:

```bash
docker compose -f compose.pi-proxy-sendspin.yml run --rm \
  --entrypoint sendspin sendspin audio-devices list
```

To inspect the host PulseAudio server from the image:

```bash
docker compose -f compose.pi-proxy-sendspin.yml run --rm \
  --entrypoint pactl sendspin info
```

If the latter fails, fix the host session, socket mount, cookie, or
permissions. If it succeeds but Sendspin cannot open its default output,
inspect the device list and ALSA configuration before selecting a
specific output; check that `pactl get-default-sink` points to your
Bluetooth speaker and that it is connected.

**Important:** The Compose file uses the prebuilt `piproxy-sendspin-1.2.1`
image. Dockerfile changes require rebuilding/publishing that tag or
using a newer tag, while the Compose command change takes effect when
the container is recreated. The default ALSA mapping exists in the
already-published Dockerfile.


## PipeWire mixing with Pi Proxy

Sendspin is a Music Assistant playback endpoint. It is **not** a generic
audio-input mixer for Pi Proxy TTS and alerts. Both containers instead send
their audio to the host PipeWire-Pulse session. PipeWire mixes independent
streams (Music Assistant via Sendspin, Pi Proxy TTS/chimes, etc.) on the same
Echo Dot Bluetooth speaker; overlapping sounds are expected unless you enable
ducking/priority policy separately.

Both Compose configurations set `PULSE_SERVER=unix:/run/pulse/native` and
`PULSE_SINK` to the Echo Dot sink discovered on this host, currently
`bluez_output.7C_61_66_3E_5E_9C.1`. Change `PULSE_SINK` in the environment
if the Bluetooth adapter/sink name changes. The Pi Proxy sets
`SDL_AUDIODRIVER=pulseaudio` so its ffplay music and MP3 voice paths
use the PulseAudio server as well.

## Music Assistant protocol compatibility

The Sendspin Docker image uses a pinned Sendspin 7.5.0 dependency family,
and extends the older aiosendspin supported-command enum for
`seek` and `seek_relative` at image **build time**. No runtime
`docker exec ... pip install` or manual patch is required. The Docker build
fails if the compatibility patch cannot be imported.

To update the running image after GitHub Actions successfully publishes it,
pull the new image and recreate only the Sendspin service. Keep the
`--url ws://192.168.1.136:8927/sendspin` option from your **working**
unified Compose deployment: the standalone example here still defaults
to local/advertised server mode.

Keep Sendspin configured with `--hardware-volume false` and PortAudio's
`default` device. Do **not** switch to `--audio-device pulse` or
upgrade `aiosendspin` to major version 9 independently of Sendspin 7.5.0.
