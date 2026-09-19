"""SQLite persistence layer.

Owns the connection, the schema and every statement run against it. Profiles,
chat history and RAG memories all live in ``data/nekosuneai.db``; the JSON and
JSONL files earlier versions wrote are imported once on first start and then
left alone.

Connections are thread-local, and a database that will not open at all is moved
aside and rebuilt rather than being allowed to block start-up.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from .paths import DATA_DIR

DB_PATH = DATA_DIR / "nekosuneai.db"

_ACTIVE_PROFILE_KEY = "active_profile_id"

# Sidecar files SQLite may leave beside the database itself.
_DB_SIDECAR_SUFFIXES = ("", "-wal", "-shm")

_CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
)

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS app_state (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profiles (
        profile_id   TEXT PRIMARY KEY,
        profile_name TEXT NOT NULL DEFAULT '',
        data         TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL DEFAULT '',
        updated_at   TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT    NOT NULL,
        role      TEXT    NOT NULL,
        content   TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_history_ts ON history(timestamp)",
    """
    CREATE TABLE IF NOT EXISTS memories (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT    NOT NULL,
        source     TEXT    NOT NULL DEFAULT 'chat',
        speaker    TEXT    NOT NULL DEFAULT '',
        content    TEXT    NOT NULL,
        embedding  BLOB,
        score      REAL    NOT NULL DEFAULT 0,
        created_at TEXT    NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mem_profile ON memories(profile_id)",
)

_MEMORY_COLUMNS = "id, source, speaker, content, embedding, score, created_at"

_local = threading.local()


# --------------------------------------------------------------------------
# Connection management
# --------------------------------------------------------------------------


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't already exist."""
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


def _open_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    try:
        for pragma in _CONNECTION_PRAGMAS:
            conn.execute(pragma)
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
    except Exception:
        # Drop the handle so a corrupt file can be renamed or removed on Windows.
        try:
            conn.close()
        except Exception:
            pass
        raise
    return conn


def _quarantine_corrupt_db() -> None:
    """Move a corrupt DB (and its WAL/SHM) aside so a fresh one can be created."""
    for suffix in _DB_SIDECAR_SUFFIXES:
        path = Path(str(DB_PATH) + suffix)
        if not path.exists():
            continue

        backup = Path(str(path) + ".corrupt")
        try:
            if backup.exists():
                backup.unlink()
            path.rename(backup)
        except OSError:
            # Renaming failed, so settle for deleting the unusable file.
            try:
                path.unlink()
            except OSError:
                pass


def get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating the DB if needed.

    A database that cannot be opened - a corrupt file, or a stale WAL pointing
    at one - is quarantined and rebuilt instead of raising and bricking
    start-up. The caller's usual migration and seeding path then refills it.
    """
    existing: sqlite3.Connection | None = getattr(_local, "conn", None)
    if existing is not None:
        return existing

    DATA_DIR.mkdir(exist_ok=True)
    try:
        conn = _open_connection()
    except sqlite3.DatabaseError:
        _quarantine_corrupt_db()
        conn = _open_connection()

    _local.conn = conn
    return conn


# --------------------------------------------------------------------------
# Statement helpers
# --------------------------------------------------------------------------


def _query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return get_connection().execute(sql, params).fetchone()


def _query_all(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return get_connection().execute(sql, params).fetchall()


def _write(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    """Run a mutating statement and commit it."""
    conn = get_connection()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor


def _write_many(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    conn = get_connection()
    conn.executemany(sql, rows)
    conn.commit()


def _count(sql: str, params: Sequence[Any] = ()) -> int:
    row = _query_one(sql, params)
    return row["cnt"] if row else 0


def _decode_json(raw: Any) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# --------------------------------------------------------------------------
# app_state
# --------------------------------------------------------------------------


def get_state(key: str, default: str = "") -> str:
    row = _query_one("SELECT value FROM app_state WHERE key=?", (key,))
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    _write(
        "INSERT INTO app_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------


def upsert_profile(profile_id: str, profile: dict[str, Any]) -> None:
    _write(
        "INSERT INTO profiles(profile_id, profile_name, data, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?) "
        "ON CONFLICT(profile_id) DO UPDATE SET "
        "  profile_name=excluded.profile_name, "
        "  data=excluded.data, "
        "  created_at=excluded.created_at, "
        "  updated_at=excluded.updated_at",
        (
            profile_id,
            str(profile.get("profile_name", "")),
            json.dumps(profile, ensure_ascii=False),
            str(profile.get("created_at", "")),
            str(profile.get("updated_at", "")),
        ),
    )


def load_all_profiles() -> dict[str, dict[str, Any]]:
    """Every stored profile, skipping any row whose JSON will not parse."""
    profiles: dict[str, dict[str, Any]] = {}
    for row in _query_all("SELECT profile_id, data FROM profiles"):
        decoded = _decode_json(row["data"])
        if decoded is not None:
            profiles[row["profile_id"]] = decoded
    return profiles


def load_single_profile(profile_id: str) -> dict[str, Any] | None:
    row = _query_one("SELECT data FROM profiles WHERE profile_id=?", (profile_id,))
    return _decode_json(row["data"]) if row is not None else None


def delete_profile_row(profile_id: str) -> None:
    _write("DELETE FROM profiles WHERE profile_id=?", (profile_id,))


def profile_exists(profile_id: str) -> bool:
    return _query_one(
        "SELECT 1 FROM profiles WHERE profile_id=?", (profile_id,)
    ) is not None


def profile_count() -> int:
    return _count("SELECT COUNT(*) AS cnt FROM profiles")


def all_profile_ids() -> list[str]:
    rows = _query_all("SELECT profile_id FROM profiles ORDER BY profile_id")
    return [row["profile_id"] for row in rows]


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

_INSERT_HISTORY_SQL = "INSERT INTO history(timestamp, role, content) VALUES(?, ?, ?)"


def append_history_row(timestamp: str, role: str, content: str) -> None:
    _write(_INSERT_HISTORY_SQL, (timestamp, role, content))


def read_history_tail(max_turns: int) -> list[dict[str, str]]:
    """Return the last *max_turns* user+assistant exchanges (up to 2x rows)."""
    rows = _query_all(
        "SELECT role, content FROM history "
        "WHERE role IN ('user', 'assistant') "
        "ORDER BY id DESC LIMIT ?",
        (max_turns * 2,),
    )
    # The query returns newest-first; callers want chronological order.
    return [
        {"role": row["role"], "content": row["content"]} for row in reversed(rows)
    ]


def clear_history() -> None:
    _write("DELETE FROM history")


def history_row_count() -> int:
    return _count("SELECT COUNT(*) AS cnt FROM history")


# --------------------------------------------------------------------------
# Memories
# --------------------------------------------------------------------------


def insert_memory(
    profile_id: str,
    source: str,
    speaker: str,
    content: str,
    embedding: bytes | None,
    score: float,
    created_at: str,
) -> int:
    cursor = _write(
        "INSERT INTO memories(profile_id, source, speaker, content, embedding, score, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (profile_id, source, speaker, content, embedding, score, created_at),
    )
    return int(cursor.lastrowid)


def fetch_memories_for_profile(profile_id: str) -> list[dict[str, Any]]:
    rows = _query_all(
        f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE profile_id=? ORDER BY id DESC",
        (profile_id,),
    )
    return [dict(row) for row in rows]


def bump_memory_score(memory_id: int, delta: float) -> None:
    _write("UPDATE memories SET score = score + ? WHERE id=?", (delta, memory_id))


def delete_memory(memory_id: int) -> None:
    _write("DELETE FROM memories WHERE id=?", (memory_id,))


def delete_all_memories_for_profile(profile_id: str) -> int:
    """Wipe every stored memory for *profile_id* back to blank. Returns the count deleted."""
    return _write("DELETE FROM memories WHERE profile_id=?", (profile_id,)).rowcount


def prune_low_memories(profile_id: str, min_score: float, keep_recent: int) -> int:
    """Delete memories below *min_score*, except the *keep_recent* newest rows."""
    cursor = _write(
        "DELETE FROM memories WHERE profile_id=? AND score < ? AND id NOT IN "
        "(SELECT id FROM memories WHERE profile_id=? ORDER BY id DESC LIMIT ?)",
        (profile_id, min_score, profile_id, keep_recent),
    )
    return cursor.rowcount


# --------------------------------------------------------------------------
# One-time migration from the legacy JSON files
# --------------------------------------------------------------------------


def _read_json_file(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


def _legacy_profiles(
    profiles_path: Path, profile_path: Path
) -> tuple[dict[str, Any], str, bool]:
    """Read whichever legacy profile file exists.

    ``profiles.json`` holds the multi-profile store; ``profile.json`` is the
    older single-profile format and is only consulted if the newer file gave
    nothing. Returns (profiles, active_id, found_anything).
    """
    profiles: dict[str, Any] = {}
    active_id = ""
    found = False

    if profiles_path.exists():
        store = _read_json_file(profiles_path)
        if store is not None:
            profiles = store.get("profiles", {})
            active_id = store.get(_ACTIVE_PROFILE_KEY, "")
            found = True

    # An empty or unreadable store still leaves the single-profile file worth a try.
    if not profiles and profile_path.exists():
        single = _read_json_file(profile_path)
        if single is not None:
            profile_id = str(single.get("profile_id", "default"))
            profiles = {profile_id: single}
            active_id = profile_id
            found = True

    return profiles, active_id, found


def _migrate_profiles(profiles_path: Path, profile_path: Path) -> bool:
    raw_profiles, active_id, found = _legacy_profiles(profiles_path, profile_path)

    for profile_id, profile in raw_profiles.items():
        upsert_profile(profile_id, profile)
    if active_id:
        set_state(_ACTIVE_PROFILE_KEY, active_id)

    return found


def _iter_history_entries(path: Path) -> list[tuple[str, str, str]]:
    """Parse a history JSONL file, skipping blank and unparseable lines."""
    batch: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = entry.get("role", "")
            content = entry.get("content", "")
            if role and content:
                batch.append((entry.get("timestamp", ""), role, content))
    return batch


def _migrate_history(history_path: Path) -> bool:
    try:
        batch = _iter_history_entries(history_path)
    except OSError:
        return False

    if not batch:
        return False

    _write_many(_INSERT_HISTORY_SQL, batch)
    return True


def migrate_from_json_if_needed(
    profiles_path: Path,
    profile_path: Path,
    history_path: Path,
) -> bool:
    """One-time import of legacy JSON/JSONL files into SQLite.

    Returns True if any data was migrated.
    """
    # Both tables already populated: there is nothing legacy left to bring over.
    if profile_count() > 0 and history_row_count() > 0:
        return False

    migrated = False

    if profile_count() == 0:
        migrated |= _migrate_profiles(profiles_path, profile_path)

    if history_row_count() == 0 and history_path.exists():
        migrated |= _migrate_history(history_path)

    return migrated
