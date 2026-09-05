## P2 - Neko Operations Center

Create one operations view that combines physical hardware, VPSs, websites, applications, Discord/community systems, GitHub, game servers and Neko nodes.

### Unified operations dashboard

- [ ] Global health states using `OK`, `INFO`, `WARNING`, `CRITICAL`, and `EMERGENCY`.
- [ ] Views for Home, Hardware Safety, VPS/Servers, Websites/APIs, Docker, Discord, GitHub, Game Servers, Streaming and Neko Peripheral Nodes.
- [ ] Overall `Neko, status report` that prioritises active problems instead of listing every healthy service.
- [ ] Incident timeline combining alerts from multiple integrations.
- [ ] Acknowledge, mute and maintenance-state controls with expiration times.
- [ ] Group repeated symptoms into one incident where possible.
- [ ] Root-cause/dependency correlation across infrastructure and community reports.
- [ ] Historical uptime/latency/resource graphs with configurable data retention.
### External/project monitoring

- [ ] GitHub repository monitoring for failed Actions workflows, releases, important issues/PRs and configured branch health.
- [ ] Docker/container fleet overview across Pi, home servers and VPS nodes.
- [ ] Minecraft/other game-server status, player count, tick/TPS/performance where supported.
- [ ] VPN/Tailscale/WireGuard node reachability for configured user-owned infrastructure.
- [ ] Internet/WAN connectivity and latency monitoring from selected nodes.
- [ ] Email delivery/service health checks for configured systems without reading unrelated mailbox content.
- [ ] Cloudflare/DNS/tunnel health where supported APIs/account permissions are configured.
### Correlation & proactive intelligence

- [ ] Correlate user/community complaints with live service telemetry before suggesting a likely cause.
- [ ] Detect patterns such as memory leaks, gradually increasing disk usage or repeating nightly failures.
- [ ] Predict likely disk-full conditions and certificate expirations before they become outages.
- [ ] Distinguish one-off transient failures from persistent incidents using configurable retry windows.
- [ ] Explain why an alert was raised and what evidence supports the conclusion.
- [ ] Suggested remediation can be generated separately from automatic execution.
### Away/asleep summary

- [ ] `What happened while I was asleep/out?` combines home safety events, VPS incidents, website outages, Discord activity, GitHub failures, streaming events and other enabled sources.
- [ ] Summaries prioritise emergencies/critical issues, then unresolved warnings, then noteworthy information.
- [ ] Avoid repeating incidents already acknowledged by the owner.
- [ ] Include what automatically recovered, what remains broken and what needs owner attention.

