"""Self-update against a GitHub repository.

Reads the upstream ``VERSION`` file, compares it with the local one, and - only
when explicitly enabled - downloads that branch as a zip, copies it over the
working tree while preserving user data, and reruns setup.

Update checks are cached so start-up does not hit the network every launch, and
extraction is validated against zip-slip before a single byte is written.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .paths import ROOT_DIR, UPDATE_STATE_PATH, VERSION_PATH

DEFAULT_GITHUB_REPO = "NekoSuneProjects/NekoSuneAI"
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_UPDATE_CACHE_SECONDS = 21600
DEFAULT_AUTO_UPDATE_CHECK = True

# Security: do NOT silently download and execute remote code on startup. Auto-
# install pulls a zip from the configured GitHub repo, overwrites local files and
# reruns setup.py with no confirmation - so whoever controls that upstream repo
# would get code execution on every launch. Default OFF: the app only *notifies*
# that an update exists. Opt in explicitly with AUTO_UPDATE_INSTALL=1 (and only
# when you trust the upstream repo) or run `python setup.py --update` by hand.
DEFAULT_AUTO_UPDATE_INSTALL = False

GITHUB_REQUEST_HEADERS = {"User-Agent": "NekoSuneAI-Updater"}

_FALLBACK_VERSION = "0.0.0"
_TRUTHY_VALUES = {"1", "true", "yes", "on"}

_VERSION_FETCH_TIMEOUT = 5.0
_ARCHIVE_FETCH_TIMEOUT = 30
_ARCHIVE_CHUNK_BYTES = 1024 * 1024
_GIT_REMOTE_TIMEOUT = 5
_GIT_STATUS_TIMEOUT = 10

# Never overwritten by an update: user configuration, virtualenvs and data.
UPDATE_EXCLUDED_TOP_LEVEL = {
    ".env",
    ".git",
    ".setup-complete",
    ".venv",
    ".venv-xtts",
    "audio",
    "vendor",
}
UPDATE_EXCLUDED_RELATIVE = {
    Path("data/history.jsonl"),
    Path("data/profile.json"),
    Path("data/profiles.json"),
    Path("data/update_state.json"),
}

# Current env var first, then the pre-rename name, so older .env files keep working.
_REPO_ENV_NAMES = ("NEKOSUNEAI_GITHUB_REPO", "NOVA_GITHUB_REPO")
_BRANCH_ENV_NAMES = ("NEKOSUNEAI_GITHUB_BRANCH", "NOVA_GITHUB_BRANCH")

# Where Git usually lands on Windows when it is not on PATH.
_WINDOWS_GIT_CANDIDATES = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"%LocalAppData%\Programs\Git\cmd\git.exe",
    r"%LocalAppData%\Programs\Git\bin\git.exe",
)


@dataclass(frozen=True)
class UpdateStatus:
    local_version: str
    remote_version: str | None
    update_available: bool
    repo_slug: str
    branch: str
    checked_at: str | None = None
    error: str | None = None


# --------------------------------------------------------------------------
# Small parsers
# --------------------------------------------------------------------------


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY_VALUES


def parse_version_tuple(value: str) -> tuple[int, ...]:
    """Turn "v1.2.3-rc" into (1, 2, 3) for ordering, ignoring non-digits."""
    normalized = value.strip().lower().lstrip("v")
    if not normalized:
        return (0,)

    parts: list[int] = []
    for piece in normalized.split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)


def _is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version_tuple(remote_version) > parse_version_tuple(local_version)


def _env_first(names: tuple[str, ...]) -> str:
    """First non-empty value among ``names``."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def read_local_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip() or _FALLBACK_VERSION
    except FileNotFoundError:
        return _FALLBACK_VERSION


# --------------------------------------------------------------------------
# Git discovery
# --------------------------------------------------------------------------


def resolve_git_executable() -> str | None:
    on_path = shutil.which("git")
    if on_path:
        return on_path

    if os.name == "nt":
        for candidate in _WINDOWS_GIT_CANDIDATES:
            path = Path(os.path.expandvars(candidate))
            if path.exists():
                return str(path)

    return None


def _run_git(arguments: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    """Run a git command in the project root; None if git is missing or failed."""
    git_executable = resolve_git_executable()
    if not git_executable:
        return None

    try:
        return subprocess.run(
            [git_executable, *arguments],
            cwd=str(ROOT_DIR),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None


def parse_repo_slug_from_remote(remote_url: str) -> str | None:
    trimmed = remote_url.strip()
    if not trimmed:
        return None

    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]

    if "github.com/" in trimmed:
        return trimmed.split("github.com/", 1)[1].strip("/")
    if trimmed.startswith("git@github.com:"):
        return trimmed.split("git@github.com:", 1)[1].strip("/")
    return None


def normalize_repo_slug(value: str) -> str:
    """Normalize a configured repo value to an ``owner/repo`` slug.

    Accepts a bare slug (``owner/repo``), an HTTPS URL
    (``https://github.com/owner/repo[.git]``), or an SSH URL
    (``git@github.com:owner/repo.git``).
    """
    trimmed = value.strip()
    if not trimmed:
        return DEFAULT_GITHUB_REPO

    from_url = parse_repo_slug_from_remote(trimmed)
    if from_url:
        return from_url

    # Not a URL, so treat it as an already-clean slug and just tidy it up.
    trimmed = trimmed.strip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    return trimmed or DEFAULT_GITHUB_REPO


def discover_repo_slug() -> str:
    configured = _env_first(_REPO_ENV_NAMES)
    if configured:
        return normalize_repo_slug(configured)

    if not (ROOT_DIR / ".git").exists():
        return DEFAULT_GITHUB_REPO

    result = _run_git(["remote", "get-url", "origin"], _GIT_REMOTE_TIMEOUT)
    if result is None or result.returncode != 0:
        return DEFAULT_GITHUB_REPO

    return parse_repo_slug_from_remote(result.stdout.strip()) or DEFAULT_GITHUB_REPO


def get_branch_name() -> str:
    return _env_first(_BRANCH_ENV_NAMES) or DEFAULT_GITHUB_BRANCH


def is_git_worktree_dirty() -> bool:
    """True when local changes exist - or when that cannot be established."""
    if not (ROOT_DIR / ".git").exists():
        return False

    result = _run_git(["status", "--porcelain"], _GIT_STATUS_TIMEOUT)
    if result is None or result.returncode != 0:
        return True  # unknown state: assume dirty rather than risk overwriting
    return bool(result.stdout.strip())


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def get_cache_window_seconds() -> int:
    raw_value = os.getenv("AUTO_UPDATE_CACHE_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_UPDATE_CACHE_SECONDS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_UPDATE_CACHE_SECONDS


def get_auto_update_check_enabled() -> bool:
    return parse_bool(os.getenv("AUTO_UPDATE_CHECK"), DEFAULT_AUTO_UPDATE_CHECK)


def get_auto_update_install_enabled() -> bool:
    return parse_bool(os.getenv("AUTO_UPDATE_INSTALL"), DEFAULT_AUTO_UPDATE_INSTALL)


def get_remote_version_url(repo_slug: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_slug}/{branch}/VERSION"


def get_remote_zip_url(repo_slug: str, branch: str) -> str:
    return f"https://github.com/{repo_slug}/archive/refs/heads/{branch}.zip"


# --------------------------------------------------------------------------
# Check caching
# --------------------------------------------------------------------------


def format_timestamp(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds).astimezone().isoformat(
        timespec="seconds"
    )


def load_update_cache() -> dict[str, Any]:
    try:
        return json.loads(UPDATE_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_update_cache(payload: dict[str, Any]) -> None:
    UPDATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _cache_is_usable(
    cache: dict[str, Any], local_version: str, repo_slug: str, branch: str
) -> bool:
    """A cache entry counts only for the same target, and only while fresh."""
    if (
        cache.get("repo_slug") != repo_slug
        or cache.get("branch") != branch
        or cache.get("local_version") != local_version
    ):
        return False

    checked_at_unix = cache.get("checked_at_unix")
    remote_version = cache.get("remote_version")
    if not isinstance(checked_at_unix, (int, float)):
        return False
    if not isinstance(remote_version, str) or not remote_version:
        return False

    window = get_cache_window_seconds()
    if window <= 0:
        return False
    return time.time() - float(checked_at_unix) <= window


def build_cached_status(
    cache: dict[str, Any],
    local_version: str,
    repo_slug: str,
    branch: str,
) -> UpdateStatus | None:
    if not _cache_is_usable(cache, local_version, repo_slug, branch):
        return None

    remote_version = cache["remote_version"]
    checked_at = cache.get("checked_at")
    return UpdateStatus(
        local_version=local_version,
        remote_version=remote_version,
        update_available=_is_newer(remote_version, local_version),
        repo_slug=repo_slug,
        branch=branch,
        checked_at=checked_at if isinstance(checked_at, str) else None,
    )


def write_update_cache(
    local_version: str,
    remote_version: str,
    repo_slug: str,
    branch: str,
) -> str:
    checked_at_unix = time.time()
    checked_at = format_timestamp(checked_at_unix)
    save_update_cache(
        {
            "repo_slug": repo_slug,
            "branch": branch,
            "local_version": local_version,
            "remote_version": remote_version,
            "checked_at": checked_at,
            "checked_at_unix": checked_at_unix,
        }
    )
    return checked_at


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------


def fetch_remote_version(
    repo_slug: str,
    branch: str,
    timeout: float = _VERSION_FETCH_TIMEOUT,
) -> str:
    response = requests.get(
        get_remote_version_url(repo_slug, branch),
        headers=GITHUB_REQUEST_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    remote_version = response.text.strip()
    if not remote_version:
        raise RuntimeError("GitHub did not return a usable VERSION file.")
    return remote_version


def check_for_updates(force: bool = False) -> UpdateStatus:
    load_dotenv()
    repo_slug = discover_repo_slug()
    branch = get_branch_name()
    local_version = read_local_version()

    if not force:
        cached = build_cached_status(
            load_update_cache(),
            local_version=local_version,
            repo_slug=repo_slug,
            branch=branch,
        )
        if cached is not None:
            return cached

    try:
        remote_version = fetch_remote_version(repo_slug, branch)
    except Exception as exc:
        return UpdateStatus(
            local_version=local_version,
            remote_version=None,
            update_available=False,
            repo_slug=repo_slug,
            branch=branch,
            error=str(exc),
        )

    checked_at = write_update_cache(
        local_version=local_version,
        remote_version=remote_version,
        repo_slug=repo_slug,
        branch=branch,
    )
    return UpdateStatus(
        local_version=local_version,
        remote_version=remote_version,
        update_available=_is_newer(remote_version, local_version),
        repo_slug=repo_slug,
        branch=branch,
        checked_at=checked_at,
    )


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------


def should_skip_update_path(relative_path: Path) -> bool:
    if not relative_path.parts:
        return False
    if relative_path.parts[0] in UPDATE_EXCLUDED_TOP_LEVEL:
        return True
    return relative_path in UPDATE_EXCLUDED_RELATIVE


def download_update_archive(repo_slug: str, branch: str, destination: Path) -> None:
    response = requests.get(
        get_remote_zip_url(repo_slug, branch),
        headers=GITHUB_REQUEST_HEADERS,
        timeout=_ARCHIVE_FETCH_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    with destination.open("wb") as zip_file:
        for chunk in response.iter_content(chunk_size=_ARCHIVE_CHUNK_BYTES):
            if chunk:
                zip_file.write(chunk)


def _is_within(base: Path, target: Path) -> bool:
    """True if ``target`` resolves to a path inside ``base`` (zip-slip guard)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _reject_unsafe_members(archive: zipfile.ZipFile, extract_dir: Path) -> None:
    """Validate every member before writing anything.

    ``zipfile.extractall()`` honours ``../`` and absolute member names, so a
    hostile archive could otherwise write anywhere on disk (zip-slip, the
    CVE-2007-4559 class). The whole archive is refused on the first escaping
    entry, rather than leaving a half-extracted tree behind.
    """
    for member in archive.namelist():
        if not _is_within(extract_dir, extract_dir / member):
            raise RuntimeError(
                f"Refusing unsafe update archive: entry '{member}' escapes "
                "the extraction directory."
            )


def extract_archive_root(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        _reject_unsafe_members(archive, extract_dir)
        archive.extractall(extract_dir)

    # A GitHub branch zip contains exactly one top-level directory.
    directories = [child for child in extract_dir.iterdir() if child.is_dir()]
    if len(directories) != 1:
        raise RuntimeError("Downloaded update archive had an unexpected layout.")
    return directories[0]


def copy_update_tree(source_root: Path, destination_root: Path) -> None:
    for source_path in source_root.rglob("*"):
        relative_path = source_path.relative_to(source_root)
        if should_skip_update_path(relative_path):
            continue

        destination_path = destination_root / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def rerun_setup() -> None:
    setup_py = ROOT_DIR / "setup.py"
    if not setup_py.exists():
        return

    # --upgrade so pulling new code also refreshes already-installed packages
    # (new/updated requirements don't just sit unmet until the next fresh
    # install) instead of only installing whatever was previously missing.
    result = subprocess.run(
        [sys.executable, str(setup_py), "--setup", "--upgrade"],
        cwd=str(ROOT_DIR),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Setup failed after updating NekoSuneAI.")


def apply_update() -> UpdateStatus:
    status = check_for_updates(force=True)
    if status.error:
        raise RuntimeError(f"Could not check GitHub for updates. {status.error}")
    if not status.update_available:
        return status

    if is_git_worktree_dirty():
        raise RuntimeError(
            "This copy looks like a git checkout with local changes, so auto-update "
            "was skipped to avoid overwriting work."
        )

    with tempfile.TemporaryDirectory(prefix="nekosuneai-update-") as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "update.zip"

        download_update_archive(status.repo_slug, status.branch, zip_path)
        extracted_root = extract_archive_root(zip_path, temp_path / "archive")
        copy_update_tree(extracted_root, ROOT_DIR)

    rerun_setup()

    # Re-stamp the cache so the freshly written version is what we compare against.
    if status.remote_version:
        write_update_cache(
            local_version=status.remote_version,
            remote_version=status.remote_version,
            repo_slug=status.repo_slug,
            branch=status.branch,
        )
    return status


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check for or apply NekoSuneAI updates."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Download and install the latest version from GitHub if an update is available.",
    )
    parser.add_argument(
        "--force-check",
        action="store_true",
        help="Ignore the cached update status and query GitHub right now.",
    )
    return parser


def print_status(status: UpdateStatus) -> None:
    print(f"Local version: {status.local_version}")
    print(f"GitHub repo: {status.repo_slug} ({status.branch})")
    if status.checked_at:
        print(f"Checked: {status.checked_at}")
    if status.error:
        print(f"Update check failed: {status.error}")
        return
    print(f"Remote version: {status.remote_version}")
    print(f"Update available: {'yes' if status.update_available else 'no'}")


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv()

    if not args.apply:
        print_status(check_for_updates(force=args.force_check))
        return

    try:
        status = apply_update()
    except Exception as exc:
        print(f"Update failed: {exc}")
        raise SystemExit(1) from exc

    if status.update_available:
        print(
            f"NekoSuneAI updated from {status.local_version} to {status.remote_version}."
        )
    else:
        print(f"NekoSuneAI is already up to date at {status.local_version}.")


if __name__ == "__main__":
    main()
