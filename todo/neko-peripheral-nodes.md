## P2 - Neko Peripheral Nodes

Build a reusable hardware capability protocol instead of hardcoding every future device into the core AI.
A node registers its identity, permissions, state and a strict set of capabilities Neko is allowed to call.

- [x] Generic authenticated node registration/pairing system.
- [x] Capability manifest such as `printer.status`, `printer.pause`, `camera.snapshot`, `display.notify`, `sensor.temperature`, `device.battery`, `audio.speak`.
- [x] Per-capability permission/confirmation policy.
- [x] Read-only vs state-changing capability classification.
- [x] Node heartbeat, latency, battery and online/offline status.
- [ ] Local WebSocket/MQTT/HTTP transport adapters with encryption/authentication.
- [ ] Remote transport option through the existing bridge without exposing unauthenticated LAN controls.
- [x] Dashboard for connected nodes, capabilities, permissions and last activity.
- [ ] 3D Printer Node.
- [ ] CCTV/NVR Node.
- [ ] ESP32 Sensor Node.
- [ ] Raspberry Pi/Server Node. (In progress as its own product/branch: see `PiProxy/` checkout, branch `build/pi-proxy-release`, per BRANCH_MAP.md. It pairs via the existing `/api/nodes/register` flow like the Windows Gaming Node, and is intentionally "lite" — no local LLM/vision/STT/TTS model inference and no yt-dlp/media resolution, only Bluetooth speaker management, local audio capture/playback, and relaying to this backend's existing `/api/nodes/media/*` endpoints — so a physical Pi stays low CPU/RAM even while this backend does the actual heavy lifting, which can now run anywhere including a VPS with more cores/GPU. As part of this split, this backend's own always-on Bluetooth reconnect watchdog (`webgui.py`'s `BluetoothSpeakerWatchdog` startup) was found forced on by `docker-compose.yml` (`BLUETOOTH_RECONNECT_ENABLED` defaulted to `true` there despite defaulting to `false` in `config.py`) and was contributing to sustained high CPU on a Pi-hosted deployment; it's now off by default in both places and only starts if a deployment explicitly re-enables it for a single-box setup with no separate Pi Proxy.)
- [ ] Weather Station Node.
- [ ] Robot/Robot Arm Node with safety-controller boundary.
- [ ] Future vehicle-telemetry node restricted to supported read-only/safe capabilities by default.

