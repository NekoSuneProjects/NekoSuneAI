## P2 - JARVIS / physical-world integration

Real-world features inspired by JARVIS that are practical with current hardware and software.
The AI should make high-level decisions while dedicated controllers enforce safety for motors,
locks, robotics and other physical systems.

### Room awareness & physical context

- [ ] Always-aware room assistant using distributed microphones/sensors and room nodes.
- [ ] Speaker/microphone-array direction finding so Neko can estimate which room/direction a request came from.
- [ ] 3D room mapping with optional depth camera/LiDAR support.
- [ ] Home digital twin mapping rooms, devices, sensors, doors and physical relationships.
- [ ] Object memory — remember where opted-in cameras last saw items such as keys, phone or controller.
- [ ] Natural object queries — `where did I leave my keys?` or `which camera last saw my phone?`.
- [ ] Gesture commands — configured hand gestures for stop, lights, music and other safe actions.
- [ ] Contextual pointing commands — combine room/location/vision so `turn that off` can target a visible device.
- [ ] Environmental awareness from temperature, humidity, CO2, air-quality, light and noise sensors.
- [ ] Automatic environmental adjustment for compatible lights, heating, fans, blinds and music.
### Computers, servers & network

- [ ] PC/server diagnostics — CPU, RAM, GPU, temperatures, storage, processes, Docker and network status.
- [ ] Predictive hardware warnings using temperature trends, SMART data, battery/UPS state and repeated errors.
- [ ] LAN awareness for the user's own devices — online/offline state, latency and local service reachability.
- [ ] Natural troubleshooting — `why is my PC slow?`, `why is the TV offline?`, `why did this container stop?`.
- [ ] Safe self-maintenance policies — restart failed Neko services/containers, reconnect Bluetooth or switch to configured fallbacks.
- [ ] Service dependency map so Neko can explain what depends on a failed service.
- [ ] Local AI fallback mode when Internet/cloud services are unavailable.
### Physical interfaces & displays

- [ ] JARVIS-style command-center dashboard showing Neko avatar, home, CCTV, weather, calendar, servers, phone, music and alerts.
- [ ] Wall-mounted Pi/tablet Neko terminals for rooms around the house.
- [ ] Projector dashboard mode for walls/desks as a practical hologram-like interface.
- [ ] Optional AR interface that can overlay device status/context onto a room using a compatible phone/headset.
- [ ] Spatial audio replies so Neko's voice can come from the most relevant room/speaker.
- [ ] LED/status-light integration showing listening, thinking, speaking, warning and offline states.
- [ ] Physical buttons/knobs via ESP32 for mute, stop, push-to-talk, room scenes and emergency disable.
### Sensors, electronics & maker integrations

- [ ] ESP32 sensor-node framework for cheap distributed motion, temperature, buttons, LEDs and custom sensors.
- [ ] Voice-controlled electronics bench — read approved serial/MQTT measurements and log results hands-free.
- [ ] GPIO bridge for safe Raspberry Pi input/output projects through explicit allowlisted actions.
- [ ] USB/serial device integration framework for custom meters/controllers.
- [ ] BLE sensor discovery for supported local environmental/beacon devices.
- [ ] Automatic sensor calibration reminders and stale-data detection.
### Robotics

- [ ] Generic robot integration API so Neko can issue high-level tasks to a separate safety controller.
- [ ] Mobile robot status/navigation requests for supported robots with collision avoidance handled outside the LLM.
- [ ] Robot charging-state awareness and `return to charger` high-level command.
- [ ] Robot-arm integration for predefined, safety-limited lightweight tasks.
- [ ] Hard motion boundaries, emergency-stop support and allowlisted robot actions.
- [ ] Drone telemetry integration for the user's own compatible drone — battery/GPS/status only by default.
- [ ] Optional safe high-level drone mission requests only when a dedicated flight controller enforces geofencing and safety.
### Proactive JARVIS-style intelligence

- [ ] `Neko, status report` combining house, PC/server, network, weather, phone, calendar, cameras and warnings.
- [ ] Daily JARVIS briefing with weather, calendar, house state, devices, overnight events and server health.
- [ ] Anomaly detection that learns normal device/sensor patterns and highlights unusual conditions.
- [ ] Event reconstruction — `what happened while I was asleep/out?` summarises opted-in local events.
- [ ] Predictive maintenance suggestions before devices/storage/batteries fail where evidence is strong enough.
- [ ] Context-aware proactive reminders based on devices, location, time and routines.
- [ ] Explainable proactive actions — Neko records why she suggested or executed an automation.
### Power, resilience & emergencies

- [ ] UPS integration — detect mains failure, battery runtime and charging state.
- [ ] Power-cut mode — reduce nonessential workloads and prepare configured systems for safe shutdown.
- [ ] Automatic graceful shutdown before UPS battery depletion.
- [ ] Recovery mode after power returns — staged service startup and health checks.
- [ ] Emergency command-center view showing which smoke/CO/leak/security sensor triggered and where.
- [ ] Priority emergency broadcast to selected speakers/displays/phones.
- [ ] Hardware emergency-disable switch that can stop Neko-controlled physical automations independently of the AI.

