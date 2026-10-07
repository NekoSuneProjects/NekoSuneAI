# Pi Proxy Sendspin Release

This branch owns only the Sendspin sidecar image:

```text
ghcr.io/nekosuneprojects/nekosuneai:piproxy-sendspin-1.2.1
```

It is intentionally separate from the normal Pi Proxy and Kinect Pi Proxy images.

Audio path:

```text
Music Assistant
  -> Sendspin
  -> host PulseAudio/PipeWire
  -> Bluetooth
  -> Alexa / Echo speaker
```

## Run

```bash
docker compose -f compose.pi-proxy-sendspin.yml pull
docker compose -f compose.pi-proxy-sendspin.yml up -d
docker compose -f compose.pi-proxy-sendspin.yml logs -f
```

Optional `.env` values:

```env
SENDSPIN_NAME=NekoSuneAI Living Room Pi
SENDSPIN_PORT=8937
SENDSPIN_AUDIO_DEVICE=pulse
PULSE_RUNTIME_DIR=/run/user/1000/pulse
PULSE_COOKIE_FILE=/home/pi/.config/pulse/cookie
```

The container stores its persistent Sendspin identity under:

```text
./sendspin-data
```

Do not delete that directory unless you want Music Assistant to see a brand-new player.

## Bluetooth / PulseAudio check

On the Pi host:

```bash
pactl info
pactl get-default-sink
pactl list short sinks
```

The default sink should be your Bluetooth Alexa/Echo sink.

To inspect Sendspin devices:

```bash
docker compose -f compose.pi-proxy-sendspin.yml run --rm \
  --entrypoint sendspin sendspin audio-devices list
```

The raw ALSA device `pulse` should be available.
