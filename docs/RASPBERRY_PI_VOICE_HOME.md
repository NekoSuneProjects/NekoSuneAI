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

Select Alexa as the Raspberry Pi host output in the normal audio panel. After
that, NekoSuneAI handles the Docker side automatically.

On startup Docker mounts the host `/run/user` sessions read-only. The entrypoint:

1. scans all active user sessions,
2. finds a working PulseAudio/PipeWire socket,
3. detects the socket owner's UID/GID,
4. reads the host default sink,
5. configures `XDG_RUNTIME_DIR`, `PULSE_SERVER`/`PIPEWIRE_REMOTE`, and ffplay,
6. drops the app to the detected host audio user, and
7. lets PortAudio follow the host default speaker.

You normally **do not** need to set `PUID`, `PGID`, `AUDIO_GID`, `VIDEO_GID`,
`XDG_RUNTIME_DIR`, `PULSE_SERVER`, or `SPEAKER_DEVICE_INDEX` anymore.

Keep this enabled in `.env`:

```env
NEKOSUNEAI_AUTO_AUDIO=true
SPEAKER_DEVICE_INDEX=
MIC_DEVICE_INDEX=
```

The startup log should contain something like:

```text
[startup] Auto-detected host audio: PulseAudio/PipeWire session UID 1000; default sink: bluez_output....
[startup] Running NekoSuneAI as detected host audio UID:GID 1000:1000
```

If you intentionally need to override detection for an unusual host, the old
`PUID`, `PGID`, `XDG_RUNTIME_DIR`, `PULSE_SERVER`, and `PIPEWIRE_REMOTE`
variables remain optional compatibility overrides.

The dashboard shows the host default source/sink names. Leaving Speaker on
**System default** means Bluetooth reconnects and host default-sink changes are
followed without editing NekoSuneAI settings.

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

## 3. Wake word and dashboard

Set a long random `WEB_DASHBOARD_TOKEN`, then enable wake-word detection:

```env
WEB_DASHBOARD_TOKEN=replace-with-a-long-random-value
WAKE_WORD_ENABLED=true
WAKE_WORD_MODEL=hey_jarvis
WAKE_WORD_FRAMEWORK=onnx
WAKE_WORD_THRESHOLD=0.55
```

Start with `docker compose up -d` and open:

```text
http://RASPBERRY_PI_IP:8788/?token=YOUR_TOKEN
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
