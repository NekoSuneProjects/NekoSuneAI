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

Select its A2DP output using the Raspberry Pi audio panel or `pactl`. Verify it
with `speaker-test` before starting Docker. Docker receives the host's
PulseAudio-compatible PipeWire socket; Bluetooth pairing remains managed by the
host so the container does not need privileged access to BlueZ or D-Bus.

Put the host user's IDs and audio group IDs in `.env` before starting Compose:

```bash
echo "PUID=$(id -u)" >> .env
echo "PGID=$(id -g)" >> .env
echo "AUDIO_GID=$(getent group audio | cut -d: -f3)" >> .env
echo "VIDEO_GID=$(getent group video | cut -d: -f3)" >> .env
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" >> .env
```

The dashboard shows the host default source/sink names. If Alexa is the host
default sink, leave Speaker on that named **System default** entry.

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

Use `MIC_DEVICE_INDEX` after checking NekoSuneAI's audio-device list. The
Compose file passes `/dev/snd` and `/dev/bus/usb` through. Kinect 360 is a
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
