# Raspberry Pi voice, Kinect 360, Alexa Bluetooth and Home Assistant

## 1. Prepare host audio

Pair the Alexa as a Bluetooth speaker on the Raspberry Pi host, not inside the
container. Say **“Alexa, pair Bluetooth”**, then use `bluetoothctl`:

```bash
bluetoothctl
power on
agent on
default-agent
scan on
# use the Alexa MAC shown by scan
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
```

Select Alexa as the Raspberry Pi host output in the normal audio panel.

Unlike the Docker/`main` backend, Pi Proxy's `Dockerfile.pi-proxy` has no
auto-detecting audio entrypoint (no session scanning, no UID auto-detection,
no privilege drop) — `compose.pi-proxy.yml` mounts the host's PulseAudio/
PipeWire session statically, assuming it belongs to UID 1000 (the default
`pi` user):

```yaml
environment:
  PULSE_SERVER: unix:/run/pulse/native
  PULSE_COOKIE: /run/pulse-cookie
volumes:
  - ${PULSE_RUNTIME_DIR:-/run/user/1000/pulse}:/run/pulse:ro
  - ${PULSE_COOKIE_FILE:-/home/pi/.config/pulse/cookie}:/run/pulse-cookie:ro
```

If the Bluetooth watchdog logs `Command '['pactl', ...]' timed out after 15
seconds`, the mounted socket almost always isn't a live server. Diagnose on
the host itself (not inside the container) **as the `pi` user, not root** —
`id -u`/`pactl info` run as root check root's own (nonexistent) audio
session at `/run/user/0/`, not `pi`'s at `/run/user/1000/`, and will fail
even when `pi`'s session is perfectly fine:

```bash
sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 pactl info      # must succeed
ls -l /run/user/1000/pulse/native                          # must exist as a socket
loginctl show-user pi -p Linger                             # Linger=no means this
                                                             # disappears once nobody
                                                             # is logged in as pi
```

Two common headless-Pi causes, often together:

1. `/run/user/<uid>/` only exists while that user has an active `logind`
   session, so a Pi that boots straight into background services with
   nobody ever logged in as `pi` may never create it:

   ```bash
   sudo loginctl enable-linger pi
   sudo systemctl status user@1000.service   # enable-linger doesn't always start
   sudo systemctl start user@1000.service    # it immediately -- start it directly if inactive
   ```

2. Even with that session running, PipeWire/PulseAudio itself may never have
   started — normally something a desktop login triggers, which never
   happens on a Lite/headless install. Enable it for `pi` directly:

   ```bash
   sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 systemctl --user enable --now pipewire pipewire-pulse wireplumber
   ```

Re-run the `pactl info` check above after each step until it succeeds, then
restart the Pi Proxy container.

If your host user's UID isn't 1000 or its home isn't `/home/pi`, set
`PULSE_RUNTIME_DIR`/`PULSE_COOKIE_FILE` in `.env` (or as shell env before
`docker compose up`) to match reality instead of the defaults above --
`scripts/detect-pulse-audio.sh` does this for you instead of guessing by
hand: it scans `/run/user/*/pulse/native` for a socket that actually answers
`pactl info`, then writes the matching `PULSE_RUNTIME_DIR`/
`PULSE_COOKIE_FILE` into `.env`.

```bash
chmod +x scripts/detect-pulse-audio.sh   # first time only
./scripts/detect-pulse-audio.sh
```

Re-run it any time the host's audio-session user changes (a different user
logs in, or you move the speaker setup to a different Pi account) --
`compose.pi-proxy.yml`'s own defaults (UID 1000, `/home/pi`) still work fine
unmodified for the common case where `pi` is that user.

## 2. Kinect 360 microphone

The Xbox 360 Kinect needs its USB/power adapter. Install host support:

```bash
sudo apt update
sudo apt install -y libfreenect-bin libfreenect-dev pulseaudio-utils alsa-utils
arecord -l
pactl list short sources
```

If Kinect is listed by `arecord -l` but not by `pactl`, make it available to
PipeWire/PulseAudio or select its ALSA entry in the dashboard. If neither
command lists it, check the Kinect power/USB adapter and host driver before
restarting the container.

Kinect 360 normally exposes four capture channels. NekoSuneAI auto-detects
that layout and sends channel 0 to wake-word/STT. To set it explicitly:

```env
MIC_SAMPLE_RATE=16000
MIC_INPUT_CHANNELS=4
MIC_CHANNEL_INDEX=0
```

The Compose file passes `/dev/snd` and `/dev/bus/usb` through. Kinect 360 is a
libfreenect device; do not install libfreenect2, which is for Kinect v2.

## 3. Wake word and status page

Enable wake-word detection:

```env
WAKE_WORD_ENABLED=true
WAKE_WORD_MODEL=hey_jarvis
WAKE_WORD_FRAMEWORK=onnx
WAKE_WORD_THRESHOLD=0.55
```

Start with `docker compose -f compose.pi-proxy.yml up -d` and open the
read-only status page (no token — see `AGENTS.md`'s note that this is
deliberately the lightweight view, not the full Docker backend dashboard):

```text
http://RASPBERRY_PI_IP:8799/
```

`hey_jarvis` is the bundled model name, not a custom “Neko” model. For a custom
phrase, train/download an openWakeWord ONNX/TFLite model, mount it into the
container, and put its path in `WAKE_WORD_MODEL`. Increase the threshold to
reduce false activations; lower it carefully if the Kinect misses your voice.
Use `onnx` on Raspberry Pi; `tflite` is optional and can fail when its native
runtime wheel does not match the Pi OS/Python combination.

## 4. Home Assistant

Enable the MQTT integration and Mosquitto broker in Home Assistant, then set
`HA_MQTT_HOST`, port, username and password. NekoSuneAI publishes retained MQTT
discovery records, an availability signal, a status sensor, a command text
entity and a Wake-and-listen button. No Home Assistant custom component is
required.

Keep MQTT and the dashboard on a trusted home network. Do not expose port 8788
or an unauthenticated MQTT broker directly to the internet.
