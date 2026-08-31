from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests

_INSTALLED = False

VOSK_MODELS = {
    "small": {
        "name": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    },
    "balanced": {
        "name": "vosk-model-en-us-0.22-lgraph",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
    },
    "large": {
        "name": "vosk-model-en-us-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
    },
}


def _total_ram_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _normalize_profile(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"medium", "better", "lgraph", "pi5", "pi-5", "8gb"}:
        return "balanced"
    if normalized in {"full", "big", "best"}:
        return "large"
    if normalized in {"lite", "light", "tiny"}:
        return "small"
    if normalized in {"small", "balanced", "large", "custom"}:
        return normalized
    return "auto"


def _auto_profile() -> str:
    # A Pi 5 8 GB has enough RAM for the much better 0.22-lgraph model while
    # still leaving room for the dashboard, TTS, music and Docker overhead.
    # Keep the 1.8 GB full model opt-in because it can pressure a 6 GB container.
    total = _total_ram_bytes()
    return "balanced" if total >= 6 * 1024**3 else "small"


def _valid_model(path: Path) -> bool:
    return (path / "am" / "final.mdl").is_file()


def _download_model(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nekosuneai-vosk-") as temp_name:
        temp = Path(temp_name)
        archive = temp / "model.zip"
        extracted = temp / "extracted"
        extracted.mkdir(parents=True, exist_ok=True)

        with requests.get(url, stream=True, timeout=(20, 300)) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)

        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extracted)

        entries = list(extracted.iterdir())
        source = entries[0] if len(entries) == 1 and entries[0].is_dir() else extracted
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))

    if not _valid_model(target):
        raise RuntimeError(f"Downloaded Vosk model is invalid: {target}")


def install_vosk_model_auto_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    provider = str(os.getenv("STT_PROVIDER", "faster-whisper")).strip().lower()
    if provider not in {"vosk", "local-lite", "local_light", "pi"}:
        _INSTALLED = True
        return

    requested = _normalize_profile(os.getenv("VOSK_MODEL_PROFILE", "auto"))
    if requested == "custom":
        _INSTALLED = True
        return

    profile = _auto_profile() if requested == "auto" else requested
    model = VOSK_MODELS[profile]
    target = Path("/app/models") / str(model["name"])

    # Profile selection owns these values. This intentionally upgrades old Pi
    # .env files that still point at vosk-model-small-en-us-0.15 when profile is
    # auto/balanced. Set VOSK_MODEL_PROFILE=custom to keep an arbitrary path.
    os.environ["VOSK_MODEL_PATH"] = str(target)
    os.environ["VOSK_MODEL_URL"] = str(model["url"])
    os.environ["VOSK_MODEL_PROFILE_ACTIVE"] = profile

    if _valid_model(target):
        print(f"[startup] Vosk {profile} model ready: {target}")
        _INSTALLED = True
        return

    print(
        f"[startup] Installing Vosk {profile} speech model for this system "
        f"({model['name']})..."
    )
    try:
        _download_model(str(model["url"]), target)
    except Exception as exc:
        if profile != "small":
            fallback = VOSK_MODELS["small"]
            fallback_target = Path("/app/models") / str(fallback["name"])
            print(f"[startup] Better Vosk model failed ({exc}); falling back to small model.")
            os.environ["VOSK_MODEL_PATH"] = str(fallback_target)
            os.environ["VOSK_MODEL_URL"] = str(fallback["url"])
            os.environ["VOSK_MODEL_PROFILE_ACTIVE"] = "small"
            if not _valid_model(fallback_target):
                _download_model(str(fallback["url"]), fallback_target)
        else:
            raise

    _INSTALLED = True
