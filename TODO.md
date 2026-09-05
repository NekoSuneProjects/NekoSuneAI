# NekoSuneAI Pi Proxy TODO

- [x] Add dedicated container/Compose files and branch-scoped `piproxy-<VERSION>` publishing workflow with amd64/arm64 smoke gates.
- [ ] Verify CI publishes `piproxy-1.2.1` and test paired audio/Bluetooth on a real Pi container. See [container guide](docs/CONTAINER.md).

Owner checkout: `PiProxy/`
Product branch and PR target: `build/pi-proxy-release`
Scope: lightweight paired Raspberry Pi node — Bluetooth speaker management,
local audio capture/playback, relaying media/commands to the Docker backend,
its own status dashboard. No local LLM/vision/STT/TTS model inference — that
stays on the Docker backend (`main`), which this node treats as "wherever the
brain runs" (a Pi, or a more powerful VPS). Exception: yt-dlp/YouTube stream
resolution runs locally here, on purpose, because it needs a residential IP
(see the `music.play` item below) — this is the one heavy-ish thing Pi Proxy
does that Docker can't, not a scope creep.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and [AGENTS.md](AGENTS.md) before choosing
work. Shared contract IDs (PAIR-01, NODE-01, CONTEXT-01, HEALTH-01,
MEDIA-RELAY-01) identify a peer deliverable on the branch named in the map,
not an instruction to add that other product's code here.

This checkout started as a full clone of `main` on 2026 — see BRANCH_MAP.md's
"Legacy Files" note. Everything under `## Legacy cleanup` below tracks that.

## P0 — Pairing and core relay

- [x] Build `nekosuneai/pi_proxy_agent.py`: pairs against the Docker backend's
      existing `/api/nodes/register` (pairing_id + pairing_code -> device_token,
      same flow the Windows Gaming Node already uses), then loops
      `/api/nodes/heartbeat` (report telemetry) and `/api/nodes/poll` (receive
      queued commands), same as
      `Windows/nekosuneai/windows_gaming_agent.py`'s pattern. `node_type`:
      `"pi-proxy"`. Includes the same first-run interactive pairing prompt
      (server address + pairing_id/pairing_code) the Windows agent has.
- [x] Capability manifest: `bluetooth.status`, `bluetooth.reconnect`,
      `audio.speak`, `audio.listen`, `music.play` / `music.stop` (search
      query or YouTube URL/id in, local yt-dlp resolution, local playback).
- [x] `audio.speak`/`audio.listen` call the Docker backend's existing
      `/api/nodes/media/tts`/`/api/nodes/media/stt` endpoints, same
      request/response shape `Windows/nekosuneai/node_media_client.py` uses.
- [x] Local config file `config/pi-proxy-agent.example.json` committed
      (mirrors `Windows/config/windows-gaming-agent.example.json`'s shape);
      the real `config/pi-proxy-agent.json` is gitignored.
- [x] Reuse `nekosuneai/bluetooth_watchdog.py` as-is for reconnect logic,
      driven from `pi_proxy_agent.py` (built from `Config.from_env()` +
      this node's own config), not from Docker's `webgui.py`.
- [x] Local audio playback/capture: `pi_proxy_agent.py` wraps
      `paplay`/`aplay`/`arecord`/`ffplay` via subprocess rather than reusing
      `audio_control.py` (too tightly coupled to the full backend's
      multi-room/database state and STT stack to extract cleanly).
- [x] Emergency/local stop: a `threading.Event` kill-switch plus a
      SIGINT/SIGTERM handler that immediately stops any active
      audio/music playback and disarms further commands until re-enabled.
- [x] Wake word: `nekosuneai/wakeword.py` (`WakeWordListener`) wired into
      `pi_proxy_agent.py`. On detection: plays a short acknowledgement chime
      (`wake.wav`, see alert sounds below), pauses the wake-word stream so
      `arecord` can open the mic, captures a short utterance, and relays it
      through `/api/nodes/media/stt` the same way `audio.listen` does. Off by
      default (`wake_word_enabled: false`); needs a real microphone + wake-word
      model file. `numpy`/`sounddevice`/`openwakeword` added to
      `requirements-pi-proxy.txt`.
      **Known gap** (also listed under Docker's own TODO, contract
      NODE-CONVERSE-01): there is still no `/api/nodes/*` endpoint for a node
      to submit a transcript and get back an actual assistant reply
      (text/TTS/commands) — peripheral nodes today only report telemetry and
      execute commands the backend already decided to send. Wake word
      captures-and-transcribes today (and the transcript is visible on the
      status page/command log); "get an intelligent spoken answer back" still
      needs that new backend endpoint.
- [x] Kinect lite vision: `nekosuneai/kinect_vision_patch.py`
      (`KinectVisionService`) and `nekosuneai/local_affect.py`
      (`LocalAffectDetector`) kept, adapted to take this node's own config
      dict (its old `settings_dashboard_patch`/full-dashboard coupling
      removed, along with `install_kinect_vision_patch()`, which only
      monkey-patched `webgui.py`/`webserver.py`), and a `describe_callback`
      instead of calling `vision.py`'s `describe_image` directly (`vision.py`
      itself was removed — Pi Proxy never calls a vision provider directly).
      Capabilities `camera.status` and `camera.snapshot` added to
      `pi_proxy_agent.py`; `camera.snapshot` relays the captured JPEG through
      `/api/nodes/media/vision`, same shape
      `Windows/nekosuneai/node_media_client.py`'s `.vision()` uses. Off by
      default (`kinect_vision_enabled: false`); needs real libfreenect/Kinect
      hardware. `opencv-python-headless`/`numpy` stay in the separate
      `requirements-vision-lite.txt` (install only if a Kinect is actually
      present). Kept `tools/setup_local_affect_model.py` (downloads the small
      FER+ ONNX model `LocalAffectDetector` needs) and
      `tools/kinect_vision_bridge.py` (an alternate generic-USB-camera bridge
      script, kept as a fallback path for setups where the in-process
      libfreenect ctypes binding doesn't work). Kept
      `docs/RASPBERRY_PI_VOICE_HOME.md` — it already documents this exact
      hardware combination (Pi + Kinect 360 + Alexa Bluetooth).
- [x] Local console control: `nekosuneai/console_control.py` (PS5/Xbox
      discovery/status/command — network-based, needed on Pi Proxy's LAN
      rather than a VPS-hosted backend with no LAN path to the console; see
      BRANCH_MAP.md's CONSOLE-LAN-01) kept and wired into `pi_proxy_agent.py`
      as `console.status`/`console.capabilities`/`console.command`, calling
      its plain functions directly. `console_integration_patch.py` (the
      `webgui.py`/`webserver.py`/`media.py`/`youtube_music.py` monkey-patch)
      was NOT kept — none of those modules exist here. `database.py`/
      `paths.py` kept as real dependencies (console state persistence,
      sqlite3-based, lightweight).
- [x] Wake/warning/danger alert sounds: `nekosuneai/alert_sounds.py`
      (`ensure_default_alert_sounds` — pure math/wave/struct, no
      dependencies) kept and generates `wake.wav`/`warning.wav`/`danger.wav`
      into `alert_sounds_dir` (config key, default `sounds/`) on startup, never
      overwriting owner-supplied sounds of the same name. `wake.wav` plays on
      wake-word detection (see above) and again as a cheerful "back online"
      cue once a lost backend connection is restored.
- [x] Fallback local TTS: `audio.speak` tries the backend's real
      `/api/nodes/media/tts` first; if that call fails for any reason, it
      falls back to a local espeak-ng synthesis (`_speak_local_fallback`,
      system tool via subprocess, not a Python package) rather than silently
      failing. Separately, three consecutive failed heartbeats trigger a
      `warning.wav` alert plus a local espeak-ng announcement
      ("Connection to the main server has been lost. Running in offline
      mode.") — this does not make Pi Proxy a local-TTS node in normal
      operation, it only covers "the backend is genuinely unreachable".

## P0 — Local dashboard

- [x] A minimal, same-network, mobile-friendly, READ-ONLY status page
      (`nekosuneai/pi_proxy_web.py`, modeled on
      `Windows/nekosuneai/web_status_server.py`) showing pairing state,
      Bluetooth link status, audio/music activity, recent command log,
      wake-word status/last transcript, console status, Kinect camera
      status, and backend-reachable/offline-mode status. This is Pi Proxy's
      "GUI mode" — deliberately kept to this lightweight page rather than
      also running the full backend's `webgui.py` locally, which would
      defeat the point of staying low CPU/RAM.

## P0 — Packaging

- [ ] `requirements-pi-proxy.txt`: trim to what `pi_proxy_agent.py` and the
      reused modules actually import (requests, psutil, yt-dlp, whatever
      `bluetooth_watchdog.py`/audio modules need) — do not ship the full
      Docker backend's requirements.txt (LLM/vision/RAG deps) on a Pi node.
      yt-dlp is the one real exception (see the coordination note below) and
      belongs here, not on the backend's own requirements.
- [ ] A systemd unit / install script for running this unattended on boot on
      a real Raspberry Pi (this is the actual target device, not just "some
      Linux box" — note any Pi-specific quirks found, e.g. BlueZ/PipeWire
      versions on Raspberry Pi OS).
- [ ] Document first-run pairing (server address + pairing code entry) the
      same way as `Windows/docs/WINDOWS_MEDIA_AND_VRCHAT.md`'s "First-run
      pairing" section — no LAN discovery required, works against a
      VPS-hosted Docker backend too.

## P1 — Multi-device support

- [ ] Verify multiple Pi Proxy installs (different `node_id`s) can pair to
      the same Docker backend concurrently without clashing (this is the
      explicit "install on multiple devices" goal — one Pi Proxy per
      room/device, all talking to one central backend).
- [ ] Per-node Bluetooth target device config so each Pi can be paired to a
      different speaker.

## Legacy cleanup — done

`nekosuneai/` is now down to exactly: `pi_proxy_agent.py`, `pi_proxy_web.py`,
`bluetooth_watchdog.py`, `config.py`, `performance.py`, `wakeword.py`,
`audio_input.py`, `models.py`, `utils.py`, `console_control.py`,
`database.py`, `paths.py`, `alert_sounds.py`, `kinect_vision_patch.py`,
`local_affect.py`, `__init__.py`, `__main__.py` (repointed at
`pi_proxy_agent.main`) — verified with a real `import nekosuneai.pi_proxy_agent;
import nekosuneai.pi_proxy_web` after every deletion pass, not just `ast.parse`.

Removed: every other inherited module (`webgui.py`, `webserver.py`,
`launcher.py`, `bootstrap.py`, `engine.py`, `cli.py`, `monitors.py`,
`routines.py`, `reminders.py`, `games/`, `vision.py`, `defaults.py`,
`storage.py`, `audio_control.py`, all `*_patch.py` files including
`console_integration_patch.py`, and everything else not listed as kept
above); top-level `Dockerfile`/`docker-compose.yml`/`docker-compose.mobile.yml`/
`docker-entrypoint.sh`/`.dockerignore`, `.env.example`/`.env.docker.example`,
the full `requirements.txt`/`requirements-gui.txt`/`requirements-voice.txt`/
`requirements-wakeword.txt`/`requirements-windows-agent.txt` (superseded by
`requirements-pi-proxy.txt` + `requirements-vision-lite.txt`), `app.py`,
`setup.py`, `NekoSuneAI.spec`, `install.sh`/`install.ps1`, `BUILD.md`,
`CHANGELOG.md`, `package.json`, `.gitlab-ci.yml`, `assets/`, top-level
`audio/`, `data/`, `test/` (the whole inherited suite — none of it tested Pi
Proxy's own modules), `.github/`/`.gitea/`, `packaging/` (full-desktop-app
`.desktop`/installer scripts, not relevant to a headless Pi service),
`nekosuneai/static/` and top-level `static/` (dashboard web UI, including
`consoles.html` which only made sense with the now-removed
`console_integration_patch.py`), `tools/yt_search.js`, and the
Docker-dashboard-specific docs (`docs/CONFIGURATION.md`,
`GAME_SKILLS_AND_REMOTE_PLAY.md`, `MCP_BRIDGE.md`, `PI_MUSIC_AND_SCHEDULES.md`,
`PROFILES.md`, `SAFETY_AND_BRIEFINGS.md`, `SETUP.md`, `SMART_HOME_MQTT.md`,
`VOICE_TONE_HOOK.md`, `WINDOWS_GAMING_AND_TWITCH.md`).

Kept beyond the code itself: `docs/NODE_MEDIA.md` and
`docs/PERIPHERAL_NODES_AND_ROUTINES.md` (document the shared `/api/nodes/*`
protocol this node relies on), `docs/RASPBERRY_PI_VOICE_HOME.md` (already
covers this exact Pi + Kinect 360 + Alexa Bluetooth hardware combination),
`tools/kinect_vision_bridge.py` + `tools/setup_local_affect_model.py` (see
the Kinect item above), `LICENSE`, `TRADEMARKS.md`, `VERSION`,
`.python-version`.

- [ ] Write Pi Proxy's own tests for `pi_proxy_agent.py`/`pi_proxy_web.py`
      (none exist yet — the inherited suite was removed as not applicable).
- [ ] No CI workflow was inherited onto this branch (`.github`/`.gitea` were
      removed as Docker-image-build-specific) — a Pi-Proxy-specific
      packaging/CI workflow is still needed, not written yet.

## Coordination note (2026, PI-PROXY split)

The Docker/`main` side removed its own always-on Bluetooth watchdog startup
as part of this split (it was contributing to sustained high CPU/RAM on a
Pi-hosted deployment) — see `main`'s own TODO for that change. A Docker
deployment that has NOT set up a Pi Proxy node loses automatic Bluetooth
speaker reconnect until either Pi Proxy is deployed, or the owner
re-enables Docker's legacy in-process watchdog manually (see `main`'s
webgui.py for the flag). This is intentional: Bluetooth hardware access is a
Pi Proxy responsibility going forward, not the backend's.
