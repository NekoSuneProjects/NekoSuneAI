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


def _set_model(profile: str, target: Path, url: str) -> None:
    os.environ["VOSK_MODEL_PATH"] = str(target)
    os.environ["VOSK_MODEL_URL"] = str(url)
    os.environ["VOSK_MODEL_PROFILE_ACTIVE"] = profile


def _models_dir_writable(models_dir: Path) -> bool:
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        probe = models_dir / ".nekosuneai-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


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
    models_dir = Path("/app/models")
    target = models_dir / str(model["name"])
    small = VOSK_MODELS["small"]
    small_target = models_dir / str(small["name"])

    _set_model(profile, target, str(model["url"]))

    if _valid_model(target):
        print(f"[startup] Vosk {profile} model ready: {target}")
        _INSTALLED = True
        return

    # The Docker container normally runs as the host audio user. If /app/models
    # is image-owned/read-only for that UID, do not download and unzip a larger
    # model only to fail at the final move. Prefer the already-installed small
    # model immediately, reducing startup I/O and memory pressure on Raspberry Pi.
    if not _models_dir_writable(models_dir):
        if _valid_model(small_target):
            _set_model("small", small_target, str(small["url"]))
            print(
                f"[startup] Vosk model directory is not writable; using existing small model: {small_target}"
            )
            _INSTALLED = True
            return
        raise PermissionError(
            f"Vosk model directory is not writable and no fallback model exists: {models_dir}"
        )

    print(
        f"[startup] Installing Vosk {profile} speech model for this system "
        f"({model['name']})..."
    )
    try:
        _download_model(str(model["url"]), target)
    except Exception as exc:
        if profile != "small":
            print(f"[startup] Better Vosk model failed ({exc}); falling back to small model.")
            _set_model("small", small_target, str(small["url"]))
            if not _valid_model(small_target):
                _download_model(str(small["url"]), small_target)
        else:
            raise

    _INSTALLED = True
