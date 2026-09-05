# Pi Proxy Branch Instructions

This checkout owns: the lightweight Raspberry Pi node — local Bluetooth
speaker management, local audio capture/playback, and relaying media
(vision/STT/TTS) and command execution to the Docker/Pi backend. It never
runs a local LLM/vision/STT/TTS model; the Docker backend (which can run on a
VPS with more cores/GPU) does that. The one deliberate exception is yt-dlp:
Pi Proxy resolves YouTube/media streams locally, on the Pi's own residential
IP, because YouTube's bot/cookie checks block datacenter/VPS IPs — a
VPS-hosted backend genuinely cannot do this reliably itself. The backend
still decides what to play; Pi Proxy resolves the stream and plays it back.
Its product branch and PR target is `build/pi-proxy-release`.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and this branch's [TODO.md](TODO.md) before
selecting or implementing work. Every local TODO item inherits this owner.

- Check `git rev-parse --show-toplevel`, `git branch --show-current` and
  `git status --short` before editing. Verify a feature branch was based on
  this product branch; a matching folder name alone is not enough.
- Keep this branch focused on the Pi-side node: pairing, Bluetooth, local
  audio, its own status dashboard, and calling the Docker backend's existing
  `/api/nodes/*` and `/api/nodes/media/*` endpoints. Do not add LLM/vision/
  RAG/yt-dlp/model-provider logic here — that belongs on `main`.
- This checkout started as a full clone of `main`, so it still carries the
  rest of the Docker backend's modules unused. Do not build new Pi Proxy
  features on top of them (`webgui.py`, `webserver.py`, the LLM/vision/RAG
  stack, etc.) — those are legacy holdovers pending a scoped removal, not
  source of truth for this product. `bluetooth_watchdog.py` and the audio
  helpers (`audio_control.py`, `audio_input.py`) are the pieces actually kept.
- Do not merge this branch into `main` or `main` into this branch wholesale.
  Port only explicitly required, scoped protocol changes (e.g. a new
  `/api/nodes/media/*` field both sides need to agree on).
- Keep TODO status, tests and commits scoped to this product. Preserve other
  uncommitted work, including changes from another assistant.
- Report the owning branch, what was verified, and any peer-branch or
  deployment work still required. Do not equate a local run with a live,
  paired Pi actually reconnecting a real Bluetooth speaker.
