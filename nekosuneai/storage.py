"""Profile and conversation-history persistence.

A thin, opinionated layer over :mod:`nekosuneai.database`. Everything stored
here is normalised on the way in and on the way out, so callers can rely on a
profile always carrying the full default key set, a filesystem-safe id, and
sensible ``created_at`` / ``updated_at`` stamps regardless of what was
originally written - including profiles migrated from the legacy JSON files.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from datetime import datetime
from typing import Any

from .database import (
    all_profile_ids,
    append_history_row,
    clear_history as db_clear_history,
    delete_profile_row,
    get_state,
    load_all_profiles,
    load_single_profile,
    migrate_from_json_if_needed,
    profile_count,
    profile_exists,
    read_history_tail,
    set_state,
    upsert_profile,
)
from .defaults import DEFAULT_PROFILE
from .paths import AUDIO_DIR, DATA_DIR, HISTORY_PATH, PROFILE_PATH, PROFILES_PATH

PROFILE_STORE_SCHEMA_VERSION = 2

_ACTIVE_PROFILE_KEY = "active_profile_id"
_DEFAULT_PROFILE_ID = "default"
_FALLBACK_PROFILE_ID = "profile"
_FALLBACK_PROFILE_NAME = "Custom Profile"

# Profile keys that must always end up as a clean list of non-empty strings.
_LIST_VALUED_KEYS = ("shared_goals", "memory_notes", "tags")

# Fields consulted, in order, when a profile does not state its own id.
_ID_SOURCE_KEYS = ("profile_id", "profile_name", "companion_name")

_DASH_RUN = re.compile(r"-+")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Identifier hygiene
# --------------------------------------------------------------------------


def _safe_profile_id(value: str) -> str:
    """Fold arbitrary text into a lowercase, dash-separated identifier."""
    lowered = value.strip().lower()
    # str.isalnum() is Unicode-aware, so accented and CJK names survive intact
    # rather than being dashed out the way a plain [a-z0-9] filter would.
    dashed = "".join(char if char.isalnum() else "-" for char in lowered)
    return _DASH_RUN.sub("-", dashed).strip("-") or _FALLBACK_PROFILE_ID


def _dedupe_profile_id(profile_id: str, existing_ids: set[str]) -> str:
    """Append the lowest numeric suffix that makes ``profile_id`` unique."""
    if profile_id not in existing_ids:
        return profile_id
    for counter in itertools.count(2):
        candidate = f"{profile_id}-{counter}"
        if candidate not in existing_ids:
            return candidate
    raise AssertionError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def _deep_merge_dicts(
    defaults: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Overlay ``incoming`` onto ``defaults``, recursing into nested mappings."""
    merged: dict[str, Any] = copy.deepcopy(defaults)
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict) and key in merged:
            merged[key] = _deep_merge_dicts(current, value)
        else:
            merged[key] = value
    return merged


def _normalize_profile_lists(profile: dict[str, Any]) -> None:
    for key in _LIST_VALUED_KEYS:
        value = profile.get(key)
        if not isinstance(value, list):
            profile[key] = []
            continue
        profile[key] = [
            text for text in (str(item).strip() for item in value) if text
        ]


def _derive_profile_id(profile: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return _safe_profile_id(explicit)
    for key in _ID_SOURCE_KEYS:
        candidate = profile.get(key)
        if candidate:
            return _safe_profile_id(str(candidate))
    return _safe_profile_id(_FALLBACK_PROFILE_ID)


def _apply_timestamps(profile: dict[str, Any]) -> None:
    """Fill in missing stamps, defaulting ``updated_at`` to ``created_at``."""
    created_at = str(profile.get("created_at", "")).strip() or _now_iso()
    updated_at = str(profile.get("updated_at", "")).strip() or created_at
    profile["created_at"] = created_at
    profile["updated_at"] = updated_at


def _normalize_profile(
    raw_profile: dict[str, Any] | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    base = copy.deepcopy(DEFAULT_PROFILE)
    profile = (
        _deep_merge_dicts(base, raw_profile) if isinstance(raw_profile, dict) else base
    )

    _normalize_profile_lists(profile)
    profile["profile_id"] = _derive_profile_id(profile, profile_id)

    if not str(profile.get("profile_name", "")).strip():
        profile["profile_name"] = (
            str(profile.get("companion_name", "")).strip() or _FALLBACK_PROFILE_NAME
        )

    _apply_timestamps(profile)
    return profile


def _touch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Copy a profile with ``updated_at`` moved to now."""
    touched = copy.deepcopy(profile)
    touched["created_at"] = str(touched.get("created_at", "")).strip() or _now_iso()
    touched["updated_at"] = _now_iso()
    return touched


def _store_touched(profile_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise, re-stamp and persist a profile in one step."""
    touched = _touch_profile(_normalize_profile(raw, profile_id))
    upsert_profile(profile_id, touched)
    return touched


def clone_default_profile() -> dict[str, Any]:
    """A fresh, fully normalised copy of the shipped default profile."""
    return _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), _DEFAULT_PROFILE_ID)


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)
    # Docker's /app/audio bind mount hides image-layer files, so create the
    # defaults in the mounted directory at runtime on first launch.
    from .alert_sounds import ensure_default_alert_sounds

    ensure_default_alert_sounds(AUDIO_DIR)


# --------------------------------------------------------------------------
# Store operations (SQLite-backed)
# --------------------------------------------------------------------------


def _ensure_db_ready() -> None:
    """Ensure the database exists and migrate legacy JSON if needed."""
    ensure_runtime_dirs()
    migrate_from_json_if_needed(PROFILES_PATH, PROFILE_PATH, HISTORY_PATH)

    # Nothing migrated and nothing stored: seed the default profile.
    if profile_count() == 0:
        default = clone_default_profile()
        upsert_profile(default["profile_id"], default)
        set_state(_ACTIVE_PROFILE_KEY, default["profile_id"])


def _normalize_all(profiles: dict[Any, Any]) -> dict[str, dict[str, Any]]:
    """Normalise every stored profile, keeping the resulting ids unique."""
    normalized: dict[str, dict[str, Any]] = {}
    taken: set[str] = set()

    for raw_id, raw_profile in profiles.items():
        profile = _normalize_profile(raw_profile, str(raw_id))
        unique_id = _dedupe_profile_id(profile["profile_id"], taken)
        profile["profile_id"] = unique_id
        taken.add(unique_id)
        normalized[unique_id] = profile

    return normalized


def load_profile_store() -> dict[str, Any]:
    _ensure_db_ready()

    normalized = _normalize_all(load_all_profiles())
    if not normalized:
        default = clone_default_profile()
        normalized = {default["profile_id"]: default}

    active_id = get_state(_ACTIVE_PROFILE_KEY, "")
    if active_id not in normalized:
        active_id = sorted(normalized)[0]

    # Write back whatever normalisation changed, so the DB converges.
    for profile_id, profile in normalized.items():
        upsert_profile(profile_id, profile)
    set_state(_ACTIVE_PROFILE_KEY, active_id)

    return {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "active_profile_id": active_id,
        "profiles": normalized,
    }


def save_profile_store(store: dict[str, Any]) -> None:
    ensure_runtime_dirs()

    active_id = store.get("active_profile_id", "")
    profiles = store.get("profiles", {})

    # Anything the caller dropped from the store is deleted from the DB.
    for removed in set(all_profile_ids()) - set(profiles):
        delete_profile_row(removed)

    for profile_id, profile in profiles.items():
        upsert_profile(profile_id, profile)

    if active_id:
        set_state(_ACTIVE_PROFILE_KEY, active_id)


def _summarize_profile(
    profile_id: str, profile: dict[str, Any], active_profile_id: str
) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "profile_name": str(profile.get("profile_name", profile_id)),
        "description": str(profile.get("description", "")).strip(),
        "companion_name": str(profile.get("companion_name", "NekoSuneAI")),
        "user_name": str(profile.get("user_name", "Friend")),
        "tags": list(profile.get("tags") or []),
        "updated_at": str(profile.get("updated_at", "")),
        "is_active": profile_id == active_profile_id,
    }


def list_profiles() -> list[dict[str, Any]]:
    store = load_profile_store()
    active_profile_id = store["active_profile_id"]

    summaries = [
        _summarize_profile(profile_id, profile, active_profile_id)
        for profile_id, profile in store["profiles"].items()
    ]
    # Active profile first, then alphabetical by display name.
    summaries.sort(
        key=lambda item: (0 if item["is_active"] else 1, item["profile_name"].lower())
    )
    return summaries


def get_active_profile_id() -> str:
    _ensure_db_ready()
    active_id = get_state(_ACTIVE_PROFILE_KEY, "")
    if active_id and profile_exists(active_id):
        return active_id
    return load_profile_store()["active_profile_id"]


def load_profile(profile_id: str | None = None) -> dict[str, Any]:
    _ensure_db_ready()

    resolved = profile_id or get_state(_ACTIVE_PROFILE_KEY, "")
    if resolved:
        data = load_single_profile(resolved)
        if data is not None:
            return copy.deepcopy(_normalize_profile(data, resolved))

    # Nothing resolvable: fall back to whatever the store considers active.
    store = load_profile_store()
    return copy.deepcopy(store["profiles"][store["active_profile_id"]])


def _require_profile(profile_id: str) -> dict[str, Any]:
    data = load_single_profile(profile_id)
    if data is None:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    return data


def load_profile_by_id(profile_id: str) -> dict[str, Any]:
    _ensure_db_ready()
    return copy.deepcopy(_normalize_profile(_require_profile(profile_id), profile_id))


def _preserve_created_at(
    normalized: dict[str, Any], existing: dict[str, Any] | None
) -> dict[str, Any]:
    """Keep the original creation stamp across an overwrite."""
    if existing:
        normalized["created_at"] = str(
            existing.get("created_at", normalized["created_at"])
        )
    return normalized


def save_profile(profile: dict[str, Any]) -> None:
    _ensure_db_ready()
    active_id = get_state(_ACTIVE_PROFILE_KEY, "")
    normalized = _preserve_created_at(
        _normalize_profile(profile, profile_id=active_id),
        load_single_profile(active_id),
    )
    upsert_profile(active_id, _touch_profile(normalized))


def save_profile_by_id(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")

    normalized = _preserve_created_at(
        _normalize_profile(profile, profile_id=profile_id),
        load_single_profile(profile_id) or {},
    )
    touched = _touch_profile(normalized)
    upsert_profile(profile_id, touched)
    return copy.deepcopy(touched)


def set_active_profile(profile_id: str) -> dict[str, Any]:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")

    set_state(_ACTIVE_PROFILE_KEY, profile_id)
    return copy.deepcopy(_store_touched(profile_id, _require_profile(profile_id)))


def create_profile(
    profile_name: str,
    base_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_db_ready()

    existing_ids = set(all_profile_ids())
    new_id = _dedupe_profile_id(_safe_profile_id(profile_name), existing_ids)

    from_scratch = base_profile is None
    source = clone_default_profile() if from_scratch else copy.deepcopy(base_profile)
    source["profile_name"] = (
        profile_name.strip() or f"Profile {len(existing_ids) + 1}"
    )
    if from_scratch:
        source["companion_name"] = source["profile_name"]
        source["description"] = "New custom profile."
        source["memory_notes"] = []

    normalized = _normalize_profile(source, profile_id=new_id)
    stamp = _now_iso()
    normalized["created_at"] = stamp
    normalized["updated_at"] = stamp

    upsert_profile(new_id, normalized)
    return copy.deepcopy(normalized)


def delete_profile(profile_id: str) -> str:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    if profile_count() <= 1:
        raise RuntimeError("You need at least one profile.")

    delete_profile_row(profile_id)

    active_id = get_state(_ACTIVE_PROFILE_KEY, "")
    if active_id == profile_id:
        active_id = sorted(all_profile_ids())[0]
        set_state(_ACTIVE_PROFILE_KEY, active_id)

    # Re-stamp whichever profile is now active.
    data = load_single_profile(active_id)
    if data:
        _store_touched(active_id, data)

    return active_id


# --------------------------------------------------------------------------
# History (SQLite-backed)
# --------------------------------------------------------------------------


def read_recent_history(max_turns: int = 50) -> list[dict[str, str]]:
    if max_turns <= 0:
        return []
    _ensure_db_ready()
    return read_history_tail(max_turns)


def append_history(role: str, content: str) -> None:
    _ensure_db_ready()
    append_history_row(_now_iso(), role, content)


def reset_history() -> None:
    _ensure_db_ready()
    db_clear_history()
