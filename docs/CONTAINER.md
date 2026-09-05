# Pi Proxy Container

Image: `ghcr.io/nekosuneprojects/nekosuneai:piproxy-1.2.1`.
Owning branch: `build/pi-proxy-release`. Backend uses `:release-1.2.1` instead.
No plain `:1.2.1` or shared `latest` tag is published by this workflow.

Push to the owning branch, or dispatch `Pi Proxy Image` on that branch, to smoke
test linux/amd64 and linux/arm64 and then publish `piproxy-<VERSION>` to GHCR.
The workflow uses the existing self-hosted Linux X64 Docker runner. It does not
move the backend's Git release tags. The image installs Pi Proxy requirements,
not the backend's model stack. Kinect extras and model downloads are not bundled.

## On a Raspberry Pi

Use 64-bit Raspberry Pi OS with Docker, host BlueZ and a working PulseAudio or
PipeWire-pulse session. The container talks to these host services; it does not
start a second Bluetooth/audio daemon.

```sh
mkdir -p data
cp config/pi-proxy-agent.example.json data/pi-proxy-agent.json
export PULSE_RUNTIME_DIR="/run/user/$(id -u)/pulse"
export PULSE_COOKIE_FILE="$HOME/.config/pulse/cookie"
docker compose -f compose.pi-proxy.yml pull
docker compose -f compose.pi-proxy.yml run --rm pi-proxy
```

Edit `data/pi-proxy-agent.json` with the backend URL and device settings before
running. Interactive first run asks for pairing ID/code and saves the token in
that bind-mounted directory. After pairing, Ctrl+C and start unattended:

```sh
docker compose -f compose.pi-proxy.yml up -d --no-build
```

`compose.pi-proxy.yml` also mounts `/dev/bus/usb` (with the matching
`device_cgroup_rules`) for Kinect camera support — harmless to leave in place
if you have no Kinect, or comment both out if you'd rather not grant USB
access at all. `kinect_vision_enabled` still defaults to `false`, and Kinect
extras (`opencv-python-headless`, `numpy`, libfreenect) still aren't bundled
in the image by default — see PiProxy/README.md's "Kinect camera" section.

Check that the Pulse socket, cookie and `/dev/snd` exist before starting. On
PipeWire configurations without a Pulse cookie, remove the cookie environment
variable and cookie mount from your local Compose file and configure host audio
socket access as needed. The service uses host networking for console discovery
and mounts the host D-Bus/audio sockets: run only on a trusted Pi. The read-only
status page is unauthenticated; do not expose port 8799 to the internet.

For a local source build instead of a published image:

```sh
docker compose -f compose.pi-proxy.yml build
```

`Dockerfile.pi-proxy.dockerignore` restricts the build context to source and the
example configuration. Never bake paired tokens, real configuration or host
audio credentials into the image. Persist config, generated sounds and optional
model files under `data/` using paths matching your configuration.

Actual ARM builds, Bluetooth, audio and pairing still require CI/Pi verification.
