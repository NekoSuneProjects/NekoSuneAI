import sys
from pathlib import Path

# PyInstaller sets sys.frozen — ROOT_DIR then needs to be the exe's own
# directory (where the release workflow copies VERSION/.env.example, and
# where a per-user install location keeps data writable), not the source
# file's location, which resolves inside PyInstaller's internal extraction
# dir (_internal/ in onedir mode) once bundled.
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
    # Bundled package data (nekosuneai/static/) lives under the extraction
    # root instead — sys._MEIPASS, PyInstaller's own convention for finding
    # bundled *code*/data in both onedir and onefile modes.
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR)) / "nekosuneai" / "static"
else:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = ROOT_DIR / "nekosuneai" / "static"

DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = ROOT_DIR / "audio"
# Rendered songs are kept here so they can be replayed without re-singing.
SONGS_DIR = AUDIO_DIR / "songs"
PROFILE_PATH = DATA_DIR / "profile.json"
PROFILES_PATH = DATA_DIR / "profiles.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
UPDATE_STATE_PATH = DATA_DIR / "update_state.json"
VERSION_PATH = ROOT_DIR / "VERSION"

XTTS_STREAM_END = object()

SONGS_DIR.mkdir(parents=True, exist_ok=True)
