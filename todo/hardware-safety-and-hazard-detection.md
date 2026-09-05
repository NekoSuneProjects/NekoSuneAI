## P2 - Hardware safety & hazard detection

Treat hazard detection as a deterministic safety layer around NekoSuneAI rather than relying on the language model to decide whether a dangerous condition is real.

### Hardware temperature & cooling monitoring

- [ ] Monitor CPU, GPU, SSD/NVMe, motherboard/chipset and other available hardware temperature sensors.
- [ ] Monitor fan RPM/pump RPM and detect stalled, disconnected or abnormally slow cooling devices.
- [ ] Track temperature trends and rate-of-rise, not just fixed maximum thresholds.
- [ ] Device-specific warning/critical thresholds instead of one global temperature limit.
- [ ] Detect sustained overheating versus short harmless temperature spikes.
- [ ] Warn when a component repeatedly thermal-throttles.
- [ ] Monitor server/rack/PC-case ambient temperature with external sensors where available.
- [ ] Detect unusually large temperature differences between internal components and room/enclosure sensors.
### Fire / smoke / thermal-risk sensors

- [ ] Integrate dedicated smoke and heat alarms through supported relay, MQTT, Home Assistant or approved local interfaces.
- [ ] Optional CO detector integration for room/home emergency awareness.
- [ ] ESP32 temperature/smoke-compatible sensor nodes for server racks, printer areas and other configured equipment zones.
- [ ] Optional thermal-camera/IR sensor integration for configured equipment, used as supporting evidence rather than the only fire detector.
- [ ] Detect rapid enclosure temperature rise and escalate independently of normal CPU/GPU temperature limits.
- [ ] Camera-based visible smoke/flame anomaly detection may provide an additional warning but must never replace certified smoke/heat alarms.
- [ ] Record which physical sensor triggered, its location and raw reading/state in the incident timeline.
### Power / electrical anomaly monitoring

- [ ] Monitor UPS voltage, load, battery health, runtime and fault state.
- [ ] Smart-plug/power-meter monitoring for configured equipment where reliable local telemetry exists.
- [ ] Detect abnormal sustained current/power draw compared with the device's learned/configured normal range.
- [ ] Detect equipment consuming power while it should be off or idle where state can be verified.
- [ ] Alert on repeated brownouts, unexpected mains loss or unstable UPS input.
- [ ] Optional current-clamp sensor nodes for circuits/equipment where appropriately installed.
- [ ] Never treat software power telemetry as a replacement for breakers, fuses, RCDs/GFCIs or electrical safety devices.
### Battery & charging safety

- [ ] Monitor available laptop/phone/UPS/portable-device battery temperature, charge rate and health telemetry.
- [ ] Detect abnormal battery temperature rise while charging where the device exposes trustworthy telemetry.
- [ ] Warn when a battery reports swelling/fault/health warnings through supported hardware APIs.
- [ ] Stop optional heavy workloads when a host battery reaches a configured critical thermal or power state.
- [ ] Treat unavailable battery-temperature telemetry as unknown rather than assuming the battery is safe.
### 3D-printer hazard watchdog

- [ ] Monitor commanded versus actual hotend/bed temperature.
- [ ] Detect continued heating when the heater should be off or temperature rises unexpectedly.
- [ ] Surface printer firmware thermal-runaway/heater-fault states immediately.
- [ ] Monitor printer enclosure temperature and external smoke/heat sensors where installed.
- [ ] Correlate printer power draw, temperature and camera events for better warnings.
- [ ] Optional high-confidence emergency pause/stop policy while keeping firmware thermal protection as the primary safety system.
- [ ] Never disable or bypass printer firmware thermal-runaway protection, heater limits or hardware safety systems.
### Water / environment hazards

- [ ] Water-leak sensor support near servers, printers, washing machines, sinks or other configured locations.
- [ ] Humidity/condensation warnings for electronics/storage areas when sensors are installed.
- [ ] Air-quality/VOC sensor support as an additional environmental warning source where useful.
- [ ] Sensor-offline/stale-data warning so missing safety telemetry cannot silently look normal.
### Alert levels & escalation

- [ ] Standard severity model: `INFO`, `WARNING`, `CRITICAL`, `EMERGENCY`.
- [ ] Example `WARNING`: unusually high temperature sustained beyond a configured duration.
- [ ] Example `CRITICAL`: extreme temperature combined with fan/pump failure or repeated thermal shutdown.
- [ ] Example `EMERGENCY`: dedicated smoke/heat alarm triggered or multiple independent sensors indicate a severe thermal event.
- [ ] Escalation cooldowns that avoid notification spam without suppressing worsening conditions.
- [ ] Voice, dashboard and Android emergency notifications with affected device/location and sensor evidence.
- [ ] Emergency alerts override normal do-not-disturb settings when the user enables that policy.
### Deterministic automatic safety actions

- [ ] Safety rules execute outside the LLM so confirmed critical sensor events do not wait for AI reasoning.
- [ ] Configurable first response: reduce AI/game/encoding workloads, stop benchmarks and pause nonessential Docker workloads.
- [ ] Gracefully stop autonomous gaming/streaming if Windows hardware reaches a configured critical state.
- [ ] Graceful OS shutdown for configured PCs/servers when trustworthy sensor rules indicate continuing dangerous overheating.
- [ ] Controlled shutdown of a 3D-print job through the printer's supported safety API where configured.
- [ ] Optional smart-plug power isolation only for explicitly allowlisted equipment and only under carefully configured rules; never from camera inference alone.
- [ ] Preserve dedicated alarm, firmware, UPS, breaker and hardware protection behaviour instead of attempting to replace it.
- [ ] Manual emergency-stop / disable control remains available independently of Neko's AI process.
### Safety dashboard & incident history

- [ ] Hardware safety dashboard showing temperatures, fans, power, smoke/heat alarms, UPS, batteries, leaks and sensor health.
- [ ] Per-device normal/warning/critical limits with editable defaults.
- [ ] Trend graphs for temperature, fan speed and power around an incident.
- [ ] Incident timeline containing warnings, sensor readings, automatic actions and recovery state.
- [ ] `Neko, why did you shut the PC down?` can explain the deterministic rule and sensor evidence that triggered it.
- [ ] Post-incident health check before automatically returning workloads/services to normal.
- [ ] Require user acknowledgement before automatically restarting hardware after a serious smoke/heat/electrical event.
- [ ] Peripheral Node capabilities such as `hardware.temperature`, `hardware.fan`, `power.current`, `safety.smoke`, `safety.heat`, `safety.leak`, `safety.alert`, and `safety.shutdown`.

