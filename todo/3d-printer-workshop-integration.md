## P2 - 3D printer / workshop integration

### Printer connectivity & control

- [ ] OctoPrint integration for printer status, jobs, temperature, camera and safe control actions.
- [ ] Klipper/Moonraker integration for Klipper-based printers.
- [ ] PrusaLink/Prusa Connect support where APIs permit it.
- [ ] Bambu-style LAN/API integration where supported, keeping cloud login optional when possible.
- [ ] Generic printer adapter interface so additional printer brands can be added without changing core assistant logic.
- [ ] Multi-printer dashboard showing idle/printing/paused/error/offline state, progress and estimated finish time.
- [ ] Natural commands such as `how is my print?`, `pause the printer`, `what temperature is the nozzle?`, and `which printer is free?`.
- [ ] Require explicit confirmation before starting a print, homing axes, heating or other actions that can move/hot-end hardware.
- [ ] Never allow the LLM to bypass printer firmware limits, thermal protection, endstops or emergency-stop behaviour.
### Print monitoring & vision

- [ ] Printer-camera monitoring via the printer/NVR/RTSP camera.
- [ ] Optional local failed-print/spaghetti detection and warning.
- [ ] Configurable auto-pause on high-confidence print failure, with user opt-in and clear reason logging.
- [ ] Layer-shift, detached-print and obvious filament-tangle alerts where computer vision can identify them reliably.
- [ ] `Neko, does my print look okay?` live snapshot analysis.
- [ ] Print-event snapshots on start, warning, pause, failure and completion.
- [ ] Timelapse trigger/integration where the printer stack already supports it.
### Filament, maintenance & planning

- [ ] Filament/spool inventory with material, colour, remaining weight and printer assignment.
- [ ] Estimate filament remaining/used from slicer or printer job metadata.
- [ ] Warn before a job if the selected spool is unlikely to contain enough filament.
- [ ] Track nozzle/runtime hours and configurable maintenance intervals.
- [ ] Maintenance reminders for lubrication, nozzle inspection, bed cleaning and other user-defined tasks.
- [ ] Print history containing job duration, material use, failures and completion status.
- [ ] Power/energy monitoring for compatible smart plugs/printers.
- [ ] Enclosure temperature/humidity monitoring when sensors exist.
- [ ] Compare printer build volume/material compatibility before suggesting which printer to use.
- [ ] Optional slicer metadata import from G-code/3MF without automatically executing untrusted files.

