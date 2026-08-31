"""NekoSuneAI - speaker volume, per-device levels, rooms and multi-room groups.

Sits on top of the same PipeWire/PulseAudio ``pactl`` interface the Bluetooth
speaker watchdog already uses, so an Alexa/Echo BlueZ sink is controllable the
same way as any other output. Implements several "Audio, speakers & multi-room"
roadmap items:

* Alexa/Echo Bluetooth volume control - up/down/set/mute/unmute on a sink.
* Per-device speaker volume and remembered levels - each sink's level is saved
  and can be restored on request.
* Multi-room audio groups - name a group of rooms and control them together.
* Whisper / night mode - a global toggle that drops output to a quiet level.

Command parsing and the ``pactl`` argument building are pure functions so they
can be unit-tested without a real audio server. Actual execution is guarded by
``shutil.which("pactl")`` and injected in tests through a fake backend.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Protocol

from .database import get_state, set_state

STATE_KEY = "assistant_audio_v1"

WHISPER_LEVEL = 20   # percent applied to the active sink in whisper/night mode


@dataclass
class Sink:
    name: str
    description: str = ""


# ── pactl backend ──────────────────────────────────────────────────────────

class AudioBackend(Protocol):
    def list_sinks(self) -> list[Sink]: ...
    def default_sink(self) -> str | None: ...
    def get_volume(self, sink: str) -> int | None: ...
    def set_volume(self, sink: str, percent: int) -> bool: ...
    def set_mute(self, sink: str, mute: bool) -> bool: ...


def parse_short_sinks(text: str) -> list[str]:
    """Parse ``pactl list short sinks`` output into sink names (column 2)."""
    names: list[str] = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[1].strip():
            names.append(cols[1].strip())
    return names


def parse_sink_descriptions(text: str) -> dict[str, str]:
    """Map sink Name -> Description from ``pactl list sinks`` output."""
    result: dict[str, str] = {}
    name: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            name = stripped[len("Name:"):].strip()
        elif stripped.startswith("Description:") and name:
            result[name] = stripped[len("Description:"):].strip()
            name = None
    return result


def parse_volume_percent(text: str) -> int | None:
    """Pull the first NN% out of ``pactl get-sink-volume`` output."""
    m = re.search(r"(\d+)%", text)
    return int(m.group(1)) if m else None


def clamp_percent(value: int) -> int:
    return max(0, min(150, value))


class PactlBackend:
    """Thin wrapper over the host ``pactl`` binary (PulseAudio / PipeWire-pulse)."""

    @staticmethod
    def available() -> bool:
        return shutil.which("pactl") is not None

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=10, check=False)

    def list_sinks(self) -> list[Sink]:
        if not self.available():
            return []
        short = self._run(["list", "short", "sinks"])
        names = parse_short_sinks(short.stdout) if short.returncode == 0 else []
        full = self._run(["list", "sinks"])
        descriptions = parse_sink_descriptions(full.stdout) if full.returncode == 0 else {}
        return [Sink(n, descriptions.get(n, "")) for n in names]

    def default_sink(self) -> str | None:
        if not self.available():
            return None
        res = self._run(["get-default-sink"])
        name = res.stdout.strip()
        return name or None

    def get_volume(self, sink: str) -> int | None:
        if not self.available():
            return None
        res = self._run(["get-sink-volume", sink])
        return parse_volume_percent(res.stdout) if res.returncode == 0 else None

    def set_volume(self, sink: str, percent: int) -> bool:
        if not self.available():
            return False
        return self._run(["set-sink-volume", sink, f"{clamp_percent(percent)}%"]).returncode == 0

    def set_mute(self, sink: str, mute: bool) -> bool:
        if not self.available():
            return False
        return self._run(["set-sink-mute", sink, "1" if mute else "0"]).returncode == 0


# ── persisted config ────────────────────────────────────────────────────────

@dataclass
class AudioState:
    aliases: dict[str, str] = field(default_factory=dict)      # room name -> sink match substring
    groups: dict[str, list[str]] = field(default_factory=dict)  # group name -> [room names]
    remembered: dict[str, int] = field(default_factory=dict)    # sink name -> last set percent
    whisper: bool = False


def _load_state() -> AudioState:
    try:
        raw = json.loads(get_state(STATE_KEY, "{}"))
    except (TypeError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return AudioState(
        aliases={str(k): str(v) for k, v in (raw.get("aliases") or {}).items()},
        groups={str(k): [str(x) for x in v] for k, v in (raw.get("groups") or {}).items() if isinstance(v, list)},
        remembered={str(k): int(v) for k, v in (raw.get("remembered") or {}).items()},
        whisper=bool(raw.get("whisper", False)),
    )


def _save_state(state: AudioState) -> None:
    set_state(STATE_KEY, json.dumps({
        "aliases": state.aliases,
        "groups": state.groups,
        "remembered": state.remembered,
        "whisper": state.whisper,
    }, ensure_ascii=False))


# ── command parsing ─────────────────────────────────────────────────────────

_LEVEL_WORDS = {"max": 100, "maximum": 100, "full": 100, "half": 50, "low": 25, "quiet": 20, "min": 10, "minimum": 10}


def _parse_level(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:%|percent)", text)
    if m:
        return clamp_percent(int(m.group(1)))
    for word, val in _LEVEL_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return val
    return None


def _split_targets(chunk: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+and\s+", chunk)
    out = []
    for p in parts:
        p = re.sub(r"\b(the|speaker|speakers|volume|to|in|group)\b", " ", p, flags=re.I).strip(" ,.-")
        if p:
            out.append(p)
    return out


def parse_audio_command(text: str) -> tuple[str, dict] | None:
    """Parse a spoken audio command into (action, payload) or None.

    Actions: 'set', 'up', 'down', 'mute', 'unmute', 'restore',
    'group_define', 'whisper_on', 'whisper_off', 'list'.
    """
    lower = text.strip().lower()
    has_keyword = re.search(r"\b(volume|speaker|speakers|mute|unmute|whisper|night mode|audio|sound|louder|quieter|turn it up|turn it down|group)\b", lower)
    # A bare "set/turn ... to N%" is treated as a volume command in this
    # last-resort handler (reminders/lists/etc. run before audio in the pipeline).
    has_set_level = re.search(r"\b(set|turn|make|change)\b", lower) and re.search(r"\d{1,3}\s*(?:%|percent)", lower)
    if not (has_keyword or has_set_level):
        return None

    # whisper / night mode
    if re.search(r"\b(whisper mode|night mode)\b", lower) or (re.search(r"\bwhisper\b", lower) and re.search(r"\b(mode|on|off|enable|disable)\b", lower)):
        if re.search(r"\b(off|disable|stop|cancel|end)\b", lower):
            return "whisper_off", {}
        return "whisper_on", {}

    # list devices
    if re.search(r"\b(list|show|what)\b.*\b(speakers|audio devices|sound devices)\b", lower):
        return "list", {}

    # group define: "group the kitchen and living room as downstairs"
    gm = re.search(r"\bgroup\s+(.+?)\s+as\s+(.+?)(?:\.|$)", lower)
    if gm:
        rooms = _split_targets(gm.group(1))
        name = gm.group(2).strip(" ,.-")
        if rooms and name:
            return "group_define", {"name": name, "rooms": rooms}

    # restore remembered
    if re.search(r"\brestore\b.*\bvolume\b", lower) or re.search(r"\bvolume\b.*\bback to normal\b", lower):
        return "restore", {"targets": _targets_in(lower)}

    # mute / unmute
    if re.search(r"\bunmute\b", lower) or (re.search(r"\bmute\b", lower) and re.search(r"\b(off|un)\b", lower)):
        return "unmute", {"targets": _targets_in(lower)}
    if re.search(r"\bmute\b", lower):
        return "mute", {"targets": _targets_in(lower)}

    # up / down (relative)
    if re.search(r"\b(turn (?:it |the volume )?up|volume up|louder|turn up)\b", lower):
        return "up", {"targets": _targets_in(lower), "delta": _parse_level(lower) or 10}
    if re.search(r"\b(turn (?:it |the volume )?down|volume down|quieter|turn down)\b", lower):
        return "down", {"targets": _targets_in(lower), "delta": _parse_level(lower) or 10}

    # absolute set
    level = _parse_level(lower)
    if level is not None and re.search(r"\b(set|make|change|volume|speaker)\b", lower):
        return "set", {"targets": _targets_in(lower), "percent": level}

    return None


# Command/filler words removed when isolating the room/group name. "and" and
# "," are preserved so multiple targets can still be split apart.
_STRIP_WORDS = (
    "set", "make", "change", "turn", "up", "down", "volume", "louder", "quieter",
    "mute", "unmute", "restore", "please", "neko", "the", "a", "to", "by", "back",
    "normal", "on", "in", "for", "it", "speaker", "speakers", "sound", "audio",
    "of", "my", "level",
)


def _targets_in(lower: str) -> list[str]:
    """Extract room/group names from phrases like 'set the kitchen and echo to 30%'."""
    s = re.sub(r"\bpercent\b", " ", lower)
    s = re.sub(r"\d{1,3}\s*%?", " ", s)
    for word in _LEVEL_WORDS:
        s = re.sub(rf"\b{word}\b", " ", s)
    s = re.sub(r"\b(?:" + "|".join(_STRIP_WORDS) + r")\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return _split_targets(s)


# ── controller ──────────────────────────────────────────────────────────────

class AudioController:
    def __init__(self, backend: AudioBackend | None = None) -> None:
        self.backend: AudioBackend = backend or PactlBackend()
        self._lock = threading.RLock()

    # resolve a spoken room/alias to concrete sink names
    def _resolve_sinks(self, target: str, sinks: list[Sink], state: AudioState) -> list[str]:
        t = target.strip().lower()
        if not t or t in {"volume", "sound", "audio", "speaker", "speakers", "everything", "all", "home", "whole home"}:
            names = [s.name for s in sinks]
            return names if t in {"everything", "all", "home", "whole home"} else names[:1] if not sinks else _default_first(names, self.backend)
        alias = state.aliases.get(t)
        matched: list[str] = []
        for s in sinks:
            hay = f"{s.name} {s.description}".lower()
            if alias and alias.lower() in hay:
                matched.append(s.name)
            elif t in hay:
                matched.append(s.name)
        return matched

    def _expand_targets(self, targets: list[str], sinks: list[Sink], state: AudioState) -> list[str]:
        resolved: list[str] = []
        names = targets or [""]
        for target in names:
            key = target.strip().lower()
            if key in state.groups:                      # a group name expands to its rooms
                for room in state.groups[key]:
                    resolved += self._resolve_sinks(room, sinks, state)
            else:
                resolved += self._resolve_sinks(target, sinks, state)
        # de-dup, preserve order
        seen: set[str] = set()
        ordered = []
        for n in resolved:
            if n and n not in seen:
                seen.add(n)
                ordered.append(n)
        return ordered

    def handle(self, text: str) -> str | None:
        parsed = parse_audio_command(text)
        if not parsed:
            return None
        action, payload = parsed
        with self._lock:
            state = _load_state()

            if action == "whisper_on":
                state.whisper = True
                sinks = self.backend.list_sinks()
                for s in sinks:
                    # Remember the current level (if not already) so we can restore it.
                    if s.name not in state.remembered:
                        cur = self.backend.get_volume(s.name)
                        if cur is not None:
                            state.remembered[s.name] = cur
                    self.backend.set_volume(s.name, WHISPER_LEVEL)
                _save_state(state)
                return f"Whisper mode is on. I've lowered the speakers to about {WHISPER_LEVEL}%."
            if action == "whisper_off":
                state.whisper = False
                _save_state(state)
                restored = 0
                for s in self.backend.list_sinks():
                    if s.name in state.remembered:
                        self.backend.set_volume(s.name, state.remembered[s.name])
                        restored += 1
                return "Whisper mode is off." + (" Speakers restored to their remembered levels." if restored else "")

            if action == "group_define":
                state.groups[payload["name"].lower()] = [r.lower() for r in payload["rooms"]]
                _save_state(state)
                return f"Got it — the '{payload['name']}' group now covers {', '.join(payload['rooms'])}."

            if action == "list":
                sinks = self.backend.list_sinks()
                if not sinks:
                    return "I can't see any audio output devices right now."
                labels = [s.description or s.name for s in sinks]
                return "Audio outputs I can see: " + "; ".join(labels)

            sinks = self.backend.list_sinks()
            targets = self._expand_targets(payload.get("targets", []), sinks, state)
            if not targets:
                return "I couldn't work out which speaker you meant. Try naming a room, or say 'list speakers'."

            if action == "set":
                pct = payload["percent"]
                for name in targets:
                    if self.backend.set_volume(name, pct):
                        state.remembered[name] = pct
                _save_state(state)
                return f"Set {_pretty(targets)} to {pct}%."

            if action in {"up", "down"}:
                delta = payload["delta"] * (1 if action == "up" else -1)
                results = []
                for name in targets:
                    cur = self.backend.get_volume(name)
                    if cur is None:
                        cur = state.remembered.get(name, 50)
                    new = clamp_percent(cur + delta)
                    if self.backend.set_volume(name, new):
                        state.remembered[name] = new
                        results.append(new)
                _save_state(state)
                if not results:
                    return "I couldn't change the volume on that device."
                return f"Turned {_pretty(targets)} {'up' if action == 'up' else 'down'} to {results[0]}%."

            if action in {"mute", "unmute"}:
                for name in targets:
                    self.backend.set_mute(name, action == "mute")
                return f"{'Muted' if action == 'mute' else 'Unmuted'} {_pretty(targets)}."

            if action == "restore":
                restored = []
                for name in targets:
                    if name in state.remembered:
                        self.backend.set_volume(name, state.remembered[name])
                        restored.append(state.remembered[name])
                if not restored:
                    return "I don't have a remembered level for that device yet."
                return f"Restored {_pretty(targets)} to {restored[0]}%."
        return None


def _default_first(names: list[str], backend: AudioBackend) -> list[str]:
    default = backend.default_sink()
    if default and default in names:
        return [default]
    return names[:1]


def _pretty(sink_names: list[str]) -> str:
    if len(sink_names) == 1:
        return "the speaker"
    return f"{len(sink_names)} speakers"
