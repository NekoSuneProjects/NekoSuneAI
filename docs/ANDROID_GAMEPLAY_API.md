# Android Gameplay — Main session API (experimental)

The Android game node is implemented separately in `NekoSuneProjects/nekosuneai-android-ai-gameplay`, draft PR #1. The backend shares its existing pairing, capability permission, device tokens and command queue. A registered node must have `node_type: android-gaming`.

Authenticated dashboard APIs (dashboard cookie or token):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/game/android/devices` | List paired Android game agents |
| GET | `/api/game/android/session?node_id=...` | Recover the current in-memory session ID after a page refresh |
| POST | `/api/game/android/start` | Queue session start with `node_id`, `game_id`, optional `duration_seconds` and `max_actions`; return `session.session_id` |
| POST | `/api/game/android/observe` | Queue `game.observe` for that `node_id` / `session_id`, optional `analyze: true` |
| POST | `/api/game/android/action` | Queue one typed `action` (`tap`, `swipe`, `back`) for the active session |
| POST | `/api/game/android/pause` | Pause approved game input |
| POST | `/api/game/android/resume` | Resume approved game input |
| POST | `/api/game/android/stop` | Stop session and disarm inputs |
| POST | `/api/game/android/emergency-stop` | Send scoped `game.input.stop` even if browser lost its session ID |

These APIs require dashboard authentication and use the existing per-node capability approval. Send `confirmed: true` **only when the owner explicitly approves that action** and the node's configured policy permits it. Action commands receive a short expiry; input is verified again on the Android agent.

Example payloads:

```json
{"node_id":"android-gameplay-1","game_id":"com.example.game","duration_seconds":300,"max_actions":50}
```

```json
{"node_id":"android-gameplay-1","session_id":"FROM_START_RESPONSE","action":{"type":"tap","x":500,"y":250}}
```

**Known limitations**: the first controller uses process-memory session bookkeeping. Restarting Main loses session records (the node will stop its own input when its bounded session expires). Commands are queued, not synchronously executed, so `ok:true` means *queued*, not *gameplay succeeded*. There is no streaming preview, live dashboard game page, automatic LLM action generation or durable result ledger yet. Do not deploy as unattended gameplay. Persisted session ledger, device acknowledgement checks, and end-to-end device testing are required before production.

The first manual dashboard page is `/android-games.html` on the Main server. It needs authenticated browser access. Session recovery works only while the same Main process still holds the session state. An emergency stop still respects the registry capability policy: a node owner can deny the capability. For safety, ensure `game.input.stop` is explicitly allowed for your paired Android node.
