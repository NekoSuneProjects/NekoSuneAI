# NekoSuneAI — Roadmap / TODO

Tracking the push toward full **Neuro-sama-style** capability, VRChat-first. This
file was rewritten from scratch after a round of cleanup — most of what used to
be here is either done differently now or gone (Image Review, built-in Radio).

## ✅ Done (this push)

- **RVC voice for normal chat** (`nekosuneai/rvc.py`) — optional real-time RVC
  voice-conversion pass over every spoken reply (not just singing), with a Pitch
  control and a couple of standard RVC knobs (index rate, protect) in Settings →
  Voice. Forces non-streaming XTTS synthesis since the whole line has to render
  before it can be converted.
- **Radio removed** (`nekosuneai/media.py`) — the built-in station directory +
  internet-radio.com search are gone. Music search/streaming (SoundCloud, plus
  Spotify/Deezer browser search) stays, and is where a future YouTube
  search/download provider will slot in (see Deferred below).
- **Image Review removed** — the manual "upload a picture and react" 🖼️ feature
  is gone. Vision is VRChat-first now: the OSC driver's per-tick screen caption
  (`games/vrchat.py`) goes through the same `vision.describe_image()` dispatcher
  Watch & React uses, so it gets the Ollama-then-OpenAI-vision fallback too.
- **Sticky wake-instructions + memory reset** (`nekosuneai/sticky.py`) — replaces
  the old `/remember <fact>` command (long-term memory was already automatic).
  Say the companion's name + a standing rule ("NekoSuneAI, always speak to me in
  0s and 1s") and it sticks until you say "stop"; say "reset"/"clear" to cancel
  that **and** wipe long-term RAG memory back to blank.
- **Thinking music** (`nekosuneai/media_player.py`) — an optional short cue that
  plays only during a noticeably long wait (slow local LLM turn, game-agent
  tick), never interrupting music you're already playing, and stops the instant
  the reply/action is ready.
- **OSC chatbox paging** (`games/vrchat.py`) — long `say` text is split across
  multiple `/chatbox/input` sends with `(N/M)` markers instead of being
  truncated at ~140 chars.
- **VRChat friends system** (`games/vrchat_friends.py`) — opt-in, credential-
  gated: auto-accepts friend requests, watches friend online/offline via a live
  `pipeline.vrchat.cloud` websocket, and sends a paged thank-you chatbox message.
  Uses VRChat's **unofficial** web API — ToS-risky for the account, off by
  default, needs real credentials to do anything.
- **VRChat embodiment** (`games/vrchat.py`, `vrchat_logs.py`) — OSC send **and**
  receive (Velocity/Grounded pose), wall + ledge awareness, strafe/run/look
  verbs, typing indicator, and free world + "who's here?" awareness by parsing
  VRChat logs.
- **Watch & React mode** — NekoSuneAI periodically glances at the live screen
  (desktop-wide, not VRChat-specific) and reacts in character, posting to chat +
  voice.
- **Per-language TTS voice** — auto-detects each reply's language (Kana/Hangul/
  CJK/Cyrillic/Arabic/Devanagari + langdetect) and speaks it in that language.
  Settings → Voice.

## 🔜 Deferred (heavier ML deps / bigger lift / opt-in)

### VRChat (from the NekoSuneAI reference implementation)
- [ ] **A* dead-reckoning navigation** — estimate position/heading from received
      Velocity, occupancy grid + pathfinding, "go to X", frontier exploration,
      per-world persisted maps. (`nav/navigator.py`, `world.py`, `locomotion.py`)
- [ ] **YOLO/ONNX screen object detection** — `person` detection with
      angle/closeness, feed obstacles into the nav grid. Heavy (onnxruntime +
      model); make opt-in. (`vision/system.py`)
- [ ] **RapidOCR nameplate reading** — read on-screen player nameplates to greet
      people by name (VRChat logs already give world/instance player lists;
      this would add nameplate-level precision during direct interaction).

### Media
- [ ] **YouTube search + download for music** — replace the open-a-browser
      fallback in `_handle_music_request()` (`nekosuneai/media.py`) with an
      in-app yt-dlp-backed search/download/stream path, reusing the same
      pattern `singing.py` already uses for backing tracks.

### Broader Neuro-sama parity
- [ ] **Voice-per-language profiles** — beyond language code, pick a distinct
      cloned voice per language (builds on the per-language TTS that now
      ships).
