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
- [ ] Raspberry Pi/Server Node.
- [ ] Weather Station Node.
- [ ] Robot/Robot Arm Node with safety-controller boundary.
- [ ] Future vehicle-telemetry node restricted to supported read-only/safe capabilities by default.

