## P2 - Gaming and Streaming Backend

Keep the Raspberry Pi/Docker instance as NekoSuneAI's persistent brain while a Windows Gaming Agent on the gaming PC handles heavy vision, game execution, real-time input, OBS and Twitch. Games must run on Windows rather than being streamed/executed inside the Pi container.

Ownership: server planning, Twitch reasoning, shared state and web dashboard only. Native capture/input/OBS execution belongs to Windows (STREAM-01); native phone views belong to Android. Inherited mixed-platform task wording below is limited to its backend portion here.

### Windows Gaming Agent

- [x] Remote supervision from the Neko dashboard/Android app with pause/take-over/stop controls.
- [x] Add `Windows Gaming Node` / `Game Vision Node` to Neko Peripheral Nodes.
### Game adapters & skills

- [x] Game objective/goal system: long-term goal on the Pi, short-term actions executed locally on Windows.
### Twitch chat & autonomous VTuber behaviour

- [x] Twitch chat connection integrated into the same Neko conversation/personality system.
- [x] Read incoming chat without speaking every message aloud.
- [x] Chat prioritisation so questions/mentions/important messages can be answered without constantly interrupting gameplay.
- [ ] Spam/repetition/raid/message-flood handling and configurable cooldowns.
- [ ] Twitch moderation integration using user-defined rules and permissions.
- [ ] Respond in Twitch chat and optionally speak selected replies through TTS.
- [ ] Recognise follows/subscriptions/raids/channel-point events where Twitch APIs expose them.
- [ ] Trigger avatar expressions/animations, sounds or overlays for configured stream events.
- [ ] Maintain stream-specific conversational context while preserving the normal Neko personality.
- [x] Separate private owner instructions from public Twitch-chat instructions so viewers cannot control the PC/Neko without permission.
- [x] Viewer interaction commands are allowlisted and rate-limited.
### Autonomous stream sessions

- [ ] High-level command such as `Neko, stream Minecraft` can prepare an autonomous stream session.
- [ ] Pre-stream checklist: Windows node online, game installed, OBS available, capture source healthy, audio healthy and Twitch connection ready.
- [x] Optional confirmation immediately before going live.
- [ ] Neko can play, talk to Twitch chat and react to stream events while the user supervises remotely.
- [ ] Scheduled/owner-triggered breaks with BRB scene and safe game pause where supported.
- [ ] Recover from game crash by stopping input, switching to BRB and notifying the owner before attempting configured recovery.
- [ ] End-stream routine: stop game actions, say goodbye, switch ending scene, stop stream, save session summary and optionally close approved apps.
- [ ] Android/dashboard view showing current game, objective, stream state, viewers/chat activity, errors and Neko's current action.
- [x] One-tap owner `take over`, `pause Neko`, `stop stream`, and `stop all input` controls.
### Architecture / performance

- [x] Pi/server performs personality, conversation, long-term memory, planning and high-level game goals.
- [x] Backpressure/queue limits so Twitch chat or vision frames cannot overwhelm Neko's reasoning pipeline.
- [ ] Session logs that record goals, observations, skills/actions and results for debugging without retaining raw video unless explicitly enabled.
- [x] Capability examples: `game.status`, `game.capture`, `game.skill`, `game.input.stop`, `obs.scene`, `obs.stream.status`, `twitch.chat.read`, and `twitch.chat.send`.

