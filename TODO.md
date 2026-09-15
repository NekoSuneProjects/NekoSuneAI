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
- [x] Full local music control (`nekosuneai/music.py`, `MusicController`),
      because the backend's own player resolves and plays on the *backend
      host* — a VPS that YouTube's bot/cookie check blocks, with its sound
      card in a datacenter rather than the owner's room. Adds `music.pause`,
      `music.resume`, `music.skip` (with `previous`), `music.volume` and
      `music.status` alongside play/stop, and a local playback queue so the
      gap between tracks is a local resolve rather than a backend round trip
      (`music.play` accepts `queries` for a whole playlist, and `queue: true`
      to append). A track that fails to resolve is skipped with a note instead
      of stranding the rest of the queue. Uses only what the image already
      installs: yt-dlp to resolve, ffplay to play, SIGSTOP/SIGCONT to pause the
      stream reader, `pactl` for volume. Pause reports itself unsupported on a
      host without those signals rather than silently doing nothing, and
      stopping a paused track sends SIGCONT first so `terminate()` is acted on.
      Music state is reported in the heartbeat so the backend can answer
      "what's playing" without queuing a command. Backend routing side is
      `main`'s `node_music.py`; see [docs/NODE_MUSIC.md](docs/NODE_MUSIC.md).
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
      **Gap now closed** (contract NODE-CONVERSE-01, backend side on `main`):
      detection no longer dead-ends at a logged transcript. `converse()` POSTs
      the transcript to the backend's new `/api/nodes/converse`, plays the
      returned TTS audio (falling back to local espeak-ng when the backend
      returns no audio, rather than answering with silence), and dispatches
      the commands that come back — so "play some music" now actually starts
      music on this node's own speaker. `listen_and_converse()` is shared by
      wake-word detection and the dashboard's Listen button so both take the
      same path. Verified against a stub backend, not yet on real hardware.
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

- [x] A minimal, same-network, mobile-friendly status page
      (`nekosuneai/pi_proxy_web.py`, modeled on
      `Windows/nekosuneai/web_status_server.py`) showing pairing state,
      Bluetooth link status, audio/music activity, recent command log,
      wake-word status/last transcript, console status, Kinect camera
      status, and backend-reachable/offline-mode status. This is Pi Proxy's
      "GUI mode" — deliberately kept to this lightweight page rather than
      also running the full backend's `webgui.py` locally, which would
      defeat the point of staying low CPU/RAM.
- [x] Owner controls on that page, no longer read-only: a conversation
      transcript with a text box and a Listen (push-to-talk) button, music
      search/play/stop, Bluetooth reconnect, an ALSA microphone picker, and
      stop/re-enable audio, plus full music transport (pause/resume, skip,
      previous, a volume slider and a now-playing readout). Every action maps
      to a capability this node already implements and the backend already
      policy-gates, so this adds a local way to reach them rather than new
      powers. Off with
      `web_control_enabled: false` (restores the previous read-only page),
      and `web_control_pin` adds a shared PIN for a less-trusted LAN. Still
      LAN-only — never forward the port to the internet. The page also now
      surfaces the failures that used to be invisible: alert-sound
      generation errors, microphone capture errors, and the resolved ALSA
      capture device.

## P0 — Audio device and reliability fixes

- [x] Command capture now targets a resolved ALSA device
      (`nekosuneai/alsa_devices.py`, used by `_record_wav` via
      `capture_device()`). `_record_wav` previously ran a bare `arecord` with
      no `-D`, so it always opened the ALSA *default* device while
      `wakeword.py` carefully resolved a specific PortAudio microphone — the
      wake word was heard on the USB/Xbox 360 mic and the command that
      followed was recorded from whatever held the default (onboard audio, or
      a Bluetooth speaker that had taken it over). Resolution order: explicit
      `mic_alsa_device` config, then the `hw:X,Y` embedded in the wake-word
      listener's own resolved PortAudio device name, then a name match against
      `arecord -l`, then a Kinect preference, then a single unambiguous card;
      it returns empty (and omits `-D`) rather than guessing between several.
      Addresses resolve to `plughw:` not `hw:` so ALSA downmixes/resamples the
      Kinect's 4-channel array into the mono 16 kHz the backend's STT endpoint
      requires — asking that device for `-c 1 -r 16000` directly just fails to
      open. `arecord` failures are now reported instead of silently swallowed.
- [x] Wake chime reliability: `alert_sounds_dir` resolves against the package
      rather than the process working directory (under a systemd unit a
      relative `sounds` wrote the generated chimes where the agent then could
      not find them, so the beep silently never played), chimes get their own
      `LocalAudioPlayer` so the chime and the spoken reply stop cutting each
      other off, and generation/playback errors surface on the status page
      instead of being swallowed.
- [x] The dashboard no longer stalls on startup: `http.server`'s own
      `server_bind()` calls `socket.getfqdn()` just to populate a
      `server_name` nothing here reads, which is a blocking reverse-DNS
      lookup. On a headless Pi with a slow or unreachable resolver that
      delayed the page answering anything by seconds (measured at ~9s per
      bind on one host). `_ThreadingHTTPServer` skips it.
- [x] Wake word could never start. `wakeword.py` resolves its microphone
      through `audio_input.resolve_input_device_info`, and the inherited
      `audio_input.py` was the full Docker backend's STT stack whose
      `_require_audio()` demanded **SpeechRecognition** before it would resolve
      anything. `requirements-pi-proxy.txt` deliberately does not install
      SpeechRecognition (this node relays STT to the backend and never runs it
      locally), so every start raised "Voice support is not installed. Install
      the optional extras with: pip install -r requirements-voice.txt" — naming
      a requirements file this branch does not even have — the wake-word thread
      died, and the status page reported that as the reason. `audio_input.py`
      is now just device enumeration/resolution and needs only sounddevice, so
      nothing extra has to be installed. `models.py` and `utils.py` existed
      solely to serve the removed STT code and are gone with it (`nekosuneai/`
      is down to 15 modules).
- [x] A speaker that connects in the wrong role is detected and recovered
      from. An Echo supports both Bluetooth directions, and when it connects as
      the audio *source* its card carries only telephony profiles
      (`audio-gateway`, `headset-*`) — so no playback sink can ever appear,
      however long the watchdog waits, because the Echo is treating the Pi as
      its output device. When BlueZ reports the device does advertise an A2DP
      Audio Sink, the roles were simply negotiated badly, so the watchdog
      reconnects once from this side to settle them — once per device, never in
      a loop, since repeatedly dropping a speaker someone is listening through
      would be worse than the fault. If that does not fix it the dashboard
      carries the manual remedy (remove the Pi in the Alexa app, "Alexa, pair
      Bluetooth", connect from the Pi). Documented in
      [docs/RASPBERRY_PI_VOICE_HOME.md](docs/RASPBERRY_PI_VOICE_HOME.md).
- [x] Echo Dot / Alexa A2DP: `_activate_a2dp_profile` guessed three hardcoded
      profile names (`a2dp-sink`, `a2dp-sink-sbc`, `a2dp_sink`). A card only
      accepts a name from its own codec-specific list — an Echo Dot can offer
      `a2dp-sink-sbc_xq` and `a2dp-sink-aac` and no plain `a2dp-sink` — so
      every guess was rejected, the card stayed on HFP/off, no sink was ever
      created, and the owner got "connected over Bluetooth, but its A2DP audio
      sink is not ready yet" indefinitely. It now reads the card's real
      profiles from `pactl list cards`, skips ones marked unavailable, and
      picks the highest-priority A2DP sink. The switch is also retried as the
      sink is awaited, because the card frequently does not exist yet on the
      first look. When it still fails, the reason is specific (on a headset
      profile / offers no A2DP at all / no card yet) and shows on the
      dashboard instead of the old unactionable message.
- [x] An unreachable audio server now checks the socket path before blaming
      the server. "Connection refused" reads as "the server is down" and sends
      the owner to a host session that is usually running fine; in a container
      the far more common cause is that the socket `PULSE_SERVER` names is not
      present, because Docker silently creates an empty directory when a
      bind-mount source is missing at container creation. The message now
      distinguishes: socket absent (listing what the directory does contain, or
      noting it is empty), path present but not a socket, and a real refusal
      from a live socket (where PULSE_COOKIE and the host service are the
      suspects).
- [x] The audio server is probed once at startup (`audio_server_probe`,
      `pactl info`) and the result shows on the dashboard. A dead audio
      session silences spoken replies, the wake chime and music as well as
      Bluetooth, but its first visible symptom was a speaker that never became
      ready — which reads as a Bluetooth fault and sends the owner to the
      wrong place entirely. The unreachable-server message now names
      `scripts/detect-pulse-audio.sh` (which already existed but was not
      discoverable at the moment of failure) and `loginctl enable-linger`,
      since the mounted socket almost always points at a UID with no live
      logind session on a headless Pi.
- [x] "No audio-server card" now says which of the several causes it is,
      instead of guessing at PULSE_SERVER for all of them. `_bluez_card`
      returned None identically whether pactl was missing, the server was
      unreachable, the server had no Bluetooth support, or the card simply
      belonged to another device — so the one message it produced was wrong
      most of the time. It now distinguishes: pactl absent; the server
      unreachable (quoting pactl's own stderr and PULSE_SERVER); a reachable
      server with no cards; a reachable server with cards but **none from
      Bluetooth** — the common headless-Pi case, where BlueZ reports
      `Connected: yes` forever because the audio server's Bluetooth module
      (`libspa-0.2-bluetooth` for PipeWire, `pulseaudio-module-bluetooth` for
      PulseAudio) was never installed; and Bluetooth cards existing for other
      addresses. Documented in
      [docs/RASPBERRY_PI_VOICE_HOME.md](docs/RASPBERRY_PI_VOICE_HOME.md).
- [x] A rejected device token is no longer reported as an outage. A 401/403
      from `/api/nodes/heartbeat` fell into the generic failure counter, so a
      node with a stale token announced "Connection to the main server has
      been lost. Running in offline mode." and the dashboard still said
      "paired" — sending the owner to look at their network when the backend
      was up and the pairing was the problem. `NodeUnauthorizedError` is now
      distinct: the dashboard shows "pairing rejected" with the actual remedy,
      it is announced once rather than every cycle, and the retry backs off to
      30s since retrying cannot fix it.
- [x] Bluetooth watchdog no longer thrashes: `_loop` runs a cheap
      still-connected/still-default check and only falls back to the full
      `reconnect_now()` when that fails, and `_set_default_sink` returns early
      when its sink is already the default. Previously every poll interval
      re-enumerated every paired device, re-set the default sink and
      re-attached every open stream with `move-sink-input` — audible as
      periodic dropouts on the speaker and a steady CPU cost on a Pi. The
      watchdog thread is also now actually stopped on shutdown.

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
- [x] First-run pairing from the node's own dashboard, so a second Pi needs
      no terminal: an unpaired node now boots, serves its page and waits there
      instead of refusing to start, and a **Pair this node** card takes the
      server address and pairing code and writes the device token into the
      config file (`pair_and_save`, rewriting only `server_url`/`device_token`
      so the rest of the owner's file is untouched). The interactive stdin
      prompt now only runs on a real TTY — under systemd or in a container it
      used to fail start-up outright. A failed attempt leaves any existing
      pairing intact. Documented in README's "First-run pairing"; the
      command-line flow still works for scripted installs.

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

- [x] Pi Proxy's own tests now exist (the inherited suite had been removed as
      not applicable): `test_alsa_devices.py`, `test_music.py`,
      `test_pi_proxy_converse.py` and `test_pi_proxy_web.py` — 49 passing, plus
      2 skipped on non-POSIX hosts where SIGSTOP/SIGCONT do not exist.
      `test_piproxy_image_tags.py` fails on this branch and on
      `build/pi-proxy-release` alike: the workflow's `smoke` job has no
      `strategy` key. Pre-existing and unrelated, but it means the image
      workflow is not what that test expects — worth a separate look.
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
