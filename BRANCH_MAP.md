# Branch Ownership Map

These are separate products in separate branches of NekoSuneAI. `main` is the
Docker/Pi backend, not an integration branch for the native apps.

| Product | Local checkout | Product branch / PR target | Owned implementation |
| --- | --- | --- | --- |
| Docker/Pi backend | `Docker/` | `main` | Server APIs, web dashboard, persistence, orchestration, Linux/Pi integrations, Docker image |
| Android companion | `Android/` | `build/android-apk` | `android/`, native UI/services/permissions, phone and wearable adapters, APK build |
| Windows app | `Windows/` | `build/windows-gaming-node-release` | Windows GUI/agent, capture/input, game profiles, OBS/desktop adapters, EXE build |

Each checkout has its own `TODO.md`, `AGENTS.md` and `CLAUDE.md`. Read the
TODO on the owning branch. Paths in that TODO are relative to that checkout.
Sibling directory names describe this workspace, not folders to create inside
the repository. In a standalone clone, use the named branch instead.

## Work Routing

1. Verify the repository root, current branch and uncommitted changes before editing.
2. Select the owning product and read its local TODO. Every checkbox inherits
   that file's owner and target branch unless it explicitly links a peer task.
3. Create any feature/fix branch from the owning product branch. Target the
   same product branch in its PR: Android and Windows PRs must not target `main`.
4. Split a feature spanning products into backend and native-client changes.
   Use the same contract ID below in each affected TODO, with a distinct
   deliverable and verification state for each branch.
5. Commit and validate each checkout separately when committing is requested.
   Do not merge an entire native-app branch into `main`, merge `main` wholesale
   into a native-app branch, or mirror client modules into Docker to keep copies
   synchronized. Port only explicitly required, scoped protocol changes.
6. Keep an item open until its owning implementation and required checks pass.
   A backend endpoint does not complete its Android/Windows UI task, and a
   successful local test does not prove a deployed container, APK or EXE works.

## Shared Contracts

These IDs link separate deliverables; they do not authorize code on another branch.

| ID | Docker / `main` | Android / `build/android-apk` | Windows / `build/windows-gaming-node-release` |
| --- | --- | --- | --- |
| PAIR-01 | Approval/code APIs, dashboard approval, token lifecycle | Native discovery, request/status, token storage | Native approval/code UI, discovery, token storage |
| NODE-01 | Capability validation, permissions, queues, heartbeat APIs | Phone/wearable capability adapter | PC/game capability adapter and local enforcement |
| CONTEXT-01 | Conversation, intercom and notification routing | Phone audio/presence/notification delivery | PC audio and context handoff |
| STREAM-01 | Session planning, Twitch reasoning, dashboard supervision | Native status and owner supervision controls | Game readiness, capture/input, OBS and local stop |
| WEAR-01 | Vision/reasoning endpoints and retained context | Glasses SDK, capture/audio/HUD, consent and controls | No wearable implementation currently assigned |
| GAME-01 | Gaming intents, permissions and high-level goals | Optional remote supervision via STREAM-01 | PC launcher and native game execution; keep Steam Deck/Linux work separate |
| HEALTH-01 | Aggregate telemetry, deterministic policy, incident dashboard | Phone sensor/battery telemetry and alerts | PC sensor collection and local deterministic stop |
| VRCX-01 | Validated history ingestion, provenance, merge/query/retention | No import implementation currently assigned | Local file selection, read-only VRCX parsing/export |

## Legacy Files

Some branches still contain historical files from before the product split.
Their presence does not change ownership. Native-client copies on `main` are
not the source of truth and must not receive new native-app features. Track
their import/package/test dependencies before a separate, scoped removal.
Documentation reorganization does not claim those legacy files were removed.

New product backlogs belong in that product's branch, not in Docker's TODO.
Changes to this map must be reflected in the other affected product checkouts.
