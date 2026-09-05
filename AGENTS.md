# Docker Branch Instructions

This checkout owns: Docker/Pi backend, server APIs, web dashboard, orchestration and integrations.
Its product branch and PR target is `main`.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and this branch's [TODO.md](TODO.md) before
selecting or implementing work. Every local TODO item inherits this owner.

- Check `git rev-parse --show-toplevel`, `git branch --show-current` and
  `git status --short` before editing. Verify a feature branch was based on
  this product branch; a matching folder name alone is not enough.
- Keep main focused on the Docker/Pi backend and web dashboard. Native Windows and Android implementation belongs on their product branches.
- For multi-product work, split backend/client deliverables and link their
  contract IDs in each owning TODO. Work in the appropriate checkout.
- Do not merge entire product branches into one another or mirror native
  modules into main. Existing legacy files do not override the branch map.
- Keep TODO status, tests and commits scoped to this product. Preserve other
  uncommitted work, including changes from another assistant.
- Report the owning branch, what was verified, and any peer-branch or
  deployment work still required. Do not equate a local build with live pairing.
