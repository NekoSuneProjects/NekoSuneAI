## P2 - VPS / infrastructure & service monitoring

Run a lightweight authenticated Neko Server Node on VPSs, dedicated servers, Raspberry Pis and supported hosts so Neko can monitor infrastructure without running heavy AI workloads on every machine.

### VPS / server node

- [ ] Lightweight Linux server agent with encrypted authenticated connection back to NekoSuneAI.
- [ ] CPU usage, load average, RAM, swap, disk usage, inode usage and uptime monitoring.
- [ ] Disk I/O, filesystem latency and rapidly-growing-disk detection.
- [ ] Network bandwidth, packet loss, latency and connection-state monitoring.
- [ ] Process and systemd-service health monitoring with restart-loop detection.
- [ ] Docker/Compose container state, health checks, CPU/RAM usage and restart-count monitoring.
- [ ] Detect Linux OOM kills, kernel errors, filesystem errors and unexpected reboots.
- [ ] GPU temperature, utilisation, VRAM and driver-health monitoring when a VPS/dedicated host exposes a GPU.
- [ ] SMART/NVMe health and temperature monitoring on dedicated hardware when host access exposes it.
- [ ] Read physical temperature/fan/power sensors only when the host/hypervisor exposes trustworthy telemetry.
- [ ] Explicitly show `unavailable` for physical CPU temperature, fan RPM, SMART or other sensors hidden by normal VPS hypervisors rather than inventing readings.
- [ ] Server tags/groups such as production, development, game servers, streaming, storage and home.
- [ ] Commands such as `Neko, how are all my servers?`, `which VPS is using the most RAM?`, and `why did this server restart?`.
### Websites, APIs & service health

- [ ] HTTP/HTTPS uptime checks with configurable expected status code and response-time limits.
- [ ] API endpoint health checks with optional authenticated health endpoints.
- [ ] WebSocket connectivity checks.
- [ ] TCP service checks for configured ports/services without general Internet scanning.
- [ ] DNS resolution checks and authoritative DNS health monitoring for configured domains.
- [ ] TLS/SSL certificate expiry and invalid-certificate warnings.
- [ ] Domain-expiry reminders where reliable registration data/API access exists.
- [ ] Database health checks for configured PostgreSQL/MySQL/MariaDB services using least-privilege monitoring credentials.
- [ ] Redis availability, memory usage and persistence-health checks.
- [ ] Reverse-proxy health for Nginx, Nginx Proxy Manager, Caddy or Traefik where integrations/log access exist.
- [ ] Detect HTTP 4xx/5xx rate changes and response-time regressions from configured services.
- [ ] Optional application-specific health endpoints for Neko projects.
### Logs, failures & diagnostics

- [ ] Structured ingestion of selected systemd/journald, Docker and application logs with per-source allowlists.
- [ ] Error-rate and repeated-exception detection without uploading every log line to the LLM.
- [ ] Group duplicate errors into one incident instead of notification spam.
- [ ] Detect restart loops, crash loops and dependency failures.
- [ ] Keep sensitive tokens/passwords/headers redacted before logs reach AI context or notifications.
- [ ] Natural diagnostics such as `why is the website down?` using current service state, dependency health and recent errors.
- [ ] Incident evidence bundle containing relevant health checks and redacted log excerpts.
### Infrastructure dependency map

- [ ] Map relationships such as domain → DNS → reverse proxy → web app → API → database/Redis.
- [ ] Correlate downstream failures so one database outage does not create ten unrelated alerts.
- [ ] Identify likely root cause and affected dependent services.
- [ ] `Neko, what broke when VPS-2 went offline?` dependency-impact query.
- [ ] Maintenance mode to suppress expected child alerts while a host/service is intentionally offline.
### Backups, storage & maintenance

- [ ] Monitor configured backup jobs and alert when a scheduled backup does not occur.
- [ ] Verify backup age, size and completion state without assuming a backup is valid merely because a file exists.
- [ ] Optional restore-test workflow for user-approved disposable test environments.
- [ ] NAS/storage capacity and disk-health monitoring through supported local APIs/agents.
- [ ] Warn before disks become critically full using predicted growth rate.
- [ ] Package/security-update availability summary without silently applying major upgrades.
- [ ] Configurable maintenance windows for approved automatic safe actions.
### Safe infrastructure actions

- [ ] Allowlisted actions such as restart a known container/service, collect diagnostics or enter maintenance mode.
- [ ] Require confirmation for host reboot/shutdown, destructive database actions, firewall changes or other high-impact operations unless a deterministic emergency policy explicitly covers them.
- [ ] Never give the AI arbitrary root-shell execution by default.
- [ ] Per-node/action permissions and audit log showing who/what requested each infrastructure change.
- [ ] Health check after automated restart/recovery and escalate if the service remains unhealthy.
- [ ] Capabilities such as `server.status`, `server.metrics`, `service.status`, `service.restart`, `docker.status`, `website.check`, `backup.status` and `network.latency`.

