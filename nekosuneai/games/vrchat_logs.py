"""Read VRChat's output logs for free world + nearby-player awareness.

VRChat writes plaintext logs to ``%LocalAppData%Low/VRChat/VRChat/output_log_*.txt``.
Parsing them gives the current world and who is in the instance with **zero** API
calls (no rate limits, no credentials, no ToS-risky web API) and no GPU. Used by
NekoSuneAI's VRChat driver so it can answer "who's here?" and key per-world
behaviour off the world id.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Log lines (verbatim shapes VRChat emits):
#   "... [Behaviour] OnPlayerJoined SomeName (usr_xxxx)"
#   "... [Behaviour] OnPlayerLeft SomeName (usr_xxxx)"
#   "... Joining wrld_xxxx:12345~..."
#   "... Entering Room: Cool World Name"
_JOINED = re.compile(r"OnPlayerJoined\s+(.+?)(?:\s+\((usr_[0-9a-fA-F-]+)\))?\s*$")
_LEFT = re.compile(r"OnPlayerLeft\s+(.+?)(?:\s+\((usr_[0-9a-fA-F-]+)\))?\s*$")
_WORLD = re.compile(r"Joining (wrld_[0-9a-fA-F-]+)")
_ROOM = re.compile(r"Entering Room:\s+(.+?)\s*$")
_LEFT_ROOM = re.compile(r"OnLeftRoom|Joining wrld_")


def default_log_dir() -> Path | None:
    """The standard Windows VRChat log directory, if it exists."""
    local_low = os.environ.get("LOCALAPPDATA", "")
    if not local_low:
        home = Path.home()
        local_low = str(home / "AppData" / "Local")
    # Logs live under LocalLow, a sibling of Local.
    candidate = Path(local_low).parent / "LocalLow" / "VRChat" / "VRChat"
    return candidate if candidate.is_dir() else None


def _resolve_dir(log_dir: str | None) -> Path | None:
    if log_dir:
        p = Path(log_dir)
        if p.is_dir():
            return p
    return default_log_dir()


def _newest_log(log_dir: Path) -> Path | None:
    logs = sorted(log_dir.glob("output_log_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _read_tail(path: Path, max_bytes: int = 1_000_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def current_world(log_dir: str | None = None) -> dict[str, str] | None:
    """Return ``{"id": "wrld_...", "name": "Room Name"}`` for the current world."""
    d = _resolve_dir(log_dir)
    if not d:
        return None
    log = _newest_log(d)
    if not log:
        return None
    text = _read_tail(log)
    world_id, room = "", ""
    for line in text.splitlines():
        m = _WORLD.search(line)
        if m:
            world_id, room = m.group(1), ""  # new world resets the room name
            continue
        m = _ROOM.search(line)
        if m:
            room = m.group(1).strip()
    if not world_id and not room:
        return None
    return {"id": world_id, "name": room}


def nearby_players(log_dir: str | None = None) -> list[str]:
    """Return display names currently present in the instance (join/leave parsed)."""
    d = _resolve_dir(log_dir)
    if not d:
        return []
    log = _newest_log(d)
    if not log:
        return []
    present: list[str] = []
    for line in _read_tail(log).splitlines():
        if _LEFT_ROOM.search(line) and "OnLeftRoom" in line:
            present.clear()
            continue
        m = _JOINED.search(line)
        if m:
            name = m.group(1).strip()
            if name and name not in present:
                present.append(name)
            continue
        m = _LEFT.search(line)
        if m:
            name = m.group(1).strip()
            if name in present:
                present.remove(name)
    return present
