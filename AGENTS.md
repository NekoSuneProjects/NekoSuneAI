# Windows Branch Instructions

This checkout owns: Native Windows app, pairing client, capture/input, game profiles, OBS and desktop integrations.
Its product branch and PR target is `build/windows-gaming-node-release`.

Read [BRANCH_MAP.md](BRANCH_MAP.md) and this branch's [TODO.md](TODO.md) before
selecting or implementing work. Every local TODO item inherits this owner.

- Check `git rev-parse --show-toplevel`, `git branch --show-current` and
  `git status --short` before editing. Verify a feature branch was based on
  this product branch; a matching folder name alone is not enough.
- Keep Windows native implementation on `build/windows-gaming-node-release` or a task branch based on it. Do not target main or copy the Docker backend into this app.
- For multi-product work, split backend/client deliverables and link their
  contract IDs in each owning TODO. Work in the appropriate checkout.
- Do not merge entire product branches into one another or mirror native
  modules into main. Existing legacy files do not override the branch map.
- Keep TODO status, tests and commits scoped to this product. Preserve other
  uncommitted work, including changes from another assistant.
- Report the owning branch, what was verified, and any peer-branch or
  deployment work still required. Do not equate a local build with live pairing.
