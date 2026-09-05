## P2 - VRChat Owner Read-Only Monitor & VRCX History

Keep the owner account physically separated from the autonomous bot account. The owner session is read-only: it may observe, import, cache, index and notify, but it must not send invites, accept requests, join worlds, change status, modify friendships, message users or perform any other account action.

Ownership: server account sessions, ingestion and timeline storage/query. Local VRCX file selection/parsing lives on Windows under VRCX-01.

Note: this is unrelated to the removed local `games/vrchat.py` OSC driver, `games/vrchat_friends.py` and `games/vrchat_logs.py` (same-machine-only VRChat control that has been deleted from this checkout in favor of the Windows checkout's implementation, reached only via the existing node-capability relay); this read-only monitor is a separate, not-yet-implemented server-account feature.

### Owner account read-only realtime monitor

- [ ] Separate owner-account credentials/session from the Neko bot account.
- [ ] Read-only adapter that exposes only approved read capabilities and contains no generic write/action endpoint.
- [ ] Consume VRChat realtime/WebSocket/event data that the current supported interface actually exposes.
- [ ] Monitor owner online/offline/session state.
- [ ] Monitor friend online/offline changes.
- [ ] Monitor friend location/world/instance changes only where VRChat exposes that information to the authenticated owner account.
- [ ] Monitor owner world/instance changes where available.
- [ ] Monitor notifications, invites, request events and friend-request events where exposed.
- [ ] Monitor user/friend status changes and other safe social presence events where exposed.
- [ ] Monitor group-related notifications/events where exposed to the owner account.
- [ ] Gracefully mark unsupported or unavailable event types instead of fabricating data.
- [ ] Automatic reconnect with backoff and event-gap detection after realtime connection loss.
- [ ] Capability examples: `vrchat.owner.status.read`, `vrchat.owner.friends.read`, `vrchat.owner.location.read`, `vrchat.owner.notifications.read`, and `vrchat.owner.events.read`.
### Friend history / unfriend tracking

- [ ] Periodic owner friend-list snapshots with timestamp and stable VRChat user IDs.
- [ ] Compare snapshots to detect additions and removals from the friend list.
- [ ] Record the first time a friendship is observed missing after previously existing.
- [ ] Dashboard `friend removed` / `friendship no longer present` event with previous last-seen friendship time.
- [ ] Do not automatically claim `they unfriended you` when the available data only proves the friendship disappeared.
- [ ] Distinguish known explanations where evidence exists, such as account unavailable/deleted, API response incomplete or user action recorded locally.
- [ ] Retry/confirm friend-list removals across multiple successful snapshots before treating temporary API failures as durable changes.
- [ ] Friend-history page showing first seen, last seen, friendship active/removed state and historical presence events.
- [ ] Query support such as `who was removed from my friends recently?`, `who is new on my friends list?`, and `when did this friendship disappear?`.
### Timeline, merging & deduplication

- [ ] Unified VRChat owner timeline combining live VRChat events, friend-list snapshots and VRCX imports.
- [ ] Every event stores a source such as `VRChat live`, `VRChat snapshot`, or `VRCX import`.
- [ ] Deduplicate equivalent VRCX/live events using stable IDs where available and timestamp/type/user matching where not.
- [ ] Preserve provenance when two sources confirm the same event rather than losing source information.
- [ ] Store confidence/state for inferred events such as friendship removal versus directly received realtime events.
- [ ] Search/filter timeline by user, world, instance, event type, source and date range.
- [ ] Dashboard catch-up view for `today`, `while I was away`, `last 24 hours`, `this week` and custom periods.
- [ ] Natural queries such as `who came online while I was away?`, `what invites did I miss?`, `when did I last see this friend?`, and `what changed in VRChat today?`.
- [ ] Include important VRChat owner events in the wider Neko Operations Center away/asleep summary when enabled.
### Privacy, retention & account safety

- [ ] Owner monitor defaults to read-only at the code/capability layer, not merely by prompt instruction.
- [ ] No owner-account capability for invite/send/accept/join/message/status/friend-modification actions.
- [ ] Bot account is the only VRChat account that may receive configured interactive/autonomous capabilities.
- [ ] Separate credential storage and session identifiers so the bot cannot accidentally reuse the owner account session.
- [ ] Configurable local retention for owner timeline/presence history.
- [ ] Per-event-category retention controls for locations, notifications and friend presence.
- [ ] One-command export/delete of locally stored owner VRChat monitoring history.
- [ ] Sensitive instance/location history can be disabled independently.
- [ ] Dashboard clearly labels imported history versus live observations and inferred friend-list changes.

