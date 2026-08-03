# NekoSuneAI — Build & CI/CD

Self-hosted build pipelines for desktop bundles. Pick the file that matches
your platform — both build the same artifacts:

| Artifact            | What it is                                        | Built by                          |
|---------------------|-----------------------------------------------------|-----------------------------------|
| **Desktop bundle**  | PyInstaller app (Win `.exe` / Linux dir)          | the `desktop:*` CI jobs           |

| Platform                        | Pipeline file                  |
|---------------------------------|--------------------------------|
| GitLab (self-hosted)            | `.gitlab-ci.yml`               |
| Gitea / Forgejo Actions         | `.gitea/workflows/ci.yml`      |
| GitHub (self-hosted) / github.com | copy that file to `.github/workflows/ci.yml` |

> These files are **not committed** — upload them directly through your
> platform's web UI or push them yourself, as you prefer.

---

## 1. GitLab CI (`.gitlab-ci.yml`)

**Runners**
- `desktop:linux`: any Docker-executor runner (uses a plain `python:*-slim`
  image, no privileged/DinD access needed).
- `desktop:windows`: a Windows shell runner **tagged `windows`** with Python 3.10
  on `PATH`. No Windows runner → that job just stays un-picked.

**When jobs run**
- `validate` — every branch / MR / tag.
- `desktop:*` — version tags, or manual from the pipeline UI.
- `release` — on `v*` tags, attaches the Linux bundle to a GitLab Release.

---

## 2. Gitea / Forgejo Actions (`.gitea/workflows/ci.yml`)

**Runners** (register `act_runner` / `forgejo-runner`)
- a Linux runner labelled **`docker`** (the standard `ubuntu-latest` act image
  is fine — it's only used as a container host for the build steps, no image
  publishing involved);
- optional Windows runner labelled **`windows`** with Python 3.10 for the `.exe`.

Builds run on the default branch and on `v*` tags (manual dispatch otherwise).
Air-gapped instance? Mirror the `actions/*` actions or point the runner's
`DEFAULT_ACTIONS_URL` at your mirror.

---

## 3. Cutting a release

Both pipelines key desktop builds + the release job off git tags:

```bash
git tag v1.1.0
git push origin v1.1.0      # (push to whichever remote hosts your CI)
```

That produces the `NekoSuneAI-linux-*` / `NekoSuneAI-windows-*` desktop
artifacts and attaches the Linux bundle to the release.

---

## Notes / caveats

- **Desktop on Linux**: the PyInstaller bundle runs the CLI out of the box.
  The native pywebview *window* (`--gui`) additionally needs system
  WebKitGTK on the target machine; install it there or use CLI mode instead.
- **Desktop on Windows**: includes the bundled CEF backend, so `NekoSuneAI.exe --gui`
  opens the native window. `--collect-all webview` pulls in the CEF runtime.
- **Voice/STT/XTTS** are intentionally excluded from these builds (large, need
  host audio hardware). Install `requirements-voice.txt` on the host if needed.
- Secrets live only in `.env` (gitignored) and CI variables — never in the
  artifacts.
