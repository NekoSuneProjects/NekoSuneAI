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
