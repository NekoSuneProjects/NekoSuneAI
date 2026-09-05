# NekoSuneAI Docker TODO

- [x] Container publishing uses `release-<VERSION>`; Compose uses `release-1.2.1`. See [image tags](docs/CONTAINER_TAGS.md).
- [ ] Verify successful amd64/arm64 CI publication of `release-1.2.1` before updating live deployments.

Owner checkout: `Docker/`
Product branch and PR target: `main`
Scope: Docker/Pi backend, server APIs, web dashboard, orchestration and integrations.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and [AGENTS.md](AGENTS.md) before choosing work.
Every task below belongs to this branch. Shared contract IDs identify a separate
peer deliverable on the branch named in the map, not an instruction to add the
other app here.

Work P0 first, then P1, then the product backlog below. Existing `[x]` and
`[ ]` states moved from Docker's old combined roadmap are preserved historical
status, not a fresh audit or proof that a peer app is implemented or deployed.
Do not bulk-complete inherited tasks without checking this branch.

- P0 backend verification and boundaries: @todo/backend-verification-and-boundaries.md
- P1 backend contracts: @todo/backend-contracts.md
- P2 smart assistant / Alexa & Google Home-style ideas: @todo/smart-assistant-alexa-and-google-home-style-ideas.md
- P2 JARVIS / physical-world integration: @todo/jarvis-physical-world-integration.md
- P2 3D printer / workshop integration: @todo/3d-printer-workshop-integration.md
- P2 Neko Peripheral Nodes: @todo/neko-peripheral-nodes.md
- P2 Console & gaming control: @todo/console-and-gaming-control.md
- P2 Gaming and Streaming Backend: @todo/gaming-and-streaming-backend.md
- P2 Hardware safety & hazard detection: @todo/hardware-safety-and-hazard-detection.md
- P2 VPS / infrastructure & service monitoring: @todo/vps-infrastructure-and-service-monitoring.md
- P2 Discord / community operations: @todo/discord-community-operations.md
- P2 Neko Operations Center: @todo/neko-operations-center.md
- P2 VRChat Owner Read-Only Monitor & VRCX History: @todo/vrchat-owner-monitor-and-vrcx-history.md
- P2 VRChat / heavier ML backlog: @todo/vrchat-heavier-ml-backlog.md
