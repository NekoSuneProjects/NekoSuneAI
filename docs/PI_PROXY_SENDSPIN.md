# Pi Proxy + Sendspin + Bluetooth Alexa/Echo

This stack turns the Raspberry Pi running NekoSuneAI Pi Proxy into a real
Music Assistant player without requiring Chromecast, DLNA, AirPlay, or a
speaker that understands Music Assistant directly.

Audio path:

```text
Music Assistant
    -> Sendspin
    -> NekoSuneAI Pi Proxy host
    -> PulseAudio/PipeWire default sink
    -> Bluetooth
    -> Alexa / Echo speaker
```

YouTube stays separate and continues to use the Pi Proxy's existing local
`yt-dlp -> ffplay -> Bluetooth` path.

## Why Sendspin runs as a sidecar

The official Sendspin CLI currently requires Python 3.12+, while Pi Proxy uses
Python 3.11 for its wake-word/Kinect/audio runtime. Keeping Sendspin in its own
small container avoids destabilising the working Pi Proxy image.

The sidecar uses:

```text
ghcr.io/nekosuneprojects/nekosuneai:piproxy-sendspin-1.2.1
```

and shares the same PulseAudio/PipeWire socket/cookie as Pi Proxy, so it outputs
to the same default Bluetooth sink.

## Requirements on the Pi host

Your Echo/Alexa should already be paired and selected as the default audio sink
for Pi Proxy.

Useful checks:

```bash
pactl info
pactl list short sinks
pactl get-default-sink
```

If the Echo is not the default sink, select it first:

```bash
pactl set-default-sink YOUR_ECHO_SINK_NAME
```

## Start the Sendspin-enabled stack

From the NekoSuneAI stack directory:

```bash
docker compose -f compose.pi-proxy-sendspin.yml pull
docker compose -f compose.pi-proxy-sendspin.yml up -d
```

The Sendspin container uses host networking and advertises itself with mDNS.
It listens on port `8937` by default rather than Sendspin's usual `8927` so
it does not collide with another Sendspin/Music Assistant service on the same
physical host.

Optional `.env` overrides:

```env
SENDSPIN_NAME=NekoSuneAI Living Room Pi
SENDSPIN_PORT=8937
```

## First discovery in Music Assistant

In Music Assistant:

1. Keep the **Sendspin** Player Provider enabled.
2. Start/restart the Pi Sendspin sidecar.
3. Open **Players** / player settings.
4. A player named **NekoSuneAI Pi Proxy** (or `SENDSPIN_NAME`) should appear.
5. Enable it if Music Assistant asks.
6. Open that player's settings to see/copy its player ID.

The Sendspin identity is persisted in:

```text
./sendspin-data
```

Do not delete that directory unless you intentionally want Music Assistant to
see it as a brand-new player.

## Check logs

```bash
docker compose -f compose.pi-proxy-sendspin.yml logs -f sendspin
```

You should see the daemon listening/advertising and then a Music Assistant
connection.

## If it does not appear

Check the sidecar is running:

```bash
docker ps --filter name=sendspin
```

Check the listener:

```bash
ss -lntup | grep 8937
```

Check mDNS traffic is not blocked by host firewall/VLAN isolation. Music
Assistant and the Pi must be able to discover/reach each other on the LAN.

If discovery is impossible across VLANs, the official Sendspin client can also
connect directly to a Sendspin server URL; discovery/listening mode is used here
because it works cleanly when Music Assistant is installed as a Home Assistant
App and does not require exposing Music Assistant's internal Sendspin port.

## Music routing

NekoSuneAI supports both paths:

```text
"play my hardstyle playlist"
    -> Music Assistant when configured

"play GPF on YouTube"
    -> Pi Proxy yt-dlp -> ffplay -> Bluetooth Echo

Music Assistant unavailable/no match
    -> YouTube yt-dlp fallback on Pi Proxy
```


## Fix: "Default audio device not found"

The Sendspin sidecar is configured to use the ALSA `pulse` virtual device,
which forwards audio into the host PulseAudio/PipeWire server and therefore to
the same Bluetooth Echo sink used by Pi Proxy.

After updating the image, verify the host first:

```bash
pactl info
pactl get-default-sink
pactl list short sinks
```

Then verify the Pulse runtime directory that is being mounted:

```bash
echo "$XDG_RUNTIME_DIR"
ls -la "${XDG_RUNTIME_DIR:-/run/user/1000}/pulse"
```

If your host Pulse socket is not under `/run/user/1000/pulse`, set these in
the stack `.env`:

```env
PULSE_RUNTIME_DIR=/run/user/YOUR_UID/pulse
PULSE_COOKIE_FILE=/home/YOUR_USER/.config/pulse/cookie
SENDSPIN_AUDIO_DEVICE=pulse
```

Then recreate the sidecar:

```bash
docker compose -f compose.pi-proxy-sendspin.yml pull
docker compose -f compose.pi-proxy-sendspin.yml up -d --force-recreate sendspin
docker compose -f compose.pi-proxy-sendspin.yml logs -f sendspin
```

You can also test the audio device directly inside the container:

```bash
docker compose -f compose.pi-proxy-sendspin.yml run --rm --entrypoint sendspin sendspin audio-devices list
```

The output should contain the raw ALSA device `pulse`.
