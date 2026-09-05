## P1 - Backend Contracts

- [x] [CONTEXT-01] Add paired-node STT/TTS processing without Pi speaker playback; preserve owner policies during capability refresh.
- [x] [STREAM-01] Add bounded gameplay vision endpoint and fresh media context to the Windows remote game driver.
- [ ] Deploy and verify Windows media requests on ARM/Pi, including provider failures, revoked tokens and Windows narration permissions.

- [ ] [NODE-01] Coordinate authenticated transport and capability changes with separate Android and Windows adapters; keep server validation and policy here.
- [ ] [CONTEXT-01] Define server routing/context persistence for phone, room and PC handoff; pair with native delivery tasks.
- [ ] [STREAM-01] Define supervision/state/event contracts for the Android view and Windows execution node; implement only the server and web dashboard here.
- [ ] [WEAR-01] Provide permission-gated wearable vision/reasoning endpoints; Android owns glasses SDK, capture and HUD implementation.
- [ ] [GAME-01] Route PC launcher intents to the Windows node; track Linux/Steam Deck adapters separately from native Windows implementation. (Legacy `nekosuneai/windows_gaming_agent.py`, `nekosuneai/game_skills.py` and `game-skills/` duplicates removed from this checkout; game skills and the full agent now live only on the Windows checkout, reached solely via the existing `nekosuneai/games/windows_remote.py` node-capability relay.)
- [ ] [HEALTH-01] Define sensor units, stale/unknown readings, alert delivery and policy boundaries for native telemetry producers.
- [ ] [VRCX-01] Accept validated owner-selected history exports from Windows and preserve source/schema/provenance during ingestion and deduplication.
- [ ] [NODE-CONVERSE-01] New `/api/nodes/*` endpoint for a paired node to submit a captured transcript (e.g. a wake-word utterance) and receive an actual assistant reply (text/TTS/commands) back. Today `/api/nodes/heartbeat`+`/api/nodes/poll` only let a node report telemetry and execute commands this backend already decided to send — there is no path for a node to *initiate* a conversational turn. Needed by Pi Proxy's wake-word support (see `PiProxy/TODO.md`); design it as a bounded, rate-limited, owner-policy-gated endpoint, not a second unauthenticated chat API.

