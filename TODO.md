# NekoSuneAI — Roadmap / TODO

Tracking the push toward full **Neuro-sama-style** capability. Big-ticket items are
already in; this file records what's done and what's deferred (with the *why*).

## ✅ Done (this push)

- **VRChat embodiment** (`nekosuneai/games/vrchat.py`, `vrchat_logs.py`) — OSC send **and**
  receive (Velocity/Grounded pose), wall + ledge awareness, strafe/run/look verbs, typing
  indicator, and free world + "who's here?" awareness by parsing VRChat logs.
- **Image review** (`nekosuneai/vision.py`) — NekoSuneAI looks at an uploaded image, reads any
  text, and gives an in-character opinion (Ollama vision model or OpenAI-compatible multimodal).
  Chat page → 🖼️ button.
- **Watch & React mode** — NekoSuneAI periodically glances at the live screen and reacts in
  character (to a game/video/anything), posting to chat + voice.
- **Per-language TTS voice** — auto-detects each reply's language (Kana/Hangul/CJK/Cyrillic/
  Arabic/Devanagari + langdetect) and speaks it in that language. Settings → Voice.

## 🔜 Deferred (heavier ML deps / bigger lift / opt-in)

### VRChat (from the NekoSuneAI reference implementation)
- [ ] **VRChat web API friends system** — auto-accept friend requests + live `pipeline.vrchat.cloud`
      websocket (friend online/offline), thank-you chatbox message. Needs username/password +
      **TOTP 2FA** and is **unofficial/ToS-risky** → must be opt-in with credentials. (`vrcapi/`)
- [ ] **A* dead-reckoning navigation** — estimate position/heading from received Velocity,
      occupancy grid + pathfinding, "go to X", frontier exploration, per-world persisted maps.
      (`nav/navigator.py`, `world.py`, `locomotion.py`)
- [ ] **YOLO/ONNX screen object detection** — `person` detection with angle/closeness, feed
      obstacles into the nav grid. Heavy (onnxruntime + model); make opt-in. (`vision/system.py`)
- [ ] **RapidOCR nameplate reading** — read on-screen player nameplates to greet people by name.

### Broader Neuro-sama parity
- [ ] **Voice-per-language profiles** — beyond language code, pick a distinct cloned voice
      per language (builds on the per-language TTS that now ships).
