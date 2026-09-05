## P2 - Discord / community operations

Use a properly authorised Discord bot in servers where the owner/admin has explicitly installed it. Monitoring should be configurable by server/channel and should not turn private community conversations into unrestricted AI training data.

### Discord server monitoring

- [ ] Monitor configured Discord guild/bot connection health and gateway reconnects.
- [ ] Track selected important channels for mentions, reports, support requests and configured keywords/events.
- [ ] Detect unanswered support/ticket threads after a configurable amount of time.
- [ ] Summarise selected channels while respecting channel/role permissions.
- [ ] Track joins/leaves, moderation-log events and bot status where permissions permit.
- [ ] Detect unusual message floods, repeated spam and raid-like join/message patterns.
- [ ] Watch configured project bots and notify when a required bot goes offline or repeatedly disconnects.
- [ ] Optional channel activity statistics without profiling individual members unnecessarily.
- [ ] Commands such as `Neko, what happened in Discord while I was away?` and `are there support tickets waiting?`.
### Community briefing & triage

- [ ] Daily/owner-requested community briefing summarising unanswered questions, reports, important mentions, project discussion and bot incidents.
- [ ] Prioritise owner/admin mentions and support/moderation queues separately from normal chatter.
- [ ] Deduplicate repeated reports about the same outage/problem.
- [ ] Correlate Discord reports with monitored infrastructure incidents, e.g. several `site is down` messages plus failing API checks.
- [ ] Create a concise incident summary for moderators/admins without exposing unrelated private conversation.
- [ ] Allow configurable channels to be completely excluded from AI summaries/history.
### Moderation assistance

- [ ] Flag likely spam, scam links, repeated flooding and raid patterns for moderator review.
- [ ] Deterministic anti-flood rules can perform preconfigured actions when explicitly enabled.
- [ ] Ambiguous harassment/context decisions stay human-reviewed rather than auto-banning from an LLM judgment alone.
- [ ] Moderator evidence view containing the relevant messages/events and rule that triggered the flag.
- [ ] Configurable escalation: log only, alert moderators, slowmode suggestion, timeout suggestion or approved deterministic action.
- [ ] Keep moderation actions permission-gated and fully auditable.
### Discord + project integrations

- [ ] Post configured service status/incidents to a selected status/admin channel.
- [ ] Post GitHub Actions/build failures and release notifications to selected development channels.
- [ ] Link Discord support reports to the matching service/project when confidence is high.
- [ ] Optional game-server status messages/player counts for configured community servers.
- [ ] Community event/reminder integration with calendar and Neko announcement systems.
- [ ] Never allow ordinary Discord users to invoke owner-only PC/server/smart-home actions.

