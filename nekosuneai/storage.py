from __future__ import annotations

import copy
import json
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_profile_id(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = "".join(
        character if character.isalnum() else "-"
        for character in lowered
    )
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    return cleaned or "profile"


def _dedupe_profile_id(profile_id: str, existing_ids: set[str]) -> str:
    if profile_id not in existing_ids:
        return profile_id
    counter = 2
    while f"{profile_id}-{counter}" in existing_ids:
        counter += 1
    return f"{profile_id}-{counter}"


def _deep_merge_dicts(defaults: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(defaults)
    for key, value in incoming.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_profile_lists(profile: dict[str, Any]) -> None:
    for key in ("shared_goals", "memory_notes", "tags"):
        value = profile.get(key)
        if isinstance(value, list):
            profile[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            profile[key] = []


def _normalize_profile(
    raw_profile: dict[str, Any] | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    base_profile = copy.deepcopy(DEFAULT_PROFILE)
    if isinstance(raw_profile, dict):
        merged_profile = _deep_merge_dicts(base_profile, raw_profile)
    else:
        merged_profile = base_profile

    _normalize_profile_lists(merged_profile)

    resolved_id = _safe_profile_id(
        profile_id
        or str(
            merged_profile.get("profile_id")
            or merged_profile.get("profile_name")
            or merged_profile.get("companion_name")
            or "profile"
        )
    )
    merged_profile["profile_id"] = resolved_id

    if not str(merged_profile.get("profile_name", "")).strip():
        merged_profile["profile_name"] = (
            str(merged_profile.get("companion_name", "")).strip()
            or "Custom Profile"
        )

    created_at = str(merged_profile.get("created_at", "")).strip()
    updated_at = str(merged_profile.get("updated_at", "")).strip()
    if not created_at:
        created_at = _now_iso()
    if not updated_at:
        updated_at = created_at
    merged_profile["created_at"] = created_at
    merged_profile["updated_at"] = updated_at
    return merged_profile


def _touch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    touched = copy.deepcopy(profile)
    created_at = str(touched.get("created_at", "")).strip() or _now_iso()
    touched["created_at"] = created_at
    touched["updated_at"] = _now_iso()
    return touched


def clone_default_profile() -> dict[str, Any]:
    return _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), "default")


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)
    # Docker's /app/audio bind mount hides image-layer files, so create the
    # defaults in the mounted directory at runtime on first launch.
    from .alert_sounds import ensure_default_alert_sounds
    ensure_default_alert_sounds(AUDIO_DIR)


# ── Store operations (SQLite-backed) ─────────────────────────────────────


def _ensure_db_ready() -> None:
    """Ensure the database exists and migrate legacy JSON if needed."""
    ensure_runtime_dirs()
    migrated = migrate_from_json_if_needed(PROFILES_PATH, PROFILE_PATH, HISTORY_PATH)

    # If DB is still empty (no JSON files existed), seed a default profile
    if profile_count() == 0:
        default = _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), "default")
        upsert_profile(default["profile_id"], default)
        set_state("active_profile_id", default["profile_id"])


def load_profile_store() -> dict[str, Any]:
    _ensure_db_ready()
    profiles = load_all_profiles()

    # Normalize all profiles
    normalized: dict[str, dict[str, Any]] = {}
    existing_ids: set[str] = set()
    for raw_id, raw_profile in profiles.items():
        norm = _normalize_profile(raw_profile, str(raw_id))
        deduped = _dedupe_profile_id(norm["profile_id"], existing_ids)
        norm["profile_id"] = deduped
        existing_ids.add(deduped)
        normalized[deduped] = norm

    if not normalized:
        default = _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), "default")
        normalized = {default["profile_id"]: default}

    active_id = get_state("active_profile_id", "")
    if active_id not in normalized:
        active_id = sorted(normalized.keys())[0]

    # Persist any normalization changes
    for pid, pdata in normalized.items():
        upsert_profile(pid, pdata)
    set_state("active_profile_id", active_id)

    return {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "active_profile_id": active_id,
        "profiles": normalized,
    }


def save_profile_store(store: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    active_id = store.get("active_profile_id", "")
    profiles = store.get("profiles", {})

    # Sync all profiles to DB
    current_ids = set(all_profile_ids())
    new_ids = set(profiles.keys())

    # Delete removed profiles
    for removed in current_ids - new_ids:
        delete_profile_row(removed)

    # Upsert all profiles
    for pid, pdata in profiles.items():
        upsert_profile(pid, pdata)

    if active_id:
        set_state("active_profile_id", active_id)


def list_profiles() -> list[dict[str, Any]]:
    store = load_profile_store()
    active_profile_id = store["active_profile_id"]
    summaries: list[dict[str, Any]] = []
    for profile_id, profile in store["profiles"].items():
        summaries.append(
            {
                "profile_id": profile_id,
                "profile_name": str(profile.get("profile_name", profile_id)),
                "description": str(profile.get("description", "")).strip(),
                "companion_name": str(profile.get("companion_name", "NekoSuneAI")),
                "user_name": str(profile.get("user_name", "Friend")),
                "tags": list(profile.get("tags") or []),
                "updated_at": str(profile.get("updated_at", "")),
                "is_active": profile_id == active_profile_id,
            }
        )

    summaries.sort(
        key=lambda item: (
            0 if item["is_active"] else 1,
            item["profile_name"].lower(),
        )
    )
    return summaries


def get_active_profile_id() -> str:
    _ensure_db_ready()
    active_id = get_state("active_profile_id", "")
    if active_id and profile_exists(active_id):
        return active_id
    # Fallback
    store = load_profile_store()
    return store["active_profile_id"]


def load_profile(profile_id: str | None = None) -> dict[str, Any]:
    _ensure_db_ready()
    resolved = profile_id or get_state("active_profile_id", "")
    if resolved:
        data = load_single_profile(resolved)
        if data is not None:
            return copy.deepcopy(_normalize_profile(data, resolved))
    # Fallback to store
    store = load_profile_store()
    active = store["active_profile_id"]
    return copy.deepcopy(store["profiles"][active])


def load_profile_by_id(profile_id: str) -> dict[str, Any]:
    _ensure_db_ready()
    data = load_single_profile(profile_id)
    if data is None:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    return copy.deepcopy(_normalize_profile(data, profile_id))


def save_profile(profile: dict[str, Any]) -> None:
    _ensure_db_ready()
    active_id = get_state("active_profile_id", "")
    existing = load_single_profile(active_id)
    normalized = _normalize_profile(profile, profile_id=active_id)
    if existing:
        normalized["created_at"] = str(existing.get("created_at", normalized["created_at"]))
    touched = _touch_profile(normalized)
    upsert_profile(active_id, touched)


def save_profile_by_id(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")

    existing = load_single_profile(profile_id) or {}
    normalized = _normalize_profile(profile, profile_id=profile_id)
    normalized["created_at"] = str(existing.get("created_at", normalized["created_at"]))
    touched = _touch_profile(normalized)
    upsert_profile(profile_id, touched)
    return copy.deepcopy(touched)


def set_active_profile(profile_id: str) -> dict[str, Any]:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    set_state("active_profile_id", profile_id)
    data = load_single_profile(profile_id)
    if data is None:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    touched = _touch_profile(_normalize_profile(data, profile_id))
    upsert_profile(profile_id, touched)
    return copy.deepcopy(touched)


def create_profile(
    profile_name: str,
    base_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_db_ready()
    existing_ids = set(all_profile_ids())
    base_id = _safe_profile_id(profile_name)
    pid = _dedupe_profile_id(base_id, existing_ids)

    source = copy.deepcopy(base_profile) if base_profile is not None else clone_default_profile()
    source["profile_name"] = profile_name.strip() or f"Profile {len(existing_ids) + 1}"
    if base_profile is None:
        source["companion_name"] = source["profile_name"]
        source["description"] = "New custom profile."
        source["memory_notes"] = []

    normalized = _normalize_profile(source, profile_id=pid)
    now = _now_iso()
    normalized["created_at"] = now
    normalized["updated_at"] = now

    upsert_profile(pid, normalized)
    return copy.deepcopy(normalized)


def delete_profile(profile_id: str) -> str:
    _ensure_db_ready()
    if not profile_exists(profile_id):
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    if profile_count() <= 1:
        raise RuntimeError("You need at least one profile.")

    delete_profile_row(profile_id)

    active_id = get_state("active_profile_id", "")
    if active_id == profile_id:
        new_active = sorted(all_profile_ids())[0]
        set_state("active_profile_id", new_active)
    else:
        new_active = active_id

    # Touch the new active profile
    data = load_single_profile(new_active)
    if data:
        touched = _touch_profile(_normalize_profile(data, new_active))
        upsert_profile(new_active, touched)

    return new_active


# ── History (SQLite-backed) ──────────────────────────────────────────────


def read_recent_history(max_turns: int = 50) -> list[dict[str, str]]:
    if max_turns <= 0:
        return []
    _ensure_db_ready()
    return read_history_tail(max_turns)


def append_history(role: str, content: str) -> None:
    _ensure_db_ready()
    ts = datetime.now().isoformat(timespec="seconds")
    append_history_row(ts, role, content)


def reset_history() -> None:
    _ensure_db_ready()
    db_clear_history()
